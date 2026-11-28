"""What it said it would come back to (docs/finbot-humanlike-plan-2026-11-28, D): 「这事我过两天再看一眼」, kept so it really does.

The kernel writes one with ``act``'s ``follow_up`` (tier 1: nothing of his changes), cancels one with ``cancel_follow_up``.  When one is due
the background loop hands it to the duty turn (``kernel.wake``, kind ``follow_up``): the model looks again and decides whether there is
anything new to tell him; the message goes through the same outbox, night hold and de-duplication as an alert's.  Limits, so it cannot
pester him: at most ``MAX_OPEN`` open at a time, due between ``MIN_MINUTES`` and ``HORIZON_DAYS`` ahead, at most ``DAILY`` fired a Beijing
day and only between 08:00 and 22:00 Beijing; one left more than ``EXPIRE_DAYS`` past its time is dropped.  ``what`` is the model's own
words and stays data wherever it is shown (the wake shows it inside its labelled data block).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, String, Text, Uuid, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

log = logging.getLogger(__name__)

BEIJING = ZoneInfo("Asia/Shanghai")
MAX_OPEN = 5
DAILY = 1
MIN_MINUTES = 30
HORIZON_DAYS = 30
EXPIRE_DAYS = 7
WAKING_HOURS = (8, 22)          # Beijing: a due one waits for the morning rather than waking him at night
WHAT_MAX = 200
ALERT_BASE = 2**41              # a follow-up's wake id: apart from the sentinel's and the missed-alert resends (selfcheck.RESEND_BASE)
_DUE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?\s*$")


class FollowUp(Base):
    __tablename__ = "agent_follow_ups"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    what: Mapped[str] = mapped_column(Text, nullable=False)                 # what to look at again, in its own words
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)          # his message of that turn
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")      # open | fired | cancelled | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)                # the wake's decision, or why it did not run


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def parse_due(text: str) -> datetime:
    """``YYYY-MM-DD HH:MM`` or ``YYYY-MM-DD`` (09:00), Beijing time, as UTC.  Raises ValueError("invalid_due")."""
    match = _DUE.match(str(text or ""))
    if not match:
        raise ValueError("invalid_due")
    year, month, day, hour, minute = match.groups()
    try:
        local = datetime(int(year), int(month), int(day), int(hour or 9), int(minute or 0), tzinfo=BEIJING)
    except ValueError as exc:
        raise ValueError("invalid_due") from exc
    return local.astimezone(UTC)


def as_dict(row: FollowUp) -> dict:
    return {"id": row.id, "what": row.what, "symbol": row.symbol, "status": row.status, "due_at": row.due_at.isoformat(),
            "due_label": due_label(row.due_at), "created_at": row.created_at.isoformat() if row.created_at else None,
            "fired_at": row.fired_at.isoformat() if row.fired_at else None, "outcome": row.outcome,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None}


def due_label(at: datetime) -> str:
    local = at.astimezone(BEIJING)
    return f"{local:%m-%d %H:%M}"


def check(owner_hash: str, due_at: datetime, now: datetime | None = None) -> None:
    """Whether one more may be added now: raises ValueError with the short code the act result explains."""
    now = now or datetime.now(UTC)
    if due_at < now + timedelta(minutes=MIN_MINUTES):
        raise ValueError("due_too_soon")
    if due_at > now + timedelta(days=HORIZON_DAYS):
        raise ValueError("due_too_far")
    with SessionLocal() as db:
        count = int(db.scalar(select(func.count()).select_from(FollowUp).where(FollowUp.owner_hash == owner_hash, FollowUp.status == "open")) or 0)
    if count >= MAX_OPEN:
        raise ValueError("too_many_follow_ups")


def add(owner_hash: str, what: str, due_at: datetime, *, symbol: str | None = None, bot_id=None, conversation_id=None, turn_id=None,
        quote: str | None = None, now: datetime | None = None) -> dict:
    what = " ".join(str(what or "").split())
    if not what or len(what) > WHAT_MAX:
        raise ValueError("invalid_what")
    check(owner_hash, due_at, now)
    with SessionLocal() as db:
        row = FollowUp(owner_hash=owner_hash, what=what, due_at=due_at, symbol=(symbol or "").upper()[:16] or None, bot_id=_uuid(bot_id),
                       conversation_id=_uuid(conversation_id), turn_id=_uuid(turn_id), quote=(quote or "")[:500] or None,
                       created_at=now or datetime.now(UTC))
        db.add(row)
        db.commit()
        return as_dict(row)


def cancel(owner_hash: str, follow_up_id: int) -> dict | None:
    with SessionLocal() as db:
        row = db.get(FollowUp, int(follow_up_id))
        if row is None or row.owner_hash != owner_hash or row.status != "open":
            return None
        row.status = "cancelled"
        db.commit()
        return as_dict(row)


def open_items(owner_hash: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(FollowUp).where(FollowUp.owner_hash == owner_hash, FollowUp.status == "open").order_by(FollowUp.due_at))
        return [as_dict(r) for r in rows]


def open_lines(owner_hash: str) -> str | None:
    """The open ones as the kernel sees them each turn (after the cache point), so it can cancel one or not promise it twice."""
    try:
        items = open_items(owner_hash)
    except Exception:
        return None
    if not items:
        return None
    lines = [f"- #{i['id']} {i['due_label']}{(' ' + i['symbol']) if i['symbol'] else ''}：{i['what']}" for i in items]
    return "你记着要回头看的事（北京时间；他说不用了就用 cancel_follow_up 取消）：\n" + "\n".join(lines)


def _fired_today(db, owner_hash: str, now: datetime) -> int:
    start = now.astimezone(BEIJING).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return int(db.scalar(select(func.count()).select_from(FollowUp).where(FollowUp.owner_hash == owner_hash, FollowUp.fired_at >= start)) or 0)


def take_due(owner_hash: str, now: datetime | None = None) -> list[dict]:
    """Mark as fired (and return) what may go to the duty turn now: due, within today's allowance and the waking hours; drop the stale."""
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        for row in db.scalars(select(FollowUp).where(FollowUp.owner_hash == owner_hash, FollowUp.status == "open",
                                                     FollowUp.due_at < now - timedelta(days=EXPIRE_DAYS))):
            row.status, row.outcome = "expired", "expired"
        db.commit()
        hour = now.astimezone(BEIJING).hour
        if not (WAKING_HOURS[0] <= hour < WAKING_HOURS[1]):
            return []
        room = DAILY - _fired_today(db, owner_hash, now)
        if room <= 0:
            return []
        rows = list(db.scalars(select(FollowUp).where(FollowUp.owner_hash == owner_hash, FollowUp.status == "open", FollowUp.due_at <= now)
                               .order_by(FollowUp.due_at).limit(room)))
        for row in rows:
            row.status, row.fired_at = "fired", now
        db.commit()
        return [as_dict(r) | {"quote": r.quote} for r in rows]


def set_outcome(follow_up_id: int, outcome: str) -> None:
    with SessionLocal() as db:
        row = db.get(FollowUp, int(follow_up_id))
        if row is not None:
            row.outcome = str(outcome or "")[:40]
            db.commit()


def wake_event(item: dict) -> dict:
    """The duty turn's event of one follow-up (``kernel.wake``): kind ``follow_up``, its own words as data."""
    return {"alert_id": ALERT_BASE + int(item["id"]), "symbol": item.get("symbol") or "—", "kind": "follow_up",
            "text": f"【跟进】{item['what']}", "follow_up": {"what": item["what"], "said_on": (item.get("created_at") or "")[:10],
                                                        "due": item["due_label"], "his_words_then": (item.get("quote") or "")[:300]}}


def run_due(owner_hash: str, now: datetime | None = None) -> list[dict]:
    """The background loop's pass: each follow-up that may go now goes to the duty turn, one at a time; returns their duty rows."""
    import asyncio

    from .kernel import wake
    judged = []
    for item in take_due(owner_hash, now):
        try:
            row = asyncio.run(wake.wake(wake_event(item), owner_hash=owner_hash))
            set_outcome(item["id"], (row or {}).get("decision") or (row or {}).get("outcome") or "")
            judged.append(row)
        except Exception:
            log.exception("follow-up %s could not be judged", item["id"])
            set_outcome(item["id"], "failed")
    return judged
