"""The daily missed-alert check: every morning (Beijing 07:45) code compares what should have reached the owner with what did.

Two checks, no model call:

* earnings of held symbols since the last check that ran (else the last 14 days): an ``earnings_events`` row that failed, one still
  ``received`` / ``analysing`` an hour after it came in, and a sentinel ``earnings_seen`` row that never became an event;
* prices of the last New York session: the sentinel's own policy replayed over that session's 5-minute bars (``sentinel.replay``), against
  the live ``alerts`` table.  A replayed alert is missed only when the live table has no alert at all on any of its symbols that New York
  date: the replay reads 5-minute bars and the live loop 1-minute bars, so a different alert on the same symbol is not a miss.

The sentinel's database is opened read-only.  Each check runs in its own ``try``: one that fails leaves its error under
``checked["errors"]`` and the other still runs.  The findings ride in the next morning brief (``kernel.brief``).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import time
from datetime import UTC, date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from sentinel import replay
from sentinel import rules as owner_rules
from sentinel.store import db_path as sentinel_db_path

from .. import duty_selfcheck, sentinel_bridge
from ..agent_chat_models import EarningsEvent
from ..database import SessionLocal
from . import wake

logger = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
ET = ZoneInfo("America/New_York")
DUE_AT = (7, 45)
LAST_HOUR = 12
STUCK = timedelta(minutes=60)
WINDOW_FIRST = timedelta(days=14)
MINUTE = "%Y-%m-%d %H:%M"
COUNTED_KINDS = ("rule", "preset", "plan_add", "plan_stop", "plan_target")
WHY_FAILED = "财报解读试了三次都没做成"
WHY_STUCK = "收到一个多小时了还没发出"
WHY_UNSEEN = "盯盘程序看到了这份财报，但没交到解读那一步"
OFF = "FINBOT_DUTY_MODE=off"


def due_day(now: datetime) -> str | None:
    """The Beijing date when ``now`` (aware) is between 07:45 inclusive and 12:00 exclusive Beijing, else None."""
    local = now.astimezone(BEIJING)
    if (local.hour, local.minute) >= DUE_AT and local.hour < LAST_HOUR:
        return local.date().isoformat()
    return None


def session_day(now: datetime) -> date | None:
    """The New York date of ``now`` when it is a weekday there and 16:00 or later, else None (a weekend, or before the close)."""
    local = now.astimezone(ET)
    if local.weekday() < 5 and local.hour >= 16:
        return local.date()
    return None


def held_symbols(snapshot: dict) -> set[str]:
    """The symbols of the snapshot's positions that have shares."""
    return {p["symbol"] for p in snapshot.get("positions") or [] if p.get("symbol") and p.get("shares")}


def watched_symbols(snapshot: dict) -> set[str]:
    """Holdings and the research queue: the companies whose earnings he expects to hear about.  A queue company's earnings are only
    recorded, not pushed, but a reader that failed records nothing (the 11-17 NVDA miss was a queue company)."""
    return held_symbols(snapshot) | {s for s in snapshot.get("research_queue") or [] if isinstance(s, str) and s}


def _replay_symbols(snapshot: dict) -> list[str]:
    """Held, then the research queue, then symbols only an owner rule names: the symbols ``replay.run_replay`` looks at."""
    held = [p["symbol"] for p in snapshot.get("positions") or [] if p.get("symbol") and p.get("shares")]
    queue = [s for s in snapshot.get("research_queue") or [] if s not in held]
    named = sorted({owner_rules.symbol_of(r) for r in snapshot.get("rules") or [] if owner_rules.valid(r)} - set(held) - set(queue))
    return list(dict.fromkeys(held + queue + named))


def _read(db_path, query: str, params: tuple) -> list[sqlite3.Row]:
    """Rows of the sentinel's database, read-only (a WAL copy without its -shm needs ``immutable``, as ``replay.compare_actual`` does)."""
    for mode in ("mode=ro", "mode=ro&immutable=1"):
        conn = sqlite3.connect(f"file:{db_path}?{mode}", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            if mode != "mode=ro":
                raise
        finally:
            conn.close()
    return []


def _bj(value: datetime | float) -> str:
    when = datetime.fromtimestamp(value, UTC) if isinstance(value, (int, float)) else value
    return when.astimezone(BEIJING).strftime(MINUTE)


# --- earnings -----------------------------------------------------------------------------------------------------------

def earnings_findings(owner: str, since: datetime, now: datetime, held: set[str], sentinel_db) -> tuple[list, dict]:
    """The earnings of held symbols filed since ``since`` (at most ``WINDOW_FIRST`` back) that did not reach him and no earlier check has
    reported.  The window is on the filing, not on when it failed: an event that came in before the last check and failed after it is
    still found.  A sentinel database that cannot be read leaves the events' findings standing and says so under ``"error"``."""
    since = min(since, now - WINDOW_FIRST)
    reported = duty_selfcheck.reported_accessions(owner)
    with SessionLocal() as db:
        events = db.scalars(select(EarningsEvent).where(EarningsEvent.owner_hash == owner, EarningsEvent.created_at >= since,
                                                        EarningsEvent.created_at < now)).all()
        rows = [{"symbol": e.symbol, "accession": e.accession, "status": e.status, "attempts": e.attempts, "url": e.source_url or "",
                 "accepted_at": e.accepted_at, "created_at": e.created_at} for e in events]
    counts: dict = {"earnings_events": len(rows), "earnings_seen": 0}
    seen: list[sqlite3.Row] = []
    try:
        seen = _read(sentinel_db, "SELECT accession, symbol, url, accepted_at, detected_at FROM earnings_seen WHERE seeded = 0"
                     " AND detected_at >= ? AND detected_at < ? ORDER BY detected_at", (since.timestamp(), now.timestamp()))
        counts["earnings_seen"] = len(seen)
    except Exception as exc:          # without the sentinel's rows the events still say what failed
        counts["error"] = f"earnings_seen: {type(exc).__name__}: {exc}"
    urls = {row["accession"]: row["url"] or "" for row in seen}
    findings = []
    for row in rows:
        if row["symbol"] not in held:
            continue
        if row["status"] == "failed":
            why = WHY_FAILED
        elif row["status"] in ("received", "analysing") and now - row["created_at"] > STUCK:
            why = WHY_STUCK
        else:
            continue
        if row["accession"] in reported:
            continue
        findings.append({"kind": "earnings", "symbol": row["symbol"], "at": _bj(row["accepted_at"]), "why": why, "accession": row["accession"],
                         "text": f"status={row['status']} attempts={row['attempts']}", "url": row["url"] or urls.get(row["accession"], "")})
    unseen = [row for row in seen if row["symbol"] in held]
    if unseen:
        with SessionLocal() as db:
            known = set(db.scalars(select(EarningsEvent.accession).where(EarningsEvent.owner_hash == owner,
                                                                         EarningsEvent.accession.in_([r["accession"] for r in unseen]))))
        for row in unseen:
            if row["accession"] not in known and row["accession"] not in reported:
                findings.append({"kind": "earnings", "symbol": row["symbol"], "at": _bj(float(row["accepted_at"])), "why": WHY_UNSEEN,
                                 "accession": row["accession"],
                                 "text": "earnings_seen without an earnings_events row", "url": row["url"] or ""})
    return findings, counts


# --- prices -------------------------------------------------------------------------------------------------------------

def _policy() -> str:
    return (os.environ.get("SENTINEL_ALERT_POLICY") or "tiers").strip().lower()


def _live_symbols(sentinel_db, day: date) -> tuple[set[str], int]:
    """The symbols the live sentinel alerted on that New York date (any kind but the earnings ones), and how many rows that was."""
    lo = datetime.combine(day, dtime(0, 0), tzinfo=ET).timestamp()
    hi = datetime.combine(day + timedelta(days=1), dtime(0, 0), tzinfo=ET).timestamp()
    rows = _read(sentinel_db, "SELECT symbol, kind FROM alerts WHERE created_at >= ? AND created_at < ?", (lo, hi))
    rows = [r for r in rows if not str(r["kind"] or "").startswith("earnings")]
    return {s for r in rows for s in str(r["symbol"]).split("+") if s}, len(rows)


def price_findings(day: date, snapshot: dict, sentinel_db, fetch=None) -> tuple[list, dict]:
    """The alerts the sentinel's policy would have sent on the New York date ``day`` with no live alert on their symbols that date.
    ``fetch(symbols)`` returns the bars (``replay.fetch_data`` by default; tests pass scripted bars)."""
    symbols = _replay_symbols(snapshot)
    data = (fetch or replay.fetch_data)(symbols + ([] if "SPY" in symbols else ["SPY"]))    # SPY: the tiers policy's market move
    with tempfile.TemporaryDirectory(prefix="selfcheck-replay-") as workdir:
        result = replay.run_replay(data, snapshot, day, day, policy=_policy(), workdir=workdir)
    counted = sorted((a for a in result["alerts"] if a.get("tier") in (1, 2) or a.get("kind") in COUNTED_KINDS), key=lambda a: a["ts"])
    live, live_rows = _live_symbols(sentinel_db, day)
    findings, told = [], set()
    for alert in counted:
        names = alert.get("symbols") or [alert["symbol"]]
        if any(s in live or s in told for s in names):
            continue
        told.update(names)
        text = alert.get("text") or ""
        findings.append({"kind": "price", "symbol": alert["symbol"], "at": datetime.fromtimestamp(alert["ts"], ET).strftime(MINUTE),
                         "text": text.strip().splitlines()[0] if text.strip() else "",
                         "why": f"replayed kind={alert.get('kind')} tier={alert.get('tier')}; no live alert on it that New York date"})
    checked = {"price_symbols": symbols, "replayed": len(counted), "live": live_rows}
    if data.get("errors"):
        checked["unfetched"] = sorted(data["errors"])
    return findings, checked


# --- the run ------------------------------------------------------------------------------------------------------------

def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _window_start(owner: str, now: datetime) -> datetime:
    """The newest done check; else 14 days back, so the first check ever reaches the misses before it."""
    last = duty_selfcheck.last_done(owner)
    if last and last.get("created_at"):
        return datetime.fromisoformat(last["created_at"])
    return now - WINDOW_FIRST


def _run(row_id: int, owner: str, now: datetime, since: datetime | None, sentinel_db, snapshot, fetch, began: float) -> dict:
    def finish(**fields) -> dict:
        return duty_selfcheck.finish(row_id, ms=round((time.monotonic() - began) * 1000), **fields)

    if wake.mode() == "off":
        return finish(outcome="skipped_off", reason=OFF)
    sentinel_db = sentinel_db or sentinel_db_path()
    if snapshot is None:
        snapshot = json.loads(sentinel_bridge.snapshot_path().read_text(encoding="utf-8"))
    since = since or _window_start(owner, now)
    findings: list[dict] = []
    checked: dict = {"since": since.isoformat(), "errors": {}}
    try:
        found, counts = earnings_findings(owner, since, now, watched_symbols(snapshot), sentinel_db)
        if "error" in counts:
            checked["errors"]["earnings"] = counts.pop("error")
        findings += found
        checked.update(counts)
    except Exception as exc:
        logger.warning("missed-alert check: the earnings check failed", exc_info=True)
        checked["errors"]["earnings"] = _error(exc)
    session = session_day(now)
    try:
        if session is not None:
            found, counts = price_findings(session, snapshot, sentinel_db, fetch)
            findings += found
            checked.update(counts)
    except Exception as exc:
        logger.warning("missed-alert check: the price check failed", exc_info=True)
        checked["errors"]["price"] = _error(exc)
    findings.sort(key=lambda f: (f.get("kind") or "", f.get("at") or ""))       # earnings (Beijing times) first, then prices (New York times)
    return finish(outcome="done", session=session.isoformat() if session else None, findings=findings, checked=checked)


def run_once(owner: str, now: datetime, *, day: str | None = None, since: datetime | None = None, sentinel_db=None,
             snapshot: dict | None = None, fetch=None) -> dict | None:
    """Run the day's check if it is due and not run yet; returns its ``duty_selfcheck`` row, or None (not due, or the day is taken).
    ``day`` skips the time check and ``since`` replaces the window's start (the shadow replay).  Never raises after the claim."""
    day = day or due_day(now)
    if day is None or duty_selfcheck.get(owner, day) is not None:
        return None
    row_id = duty_selfcheck.claim(owner, day)
    if row_id is None:
        return None
    began = time.monotonic()
    try:
        return _run(row_id, owner, now, since, sentinel_db, snapshot, fetch, began)
    except Exception as exc:
        logger.exception("missed-alert check %s failed", day)
        try:
            return duty_selfcheck.finish(row_id, outcome="failed", reason=_error(exc), ms=round((time.monotonic() - began) * 1000))
        except Exception:
            logger.exception("missed-alert check %s: the failure could not be logged", day)
            return None
