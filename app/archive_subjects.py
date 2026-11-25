"""The companies the system keeps an archive for, and the bounded worker that builds a new company's archive from SEC filings.

A subject is a company the owner holds, queues for research, or asked about.  The hourly SEC monitor follows the non-retired subjects
(``active_symbols``); the first time the owner asks about a company SEC knows and we have nothing on, one build fetches its latest
annual report, three latest quarterly reports and four latest 8-Ks and rebuilds its facts.  No model is called and no card is made:
this is a read of public filings, triggered only by the owner (the caller checks that) and only for a symbol SEC's own ticker list knows.

Bounds: one build at a time, at most 20 waiting, at most 30 builds started per hour, a symbol is not rebuilt within 1 hour of a
failure or partial build (a finished one is not rebuilt by a mention at all), and a build stops at the next SEC request after 5 minutes
or after a shutdown was asked for.  SEC's rate limit and identification are the provider's own.

A build is ``ok`` only when the archive is really there: a fetched 10-K or 10-Q with figures and an ``ok`` quarter of revenue in
``company_facts``.  Otherwise it is ``partial`` (some filings stored; ``build_error`` names what is missing) or ``failed``.

``FINBOT_ARCHIVE_BUILDS`` (on/off) decides whether the worker starts; unset, it follows ``BACKGROUND_LOOPS``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .database import SessionLocal
from .models import ArchiveSubject, CompanyFact, SecFilingInventory
from .sec_filings import (SEC_TICKERS_URL, SecEdgarProvider, SecFilingsError, fetch_inventory_content, scan_sec_filings,
                          store_inventory_figures)
from .symbols import normalize_market_symbol

log = logging.getLogger(__name__)

MAX_WAITING = 20
MAX_BUILDS_PER_HOUR = 30
REBUILD_AFTER_FAILED = timedelta(hours=1)
BUILD_WALL_SECONDS = 300
TICKER_LIST_TTL = timedelta(hours=24)
RETIRE_AFTER = timedelta(days=90)
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
FIGURE_FORMS = ("10-K", "10-Q", "20-F")      # the forms whose XBRL figures make an archive
WINDOW_DAYS = 457                            # fifteen months: the 10-Qs and earnings 8-Ks a build reads
MAX_QUARTERLY, MAX_8K_EXAMINED = 6, 30       # an 8-K counts only if its Exhibit 99.1 is an earnings release; at most 30 are looked at
TICKER_RETRY = timedelta(hours=1)
STOP_WAIT_SECONDS = 15
STOP_AFTER_UNAVAILABLE = 2           # SEC refusing this many fetches in a row ends the build
WORKER_POLL_SECONDS = 60

_TICKERS: dict = {"at": None, "symbols": None, "tried_at": None}
_TICKERS_LOCK = threading.Lock()
_STATE: dict = {"task": None, "loop": None, "event": None}
_STOPPING = threading.Event()                 # set by stop(): the worker's thread builds nothing more and the next SEC request is refused
_IDLE = threading.Event()                     # set whenever no worker thread is draining the queue
_IDLE.set()


class _BuildStop(BaseException):
    """Raised at a SEC request boundary when the build's deadline passed or a shutdown was asked for.  Not an Exception: nothing swallows it."""


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

def refresh_ticker_list() -> bool:
    """Fetch SEC's ticker list if the cached one is older than a day, unless a fetch was tried in the last hour (a failure keeps the previous
    list).  Network work: called from background threads only (the worker, the six-hour sweep); ``sec_symbol`` never calls it."""
    now = _now()
    with _TICKERS_LOCK:                              # the lock covers the decision, never the fetch
        at, tried = _TICKERS["at"], _TICKERS["tried_at"]
        if _TICKERS["symbols"] is not None and at is not None and now - at < TICKER_LIST_TTL:
            return False
        if tried is not None and now - tried < TICKER_RETRY:
            return False
        _TICKERS["tried_at"] = now
    try:
        payload = _fetch_ticker_list()
        found = set()
        for item in payload.values():
            try:
                found.add(normalize_market_symbol(str(item.get("ticker"))))
            except (ValueError, AttributeError):
                continue
    except Exception as exc:  # noqa: BLE001 - SEC being unreachable must never break anything
        log.warning("SEC ticker list not refreshed (%s)", type(exc).__name__)
        return False
    if not found:
        return False
    with _TICKERS_LOCK:
        _TICKERS.update(at=now, symbols=frozenset(found))
    return True


_WARMING = threading.Event()


def warm_ticker_list() -> None:
    """Start one background fetch of SEC's ticker list when none has arrived yet and builds are on (a no-op otherwise, and while one is under
    way); a turn that met a cold cache ignores the unknown ticker this time and the next turn finds the list."""
    if _TICKERS["symbols"] is not None or _WARMING.is_set() or not builds_enabled():
        return
    _WARMING.set()

    def run() -> None:
        try:
            refresh_ticker_list()
        finally:
            _WARMING.clear()

    threading.Thread(target=run, name="sec-tickers-warm", daemon=True).start()


def sec_symbol(value: str) -> str | None:
    """The normalised symbol if SEC's ticker list has it, else None (a word like CEO or IT is not a company until SEC says it is).
    Reads the cached list only, never the network: until the first list has arrived (a moment after startup) nothing is known."""
    try:
        symbol = normalize_market_symbol(value)
    except (ValueError, AttributeError):
        return None
    known = _TICKERS["symbols"]
    return symbol if known is not None and symbol in known else None


# --- asking, queueing -------------------------------------------------------------------------------------------

def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else (value if value.tzinfo else value.replace(tzinfo=UTC))


def _state(subject: ArchiveSubject) -> str:
    if subject.build_status in ("failed", "partial"):
        return f"{subject.build_status}:{subject.build_error or 'error'}"
    return {"ok": "ok", "building": "building", "queued": "queued"}.get(subject.build_status, "never")


def _has_archive(db, symbol: str) -> bool:
    """The archive is there: a fetched 10-K/10-Q/20-F with figures AND an ok quarter of revenue in the company facts.  Metadata rows alone are not."""
    figures = db.scalar(select(func.count()).select_from(SecFilingInventory).where(
        SecFilingInventory.symbol == symbol, SecFilingInventory.content_status == "fetched", SecFilingInventory.form.in_(FIGURE_FORMS),
        SecFilingInventory.content_financials.is_not(None)))
    if not figures:
        return False
    return bool(db.scalar(select(func.count()).select_from(CompanyFact).where(
        CompanyFact.symbol == symbol, CompanyFact.metric == "revenue", CompanyFact.span == "quarter", CompanyFact.status == "ok")))


def _may_queue(db, now: datetime) -> bool:
    waiting = db.scalar(select(func.count()).select_from(ArchiveSubject).where(ArchiveSubject.build_status == "queued"))
    started = db.scalar(select(func.count()).select_from(ArchiveSubject).where(ArchiveSubject.build_started_at > now - timedelta(hours=1),
                                                                               ArchiveSubject.build_status != "queued"))
    return waiting < MAX_WAITING and waiting + started < MAX_BUILDS_PER_HOUR


def _ask_once(symbol: str, now: datetime) -> tuple[str, bool]:
    with SessionLocal() as db:
        subject = db.get(ArchiveSubject, symbol)
        if subject is None:
            subject = ArchiveSubject(symbol=symbol, held=False, queued=False, first_seen_at=now, last_active_at=now, build_status="never", filings_added=0)
            db.add(subject)
        if subject.build_status != "queued":            # asking again must not send a waiting build to the back of the line
            subject.asked_at = now
        subject.last_active_at = now
        subject.retired_at = None
        queued_now = False
        if subject.build_status == "never":
            if _has_archive(db, symbol):
                subject.build_status = "ok"                    # really archived already: a mention fetches nothing
            elif _may_queue(db, now):
                subject.build_status, queued_now = "queued", True
            else:
                db.commit()
                return "limited", False
        elif subject.build_status in ("failed", "partial"):
            finished = _as_utc(subject.build_finished_at) or now
            if now - finished >= REBUILD_AFTER_FAILED:
                if _may_queue(db, now):
                    subject.build_status, subject.build_error, subject.filings_added, queued_now = "queued", None, 0, True
                else:
                    db.commit()
                    return "limited", False
        state = _state(subject)
        db.commit()
        return state, queued_now


def _ask(symbol: str, now: datetime) -> tuple[str, bool]:
    """Record the ask and queue a build if one is due and allowed; returns (state, queued_now)."""
    try:
        return _ask_once(symbol, now)
    except IntegrityError:                                     # two writers made the row at once: the second one reads it
        return _ask_once(symbol, now)


def note_asked(symbol: str) -> str:
    """Record that the owner asked about ``symbol`` and return its state for the block: ``ok``, ``building``, ``queued``,
    ``failed:<reason>``, ``partial:<what is missing>``, ``limited`` (a cap held it back; nothing was queued) or ``unknown`` (SEC does not
    list it: no row, no build).  Owner only: the caller checks.  Touches the database, not the network."""
    normalized = sec_symbol(symbol)
    if normalized is None:
        return "unknown"
    state, queued_now = _ask(normalized, _now())
    if queued_now:
        _poke()
    return state


async def enqueue_build(symbol: str) -> bool:
    """Queue a build for a symbol SEC knows; False if it is unknown, already waiting or built, or a cap held it back."""
    normalized = sec_symbol(symbol)
    if normalized is None:
        return False
    state, queued_now = await asyncio.to_thread(_ask, normalized, _now())
    if queued_now:
        _poke()
    return queued_now


# --- the build --------------------------------------------------------------------------------------------------

def _reason(exc: BaseException) -> str:
    cause = exc.__cause__ or exc.__context__ or exc
    if isinstance(cause, TimeoutError) or isinstance(getattr(cause, "reason", None), TimeoutError):
        return "timeout"
    code = getattr(cause, "code", None)
    if isinstance(code, int):
        return f"http_{code}"[:64]
    if isinstance(exc, SecFilingsError):
        return "sec_error"
    return "error"


def _xbrl_problem(errors: list) -> str | None:
    """The first rate-limit, auth or timeout error among the XBRL requests (a 404 is just a concept the company does not use)."""
    for exc in errors:
        reason = _reason(exc)
        if reason in ("http_429", "http_403", "http_401", "timeout"):
            return f"xbrl_{reason.removeprefix('http_')}"
    return None


def _finish(symbol: str, status: str, error: str | None, added: int) -> None:
    with SessionLocal() as db:
        subject = db.get(ArchiveSubject, symbol)
        if subject is not None:
            subject.build_status, subject.build_error = status, (error[:64] if error else None)
            subject.build_finished_at, subject.filings_added = _now(), added
            db.commit()


def _guard(provider, started: float, deadline_seconds: float) -> None:
    """Refuse every SEC request of this provider once the build's deadline passed or a stop was asked for (throttle and headers are untouched)."""
    raw = getattr(provider, "_get_bytes", None)
    if raw is None:
        return

    def guarded(*args, **kwargs):
        _check(started, deadline_seconds)
        return raw(*args, **kwargs)
    provider._get_bytes = guarded


def _check(started: float, deadline_seconds: float) -> None:
    if _STOPPING.is_set():
        raise _BuildStop("stopping")
    if _monotonic() - started > deadline_seconds:
        raise _BuildStop("deadline")


def _plan(db, symbol: str, today) -> tuple[list[str], list[str], list[str]]:
    """What a build reads: the latest annual report; every 10-Q of the last fifteen months (at most six); the 8-Ks of the last fifteen months,
    newest first, at most thirty looked at (each costs an index, an exhibit and sometimes the primary document: up to three requests), of
    which only those whose Exhibit 99.1 turns out to be an earnings release are counted."""
    since = today - timedelta(days=WINDOW_DAYS)
    rows = db.execute(select(SecFilingInventory.accession_number, SecFilingInventory.form, SecFilingInventory.filed_at)
                      .where(SecFilingInventory.symbol == symbol)
                      .order_by(SecFilingInventory.filed_at.desc(), SecFilingInventory.accession_number.desc())).all()
    annual = [a for a, f, d in rows if f in ANNUAL_FORMS][:1]
    quarterly = [a for a, f, d in rows if f == "10-Q" and d is not None and d >= since][:MAX_QUARTERLY]
    eight_k = [a for a, f, d in rows if f == "8-K" and d is not None and d >= since][:MAX_8K_EXAMINED]
    return annual, quarterly, eight_k


def _revenue_quarter_ok(symbol: str) -> bool:
    with SessionLocal() as db:
        return bool(db.scalar(select(func.count()).select_from(CompanyFact).where(
            CompanyFact.symbol == symbol, CompanyFact.metric == "revenue", CompanyFact.span == "quarter", CompanyFact.status == "ok")))


def build(symbol: str, *, deadline_seconds: float = BUILD_WALL_SECONDS) -> dict:
    """Scan the company's filings, read the ones that matter (``_plan``), rebuild its facts once.  ``ok`` only if the archive is then really
    there; ``partial`` if some filings were stored but something is missing (``error`` names it: ``deadline``, ``stopping``, ``sec_unavailable``,
    ``unavailable``, ``xbrl_429``, ``no_figures``, ``no_facts``...); ``failed`` if nothing was stored.  Records its own outcome; never raises."""
    symbol = symbol.strip().upper()
    started = _monotonic()
    out = {"symbol": symbol, "status": "failed", "error": None, "filings_added": 0, "fetched": 0, "releases": 0, "with_figures": 0, "facts": None}
    try:
        with SessionLocal() as db:
            subject = db.get(ArchiveSubject, symbol)
            if subject is None:
                return {**out, "error": "no_subject"}
            subject.build_status, subject.build_started_at, subject.build_error = "building", _now(), None
            db.commit()
        provider = _provider()
        _guard(provider, started, deadline_seconds)
        errors: list = []
        try:
            _check(started, deadline_seconds)
            with SessionLocal() as db:
                _, created, _ = scan_sec_filings(symbol=symbol, db=db, provider=provider)
                out["filings_added"] = created
                annual, quarterly, eight_k = _plan(db, symbol, _now().date())
                unavailable, in_a_row = 0, 0
                for accession in annual + quarterly + eight_k:
                    _check(started, deadline_seconds)
                    filing, cached = fetch_inventory_content(symbol=symbol, accession_number=accession, db=db, provider=provider,
                                                             refresh_facts=False, xbrl_errors=errors)
                    if filing.content_status != "fetched":
                        unavailable, in_a_row = unavailable + 1, in_a_row + 1
                        if in_a_row >= STOP_AFTER_UNAVAILABLE:
                            out["error"] = "sec_unavailable"
                            break
                        continue
                    in_a_row = 0
                    out["fetched"] += 1
                    if filing.form == "8-K":
                        out["releases"] += filing.content_kind == "exhibit_99_1"
                    elif filing.form in FIGURE_FORMS:
                        if not filing.content_financials and cached:      # stored earlier without figures: ask XBRL again, not the body
                            store_inventory_figures(symbol=symbol, accession_number=accession, db=db, provider=provider, xbrl_errors=errors)
                            db.refresh(filing)
                        out["with_figures"] += bool(filing.content_financials)
                if out["error"] is None and unavailable:
                    out["error"] = "unavailable"
            if out["error"] != "sec_unavailable":
                _check(started, deadline_seconds)
            if out["with_figures"] or out["fetched"]:
                try:
                    out["facts"] = _refresh_facts(symbol).get("facts")
                except Exception as exc:  # noqa: BLE001 - the filings are stored; the six-hour sweep retries the facts
                    log.warning("archive build of %s: facts refresh failed (%s)", symbol, type(exc).__name__)
        except _BuildStop as stop:
            out["error"] = str(stop)
        if out["error"] in (None, "unavailable"):
            missing = None
            if not out["with_figures"]:
                missing = _xbrl_problem(errors) or "no_figures"
            elif not _revenue_quarter_ok(symbol):
                missing = "no_facts"
            out["error"] = missing or out["error"]
        if out["error"] is None:
            out["status"] = "ok"
        else:
            out["status"] = "partial" if (out["fetched"] or out["filings_added"]) else "failed"
    except Exception as exc:  # noqa: BLE001 - a build never takes the worker down
        out["error"] = _reason(exc)
        out["status"] = "partial" if out["fetched"] else "failed"
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
    """Build every waiting company, one at a time (the worker's job, callable on its own); returns how many it built.  Stops between builds
    (and, through the build's guard, at the next SEC request) once ``stop`` was called."""
    done = 0
    _IDLE.clear()
    try:
        while not _STOPPING.is_set() and (symbol := _claim_next()) is not None:
            try:
                build(symbol)
            except Exception:  # noqa: BLE001
                log.exception("archive build of %s escaped", symbol)
            done += 1
    finally:
        _IDLE.set()
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
    """``FINBOT_ARCHIVE_BUILDS`` on/off; unset, the worker runs wherever the background loops do (so a shadow copy of the API does not build)."""
    value = os.environ.get("FINBOT_ARCHIVE_BUILDS")
    if value is None:
        from .background import enabled
        return enabled()
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
            await asyncio.to_thread(refresh_ticker_list)
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
    if (task is not None and not task.done()) or not _IDLE.is_set():
        return                                       # one worker at a time, a draining thread of an earlier one included
    _STOPPING.clear()
    event = asyncio.Event()
    _STATE.update(loop=current, event=event, task=current.create_task(_work(event), name="archive-worker"))


async def stop() -> None:
    """Ask the worker to stop: no new build, the running one ends at its next SEC request; waits a bounded time for the thread."""
    task = _STATE["task"]
    _STATE.update(task=None, loop=None, event=None)
    _STOPPING.set()
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    if await asyncio.to_thread(_IDLE.wait, STOP_WAIT_SECONDS):
        _STOPPING.clear()


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
    refresh_ticker_list()
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
