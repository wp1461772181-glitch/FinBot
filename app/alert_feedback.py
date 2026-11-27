"""「有用／没用」 on alerts and duty messages (5c-3b).

The owner's verdict on one sentinel alert (target ``sentinel``, its alert id) or on one outbox message of source ``duty`` or ``brief``
(target ``outbox``, its group id).  One row per owner and target: pressing again changes the verdict (the last one wins), the same
verdict twice changes nothing.  The kernel's wake reads the latest verdicts as data.  ``resolve`` finds the message he means when he
rates one in words (5c-3c).  Nothing here holds a key or a credential.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

logger = logging.getLogger(__name__)

TARGETS = ("sentinel", "outbox")
VERDICTS = ("useful", "not_useful")
CHANNELS = ("telegram", "web", "chat")          # chat: said in a conversation (5c-3c), on any channel
VERDICT_WORDS = {"useful": "有用", "not_useful": "没用"}
RESOLVE_WINDOW = timedelta(hours=48)
BEIJING = ZoneInfo("Asia/Shanghai")
SOURCES = ("duty", "brief")          # the outbox sources that carry the buttons
TEXT_MAX = 200
CALLBACK_MAX = 64                    # Telegram's limit on callback_data, in bytes
_VERDICT_OF = {"fu": "useful", "fn": "not_useful"}
_TARGET_OF = {"s": "sentinel", "o": "outbox"}
_ALERT_ID = re.compile(r"[1-9][0-9]{0,17}")
_NAME_LINE = re.compile(r"【[^】\n]{1,40}】")


class AlertFeedback(Base):
    __tablename__ = "alert_feedback"
    __table_args__ = (UniqueConstraint("owner_hash", "target", "target_id", name="uq_alert_feedback_target"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(8), nullable=False)               # sentinel | outbox
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)           # the alert id, or the outbox group id
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)             # useful | not_useful
    channel: Mapped[str] = mapped_column(String(10), nullable=False)             # telegram | web | chat: where the last verdict came from
    symbol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(24), nullable=True)          # the alert kind, or the outbox source
    text: Mapped[str | None] = mapped_column(Text, nullable=True)                # the first line of what was said


def as_dict(row: AlertFeedback) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None, "target": row.target, "target_id": row.target_id,
            "verdict": row.verdict, "channel": row.channel, "symbol": row.symbol, "kind": row.kind, "text": row.text}


def check_target(target, target_id) -> str:
    """The target id in its one accepted form (an alert id as a positive int, a group id as a lowercase uuid); ValueError otherwise."""
    if target not in TARGETS or not isinstance(target_id, str):
        raise ValueError("invalid_feedback")
    if target == "sentinel":
        if not _ALERT_ID.fullmatch(target_id):
            raise ValueError("invalid_feedback")
        return target_id
    try:
        parsed = uuid.UUID(target_id)
    except ValueError:
        raise ValueError("invalid_feedback") from None
    if str(parsed) != target_id:
        raise ValueError("invalid_feedback")
    return target_id


def parse_callback(data) -> tuple[str, str, str] | None:
    """``fu:s:<alert id>`` / ``fn:s:<alert id>`` / ``fu:o:<group id>`` / ``fn:o:<group id>`` as (target, target id, verdict); None for anything else."""
    if not isinstance(data, str) or len(data.encode()) > CALLBACK_MAX:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] not in _VERDICT_OF or parts[1] not in _TARGET_OF:
        return None
    target = _TARGET_OF[parts[1]]
    try:
        target_id = check_target(target, parts[2])
    except ValueError:
        return None
    return target, target_id, _VERDICT_OF[parts[0]]


def _first_line(text) -> str | None:
    """The first line of a message that is not the 「【名字】」 line in front, clipped to ``TEXT_MAX``."""
    if not isinstance(text, str):
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and _NAME_LINE.fullmatch(lines[0]):
        lines = lines[1:]
    return lines[0][:TEXT_MAX] if lines else None


def record(owner_hash: str, target: str, target_id: str, verdict: str, channel: str, *, symbol: str | None = None,
           kind: str | None = None, text: str | None = None) -> dict:
    """Store the owner's verdict on one target and return the row.  A new verdict replaces the old one; the same one again changes nothing."""
    target_id = check_target(target, target_id)
    if verdict not in VERDICTS or channel not in CHANNELS:
        raise ValueError("invalid_feedback")
    symbol = symbol[:80] if isinstance(symbol, str) and symbol else None
    kind = kind[:24] if isinstance(kind, str) and kind else None
    text = _first_line(text)
    where = (AlertFeedback.owner_hash == owner_hash, AlertFeedback.target == target, AlertFeedback.target_id == target_id)
    for _ in range(2):
        now = datetime.now(UTC)
        with SessionLocal() as db:
            row = db.scalar(select(AlertFeedback).where(*where).with_for_update())
            if row is None:
                row = AlertFeedback(owner_hash=owner_hash, target=target, target_id=target_id, verdict=verdict, channel=channel,
                                    symbol=symbol, kind=kind, text=text, created_at=now, updated_at=now)
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:          # another press wrote the row first: update that one
                    db.rollback()
                    continue
                db.refresh(row)
                return as_dict(row)
            if row.verdict != verdict:
                row.verdict, row.channel, row.updated_at = verdict, channel, now
                row.symbol, row.kind, row.text = row.symbol or symbol, row.kind or kind, row.text or text
                db.commit()
                db.refresh(row)
            return as_dict(row)
    raise RuntimeError("alert_feedback_conflict")


# --- what a target was about -------------------------------------------------------------------------------------------

def _sentinel_alert(alert_id: int) -> dict | None:
    """The alert's symbol, kind and text from the sentinel's ``alerts`` table (read-only); None when it cannot be read."""
    from sentinel.store import db_path
    path = db_path()
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute("SELECT symbol, kind, text FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    return {"symbol": row[0], "kind": row[1], "text": row[2]} if row else None


def _outbox_group(owner_hash: str, group_id: str) -> dict:
    from .agent_chat_models import AgentTelegramMessage
    from .duty_brief import DutyBrief
    from .duty_log import DutyLog
    group = uuid.UUID(group_id)
    found: dict = {"symbol": None, "kind": None, "text": None}
    with SessionLocal() as db:
        row = db.scalar(select(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash,
            or_(AgentTelegramMessage.group_id == group, AgentTelegramMessage.id == group)).order_by(AgentTelegramMessage.created_at).limit(1))
        duty = db.scalar(select(DutyLog).where(DutyLog.owner_hash == owner_hash, DutyLog.delivery_group == group).limit(1))
        brief = None if duty else db.scalar(select(DutyBrief).where(DutyBrief.owner_hash == owner_hash, DutyBrief.delivery_group == group).limit(1))
        if duty is not None:
            event = duty.event if isinstance(duty.event, dict) else {}
            found["symbol"] = event.get("symbol") if isinstance(event.get("symbol"), str) else None
            found["text"] = _first_line(duty.message)
        elif brief is not None:
            found["text"] = _first_line(brief.message)
        found["kind"] = row.source if row is not None else "duty" if duty is not None else "brief" if brief is not None else None
        if found["text"] is None and row is not None:
            found["text"] = _first_line(row.text)
    return found


def describe(owner_hash: str, target: str, target_id: str) -> dict:
    """``{"symbol", "kind", "text"}`` of what the target was: from the sentinel's alert, or from the outbox rows and the duty or brief row
    that sent them.  A field that cannot be found stays None; this never raises."""
    empty = {"symbol": None, "kind": None, "text": None}
    try:
        target_id = check_target(target, target_id)
        if target == "sentinel":
            alert = _sentinel_alert(int(target_id))
            if alert is None:
                return empty
            return {"symbol": alert["symbol"] or None, "kind": alert["kind"] or None, "text": _first_line(alert["text"])}
        return _outbox_group(owner_hash, target_id)
    except Exception:
        return empty


# --- which message he means (5c-3c) ----------------------------------------------------------------------------------------

def _names(symbol: str, symbols) -> bool:
    """True when ``symbol`` (upper-cased) is one of ``symbols``."""
    return symbol in {str(s).strip().upper() for s in symbols if isinstance(s, str) and s.strip()}


def _newest_sentinel(since: datetime, until: datetime, symbol: str | None) -> dict | None:
    """The newest alert in the sentinel's ``alerts`` table in the window (read-only); None when there is none or it cannot be read."""
    from sentinel.store import db_path
    path = db_path()
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2.0)
        try:
            # Only what reached him: a member a merged message replaced never did on its own (he saw the merged one); a record line is
            # never sent on its own; a line held over the night reached him with the 08:00 digest, so that is when he saw it.
            seen = "CASE WHEN deferred = 1 THEN digested_at ELSE created_at END"
            rows = conn.execute(f"SELECT id, symbol, kind, text, {seen} AS seen_at FROM alerts WHERE superseded_by IS NULL AND kind != 'record' "
                                f"AND (deferred = 0 OR digested_at IS NOT NULL) AND {seen} >= ? AND {seen} <= ? "
                                f"ORDER BY {seen} DESC, id DESC", (since.timestamp(), until.timestamp())).fetchall()
        finally:
            conn.close()
    except Exception:
        logger.warning("sentinel alerts unreadable; only duty messages are matched", exc_info=True)
        return None
    for alert_id, alert_symbol, kind, text, created_at in rows:
        if symbol and not _names(symbol, str(alert_symbol or "").split("+")):
            continue
        return {"target": "sentinel", "target_id": str(alert_id), "kind": kind or None, "symbol": alert_symbol or None,
                "text": _first_line(text), "at": datetime.fromtimestamp(float(created_at), UTC)}
    return None


def _newest_duty(owner_hash: str, since: datetime, until: datetime, symbol: str | None) -> dict | None:
    """The newest duty message that reached him on its own (told now, mode on, queued) in the window.  A follow-up held over the night
    reached him inside the morning brief: he rates the brief for that."""
    from .duty_log import DutyLog
    with SessionLocal() as db:
        rows = db.scalars(select(DutyLog).where(
            DutyLog.owner_hash == owner_hash, DutyLog.decision == "tell_now", DutyLog.mode == "on", DutyLog.delivery == "queued",
            DutyLog.delivery_group.is_not(None), DutyLog.created_at >= since, DutyLog.created_at <= until)
            .order_by(DutyLog.created_at.desc(), DutyLog.id.desc())).all()
        for row in rows:
            event = row.event if isinstance(row.event, dict) else {}
            named = event.get("symbol") if isinstance(event.get("symbol"), str) else None
            if symbol and not _names(symbol, [named, *(event.get("members") or [])]):
                continue
            return {"target": "outbox", "target_id": str(row.delivery_group), "kind": "duty", "symbol": named,
                    "text": _first_line(row.message), "at": row.created_at}
    return None


def _newest_brief(owner_hash: str, since: datetime, until: datetime) -> dict | None:
    from .duty_brief import DutyBrief
    with SessionLocal() as db:
        row = db.scalar(select(DutyBrief).where(
            DutyBrief.owner_hash == owner_hash, DutyBrief.outcome == "done", DutyBrief.delivery_group.is_not(None),
            DutyBrief.created_at >= since, DutyBrief.created_at <= until).order_by(DutyBrief.created_at.desc(), DutyBrief.id.desc()).limit(1))
        if row is None:
            return None
        return {"target": "outbox", "target_id": str(row.delivery_group), "kind": "brief", "symbol": None,
                "text": _first_line(row.message), "at": row.created_at}


def resolve(owner_hash: str, *, about: str = "alert", symbol: str | None = None, now: datetime | None = None) -> dict | None:
    """The message he means when he rates one in words: the newest that fits within ``RESOLVE_WINDOW``.

    ``about="brief"``: his newest delivered morning brief.  ``about="alert"``: the newer of the newest sentinel alert and the newest duty
    message that reached him, both naming ``symbol`` when it is given.  ``{"target", "target_id", "kind", "symbol", "text", "at"}``, or None."""
    until = now or datetime.now(UTC)
    since = until - RESOLVE_WINDOW
    if about == "brief":
        return _newest_brief(owner_hash, since, until)
    symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None
    found = [m for m in (_newest_sentinel(since, until, symbol), _newest_duty(owner_hash, since, until, symbol)) if m is not None]
    return max(found, key=lambda m: m["at"]) if found else None


def frozen(match: dict) -> dict:
    """``match`` as it is frozen into an operation: plain JSON (the time as an ISO string)."""
    at = match.get("at")
    return {**match, "at": at.astimezone(UTC).isoformat() if isinstance(at, datetime) else at}


def when_text(at) -> str:
    """Beijing time of a match, ``%m-%d %H:%M``; empty when it has none."""
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return ""
    if not isinstance(at, datetime):
        return ""
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(BEIJING).strftime("%m-%d %H:%M")


# --- reading -------------------------------------------------------------------------------------------------------------

def recent(owner_hash: str, limit: int = 10) -> list[dict]:
    """The owner's latest verdicts, newest first."""
    with SessionLocal() as db:
        rows = db.scalars(select(AlertFeedback).where(AlertFeedback.owner_hash == owner_hash)
                          .order_by(AlertFeedback.updated_at.desc(), AlertFeedback.id.desc()).limit(max(1, int(limit))))
        return [as_dict(row) for row in rows]


def counts(owner_hash: str, since: datetime) -> dict:
    """How many targets got each verdict since ``since`` (by when the verdict was last given)."""
    found = {verdict: 0 for verdict in VERDICTS}
    with SessionLocal() as db:
        for verdict, number in db.execute(select(AlertFeedback.verdict, func.count()).where(
                AlertFeedback.owner_hash == owner_hash, AlertFeedback.updated_at >= since).group_by(AlertFeedback.verdict)):
            if verdict in found:
                found[verdict] = int(number)
    return found


def verdicts(owner_hash: str, target: str, target_ids: list[str]) -> dict[str, str]:
    """``{target id: verdict}`` for the ids that have one."""
    ids = [str(i) for i in target_ids if i]
    if not ids:
        return {}
    with SessionLocal() as db:
        return {target_id: verdict for target_id, verdict in db.execute(select(AlertFeedback.target_id, AlertFeedback.verdict).where(
            AlertFeedback.owner_hash == owner_hash, AlertFeedback.target == target, AlertFeedback.target_id.in_(ids)))}
