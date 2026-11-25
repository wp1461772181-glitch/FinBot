"""The companies the system keeps an archive for, and the bounded worker that builds a new company's archive from SEC filings.

A subject is a company the owner holds, queues for research, or asked about.  The hourly SEC monitor follows the non-retired subjects
(``active_symbols``); the first time the owner asks about a company SEC knows and we have nothing on, one build fetches its latest
annual report, three latest quarterly reports and four latest 8-Ks and rebuilds its facts.  No model is called and no card is made:
this is a read of public filings, triggered only by the owner (the caller checks that) and only for a symbol SEC's own ticker list knows.

Bounds: one build at a time, at most 20 waiting, at most 30 builds started per hour, a symbol is not rebuilt within 6 hours of a
success or 1 hour of a failure, and a build stops after 5 minutes.  SEC's rate limit and identification are the provider's own.
``FINBOT_ARCHIVE_BUILDS=off`` keeps the worker from starting (the queue is still recorded).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from .database import SessionLocal
from .models import ArchiveSubject, SecFilingInventory
from .sec_filings import SEC_TICKERS_URL, SecEdgarProvider, SecFilingsError, fetch_inventory_content, scan_sec_filings
from .symbols import normalize_market_symbol

log = logging.getLogger(__name__)

MAX_WAITING = 20
MAX_BUILDS_PER_HOUR = 30
REBUILD_AFTER_OK = timedelta(hours=6)
REBUILD_AFTER_FAILED = timedelta(hours=1)
BUILD_WALL_SECONDS = 300
TICKER_LIST_TTL = timedelta(hours=24)
RETIRE_AFTER = timedelta(days=90)
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
FETCH_ANNUAL, FETCH_QUARTERLY, FETCH_8K = 1, 3, 4
STOP_AFTER_UNAVAILABLE = 2           # SEC refusing this many fetches in a row ends the build
WORKER_POLL_SECONDS = 60

_TICKERS: dict = {"at": None, "symbols": None}
_TICKERS_LOCK = threading.Lock()
_STATE: dict = {"task": None, "loop": None, "event": None}


def _now() -> datetime:
    return datetime.now(UTC)


def _monotonic() -> float:
    return time.monotonic()


def _provider() -> SecEdgarProvider:
    return SecEdgarProvider()


def _fetch_ticker_list() -> dict:
    return _provider()._get_json(SEC_TICKERS_URL)


def _refresh_facts(symbol: str) -> dict:
    from .company_facts import refresh
    return refresh(symbol)


# --- SEC's ticker list ------------------------------------------------------------------------------------------

def _known_symbols() -> frozenset[str] | None:
    """Every ticker SEC lists, normalised; cached for a day, and a failed fetch keeps the previous list (None only if there never was one)."""
    with _TICKERS_LOCK:
        at, symbols = _TICKERS["at"], _TICKERS["symbols"]
        if symbols is not None and at is not None and _now() - at < TICKER_LIST_TTL:
            return symbols
        try:
            payload = _fetch_ticker_list()
            found = set()
            for item in payload.values():
                try:
                    found.add(normalize_market_symbol(str(item.get("ticker"))))
                except (ValueError, AttributeError):
                    continue
            if found:
                _TICKERS.update(at=_now(), symbols=frozenset(found))
        except Exception as exc:  # noqa: BLE001 - the list being unreachable must never break a chat turn
            log.warning("SEC ticker list not refreshed (%s)", type(exc).__name__)
        return _TICKERS["symbols"]


def sec_symbol(value: str) -> str | None:
    """The normalised symbol if SEC's ticker list has it, else None (a word like CEO or IT is not a company until SEC says it is)."""
    try:
        symbol = normalize_market_symbol(value)
    except (ValueError, AttributeError):
        return None
    known = _known_symbols()
    return symbol if known is not None and symbol in known else None


# --- asking, queueing -------------------------------------------------------------------------------------------

def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else (value if value.tzinfo else value.replace(tzinfo=UTC))


def _state(subject: ArchiveSubject) -> str:
    if subject.build_status == "failed":
        return f"failed:{subject.build_error or 'error'}"
    return {"ok": "ok", "building": "building", "queued": "queued"}.get(subject.build_status, "never")


def _has_archive(db, symbol: str) -> bool:
    return db.scalar(select(func.count()).select_from(SecFilingInventory).where(SecFilingInventory.symbol == symbol)) > 0


def _may_queue(db, now: datetime) -> bool:
    waiting = db.scalar(select(func.count()).select_from(ArchiveSubject).where(ArchiveSubject.build_status == "queued"))
    started = db.scalar(select(func.count()).select_from(ArchiveSubject).where(ArchiveSubject.build_started_at > now - timedelta(hours=1),
                                                                                   ArchiveSubject.build_status != "queued"))
    return waiting < MAX_WAITING and waiting + started < MAX_BUILDS_PER_HOUR


def _ask(symbol: str, now: datetime) -> tuple[str, bool]:
    """Record the ask and queue a build if one is due and allowed; returns (state, queued_now)."""
    with SessionLocal() as db:
        subject = db.get(ArchiveSubject, symbol)
        if subject is None:
            subject = ArchiveSubject(symbol=symbol, held=False, queued=False, first_seen_at=now, last_active_at=now, build_status="never", filings_added=0)
            db.add(subject)
        subject.asked_at = subject.last_active_at = now
        subject.retired_at = None
        queued_now = False
        if subject.build_status == "never":
            if _has_archive(db, symbol):
                subject.build_status = "ok"                    # already archived (held, defaults, the monitor's own scans): a mention fetches nothing
            elif _may_queue(db, now):
                subject.build_status, queued_now = "queued", True
            else:
                db.commit()
                return "limited", False
        elif subject.build_status == "ok":
            pass                                               # a success is rebuilt by the monitor, not by a mention
        elif subject.build_status == "failed":
            finished = _as_utc(subject.build_finished_at) or now
            if now - finished >= REBUILD_AFTER_FAILED:
                if _may_queue(db, now):
                    subject.build_status, subject.build_error, queued_now = "queued", None, True
                else:
                    db.commit()
                    return "limited", False
        state = _state(subject)
        db.commit()
        return state, queued_now


def note_asked(symbol: str) -> str:
    """Record that the owner asked about ``symbol`` and return its state for the block: ``ok``, ``building``, ``queued``, ``failed:<reason>``,
    ``limited`` (a cap held it back; nothing was queued) or ``unknown`` (SEC does not list it: no row, no build).  Owner only: the caller checks."""
    normalized = sec_symbol(symbol)
    if normalized is None:
        return "unknown"
    state, queued_now = _ask(normalized, _now())
    if queued_now:
        _poke()
    return state


async def enqueue_build(symbol: str) -> bool:
    """Queue a build for a symbol SEC knows; False if it is unknown, already waiting or built, or a cap held it back."""
    normalized = await asyncio.to_thread(sec_symbol, symbol)
    if normalized is None:
        return False
    state, queued_now = await asyncio.to_thread(_ask, normalized, _now())
    if queued_now:
        _poke()
    return queued_now


# --- the build --------------------------------------------------------------------------------------------------

def _reason(exc: BaseException) -> str:
    cause = exc.__cause__ or exc.__context__ or exc
    code = getattr(cause, "code", None)
    if isinstance(cause, TimeoutError):
        return "timeout"
    if isinstance(code, int):
        return f"http_{code}"[:64]
    if isinstance(exc, SecFilingsError):
        return "sec_error"
    return "error"


def _finish(symbol: str, status: str, error: str | None, added: int) -> None:
    with SessionLocal() as db:
        subject = db.get(ArchiveSubject, symbol)
        if subject is not None:
            subject.build_status, subject.build_error = status, (error[:64] if error else None)
            subject.build_finished_at, subject.filings_added = _now(), added
            db.commit()


def _chosen(db, symbol: str) -> list[str]:
    rows = db.execute(select(SecFilingInventory.accession_number, SecFilingInventory.form).where(SecFilingInventory.symbol == symbol)
                      .order_by(SecFilingInventory.filed_at.desc(), SecFilingInventory.accession_number.desc())).all()
    annual = [a for a, f in rows if f in ANNUAL_FORMS][:FETCH_ANNUAL]
    quarterly = [a for a, f in rows if f == "10-Q"][:FETCH_QUARTERLY]
    eight_k = [a for a, f in rows if f == "8-K"][:FETCH_8K]
    return annual + quarterly + eight_k


def build(symbol: str, *, deadline_seconds: float = BUILD_WALL_SECONDS) -> dict:
    """Scan the company's filings, fetch the ones that matter (annual, quarterly, earnings 8-Ks), rebuild its facts once.
    Records its own outcome on the subject; never raises.  Filings already stored stay whatever happens."""
    symbol = symbol.strip().upper()
    started = _monotonic()
    out = {"symbol": symbol, "status": "failed", "error": None, "filings_added": 0, "fetched": 0, "facts": None}
    try:
        with SessionLocal() as db:
            subject = db.get(ArchiveSubject, symbol)
            if subject is None:
                return {**out, "error": "no_subject"}
            subject.build_status, subject.build_started_at, subject.build_error = "building", _now(), None
            db.commit()
        provider = _provider()
        with SessionLocal() as db:
            _, created, _ = scan_sec_filings(symbol=symbol, db=db, provider=provider)
            out["filings_added"] = created
            unavailable_in_a_row = 0
            for accession in _chosen(db, symbol):
                if _monotonic() - started > deadline_seconds:
                    out["error"] = "timeout"
                    break
                filing, _cached = fetch_inventory_content(symbol=symbol, accession_number=accession, db=db, provider=provider, refresh_facts=False)
                if filing.content_status == "unavailable":
                    unavailable_in_a_row += 1
                    if unavailable_in_a_row >= STOP_AFTER_UNAVAILABLE:
                        out["error"] = "sec_unavailable"
                        break
                else:
                    unavailable_in_a_row = 0
                    out["fetched"] += 1
        if out["error"] is None:
            try:
                out["facts"] = _refresh_facts(symbol).get("facts")
            except Exception as exc:  # noqa: BLE001 - the filings are stored; a facts problem is the sweep's to retry in six hours
                log.warning("archive build of %s: facts refresh failed (%s)", symbol, type(exc).__name__)
        out["status"] = "failed" if out["error"] else "ok"
    except Exception as exc:  # noqa: BLE001 - a build never takes the worker down
        out["error"] = _reason(exc)
        log.warning("archive build of %s failed (%s: %s)", symbol, type(exc).__name__, str(exc)[:200])
    try:
        _finish(symbol, out["status"], out["error"], out["filings_added"])
    except Exception:  # noqa: BLE001
        log.exception("archive build of %s: could not record the outcome", symbol)
    return out


# --- the worker -------------------------------------------------------------------------------------------------

def _claim_next() -> str | None:
    """The oldest ask waiting, marked building, unless 30 builds already started this hour."""
    now = _now()
    with SessionLocal() as db:
        started = db.scalar(select(func.count()).select_from(ArchiveSubject).where(ArchiveSubject.build_started_at > now - timedelta(hours=1),
                                                                                   ArchiveSubject.build_status != "queued"))
        if started >= MAX_BUILDS_PER_HOUR:
            return None
        subject = db.scalars(select(ArchiveSubject).where(ArchiveSubject.build_status == "queued")
                             .order_by(ArchiveSubject.asked_at.asc().nulls_first(), ArchiveSubject.symbol).limit(1).with_for_update(skip_locked=True)).first()
        if subject is None:
            return None
        subject.build_status, subject.build_started_at = "building", now
        db.commit()
        return subject.symbol


def run_pending() -> int:
    """Build every waiting company, one at a time (the worker's job, callable on its own); returns how many it built."""
    done = 0
    while (symbol := _claim_next()) is not None:
        try:
            build(symbol)
        except Exception:  # noqa: BLE001
            log.exception("archive build of %s escaped", symbol)
        done += 1
    return done


def recover_interrupted() -> int:
    """A build a restart left in ``building`` goes back to the queue."""
    with SessionLocal() as db:
        rows = db.scalars(select(ArchiveSubject).where(ArchiveSubject.build_status == "building")).all()
        for subject in rows:
            subject.build_status = "queued"
        db.commit()
        return len(rows)


def builds_enabled() -> bool:
    return os.environ.get("FINBOT_ARCHIVE_BUILDS", "on").strip().lower() not in {"off", "0", "false", "no"}


def _poke() -> None:
    """Wake the worker from any thread; nothing to wake when it is not running."""
    loop, event = _STATE["loop"], _STATE["event"]
    if loop is not None and event is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass


async def _work(event: asyncio.Event) -> None:
    try:
        await asyncio.to_thread(recover_interrupted)
    except Exception:  # noqa: BLE001
        log.exception("archive worker: recovery failed")
    while True:
        try:
            await asyncio.to_thread(run_pending)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("archive worker pass failed")
        try:
            await asyncio.wait_for(event.wait(), timeout=WORKER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        event.clear()


def start() -> None:
    """Start the one worker on the running loop (the API's startup); a no-op when ``FINBOT_ARCHIVE_BUILDS`` is off or it already runs."""
    if not builds_enabled():
        return
    current = asyncio.get_running_loop()
    task = _STATE["task"]
    if task is not None and not task.done() and _STATE["loop"] is current:
        return
    event = asyncio.Event()
    _STATE.update(loop=current, event=event, task=current.create_task(_work(event), name="archive-worker"))


async def stop() -> None:
    task = _STATE["task"]
    _STATE.update(task=None, loop=None, event=None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# --- the owner's list -------------------------------------------------------------------------------------------

def _owner_symbols(db, owner_hash: str) -> tuple[set[str], set[str]]:
    from .agent_chat_models import AgentResearchQueue
    from .portfolio import _row_to_txn, load_transactions, replay

    ledger = replay([_row_to_txn(r) for r in load_transactions(db, owner_hash)])
    held = set()
    for symbol, position in ledger.positions.items():
        try:
            if position.shares > 0:
                held.add(normalize_market_symbol(symbol))
        except ValueError:
            continue
    queue = db.get(AgentResearchQueue, owner_hash)
    queued = set()
    for value in (queue.symbols if queue is not None and isinstance(queue.symbols, list) else []):
        try:
            queued.add(normalize_market_symbol(str(value)))
        except ValueError:
            continue
    return held, queued


def sync_owner_subjects(owner_hash: str) -> dict:
    """Set ``held`` / ``queued`` from the owner's holdings and research queue, create subjects for the ones SEC knows, and retire the
    subjects nobody has held, queued or asked about for 90 days (the row and its stored filings stay)."""
    now = _now()
    with SessionLocal() as db:
        held, queued = _owner_symbols(db, owner_hash)
    wanted = {s for s in held | queued if sec_symbol(s)}
    out = {"held": len(held & wanted), "queued": len(queued & wanted), "created": 0, "retired": 0, "revived": 0}
    with SessionLocal() as db:
        existing = {s.symbol: s for s in db.scalars(select(ArchiveSubject))}
        for symbol in wanted - set(existing):
            existing[symbol] = ArchiveSubject(symbol=symbol, held=False, queued=False, first_seen_at=now, last_active_at=now, build_status="never", filings_added=0)
            db.add(existing[symbol])
            out["created"] += 1
        for symbol, subject in existing.items():
            subject.held, subject.queued = symbol in held, symbol in queued
            if subject.held or subject.queued:
                subject.last_active_at = now
                if subject.retired_at is not None:
                    subject.retired_at = None
                    out["revived"] += 1
            elif subject.retired_at is None and now - (_as_utc(subject.last_active_at) or now) >= RETIRE_AFTER:
                subject.retired_at = now
                out["retired"] += 1
        db.commit()
    return out
