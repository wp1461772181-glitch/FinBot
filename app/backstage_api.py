"""The owner's backstage: read-only endpoints over what the assistant did (answers and their courses, model-call usage,
confirmation cards, the outbox).

Every route is a GET and answers 403 ``owner_only`` to anyone but the owner (the same check as the other owner pages).  Nothing here
writes.  Stored records come in two shapes (the kernel's turn, the old engine's) and some are null or damaged; every reader below
takes what it finds and shows what it can.  A card's button value (``confirm:``, ``authorize:``, ``change:``, ``reply:``,
``cancel:``) never leaves this module: the detail and the lists strip any that a stored record carries.

Days in the usage totals are UTC: the app has no timezone setting for the owner (``agent_telegram.CAP_TIMEZONE`` is the daily
message cap's own constant, not his setting), and the response says so.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.routing import APIRoute
from sqlalchemy import String, Text, and_, cast, exists, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from . import channels
from .agent_chat_models import AgentBot, AgentConversation, AgentConversationTitle, AgentMessage, ModelCall
from .agent_chat_store import owner_hash as hash_of
from .agent_workflow.models import AgentConsent
from .database import SessionLocal
from .duty_log import DECISIONS, DUTY_TITLE, OUTCOMES, DutyLog
from .model_usage import missing_price



class _NoStoreRoute(APIRoute):
    """Every response of the backstage (answers, refusals and validation errors too) is marked ``Cache-Control: no-store``."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            response.headers["Cache-Control"] = "no-store"
            return response
        return handler


router = APIRouter(prefix="/backstage", tags=["backstage"], route_class=_NoStoreRoute)

STATUSES = ("failed", "cancelled", "succeeded", "waiting_for_input", "incomplete")
MIN_DAY, MAX_DAY = date(2000, 1, 1), date(2100, 12, 31)
GROUPS = ("day", "model", "bot", "purpose")
PREVIEW_CHARS = 200
PENDING_WINDOW = timedelta(minutes=2)       # a turn that ended less than this ago may still have ledger rows on their way
MAX_LIMIT = 200
MAX_DAYS = 400
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_BUTTON = re.compile(r"\b(?:confirm|authorize|change|reply|cancel):[A-Za-z0-9_\-]{16,}(?::[A-Za-z0-9_\-]*)*")
_SECRET_KEYS = {"identity_credential", "api_key", "authorization", "token", "capability", "secret", "password", "bearer"}
_TITLE_KEYS = ("title", "headline", "label", "name", "symbol")
_TRACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_PARSE = 2_000_000


def _owner(x_chat_session: str | None) -> str:
    from .agent_chat_stream import _owner_only
    return hash_of(_owner_only(x_chat_session))


# --- small readers ------------------------------------------------------------------------------------------------

def scrub(value):
    """``value`` with every card button value replaced and every credential-named key dropped, however deep."""
    if isinstance(value, str):
        return _BUTTON.sub("[已移除]", value)
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if str(key).lower() not in _SECRET_KEYS}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def _record(value) -> dict:
    """A stored message's ``tool_calls`` as a dict: whatever else is stored there (null, text, a list) is no record."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _iso(value):
    return value.isoformat() if value is not None else None


def _question(text) -> str:
    """The user's line of a turn.  A press on a card is stored as its button value: shown as what it was, never as the value."""
    text = text or ""
    if text.startswith("reply:"):
        return text[len("reply:"):]
    if re.match(r"(?:confirm|authorize|change|cancel):", text):
        return "（卡片按钮）"
    return scrub(text)


def _cursor(created_at, identity) -> str:
    return f"{(created_at.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)}.{identity}"


def _parse_cursor(value):
    if not value:
        return None
    try:
        micros, identity = value.split(".", 1)
        return _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(identity)
    except (ValueError, OverflowError):
        raise HTTPException(400, "invalid_before") from None


def _uuid_or_400(value, code):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(400, code) from None


def _bot_names(db, owner) -> dict:
    return {str(row.id): row.name for row in db.scalars(select(AgentBot).where(AgentBot.owner_hash == owner))}


def is_tool_round(row) -> bool:
    """A stored tool round (the kernel and the old engine store each one as an assistant row with ``calls``, no text and no ``audit``):
    never an answer.  A turn whose last assistant row is one stopped there."""
    record = _record(row.tool_calls)
    return (row.status == "complete" and not (row.content or "").strip() and isinstance(record.get("calls"), list)
            and "audit" not in record)


def derive_status(message_status, terminal) -> str:
    """The turn's outcome from the message's own status and the kernel's ``terminal_status`` (failed beats cancelled beats waiting)."""
    if message_status == "failed" or terminal == "failed":
        return "failed"
    if message_status == "cancelled":
        return "cancelled"
    return "waiting_for_input" if terminal == "waiting_for_input" else "succeeded"


def _engine(record) -> str:
    return "v2" if record.get("route") == "K" else "v1"


def _tier(record):
    return _dict(record.get("audit")).get("tier") or record.get("tier")


def _total_ms(record):
    given = _number(record.get("thinking_ms"))
    if given is not None:
        return round(given)
    lines = [_number(_dict(call).get("ms")) for call in _list(_dict(record.get("audit")).get("calls"))]
    lines = [value for value in lines if value is not None]
    return round(sum(lines)) if lines else None


def _percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


# --- answers: list -------------------------------------------------------------------------------------------------

def _jsonb(alias):
    """``alias.tool_calls`` as jsonb.  A stored NUL escape is legal JSON but not jsonb: it is swapped for a space of the same length
    first (the swap keeps every other escape valid), so one such row cannot make a list fail."""
    return cast(func.replace(cast(alias.tool_calls, Text), "\\u0000", "\\u0020"), JSONB)


def _json_text(alias, *path):
    """A text field of ``alias.tool_calls`` by path: NULL for a record that is null, text, a list or lacks the field (never an error)."""
    return func.jsonb_extract_path_text(_jsonb(alias), *path)


def _incomplete_clause(F):
    """The turn has no final assistant row, or its last assistant row is a tool round."""
    calls = func.jsonb_typeof(func.jsonb_extract_path(_jsonb(F), "calls"))
    return or_(F.id.is_(None), and_(F.status == "complete", func.btrim(func.coalesce(F.content, "")) == "", calls == "array",
                                    func.jsonb_extract_path(_jsonb(F), "audit").is_(None)))


def _status_clause(F, status):
    own, terminal = F.status, func.coalesce(_json_text(F, "audit", "terminal_status"), "")
    incomplete = _incomplete_clause(F)
    if status == "incomplete":
        return incomplete
    if status == "failed":
        return and_(~incomplete, or_(own == "failed", terminal == "failed"))
    if status == "cancelled":
        return and_(~incomplete, own == "cancelled", terminal != "failed")
    if status == "waiting_for_input":
        return and_(~incomplete, own.notin_(("failed", "cancelled")), terminal == "waiting_for_input")
    return and_(~incomplete, own.notin_(("failed", "cancelled")), terminal.notin_(("failed", "waiting_for_input")))


def _like(text):
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _ledger_by_turn(db, turn_ids) -> dict:
    """Per turn: calls, tokens, cache, how many calls have no price, and the models' names, from the ledger."""
    if not turn_ids:
        return {}
    L = ModelCall
    totals = db.execute(select(
        L.turn_id, func.count(), func.sum(L.input_tokens + L.output_tokens + L.cache_read_tokens + L.cache_write_tokens),
        func.sum(L.cache_read_tokens), func.sum(L.cache_write_tokens), func.count().filter(L.cost_usd.is_(None)),
        func.sum(L.cost_usd), func.count().filter(L.ok.is_(True), L.purpose == "chat")).where(L.turn_id.in_(turn_ids)).group_by(L.turn_id)).all()
    names = {}
    for turn_id, name in db.execute(select(L.turn_id, func.coalesce(L.catalog_name, L.model)).where(L.turn_id.in_(turn_ids))
                                    .group_by(L.turn_id, func.coalesce(L.catalog_name, L.model)).order_by(func.min(L.created_at))):
        names.setdefault(turn_id, []).append(name)
    # What keeps a turn's unpriced calls unpriced: the catalog entry each one ran under, and whether it used cache tokens.
    lacking = {}
    for turn_id, name, read, write in db.execute(select(L.turn_id, L.catalog_name, func.bool_or(L.cache_read_tokens > 0), func.bool_or(L.cache_write_tokens > 0))
                                                 .where(L.turn_id.in_(turn_ids), L.cost_usd.is_(None)).group_by(L.turn_id, L.catalog_name)):
        lacking.setdefault(turn_id, []).append((name, bool(read), bool(write)))
    return {row[0]: {"calls": row[1], "tokens": int(row[2] or 0), "cache_read": int(row[3] or 0), "cache_write": int(row[4] or 0),
                     "unpriced": row[5], "cost": row[6], "ok_chat_calls": row[7], "models": names.get(row[0], []),
                     "lacking": lacking.get(row[0], [])} for row in totals}


def _missing_names(lacking) -> list:
    """The catalog prices (input, output, cache_read, cache_write) whose absence keeps these calls unpriced, as the entries are now."""
    lacking = list(lacking)
    if not lacking:
        return []
    from . import agent_model_catalog as catalog
    try:
        by_name = {item["name"]: item for item in catalog.entries()[0]}
    except Exception:  # noqa: BLE001 - a catalog that cannot be read leaves the names out; the state still says unpriced
        by_name = {}
    found = set()
    for name, read, write in lacking:
        found |= _missing_prices(by_name.get(name), read, write)
    return sorted(found)


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def cost_state(*, calls, ok_chat, expected, unpriced, ended_at, now, incomplete=False) -> str:
    """``pending`` (the turn ended under two minutes ago and its ledger rows may still be on their way: fewer chat rows than the audit counted, or
    a turn that never finished and so has no count to check), ``none`` (no model call), ``unrecorded`` (the audit counted calls and the ledger has
    fewer rows for good: history from before the ledger, or lost rows; nothing says a price was missing), ``unpriced`` (the ledger rows are all
    there and some call has no price), else ``priced``."""
    ended = _aware(ended_at)
    recent = ended is not None and now - ended < PENDING_WINDOW
    if recent and (incomplete or ok_chat < expected):
        return "pending"
    if not calls and not expected:
        return "none"
    if ok_chat < expected:
        return "unrecorded"
    return "unpriced" if unpriced else "priced"


def _list_item(asked, final, bot_id, ledger, bots, now, source="chat") -> dict:
    """One turn: ``asked`` is its user row, ``final`` its last assistant row (None when there is none).  A tool round is not an answer:
    a turn that stopped at one (or never got one) is ``incomplete`` and its item carries the question's id."""
    incomplete = final is None or is_tool_round(final)
    record = {} if incomplete else _record(final.tool_calls)
    audit = _dict(record.get("audit"))
    audit_calls = [_dict(call) for call in _list(audit.get("calls"))]
    expected = _number(audit.get("model_calls")) or len(audit_calls)
    if ledger:
        calls, tokens = ledger["calls"], {"total": ledger["tokens"], "cache_read": ledger["cache_read"], "cache_write": ledger["cache_write"]}
        models = ledger["models"]
        # Rows are written a moment after the turn: a cost is the turn's only when every call it made has landed and has a price.
        cost = ledger["cost"] if not ledger["unpriced"] and ledger["ok_chat_calls"] >= expected else None
        state = cost_state(calls=calls, ok_chat=ledger["ok_chat_calls"], expected=expected, unpriced=ledger["unpriced"],
                           ended_at=(final or asked).created_at, now=now, incomplete=incomplete)
        missing = _missing_names(ledger["lacking"]) if state == "unpriced" else []
    else:
        calls = expected
        tokens = {"total": _number(audit.get("token_usage")) or 0, "cache_read": _number(audit.get("cache_read_tokens")) or 0,
                  "cache_write": _number(audit.get("cache_write_tokens")) or 0}
        models = list(dict.fromkeys(str(call["model"]) for call in audit_calls if call.get("model")))
        cost = None
        state = cost_state(calls=0, ok_chat=0, expected=expected, unpriced=0, ended_at=(final or asked).created_at, now=now, incomplete=incomplete)
        missing = []
    writes = [_dict(item).get("outcome") for item in _list(audit.get("writes")) if _dict(item).get("outcome")]
    shown = asked if incomplete else final
    return {"message_id": str(shown.id), "conversation_id": str(asked.conversation_id), "source": source, "bot_id": str(bot_id) if bot_id else None,
            "bot_name": bots.get(str(bot_id)) if bot_id else None, "created_at": _iso(shown.created_at),
            "question": _question(asked.content)[:PREVIEW_CHARS], "answer": "" if incomplete else scrub(final.content or "")[:PREVIEW_CHARS],
            "engine": None if incomplete else _engine(record),
            "status": "incomplete" if incomplete else derive_status(final.status, audit.get("terminal_status")),
            "tier": _tier(record), "models": scrub(models), "total_ms": _total_ms(record), "model_calls": calls, "tokens": tokens,
            "cost_usd": cost, "cost_state": state, "missing_prices": missing,
            "tool_count": _number(audit.get("tool_calls")) if _number(audit.get("tool_calls")) is not None else len(_list(record.get("tool_trace"))),
            "write_outcomes": writes, "write_outcome": audit.get("write_outcome")}


@router.get("/answers")
def answers(x_chat_session: str | None = Header(default=None), bot_id: str | None = None,
            engine: str | None = Query(default=None), status: str | None = None, tier: str | None = None, slow: int = 0,
            source: str | None = Query(default=None),
            q: str | None = Query(default=None, max_length=100), before: str | None = None,
            limit: int = Query(default=50, ge=1, le=MAX_LIMIT)):
    """The owner's turns, newest question first: one item per turn, from its stored rows and the model-call ledger.  A turn with no
    final assistant row (or only tool rounds) is ``incomplete``."""
    owner = _owner(x_chat_session)
    if engine not in (None, "v1", "v2") or (status is not None and status not in STATUSES) or source not in (None, "chat", "duty"):
        raise HTTPException(400, "invalid_filter")
    bot = _uuid_or_400(bot_id, "invalid_bot_id") if bot_id else None
    cursor = _parse_cursor(before)
    M, C, F = AgentMessage, AgentConversation, aliased(AgentMessage)
    later, earlier = aliased(AgentMessage), aliased(AgentMessage)
    last_assistant = (select(later.id).where(later.turn_id == M.turn_id, later.conversation_id == M.conversation_id,
                                             later.role == "assistant").order_by(later.sequence.desc()).limit(1).correlate(M).scalar_subquery())
    # The wake turns (kernel.wake) live in one hidden, archived conversation of the owner's, titled DUTY_TITLE: the list leaves them out unless asked.
    is_duty = and_(C.archived_at.is_not(None), exists().where(AgentConversationTitle.conversation_id == C.id, AgentConversationTitle.title == DUTY_TITLE))
    query = (select(M, F, C.bot_id, is_duty).select_from(M).join(C, C.id == M.conversation_id).outerjoin(F, F.id == last_assistant)
             .where(C.owner_hash == owner, M.role == "user",
                    ~exists().where(earlier.turn_id == M.turn_id, earlier.conversation_id == M.conversation_id, earlier.role == "user",
                                    earlier.sequence < M.sequence)))
    query = query.where(is_duty if source == "duty" else ~is_duty)
    if bot:
        query = query.where(C.bot_id == bot)
    if engine:
        route = func.coalesce(_json_text(F, "route"), "")
        query = query.where(route == "K" if engine == "v2" else route != "K", ~_incomplete_clause(F))
    if status:
        query = query.where(_status_clause(F, status))
    if tier:
        query = query.where(func.coalesce(_json_text(F, "audit", "tier"), _json_text(F, "tier")) == tier)
    if q and q.strip():
        pattern = _like(q.strip())
        query = query.where(or_(M.content.ilike(pattern, escape="\\"), F.content.ilike(pattern, escape="\\")))
    if cursor:
        query = query.where(tuple_(M.created_at, M.id) < tuple_(cursor[0], cursor[1]))
    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = db.execute(query.order_by(M.created_at.desc(), M.id.desc()).limit(limit + 1)).all()
        more, rows = len(rows) > limit, rows[:limit]
        ledger = _ledger_by_turn(db, [row[0].turn_id for row in rows])
        bots = _bot_names(db, owner)
        items = [_list_item(asked, final, bot_of, ledger.get(asked.turn_id), bots, now, "duty" if duty else "chat") for asked, final, bot_of, duty in rows]
        next_before = _cursor(rows[-1][0].created_at, rows[-1][0].id) if more else None
    threshold = None
    if slow:
        timed = [item["total_ms"] for item in items if item["total_ms"] is not None]
        threshold = _percentile(timed, 0.9) if timed else None
        items = [item for item in items if threshold is not None and item["total_ms"] is not None and item["total_ms"] > threshold]
    return {"items": items, "next_before": next_before, "slow_threshold_ms": threshold,
            "slow_rule": "total_ms above the p90 of the turns in this page's window" if slow else None}


# --- answers: detail -------------------------------------------------------------------------------------------------

def _row_titles(rows) -> list:
    titles = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in _TITLE_KEYS:
            if isinstance(row.get(key), str) and row[key].strip():
                titles.append(scrub(row[key])[:120])
                break
        if len(titles) == 3:
            break
    return titles


def _result_summary(content, traced) -> dict | None:
    """ok, error code, row count and the first rows' titles of one tool call, from its stored result (else from the trace)."""
    parsed = None
    if isinstance(content, str) and len(content) <= _MAX_PARSE:
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = None
    if isinstance(parsed, dict):
        data = parsed.get("data")
        return {"ok": parsed.get("ok"), "error_code": parsed.get("error_code") if isinstance(parsed.get("error_code"), str) else None,
                "count": len(data) if isinstance(data, list) else None, "row_titles": _row_titles(data) if isinstance(data, list) else []}
    if isinstance(traced, dict):
        return {"ok": traced.get("ok"), "error_code": traced.get("error_code"), "count": traced.get("count"), "row_titles": []}
    return None


def _tool_calls(turn_rows, record) -> list:
    traced = {_dict(item).get("call_id"): _dict(item) for item in _list(record.get("tool_trace"))}
    results = {row.tool_call_id: row.content for row in turn_rows if row.role == "tool"}
    found = []
    for row in turn_rows:
        if row.role != "assistant":
            continue
        for call in _list(_record(row.tool_calls).get("calls")):
            call = _dict(call)
            function = _dict(call.get("function"))
            raw = function.get("arguments")
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                arguments = None
            if arguments is None and isinstance(raw, str):
                arguments = {"_raw": scrub(raw)[:500]}
            call_id = call.get("id")
            result = _result_summary(results.get(call_id), _dict(traced.get(call_id)).get("result"))
            ok = result.get("ok") if result else None
            found.append({"call_id": call_id, "name": function.get("name") or call.get("name"), "arguments": scrub(arguments or {}),
                          "status": "unfinished" if result is None else "complete" if ok is True else "failed" if ok is False else "complete",
                          "result": result})
    return found


def _call_line(*, tier, model, catalog_name, purpose, ms, tokens, attempt, ok, error, cost, at, recorded=True) -> dict:
    """One model call.  ``recorded`` is whether the ledger has a row for it: a call shown from the audit has none (its price is unknown, not missing)."""
    return {"recorded": recorded, "tier": tier, "model": model, "catalog_name": catalog_name, "purpose": purpose, "ms": ms, "tokens": tokens,
            "attempt": attempt, "ok": ok, "error": error, "cost_usd": cost, "priced": cost is not None, "at": at}


def _model_calls(db, turn_id, record):
    """(lines, source, rows): the ledger's rows of the turn when they are all there, else the audit's lines; ``rows`` are all the ledger has."""
    audit_calls = [_dict(call) for call in _list(_dict(record.get("audit")).get("calls"))]
    rows = list(db.scalars(select(ModelCall).where(ModelCall.turn_id == turn_id).order_by(ModelCall.created_at, ModelCall.id)))
    chat_ok = [row for row in rows if row.purpose == "chat" and row.ok]
    if rows and (not audit_calls or len(chat_ok) >= len(audit_calls)):
        tiers = {row.id: _dict(call).get("tier") for row, call in zip(chat_ok, audit_calls, strict=False)} if len(chat_ok) == len(audit_calls) else {}
        lines = [_call_line(tier=tiers.get(row.id), model=row.model, catalog_name=row.catalog_name, purpose=row.purpose, ms=row.ms,
                            tokens={"input": row.input_tokens, "output": row.output_tokens, "cache_read": row.cache_read_tokens,
                                    "cache_write": row.cache_write_tokens,
                                    "total": row.input_tokens + row.output_tokens + row.cache_read_tokens + row.cache_write_tokens},
                            attempt=row.attempt, ok=row.ok, error=row.error, cost=row.cost_usd, at=_iso(row.created_at)) for row in rows]
        return lines, "ledger", rows
    if audit_calls:
        return [_call_line(tier=call.get("tier"), model=call.get("model"), catalog_name=None, purpose="chat", ms=call.get("ms"),
                           tokens={"input": None, "output": None, "cache_read": call.get("cache_read"), "cache_write": call.get("cache_write"),
                                   "total": call.get("tokens")}, attempt=None, ok=None, error=None, cost=None, at=None, recorded=False)
                for call in audit_calls], "audit", rows
    return [], "none", rows


def _model_positions(source, rows, audit_calls) -> dict:
    """Which entry of ``model_calls`` each of the audit's calls (the kernel timeline's ``call`` index) is: by order among the chat rows that
    succeeded, when they are as many as the audit's lines (the same match that gives a row its tier); by position when the lines are shown."""
    if source == "audit":
        return {i: i for i in range(len(audit_calls))}
    if source != "ledger" or not audit_calls:
        return {}
    chat_ok = [position for position, row in enumerate(rows) if row.purpose == "chat" and row.ok]
    return dict(enumerate(chat_ok)) if len(chat_ok) == len(audit_calls) else {}


def _event(kind, at_ms=None, step=None, **ref) -> dict:
    return {"kind": kind, "at_ms": at_ms, "step": step, **ref}


def _events(record, narration, model_count, positions, tool_calls) -> tuple[bool, list]:
    """The detail's events in the order they happened, as references into ``narration``, ``model_calls`` and ``tool_calls``.

    With the kernel's ``audit.timeline`` they are interleaved by it (``ordered`` true; entries that do not point at anything are dropped; a
    failed attempt, which the timeline does not know, sits before the call that followed it, and rows after the last call go last).  Without it
    (an older record, or a damaged one) they keep the kind order: narration, model calls, tool calls."""
    ids = [call.get("call_id") for call in tool_calls if isinstance(call.get("call_id"), str)]
    taken = set()
    def number(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    ordered, placed, mapped = [], set(), set(positions.values())
    for entry in _list(_dict(record.get("audit")).get("timeline")):
        entry = _dict(entry)
        kind, at_ms, step = entry.get("kind"), number(entry.get("at_ms")), number(entry.get("step"))
        index, call_id = number(entry.get("index")), entry.get("call_id")
        if at_ms is None or not isinstance(kind, str) or (call_id is not None and not isinstance(call_id, str)):
            continue
        if kind == "say" and index is not None and index < len(narration) and ("say", index) not in taken:
            taken.add(("say", index))
            ordered.append(_event("narration", at_ms, step, index=index))
        elif kind == "call" and index in positions and positions[index] not in placed:
            position = positions[index]
            for earlier in range(position):         # attempts the timeline does not know come before the call that followed them
                if earlier not in mapped and earlier not in placed and earlier < model_count:
                    placed.add(earlier)
                    ordered.append(_event("model_call", index=earlier))
            placed.add(position)
            ordered.append(_event("model_call", at_ms, step, index=position))
        elif kind in ("tool", "tool_done") and call_id in ids and (kind, call_id) not in taken:
            taken.add((kind, call_id))
            ordered.append(_event("tool_call" if kind == "tool" else "tool_done", at_ms, step, call_id=call_id))
    if not ordered:
        return False, [*(_event("narration", index=i) for i in range(len(narration))), *(_event("model_call", index=i) for i in range(model_count)),
                       *(_event("tool_call", call_id=i) for i in ids if i is not None)]
    ordered += [_event("model_call", index=i) for i in range(model_count) if i not in placed]
    ordered += [_event("narration", index=i) for i in range(len(narration)) if ("say", i) not in taken]
    ordered += [_event("tool_call", call_id=i) for i in ids if i is not None and ("tool", i) not in taken]
    return True, ordered


def _kind(value) -> str:
    return value.split(":", 1)[0] if isinstance(value, str) and ":" in value else "other"


def _consent_item(row, now) -> dict:
    """One confirmation card as the owner saw it: never the capability hash, the payload digest or the operations' arguments."""
    from .kernel.act import tier_of
    expired = row.status == "proposed" and row.expires_at <= now
    result = _dict(row.result)
    outcomes = [{"ok": _dict(item).get("ok"), "error_code": _dict(item).get("error_code")} for item in _list(result.get("data"))]
    names = []
    for operation in _list(row.operations):
        name = _dict(operation).get("name")
        if isinstance(name, str):
            try:
                tier = tier_of(name)
            except Exception:  # noqa: BLE001 - an operation the kernel no longer knows has no tier to show
                tier = None
            names.append({"name": name, "tier": tier})
    display = _dict(row.display)
    return {"id": str(row.id), "conversation_id": row.conversation_id, "created_at": _iso(row.created_at), "expires_at": _iso(row.expires_at),
            "title": scrub(display.get("title")), "targets": scrub(_list(display.get("targets"))), "operations": names,
            "status": row.status, "expired": expired, "decided_at": _iso(row.decided_at),
            "result": {"ok": result.get("ok"), "status": result.get("status"), "outcomes": outcomes} if result else None}


def _card(db, owner, record, now) -> dict | None:
    stored = _dict(record.get("clarification"))
    if not stored:
        return None
    display = _dict(stored.get("display"))
    card = {"request_id": stored.get("request_id"), "reason": stored.get("reason"), "title": scrub(display.get("title")),
            "targets": scrub(_list(display.get("targets"))), "question": scrub(stored.get("question")),
            "choices": [{"label": scrub(_dict(choice).get("label")), "kind": _kind(_dict(choice).get("value"))}
                        for choice in _list(stored.get("choices"))], "consent": None}
    try:
        row = db.get(AgentConsent, uuid.UUID(str(stored.get("request_id"))))
    except ValueError:
        row = None
    if row is not None and row.owner_hash == owner:
        item = _consent_item(row, now)
        card["consent"] = {key: item[key] for key in ("status", "expired", "decided_at", "operations", "result")}
    return card


def _langfuse_url(record):
    from .observability import _config
    trace_id = _dict(record.get("audit")).get("trace_id") or record.get("trace_id")
    config = _config()
    if config is None or not isinstance(trace_id, str) or not _TRACE_ID.match(trace_id):
        return None
    return f"{config[2].rstrip('/')}/trace/{trace_id}"


@router.get("/answers/{message_id}")
def answer(message_id: str, x_chat_session: str | None = Header(default=None)):
    """The whole course of one turn in time order: the question, each model call, narration, checklist, each tool call, citations,
    write proposals and outcomes, the final answer.  The id is the one the list gives: the final answer's, or the question's when the
    turn has no final answer (the question's id of any turn opens it too).  An old-engine, damaged or unfinished turn shows what it has
    and says ``partial``."""
    owner = _owner(x_chat_session)
    try:
        identity = uuid.UUID(message_id)
    except ValueError:
        raise HTTPException(404, "not_found") from None
    now = datetime.now(UTC)
    with SessionLocal() as db:
        found = db.execute(select(AgentMessage, AgentConversation.bot_id).join(AgentConversation, AgentConversation.id == AgentMessage.conversation_id)
                           .where(AgentMessage.id == identity, AgentConversation.owner_hash == owner)).first()
        if found is None:
            raise HTTPException(404, "not_found")
        opened, bot_id = found
        turn_rows = list(db.scalars(select(AgentMessage).where(AgentMessage.turn_id == opened.turn_id,
                                                               AgentMessage.conversation_id == opened.conversation_id)
                                    .order_by(AgentMessage.sequence)))
        assistants = [row for row in turn_rows if row.role == "assistant"]
        final = assistants[-1] if assistants else None
        asked_row = next((row for row in turn_rows if row.role == "user"), None)
        # Only the turn's question or its last assistant row open it: an earlier tool round is not an answer.
        if opened.role not in ("user", "assistant") or (opened.role == "assistant" and opened is not final and opened.id != final.id):
            raise HTTPException(404, "not_found")
        incomplete = final is None or is_tool_round(final)
        record = {} if incomplete else _record(final.tool_calls)
        audit = _dict(record.get("audit"))
        calls, source, ledger_rows = _model_calls(db, opened.turn_id, record)
        card = _card(db, owner, record, now)
        bot_name = _bot_names(db, owner).get(str(bot_id)) if bot_id else None
        audit_calls = _list(audit.get("calls"))
        expected = _number(audit.get("model_calls")) or len(audit_calls)
        lacking = [(row.catalog_name, row.cache_read_tokens > 0, row.cache_write_tokens > 0) for row in ledger_rows if row.cost_usd is None]
        state = cost_state(calls=len(ledger_rows) or (expected if source == "audit" else 0), ok_chat=sum(1 for row in ledger_rows if row.purpose == "chat" and row.ok),
                           expected=expected, unpriced=len(lacking), ended_at=(final or opened).created_at, now=now, incomplete=incomplete)
        missing = _missing_names(lacking) if state == "unpriced" else []
        positions = _model_positions(source, ledger_rows, audit_calls)
    shown = asked_row if incomplete and asked_row is not None else final or opened
    engine = None if incomplete else _engine(record)
    citations = [{"ordinal": item.get("ordinal"), "title": scrub(item.get("title")), "url": scrub(item.get("url")),
                  "source_type": item.get("source_type")} for item in map(_dict, _list(record.get("citations"))) if item]
    fallback = audit.get("fallback")
    narration = scrub([line for line in _list(record.get("narration")) if isinstance(line, str)])
    tool_calls = _tool_calls(turn_rows, record)
    ordered, events = _events(record, narration, len(calls), positions, tool_calls)
    return {"message_id": str(shown.id), "conversation_id": str(opened.conversation_id), "turn_id": str(opened.turn_id),
            "bot_id": str(bot_id) if bot_id else None, "bot_name": bot_name, "created_at": _iso(shown.created_at),
            "engine": engine, "partial": engine != "v2",
            "status": "incomplete" if incomplete else derive_status(final.status, audit.get("terminal_status")),
            "tier": _tier(record), "total_ms": _total_ms(record), "question": _question(asked_row.content if asked_row else ""),
            "model_calls": calls, "model_calls_source": source, "cost_state": state, "missing_prices": missing,
            "narration": narration, "ordered": ordered, "events": events,
            "checklist": scrub(_list(record.get("checklist"))), "tool_calls": tool_calls, "citations": citations,
            "writes": scrub([item for item in _list(audit.get("writes")) if isinstance(item, dict)]),
            "write_outcome": audit.get("write_outcome"), "card": card, "answer": "" if incomplete else scrub(final.content or ""),
            "backup_model": scrub(fallback) if isinstance(fallback, dict) else None,
            "latest_known": [scrub(symbol) for symbol in _list(audit.get("latest_known"))[:6] if isinstance(symbol, str)], "langfuse_url": _langfuse_url(record)}


# --- usage ---------------------------------------------------------------------------------------------------------

def _aggregates():
    L = ModelCall
    return [func.count(), func.count().filter(L.ok.is_(False)), func.coalesce(func.sum(L.input_tokens), 0),
            func.coalesce(func.sum(L.output_tokens), 0), func.coalesce(func.sum(L.cache_read_tokens), 0),
            func.coalesce(func.sum(L.cache_write_tokens), 0), func.percentile_cont(0.5).within_group(L.ms),
            func.coalesce(func.sum(L.cost_usd), 0.0), func.count().filter(L.cost_usd.is_(None))]


def _usage_line(values, missing=()) -> dict:
    """``cost_usd`` sums the priced calls and is null when none was priced (never a made-up zero); ``missing_prices`` names the
    catalog prices (input, output, cache_read, cache_write) whose absence keeps this group's calls unpriced."""
    calls, failed, plain, output, read, write, p50, cost, unpriced = values
    return {"calls": calls, "failed_calls": failed, "tokens": {"input": int(plain), "output": int(output), "cache_read": int(read),
                                                                "cache_write": int(write)},
            "ms_p50": float(p50) if p50 is not None else None, "cost_usd": float(cost) if calls > unpriced else None,
            "unpriced_calls": unpriced, "missing_prices": sorted(missing)}


def _missing_prices(entry, cache_read, cache_write) -> set:
    """Every price of catalog ``entry`` that a call (with or without cache tokens) needs and lacks, as ``missing_price`` names them."""
    entry, found = dict(entry or {}), set()
    row = {"cache_read_tokens": 1 if cache_read else 0, "cache_write_tokens": 1 if cache_write else 0}
    while (name := missing_price(row, entry)) is not None and name not in found:
        found.add(name)
        entry[f"price_{name}"] = 0.0
    return found


def _day(value, code):
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, code) from None
    if not MIN_DAY <= day <= MAX_DAY:
        raise HTTPException(422, "invalid_range")
    return day


@router.get("/usage")
def usage(x_chat_session: str | None = Header(default=None), group: str = "day",
          from_: str | None = Query(default=None, alias="from"), to: str | None = None):
    """Model-call totals per day, model, bot or purpose over an inclusive range of UTC days (default: the last 30 days)."""
    owner = _owner(x_chat_session)
    if group not in GROUPS:
        raise HTTPException(400, "invalid_group")
    last = _day(to, "invalid_to") if to else datetime.now(UTC).date()
    first = _day(from_, "invalid_from") if from_ else last - timedelta(days=29)
    if first > last or (last - first).days >= MAX_DAYS:
        raise HTTPException(400, "invalid_range")
    L = ModelCall
    start = datetime(first.year, first.month, first.day, tzinfo=UTC)
    end = datetime(last.year, last.month, last.day, tzinfo=UTC) + timedelta(days=1)
    where = (L.created_at >= start, L.created_at < end, or_(L.owner_hash == owner, L.owner_hash.is_(None)))
    key = {"day": func.to_char(func.timezone("UTC", L.created_at), "YYYY-MM-DD"), "model": func.coalesce(L.catalog_name, L.model),
           "bot": func.coalesce(cast(L.bot_id, String), "none"), "purpose": L.purpose}[group]
    with SessionLocal() as db:
        total_row = db.execute(select(*_aggregates()).where(*where)).one()
        rows = db.execute(select(key, *_aggregates()).where(*where).group_by(key)).all()
        bots = _bot_names(db, owner) if group == "bot" else {}
        # What keeps the unpriced calls unpriced: per group, the catalog entry's prices as they are now.
        unpriced = db.execute(select(key, L.catalog_name, func.bool_or(L.cache_read_tokens > 0), func.bool_or(L.cache_write_tokens > 0))
                              .where(*where, L.cost_usd.is_(None)).group_by(key, L.catalog_name)).all()
        from . import agent_model_catalog as catalog
        by_name = {item["name"]: item for item in catalog.entries()[0]} if unpriced else {}
    missing, every = {}, set()
    for name, catalog_name, read, write in unpriced:
        found = _missing_prices(by_name.get(catalog_name), read, write)
        missing.setdefault(name if name is not None else "none", set()).update(found)
        every |= found
    totals = _usage_line(total_row, every)
    groups = []
    for row in rows:
        name = row[0] if row[0] is not None else "none"
        label = (bots.get(name) or name[:8]) if group == "bot" and name != "none" else "（无）" if group == "bot" else name
        groups.append({"key": name, "label": label, **_usage_line(row[1:], missing.get(name, ()))})
    groups.sort(key=(lambda g: g["key"]) if group == "day" else (lambda g: (-g["calls"], g["key"])))
    return {"from": first.isoformat(), "to": last.isoformat(), "group": group, "timezone": "UTC",
            "timezone_note": "No owner timezone is configured, so days are UTC days (00:00 to 24:00 UTC).",
            "totals": totals, "groups": groups}


# --- operations ----------------------------------------------------------------------------------------------------

@router.get("/operations")
def operations(x_chat_session: str | None = Header(default=None), limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
               before: str | None = None):
    """Confirmation cards, newest first, with their state and result summary (never the hash, the digest or the arguments)."""
    owner = _owner(x_chat_session)
    cursor = _parse_cursor(before)
    A = AgentConsent
    query = select(A).where(A.owner_hash == owner)
    if cursor:
        query = query.where(tuple_(A.created_at, A.id) < tuple_(cursor[0], cursor[1]))
    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = list(db.scalars(query.order_by(A.created_at.desc(), A.id.desc()).limit(limit + 1)))
        more, rows = len(rows) > limit, rows[:limit]
        bots = _bot_names(db, owner)
        conversations = {}
        ids = set()
        for row in rows:
            try:
                ids.add(uuid.UUID(row.conversation_id))
            except ValueError:
                pass
        if ids:
            conversations = {str(c.id): c.bot_id for c in db.scalars(select(AgentConversation).where(AgentConversation.id.in_(ids),
                                                                                                       AgentConversation.owner_hash == owner))}
        items = []
        for row in rows:
            item = _consent_item(row, now)
            bot = conversations.get(row.conversation_id)
            items.append({**item, "bot_id": str(bot) if bot else None, "bot_name": bots.get(str(bot)) if bot else None})
        next_before = _cursor(rows[-1].created_at, rows[-1].id) if more else None
    return {"items": items, "next_before": next_before}


# --- deliveries ----------------------------------------------------------------------------------------------------

@router.get("/deliveries")
def deliveries(x_chat_session: str | None = Header(default=None), limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
               before: str | None = None):
    """The outbox list ``channels.deliveries`` builds (proactive messages, newest first), with paging."""
    owner = _owner(x_chat_session)
    cursor = _parse_cursor(before)
    rows = channels.deliveries(owner, limit + 1, cursor)
    more, rows = len(rows) > limit, rows[:limit]
    next_before = _cursor(datetime.fromisoformat(rows[-1]["created_at"]), rows[-1]["id"]) if more else None
    return {"items": rows, "next_before": next_before}


# --- duty ----------------------------------------------------------------------------------------------------------

def _duty_cursor(created_at, identity) -> str:
    return f"{(created_at.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)}.{identity}"


def _parse_duty_cursor(value):
    if not value:
        return None
    try:
        micros, identity = value.split(".", 1)
        return _EPOCH + timedelta(microseconds=int(micros)), int(identity)
    except (ValueError, OverflowError):
        raise HTTPException(400, "invalid_before") from None


def _duty_item(row, opens) -> dict:
    event = _dict(row.event)
    text = event.get("text") if isinstance(event.get("text"), str) else ""
    return {"id": row.id, "created_at": _iso(row.created_at), "alert_id": row.alert_id, "symbol": scrub(event.get("symbol")) if isinstance(event.get("symbol"), str) else None,
            "kind": scrub(event.get("kind")) if isinstance(event.get("kind"), str) else None, "what": scrub(text.strip().split("\n", 1)[0]) if text.strip() else "",
            "mode": row.mode, "outcome": row.outcome, "decision": row.decision, "reason": scrub(row.reason), "message": scrub(row.message), "delivery": row.delivery,
            "turn_id": str(row.turn_id) if row.turn_id else None, "message_id": opens.get(row.turn_id), "ms": row.ms, "model_calls": row.model_calls}


@router.get("/duty")
def duty(x_chat_session: str | None = Header(default=None), decision: str | None = None, outcome: str | None = None,
         before: str | None = None, limit: int = Query(default=50, ge=1, le=MAX_LIMIT)):
    """Each time an alert woke the agent (``duty_log``), newest first: what the alert said, what it decided and why, the message when it
    told you, whether that went out.  ``mode`` is what ``FINBOT_DUTY_MODE`` says now.  ``message_id`` opens the wake turn in ``/answers/{id}``."""
    from .kernel import wake
    owner = _owner(x_chat_session)
    if (decision is not None and decision not in DECISIONS) or (outcome is not None and outcome not in OUTCOMES):
        raise HTTPException(400, "invalid_filter")
    cursor = _parse_duty_cursor(before)
    D = DutyLog
    query = select(D).where(D.owner_hash == owner)
    if decision:
        query = query.where(D.decision == decision)
    if outcome:
        query = query.where(D.outcome == outcome)
    if cursor:
        query = query.where(tuple_(D.created_at, D.id) < tuple_(cursor[0], cursor[1]))
    with SessionLocal() as db:
        rows = list(db.scalars(query.order_by(D.created_at.desc(), D.id.desc()).limit(limit + 1)))
        more, rows = len(rows) > limit, rows[:limit]
        turns = [row.turn_id for row in rows if row.turn_id]
        opens = {}
        if turns:
            for turn_id, message_id in db.execute(select(AgentMessage.turn_id, AgentMessage.id).join(AgentConversation, AgentConversation.id == AgentMessage.conversation_id)
                                                  .where(AgentMessage.turn_id.in_(turns), AgentMessage.role == "user", AgentConversation.owner_hash == owner)
                                                  .order_by(AgentMessage.sequence.desc())):
                opens[turn_id] = str(message_id)             # the earliest question of the turn wins (the order above is reversed)
        items = [_duty_item(row, opens) for row in rows]
        next_before = _duty_cursor(rows[-1].created_at, rows[-1].id) if more else None
    return {"mode": wake.mode(), "items": items, "next_before": next_before}
