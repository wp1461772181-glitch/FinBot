"""「这事怎么没告诉我」 (design 7.3, the after-the-fact layer): what the owner says he was not told and should have been.

One row each time he says it, in his own words, with the conversation and turn it was said in.  The kernel writes it (``act``'s
``report_missed``, tier 1: his own words, nothing changes but this record), then looks up why and, when a rule would catch it next
time, proposes one on a card.  The rows are the raw material for new watch rules and new ruler questions
(``python -m scripts.missed_reports``): the same thing should not be missed twice.  Nothing here holds a key or a credential.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, String, Text, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

WHAT_MAX = 200
BEIJING = ZoneInfo("Asia/Shanghai")


class MissedReport(Base):
    __tablename__ = "missed_reports"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    what: Mapped[str] = mapped_column(Text, nullable=False)                    # what he says he was not told, in one line
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)             # his own words of that turn
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _line(text) -> str:
    return " ".join(str(text or "").split())[:WHAT_MAX]


def record(owner_hash: str, what: str, *, symbol: str | None = None, quote: str | None = None, conversation_id=None, turn_id=None) -> dict:
    """Store one report and return it.  ``what`` is required (one line); the rest is kept when given."""
    what = _line(what)
    if not what:
        raise ValueError("invalid_arguments")
    row = MissedReport(owner_hash=owner_hash, what=what, symbol=(symbol or "").strip().upper()[:16] or None, quote=_line(quote) or None,
                       conversation_id=_uuid(conversation_id), turn_id=_uuid(turn_id))
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        return as_dict(row)


def as_dict(row: MissedReport) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat(), "created_local": row.created_at.astimezone(BEIJING).strftime("%m-%d %H:%M"),
            "symbol": row.symbol, "what": row.what, "quote": row.quote,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None, "turn_id": str(row.turn_id) if row.turn_id else None}


def recent(owner_hash: str, limit: int = 50) -> list[dict]:
    with SessionLocal() as db:
        return [as_dict(r) for r in db.scalars(select(MissedReport).where(MissedReport.owner_hash == owner_hash)
                                               .order_by(MissedReport.created_at.desc()).limit(limit))]


def recorded_line(row: dict) -> str:
    """The sentence the tool returns: what was recorded, so the model can say it back."""
    return f"已记下：{(row['symbol'] + ' ') if row.get('symbol') else ''}{row['what']}"
