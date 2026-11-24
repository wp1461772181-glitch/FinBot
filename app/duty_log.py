"""The duty log: one row for every alert the sentinel raised and the kernel was woken for (``kernel.wake``).

A row is written whatever happened (decided, failed, no decision, dropped from a full queue, or the feature switched off), so the
owner can read what the agent judged and why before anything is built on it.  One row per owner and alert id: the sentinel may
send an alert more than once, it is judged once.  Nothing here holds a key or a credential.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

MODES = ("off", "shadow", "on")
OUTCOMES = ("decided", "failed", "no_decision", "dropped", "skipped_off")
DECISIONS = ("tell_now", "digest", "record", "ignore")
REASON_MAX = 500
MESSAGE_MAX = 1500


class DutyLog(Base):
    __tablename__ = "duty_log"
    __table_args__ = (UniqueConstraint("owner_hash", "alert_id", name="uq_duty_log_owner_alert"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)          # the alert as the sentinel posted it
    mode: Mapped[str] = mapped_column(String(8), nullable=False)                      # off | shadow | on: the mode when it was judged
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)                  # only for tell_now
    delivery_group: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)     # the outbox group (mode on, tell_now)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)            # opens the turn in the backstage; tags the ledger
    ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def as_dict(row: DutyLog) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None, "owner_hash": row.owner_hash,
            "alert_id": row.alert_id, "event": row.event or {}, "mode": row.mode, "outcome": row.outcome, "decision": row.decision,
            "reason": row.reason, "message": row.message, "delivery_group": str(row.delivery_group) if row.delivery_group else None,
            "turn_id": str(row.turn_id) if row.turn_id else None, "ms": row.ms, "model_calls": row.model_calls}


def get(owner_hash: str, alert_id: int) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(DutyLog).where(DutyLog.owner_hash == owner_hash, DutyLog.alert_id == alert_id))
        return as_dict(row) if row else None


def record(owner_hash: str, alert_id: int, *, event: dict, mode: str, outcome: str, decision: str | None = None,
           reason: str | None = None, message: str | None = None, delivery_group=None, turn_id=None, ms: int = 0,
           model_calls: int = 0) -> dict:
    """Write the alert's row and return it.  An alert id that already has a row keeps it: the first judgement stands."""
    if outcome not in OUTCOMES or (decision is not None and decision not in DECISIONS):
        raise ValueError("invalid_duty_row")
    row = DutyLog(owner_hash=owner_hash, alert_id=int(alert_id), event=event, mode=mode if mode in MODES else "shadow", outcome=outcome,
                  decision=decision, reason=(reason or None) and reason[:REASON_MAX],
                  message=(message or None) if decision == "tell_now" and message else None,
                  delivery_group=delivery_group, turn_id=turn_id, ms=max(0, int(ms)), model_calls=max(0, int(model_calls)))
    if row.message:
        row.message = row.message[:MESSAGE_MAX]
    with SessionLocal() as db:
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return get(owner_hash, int(alert_id)) or {}
        db.refresh(row)
        return as_dict(row)


def recent(owner_hash: str, limit: int = 50, *, decision: str | None = None) -> list[dict]:
    """The owner's rows, newest first (optionally only one decision)."""
    query = select(DutyLog).where(DutyLog.owner_hash == owner_hash)
    if decision is not None:
        query = query.where(DutyLog.decision == decision)
    with SessionLocal() as db:
        return [as_dict(row) for row in db.scalars(query.order_by(DutyLog.created_at.desc(), DutyLog.id.desc()).limit(max(1, int(limit))))]
