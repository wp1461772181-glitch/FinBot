"""The sentinel's alerts copied to WeChat (5c-2b).

The sentinel sends every alert to Telegram itself and posts it to the API (``alert_posted``).  When the owner's channel preference
puts WeChat first, or asks for every channel, the API queues one copy of the alert on WeChat through the outbox (source ``SOURCE``),
once per alert id, at the moment the alert is posted.  The sentinel's own path is not touched.

One ``sentinel_copy`` row per (owner, alert id) records the decision; a preference that wants no copy (the common case) writes none.
A night-held alert (``deferred``) is not copied: it reaches the owner with the 08:00 digest and the morning brief.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

logger = logging.getLogger(__name__)

SOURCE = "sentinel"
CHANNEL = "wechat"
OUTCOMES = ("queued", "skipped_deferred", "skipped_stale", "skipped_unwanted", "skipped_unavailable", "failed")


class SentinelCopy(Base):
    __tablename__ = "sentinel_copy"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)                 # one of OUTCOMES, never skipped_unwanted
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)          # the outbox group of the WeChat row (queued)


def as_dict(row: SentinelCopy) -> dict:
    return {"owner_hash": row.owner_hash, "alert_id": row.alert_id, "created_at": row.created_at.isoformat() if row.created_at else None,
            "outcome": row.outcome, "group_id": str(row.group_id) if row.group_id else None}


def wanted(prefs: dict) -> bool:
    """Whether the preference asks for a WeChat copy: WeChat listed first, or listed at all in mode ``all``.  WeChat as a mere
    fallback behind Telegram gets none (the sentinel's own Telegram send is its path)."""
    listed = list(prefs.get("channels") or [])
    if CHANNEL not in listed:
        return False
    return prefs.get("mode") == "all" or listed[0] == CHANNEL


def _stale(event: dict, now: datetime | None = None) -> bool:
    """The alert was sent longer ago than ``channels.SENTINEL_COPY_STALE`` (its own ``created_at``, not when the API heard of it)."""
    from . import channels
    created = event.get("created_at")
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        return False
    return (now or datetime.now(UTC)) - datetime.fromtimestamp(float(created), UTC) > channels.SENTINEL_COPY_STALE


def copy_to_wechat(owner_hash: str, event: dict) -> dict:
    """Queue the alert ``event`` (as ``wake.clean_event`` returns it) on WeChat when the owner's preference wants it.  Returns the
    alert's row as a dict, or ``{"outcome": "skipped_unwanted"}``.  Never raises: a failure is logged, leaves a ``failed`` row and is
    ``{"outcome": "failed"}`` (the sentinel has its 202 and drops the event, so nothing retries it)."""
    try:
        return _copy(owner_hash, event)
    except Exception:
        alert_id = event.get("alert_id") if isinstance(event, dict) else None
        logger.exception("sentinel copy: alert %s was not copied to WeChat", alert_id)
        _record_failure(owner_hash, alert_id)
        return {"outcome": "failed"}


def _record_failure(owner_hash: str, alert_id) -> None:
    """Leave a ``failed`` row so the miss is visible (the sentinel drops the event once it has its 202: nothing retries it)."""
    try:
        with SessionLocal() as db:
            if isinstance(alert_id, int) and not isinstance(alert_id, bool) and db.get(SentinelCopy, (owner_hash, alert_id)) is None:
                db.add(SentinelCopy(owner_hash=owner_hash, alert_id=alert_id, outcome="failed"))
                db.commit()
    except Exception:
        logger.exception("sentinel copy: the failure of alert %s could not be recorded", alert_id)


def _copy(owner_hash: str, event: dict) -> dict:
    from . import agent_bots, agent_telegram, channels
    from .agent_chat_models import AgentTelegramMessage
    alert_id = int(event["alert_id"])
    with SessionLocal() as db:
        if not wanted(channels.prefs(db, owner_hash)):
            return {"outcome": "skipped_unwanted"}
        found = db.get(SentinelCopy, (owner_hash, alert_id))
        if found is not None:
            return as_dict(found)        # decided before (a re-posted night line, a re-delivered event): nothing more
    bot = agent_bots.ensure_default_bot(owner_hash)
    with SessionLocal() as db:
        if event.get("deferred"):
            outcome = "skipped_deferred"
        elif _stale(event):
            outcome = "skipped_stale"           # a post that waited in the sentinel's queue (the API was down): its price is old
        elif not channels.available(db, owner_hash, CHANNEL, bot):
            outcome = "skipped_unavailable"
        else:
            outcome = "queued"
        row = SentinelCopy(owner_hash=owner_hash, alert_id=alert_id, outcome=outcome)
        db.add(row)
        try:
            db.flush()              # the row first: a second post of the same alert waits here, then finds it
        except IntegrityError:
            db.rollback()
            found = db.get(SentinelCopy, (owner_hash, alert_id))
            return as_dict(found) if found is not None else {"outcome": "failed"}
        if outcome == "queued":
            now = datetime.now(UTC)
            agent_telegram.enqueue(db, owner_hash, bot.id, agent_telegram.render(bot.name, event["text"]), source=SOURCE, now=now,
                                   channels=[CHANNEL])
            rows = list(db.scalars(select(AgentTelegramMessage).where(
                AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.source == SOURCE,
                AgentTelegramMessage.created_at == now, AgentTelegramMessage.bot_id == bot.id)))
            group = next((r.group_id for r in rows if r.group_id), None) or uuid.uuid4()
            for queued in rows:
                queued.group_id = group     # one group per message, as wake._deliver does
            row.group_id = group
        db.commit()
        db.refresh(row)
        return as_dict(row)
