"""The log of changes to what the assistant keeps about the owner (5d-2): his memory (``agent_profile`` items) and his views of companies
(``owner_views`` versions).

Every function that changes one of those rows calls ``log`` inside its own session, before its own commit: the change and its record are
written together or not at all (a change that is rolled back leaves no event).  ``by`` says who made it: a chat turn, the memory page, the
monthly review, the quarterly settle, a role template, the old pipeline's extraction.  ``basis`` says what it rests on: his quote and the
conversation it came from, the review's examples and run, the item that replaced it.  A consequence of another change (a topic replaced, the
30-item cap, the 20-proposal limit, the 60-day rule) carries the cause's ``by`` and a ``reason``.

The table is append-only, with one exception: when the owner deletes an item, or turns a guess down, ``scrub`` takes its words out of its
earlier events (the text, an edit's old text, the quotes and examples of the basis).  What happened, when and by whom stays.

``backfill`` rebuilds once what happened before this log, from the rows' own timestamps, and marks it ``reconstructed``.  Edits, layer moves,
restores and deletions made before the log left nothing to rebuild from.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, inspect as sa_inspect, or_, select, text as sql, tuple_

from .agent_chat_models import AgentProfileItem, MemoryEvent, OwnerView
from .database import SessionLocal

logger = logging.getLogger(__name__)

TARGETS = ("profile", "view")
PROFILE_ACTIONS = ("added", "noticed", "proposed", "confirmed", "edited", "moved", "archived", "restored", "settled", "rejected", "deleted")
VIEW_ACTIONS = ("recorded", "superseded", "dropped", "archived", "restored", "deleted")
ACTIONS = tuple(dict.fromkeys(PROFILE_ACTIONS + VIEW_ACTIONS))
BYS = ("chat", "page", "review", "settle", "template", "extract", "unknown")
# The reasons the code itself gives (the settle's and a view archive's own sentences are stored as they are written).
REPLACED, CAP, LIMIT, STALE, RESTATED, BOT_DELETED = "replaced", "cap", "limit", "stale", "restated", "bot_deleted"
TEXT_MAX = 200
SCRUBBED = ("quote", "examples")          # what a deletion takes out of an earlier event's basis
_LAYER_KEYS = ("from_bot", "to_bot")      # None there is the global layer, and is kept
_ACTOR_KEYS = ("conversation_id", "turn_id", "message_id", "run", "template")
BACKFILL_LOCK = "memory_events:backfill"


@dataclass(frozen=True)
class Actor:
    """Who made a change, and where it came from: a chat turn (its conversation, turn and message), a review run, a template."""
    by: str
    conversation_id: str | None = None
    turn_id: str | None = None
    message_id: str | None = None
    run: str | None = None
    template: str | None = None

    def __post_init__(self):
        if self.by not in BYS:
            raise ValueError("invalid_memory_actor")

    def basis(self) -> dict:
        return {key: value for key in _ACTOR_KEYS if (value := getattr(self, key))}


def _uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError, AttributeError):
        return None


def _id(value) -> str | None:
    """A uuid as text; anything that is not one (None, "", junk) is None."""
    found = _uuid(value)
    return str(found) if found else None


def chat(conversation_id, turn_id=None, message_id=None) -> Actor:
    """A chat turn (the kernel's or the old pipeline's card): the conversation, the turn and his message, whichever are known."""
    return Actor("chat", conversation_id=_id(conversation_id), turn_id=_id(turn_id), message_id=_id(message_id))


PAGE = Actor("page")
SETTLE = Actor("settle")
UNKNOWN = Actor("unknown")


def review(run) -> Actor:
    return Actor("review", run=_id(run))


def template(template_id) -> Actor:
    return Actor("template", template=str(template_id)[:32] if template_id else None)


def extract(message_id=None) -> Actor:
    return Actor("extract", message_id=_id(message_id))


def _actor(by) -> Actor:
    if by is None:
        return UNKNOWN
    if isinstance(by, Actor):
        return by
    return Actor(str(by))


def _clip(value) -> str | None:
    if value is None:
        return None
    folded = " ".join(str(value).split())
    return folded[:TEXT_MAX] or None


def _json(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


_ready = False


def ensure_table() -> None:
    """The table, for a process that did not run the API's startup (the Telegram bridge, the sentinel, a worker) or a database made before it.
    Once per process; a second process creating it at the same moment is not an error."""
    global _ready
    if _ready:
        return
    from .database import engine
    try:
        MemoryEvent.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        if not sa_inspect(engine).has_table(MemoryEvent.__tablename__):
            raise
    _ready = True


def log(db, owner_hash: str, *, target: str, item_id, action: str, by, at: datetime | None = None, text: str | None = None,
        before: str | None = None, reason: str | None = None, basis: dict | None = None, bot_id=None, symbol: str | None = None,
        reconstructed: bool = False) -> MemoryEvent:
    """Add one event to the caller's session.  Never commits: the caller's commit writes the change and its record together, its rollback
    drops both.  ``by`` is an ``Actor`` (or a ``by`` word, or None: unknown); its conversation, turn, message, run and template join ``basis``."""
    identity = _uuid(item_id)
    if target not in TARGETS or action not in (PROFILE_ACTIONS if target == "profile" else VIEW_ACTIONS) or identity is None:
        raise ValueError("invalid_memory_event")
    actor = _actor(by)
    ensure_table()
    merged = {}
    for key, value in {**actor.basis(), **(basis or {})}.items():
        if value is None and key not in _LAYER_KEYS:
            continue
        if isinstance(value, (str, list, dict)) and not value:
            continue
        merged[key] = _json(value)
    row = MemoryEvent(owner_hash=owner_hash, at=at or datetime.now(UTC), target=target, item_id=identity, action=action, by=actor.by,
                      text=_clip(text), before=_clip(before), reason=_clip(reason), basis=merged or None, bot_id=_uuid(bot_id),
                      symbol=str(symbol)[:12] if symbol else None, reconstructed=reconstructed)
    db.add(row)
    return row


def scrub(db, owner_hash: str, target: str, item_id) -> int:
    """The owner deleted the item (or turned the guess down): every earlier event of it loses its text, an edit's old text and the quotes and
    examples of its basis; ``action``, ``at`` and ``by`` stay.  In the caller's session, never committed here.  Returns how many changed."""
    identity = _uuid(item_id)
    if identity is None:
        return 0
    ensure_table()
    changed = 0
    for row in db.scalars(select(MemoryEvent).where(MemoryEvent.owner_hash == owner_hash, MemoryEvent.target == target,
                                                    MemoryEvent.item_id == identity)).all():
        basis = row.basis if isinstance(row.basis, dict) else None
        kept = {key: value for key, value in basis.items() if key not in SCRUBBED} if basis else None
        if row.text is not None or row.before is not None or (basis is not None and kept != basis):
            row.text, row.before, row.basis = None, None, kept or None
            changed += 1
    return changed


def quote_basis(quote, text) -> str | None:
    """His quote as a basis, unless it only repeats the text (an item or view he typed on the page is its own quote)."""
    quote = " ".join(str(quote or "").split())
    return quote if quote and quote.casefold() != " ".join(str(text or "").split()).casefold() else None


def as_dict(row: MemoryEvent) -> dict:
    return {"id": str(row.id), "at": row.at.isoformat() if row.at else None, "target": row.target, "item_id": str(row.item_id),
            "action": row.action, "by": row.by, "text": row.text, "before": row.before, "reason": row.reason,
            "basis": row.basis if isinstance(row.basis, dict) else {}, "bot_id": str(row.bot_id) if row.bot_id else None,
            "symbol": row.symbol, "reconstructed": bool(row.reconstructed)}


# --- what happened before the log ------------------------------------------------------------------------------------

def _creation(row: AgentProfileItem) -> tuple[str, Actor]:
    """How an item came to be, as far as its row tells."""
    if row.template:
        return "added", template(row.template)
    if row.origin == "manual":
        return "added", PAGE
    if row.origin == "explicit":
        return "added", chat(None, None, row.source_message_id) if row.source_message_id else UNKNOWN
    if row.origin == "inferred":
        return "added", extract(row.source_message_id)
    if row.origin == "pattern":
        return ("proposed", review(row.review_run)) if row.review_run else ("noticed", chat(None, None, row.source_message_id))
    return "added", UNKNOWN


def _rebuild_item(db, row: AgentProfileItem) -> int:
    rejected = row.status == "rejected"
    words = None if rejected else row.text                       # a rejected guess keeps only a fingerprint: no words to show
    action, actor = _creation(row)
    basis = {} if rejected else {"quote": quote_basis(row.quote, row.text), "examples": row.examples}
    events = [(row.created_at, action, actor, {"text": words, "basis": basis})]
    if row.confirmed_at:
        events.append((row.confirmed_at, "confirmed", PAGE, {"text": words}))        # only the memory page confirms
    if row.settled_at:
        events.append((row.settled_at, "settled", SETTLE, {"text": words}))
    if row.status == "archived":
        # Only the quarterly settle stamps archived_at; any other archive (forget, the cap, a topic, the limits) left only updated_at.
        events.append((row.archived_at or row.updated_at, "archived", SETTLE if row.archived_at else UNKNOWN,
                       {"text": words, "reason": row.archived_reason if row.archived_at else None}))
    if rejected:
        events.append((row.updated_at, "rejected", UNKNOWN, {}))
    for at, kind, by, fields in events:
        log(db, row.owner_hash, target="profile", item_id=row.id, action=kind, by=by, at=at or row.created_at or datetime.now(UTC),
            bot_id=row.bot_id, reconstructed=True, **fields)
    return len(events)


def _view_actor(row: OwnerView) -> Actor:
    """A version said in a conversation names it; the memory page's carries none."""
    if row.conversation_id or row.source_message_id:
        return chat(row.conversation_id, row.turn_id, row.source_message_id)
    return PAGE


def _rebuild_view(db, row: OwnerView) -> int:
    def put(at, kind, by, **fields):
        log(db, row.owner_hash, target="view", item_id=row.id, action=kind, by=by, at=at or row.created_at or datetime.now(UTC),
            text=row.text, symbol=row.symbol, reconstructed=True, **fields)
    put(row.created_at, "recorded", _view_actor(row), basis={"quote": quote_basis(row.quote, row.text)})
    if row.status == "superseded":
        after = db.scalars(select(OwnerView).where(OwnerView.owner_hash == row.owner_hash, OwnerView.symbol == row.symbol, OwnerView.id != row.id,
                                                   OwnerView.created_at == row.ended_at).limit(1)).first() if row.ended_at else None
        put(row.ended_at, "superseded", _view_actor(after) if after else UNKNOWN, basis={"by_item": after.id if after else None})
    elif row.status == "dropped":
        put(row.ended_at, "dropped", UNKNOWN)
    elif row.status == "archived":
        put(row.ended_at, "archived", SETTLE, reason=row.archived_reason)          # only the quarterly settle archives a view
    else:
        return 1
    return 2


def backfill(owner_hash: str | None = None) -> int:
    """Once, idempotent: every profile item and view version with no event yet gets the events its row tells of, ``reconstructed``.  One
    writer at a time: a process that finds another one backfilling skips (it never waits at startup).  Each owner's rows are read under the
    writer locks ``agent_profile`` and ``owner_views`` take, so an item deleted meanwhile cannot get its words back into the log after its
    ``scrub``.  A row whose change was logged already is never touched.  Returns how many events were written."""
    ensure_table()
    E, P, V = MemoryEvent, AgentProfileItem, OwnerView
    items = select(P).where(~exists().where(E.owner_hash == P.owner_hash, E.target == "profile", E.item_id == P.id))
    versions = select(V).where(~exists().where(E.owner_hash == V.owner_hash, E.target == "view", E.item_id == V.id))
    if owner_hash:
        items, versions = items.where(P.owner_hash == owner_hash), versions.where(V.owner_hash == owner_hash)
    written = 0
    with SessionLocal() as db:
        if not db.execute(sql("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": BACKFILL_LOCK}).scalar():
            logger.info("memory change log: another process is backfilling; skipped")
            return 0
        owners = sorted({row.owner_hash for row in db.scalars(items).all()} | {row.owner_hash for row in db.scalars(versions).all()})
        for owner in owners:
            from .owner_views import _lock as view_lock
            db.execute(sql("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "profile:" + owner})       # agent_profile._lock
            for symbol in sorted(set(db.scalars(select(V.symbol).where(V.owner_hash == owner)))):
                view_lock(db, owner, symbol)
            for row in db.scalars(items.where(P.owner_hash == owner).order_by(P.created_at, P.id)).all():
                written += _rebuild_item(db, row)
            for row in db.scalars(versions.where(V.owner_hash == owner).order_by(V.created_at, V.id)).all():
                written += _rebuild_view(db, row)
        db.commit()
    return written


def backfill_at_startup() -> None:
    """The API's startup: the backfill, its count logged.  A failure is logged and the API still starts (the next start tries again)."""
    try:
        written = backfill()
    except Exception:  # noqa: BLE001 - the log of past changes is not a reason to stay down
        logger.warning("memory change log: the backfill failed", exc_info=True)
        return
    logger.info("memory change log: %d events reconstructed", written)


# --- reading -----------------------------------------------------------------------------------------------------------

def page(owner_hash: str, *, target: str | None = None, action=None, by: str | None = None, q: str | None = None, before=None,
         limit: int = 50) -> tuple[list[dict], bool]:
    """The owner's events, newest first: ``(items, more)``.  ``action`` is one action or a list of them; ``q`` searches the text, an edit's
    old text and the reason; ``before`` is the ``(at, id)`` of the last event of the page before.  ValueError for a filter that is no value."""
    from .backstage_api import _like
    actions = [action] if isinstance(action, str) else list(action or [])
    if (target is not None and target not in TARGETS) or any(a not in ACTIONS for a in actions) or (by is not None and by not in BYS):
        raise ValueError("invalid_filter")
    ensure_table()
    E = MemoryEvent
    query = select(E).where(E.owner_hash == owner_hash)
    if target:
        query = query.where(E.target == target)
    if actions:
        query = query.where(E.action.in_(actions))
    if by:
        query = query.where(E.by == by)
    if q and q.strip():
        pattern = _like(q.strip())
        query = query.where(or_(E.text.ilike(pattern, escape="\\"), E.before.ilike(pattern, escape="\\"), E.reason.ilike(pattern, escape="\\")))
    if before:
        query = query.where(tuple_(E.at, E.id) < tuple_(before[0], before[1]))
    with SessionLocal() as db:
        rows = list(db.scalars(query.order_by(E.at.desc(), E.id.desc()).limit(limit + 1)))
        return [as_dict(row) for row in rows[:limit]], len(rows) > limit
