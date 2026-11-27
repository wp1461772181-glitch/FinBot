"""The missed-alert check log: one row per owner and Beijing day for the daily check the kernel runs (``kernel.selfcheck``).

The row is claimed (``running``) before anything else happens, so two workers or a restart never run the same day's check twice, and
it is finished whatever happened (done, switched off, failed).  The morning brief reads the findings of the done rows.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

OUTCOMES = ("running", "done", "skipped_off", "failed")
FIELDS = ("outcome", "reason", "session", "findings", "checked", "ms")


class DutySelfcheck(Base):
    __tablename__ = "duty_selfcheck"
    __table_args__ = (UniqueConstraint("owner_hash", "day", name="uq_duty_selfcheck_owner_day"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)                     # Beijing date, "2026-11-28"
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped[str | None] = mapped_column(String(10), nullable=True)           # the New York date the price check covered
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)       # [{kind, symbol, at, text, why, url?}]
    checked: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)        # counts, symbols and errors of the two checks
    ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    briefed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # the morning brief carried its findings


def as_dict(row: DutySelfcheck) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None, "owner_hash": row.owner_hash, "day": row.day,
            "outcome": row.outcome, "reason": row.reason, "session": row.session, "findings": list(row.findings or []),
            "checked": dict(row.checked or {}), "briefed_at": row.briefed_at.isoformat() if row.briefed_at else None, "ms": row.ms}


def claim(owner_hash: str, day: str) -> int | None:
    """Insert the day's ``running`` row and return its id; None when the day already has a row (another worker or an earlier run)."""
    row = DutySelfcheck(owner_hash=owner_hash, day=day, outcome="running", findings=[], checked={})
    with SessionLocal() as db:
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return row.id


def finish(row_id: int, **fields) -> dict:
    """Update the row with ``fields`` (only the known ones) and return it."""
    unknown = set(fields) - set(FIELDS)
    if unknown or ("outcome" in fields and fields["outcome"] not in OUTCOMES):
        raise ValueError("invalid_selfcheck_row")
    with SessionLocal() as db:
        row = db.get(DutySelfcheck, row_id)
        if row is None:
            raise LookupError("selfcheck_row_missing")
        for key, value in fields.items():
            if key == "ms":
                value = max(0, int(value or 0))
            elif key == "findings":
                value = list(value or [])
            elif key == "checked":
                value = dict(value or {})
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return as_dict(row)


def get(owner_hash: str, day: str) -> dict | None:
    """The owner's row for ``day``, or None."""
    with SessionLocal() as db:
        row = db.scalar(select(DutySelfcheck).where(DutySelfcheck.owner_hash == owner_hash, DutySelfcheck.day == day))
        return as_dict(row) if row else None


def last_done(owner_hash: str) -> dict | None:
    """The owner's newest check that ran (``done``), or None."""
    with SessionLocal() as db:
        row = db.scalar(select(DutySelfcheck).where(DutySelfcheck.owner_hash == owner_hash, DutySelfcheck.outcome == "done")
                        .order_by(DutySelfcheck.created_at.desc(), DutySelfcheck.id.desc()).limit(1))
        return as_dict(row) if row else None


def since(owner_hash: str, after: datetime) -> list[dict]:
    """The owner's done checks created after ``after``, oldest first."""
    with SessionLocal() as db:
        rows = db.scalars(select(DutySelfcheck).where(DutySelfcheck.owner_hash == owner_hash, DutySelfcheck.outcome == "done",
                                                      DutySelfcheck.created_at > after)
                          .order_by(DutySelfcheck.created_at.asc(), DutySelfcheck.id.asc())).all()
        return [as_dict(row) for row in rows]


def unbriefed(owner_hash: str) -> list[dict]:
    """The owner's done checks whose findings no morning brief has carried yet, oldest first (a check that ends after the day's brief
    is carried by the next one)."""
    with SessionLocal() as db:
        rows = db.scalars(select(DutySelfcheck).where(DutySelfcheck.owner_hash == owner_hash, DutySelfcheck.outcome == "done",
                                                      DutySelfcheck.briefed_at.is_(None))
                          .order_by(DutySelfcheck.created_at.asc(), DutySelfcheck.id.asc())).all()
        return [as_dict(row) for row in rows]


def mark_briefed(row_ids: list[int]) -> None:
    """The morning brief carried these checks' findings."""
    ids = [int(i) for i in row_ids or []]
    if not ids:
        return
    with SessionLocal() as db:
        for row in db.scalars(select(DutySelfcheck).where(DutySelfcheck.id.in_(ids))):
            row.briefed_at = datetime.now(UTC)
        db.commit()


def reported_accessions(owner_hash: str) -> set[str]:
    """The filings an earlier done check already reported as missed: each is told once."""
    with SessionLocal() as db:
        found = db.scalars(select(DutySelfcheck.findings).where(DutySelfcheck.owner_hash == owner_hash, DutySelfcheck.outcome == "done")).all()
    return {f["accession"] for findings in found for f in (findings or []) if isinstance(f, dict) and f.get("accession")}
