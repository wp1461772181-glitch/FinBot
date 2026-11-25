"""The owner's own view of each company (「你的看法」): what he said he thinks of it, in his words, with a history.

A view is one line the model renders (``text``) next to the owner's own words (``quote``), found in a message of the turn that recorded it.
It is not evidence and it authorizes nothing: it only lets the next turn know what the owner already thinks.  One version is active per
(owner, symbol); recording a new one marks the old ``superseded`` (with its end date), ``drop`` marks the active one ``dropped``.  Nothing
is deleted here; only the owner, on the web page, removes one version (``delete_version``).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text as sql

from .agent_chat_models import OwnerView
from .company_directory import ALIASES
from .database import SessionLocal
from .symbols import normalize_market_symbol

TEXT_MAX_CHARS = 200
QUOTE_MAX_CHARS = 400
QUOTE_MIN_CHARS = 4          # after whitespace folding: a view's own rule (remember keeps profile.QUOTE_MIN_CHARS); a trivial quote could anchor any text
ACTIVE, SUPERSEDED, DROPPED, ARCHIVED = "active", "superseded", "dropped", "archived"
STATUS_LABELS = {SUPERSEDED: "已更新", DROPPED: "已撤回", ARCHIVED: "已归档"}
ARCHIVE_REASON_MAX = 80
RESTORE_BLOCKED = "这家公司已有一条当前看法，先撤回它再恢复"
NOT_RECOGNIZED = "没认出是哪家公司；用代码再说一次"


class ViewError(ValueError):
    """A short code the caller may show; never the rejected text."""


def resolve_symbol(value) -> str | None:
    """The ticker a company name or ticker names: the 2a name table first (「英伟达」, nvidia), else the ticker itself; None when it is neither."""
    word = " ".join(str(value or "").split()).casefold()
    if not word:
        return None
    if word in ALIASES:
        return ALIASES[word]
    try:
        return normalize_market_symbol(word)
    except ValueError:
        return None


def display_name(symbol: str) -> str:
    """The Chinese name the owner uses for a company, else its ticker."""
    from .company_directory import COMPANIES
    return next((n for n in COMPANIES.get(symbol, ()) if not n.isascii()), symbol)


def _plain(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def serialize(row: OwnerView) -> dict:
    return {"id": str(row.id), "symbol": row.symbol, "text": row.text, "quote": row.quote, "status": row.status,
            "status_label": STATUS_LABELS.get(row.status, ""), "source_message_id": str(row.source_message_id) if row.source_message_id else None,
            "conversation_id": str(row.conversation_id) if row.conversation_id else None, "turn_id": str(row.turn_id) if row.turn_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None, "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "archived_reason": row.archived_reason}


def ensure_archive_column() -> None:
    """Add the archive reason (stage 4c) to a table made before it.  A fresh database gets it from the model."""
    from .database import engine
    with engine.begin() as connection:
        connection.execute(sql("ALTER TABLE owner_views ADD COLUMN IF NOT EXISTS archived_reason VARCHAR(80)"))


def _lock(db, owner_hash: str, symbol: str) -> None:
    # One writer per (owner, company): two turns finishing together cannot both leave an active version.
    db.execute(sql("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"views:{owner_hash}:{symbol}"})


def _active(db, owner_hash: str, symbol: str) -> OwnerView | None:
    return db.scalar(select(OwnerView).where(OwnerView.owner_hash == owner_hash, OwnerView.symbol == symbol, OwnerView.status == ACTIVE))


def record(owner_hash: str, symbol: str, text: str, quote: str, source_message_id=None, conversation_id=None, turn_id=None,
           *, at: datetime | None = None) -> dict:
    """Make ``text`` the active view of ``symbol``; the one it replaces is kept, marked superseded at the same moment.

    Returns ``{status: recorded|unchanged, view, replaced}`` (``replaced`` is the earlier version, or None).  The quote is the caller's to
    check against the owner's message; here only its shape is."""
    symbol = resolve_symbol(symbol)
    text, quote = " ".join(str(text or "").split()), " ".join(str(quote or "").split())
    if not symbol:
        raise ViewError("company_not_recognized")
    if not text or len(text) > TEXT_MAX_CHARS:
        raise ViewError("invalid_view_text")
    if len("".join(quote.split())) < QUOTE_MIN_CHARS:
        raise ViewError("view_quote_too_short")
    if len(quote) > QUOTE_MAX_CHARS:
        raise ViewError("invalid_view_quote")
    now = at or datetime.now(UTC)
    with SessionLocal() as db:
        _lock(db, owner_hash, symbol)
        old = _active(db, owner_hash, symbol)
        if old and _plain(old.text) == _plain(text):
            return {"status": "unchanged", "view": serialize(old), "replaced": None}
        replaced = None
        if old:
            old.status, old.ended_at = SUPERSEDED, now
            db.flush()          # the old version leaves the active slot before the new one takes it
            replaced = serialize(old)
        row = OwnerView(owner_hash=owner_hash, symbol=symbol, text=text, quote=quote, source_message_id=_uuid(source_message_id),
                        conversation_id=_uuid(conversation_id), turn_id=_uuid(turn_id), status=ACTIVE, created_at=now)
        db.add(row)
        db.commit()
        return {"status": "recorded", "view": serialize(row), "replaced": replaced}


def drop(owner_hash: str, symbol: str, *, at: datetime | None = None) -> dict | None:
    """Withdraw the active view of ``symbol`` (it stays in the history as dropped); None when there is none."""
    symbol = resolve_symbol(symbol)
    if not symbol:
        return None
    with SessionLocal() as db:
        _lock(db, owner_hash, symbol)
        row = _active(db, owner_hash, symbol)
        if row is None:
            return None
        row.status, row.ended_at = DROPPED, at or datetime.now(UTC)
        db.commit()
        return serialize(row)


def current(owner_hash: str, symbols) -> dict[str, dict]:
    """The active view of each of ``symbols`` that has one, by symbol."""
    wanted = [s for s in dict.fromkeys(symbols or ()) if s]
    if not owner_hash or not wanted:
        return {}
    with SessionLocal() as db:
        rows = db.scalars(select(OwnerView).where(OwnerView.owner_hash == owner_hash, OwnerView.status == ACTIVE, OwnerView.symbol.in_(wanted)))
        return {row.symbol: serialize(row) for row in rows}


def all_current(owner_hash: str) -> list[dict]:
    """Every active view the owner has, newest first (the memory page)."""
    with SessionLocal() as db:
        rows = db.scalars(select(OwnerView).where(OwnerView.owner_hash == owner_hash, OwnerView.status == ACTIVE).order_by(OwnerView.created_at.desc()))
        return [serialize(row) for row in rows]


def history(owner_hash: str, symbol: str) -> list[dict]:
    """Every version of the owner's view of one company, newest first (the active one, if any, leads)."""
    symbol = resolve_symbol(symbol)
    if not symbol:
        return []
    with SessionLocal() as db:
        rows = db.scalars(select(OwnerView).where(OwnerView.owner_hash == owner_hash, OwnerView.symbol == symbol)
                          .order_by(OwnerView.created_at.desc(), OwnerView.ended_at.is_(None).desc()))
        return [serialize(row) for row in rows]


def delete_version(owner_hash: str, view_id: str) -> bool:
    """The owner removes one version on the web page.  Another owner's id, or one that is not an id, deletes nothing."""
    key = _uuid(view_id)
    if key is None:
        return False
    with SessionLocal() as db:
        row = db.get(OwnerView, key)
        if row is None or row.owner_hash != owner_hash:
            return False
        db.delete(row)
        db.commit()
        return True


def archive(owner_hash: str, view_id, reason: str, *, at: datetime | None = None) -> dict | None:
    """The quarterly settle sets an active view aside: status ``archived`` with the end date and the reason.  Kept, and restorable.  None when
    the id is not an active view of this owner."""
    key = _uuid(view_id)
    if key is None:
        return None
    with SessionLocal() as db:
        row = db.get(OwnerView, key)
        if row is None or row.owner_hash != owner_hash:
            return None
        _lock(db, owner_hash, row.symbol)
        db.refresh(row)
        if row.status != ACTIVE:
            return None
        row.status, row.ended_at, row.archived_reason = ARCHIVED, at or datetime.now(UTC), " ".join(str(reason or "").split())[:ARCHIVE_REASON_MAX]
        db.commit()
        return serialize(row)


def restore(owner_hash: str, view_id) -> dict | None:
    """The owner brings an archived view back (the memory page).  None when it is not his archived view; ``ViewError("view_active_exists")``
    when the company already has a current one (he withdraws that first)."""
    key = _uuid(view_id)
    if key is None:
        return None
    with SessionLocal() as db:
        row = db.get(OwnerView, key)
        if row is None or row.owner_hash != owner_hash or row.status != ARCHIVED:
            return None
        _lock(db, owner_hash, row.symbol)
        db.refresh(row)
        if row.status != ARCHIVED:
            return None
        if _active(db, owner_hash, row.symbol) is not None:
            raise ViewError("view_active_exists")
        row.status, row.ended_at, row.archived_reason = ACTIVE, None, None
        db.commit()
        return serialize(row)

