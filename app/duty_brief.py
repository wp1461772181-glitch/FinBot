"""The brief log: one row per owner and Beijing day for the morning brief the kernel writes (``kernel.brief``).

The row is claimed (``running``) before anything else happens, so two workers or a restart never write the same day's brief twice, and
it is finished whatever happened (done, skipped, switched off, failed).  Nothing here holds a key or a credential.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

MODES = ("off", "shadow", "on")
OUTCOMES = ("running", "done", "skipped", "skipped_off", "failed")
FIELDS = ("outcome", "reason", "message", "delivery", "delivery_group", "turn_id", "counts", "ms", "model_calls")


class DutyBrief(Base):
    __tablename__ = "duty_brief"
    __table_args__ = (UniqueConstraint("owner_hash", "day", name="uq_duty_brief_owner_day"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)                     # Beijing date, "2026-11-28"
    mode: Mapped[str] = mapped_column(String(8), nullable=False)                     # off | shadow | on: the mode when it ran
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)                 # the brief as written (also in shadow)
    delivery: Mapped[str | None] = mapped_column(String(32), nullable=True)          # mode on: queued | why nothing was queued
    delivery_group: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)    # the outbox group (mode on)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)           # the model turn, when one ran
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)         # digest, held, record, ignore, told, failed
    ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def as_dict(row: DutyBrief) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None, "owner_hash": row.owner_hash, "day": row.day,
            "mode": row.mode, "outcome": row.outcome, "reason": row.reason, "message": row.message, "delivery": row.delivery,
            "delivery_group": str(row.delivery_group) if row.delivery_group else None, "turn_id": str(row.turn_id) if row.turn_id else None,
            "counts": row.counts or {}, "ms": row.ms, "model_calls": row.model_calls}


def claim(owner_hash: str, day: str, mode: str) -> int | None:
    """Insert the day's ``running`` row and return its id; None when the day already has a row (another worker or an earlier run)."""
    row = DutyBrief(owner_hash=owner_hash, day=day, mode=mode if mode in MODES else "shadow", outcome="running", counts={})
    with SessionLocal() as db:
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return row.id


def _uuid(value):
    return uuid.UUID(str(value)) if value is not None and not isinstance(value, uuid.UUID) else value


def finish(row_id: int, **fields) -> dict:
    """Update the row with ``fields`` (only the known ones) and return it."""
    unknown = set(fields) - set(FIELDS)
    if unknown or ("outcome" in fields and fields["outcome"] not in OUTCOMES):
        raise ValueError("invalid_brief_row")
    with SessionLocal() as db:
        row = db.get(DutyBrief, row_id)
        if row is None:
            raise LookupError("brief_row_missing")
        for key, value in fields.items():
            if key in ("delivery_group", "turn_id"):
                value = _uuid(value)
            elif key in ("ms", "model_calls"):
                value = max(0, int(value or 0))
            elif key == "counts":
                value = dict(value or {})
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return as_dict(row)


def last_done(owner_hash: str) -> dict | None:
    """The owner's newest brief that ran (``done``), or None."""
    with SessionLocal() as db:
        row = db.scalar(select(DutyBrief).where(DutyBrief.owner_hash == owner_hash, DutyBrief.outcome == "done")
                        .order_by(DutyBrief.created_at.desc(), DutyBrief.id.desc()).limit(1))
        return as_dict(row) if row else None


def get(owner_hash: str, day: str) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(DutyBrief).where(DutyBrief.owner_hash == owner_hash, DutyBrief.day == day))
        return as_dict(row) if row else None
