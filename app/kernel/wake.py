"""The wake: an alert the sentinel raised wakes the kernel, which decides what (if anything) to add for the owner.

The sentinel has already sent its own alert; nothing here can hold one back.  The sentinel posts ``alert_posted`` to the API, the
endpoint validates it and puts it on a small queue, and one worker takes the events one at a time.  A wake turn is the kernel's own
loop with read tools, ``plan``/``escalate`` and ``decide`` only (``loop.run_wake``): it cannot change anything and asks nobody.  It
ends with one of four decisions, a reason and, for ``tell_now``, the kernel's own message.  Every wake-up leaves one ``duty_log``
row whatever happened.

``FINBOT_DUTY_MODE``: ``off`` (nothing is woken; the alert is logged as ``skipped_off``), ``shadow`` (the default: judged and
logged, nothing is sent), ``on`` (a ``tell_now`` message goes to the owner through the outbox, source ``duty``).

The turn is kept as an ordinary stored turn (a question row, its tool rounds, a final answer row carrying the audit and timeline) in
one hidden conversation per owner, titled ``DUTY_TITLE`` and archived so no list shows it; the backstage opens it by its turn id
exactly as it opens a chat turn.  The text of the event is data everywhere: it is shown to the model only inside the labelled data
block of the system prompt and stored only as the turn's question.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from .. import duty_log, latest_known, model_usage
from . import loop, prompt

logger = logging.getLogger(__name__)

MODES = ("off", "shadow", "on")
DEFAULT_MODE = "shadow"
QUEUE_MAX = 50
WALL_SECONDS = 120
DUTY_TITLE = duty_log.DUTY_TITLE
DEFAULT_DAILY_CAP = 10
MAX_ALERT_ID = 2**62
TEXT_MAX = 2000
VALUE_MAX = 300
RECENT = 10
RECENT_TEXT = 300
QUESTION_MAX = 1000
HELD_NIGHT = "held_night"       # delivery of a tell_now for an alert the sentinel held over the night
TIER_LABELS = {1: "值得知道", 2: "重大"}      # the sentinel's alert tiers that make the kernel look for a cause


def daily_cap() -> int:
    """How many ``tell_now`` messages one UTC day may send (``FINBOT_DUTY_DAILY_CAP``, default 10): a count of its own, apart from the bot's notify cap."""
    try:
        return max(0, int(os.environ.get("FINBOT_DUTY_DAILY_CAP", DEFAULT_DAILY_CAP)))
    except ValueError:
        return DEFAULT_DAILY_CAP


def mode() -> str:
    """The wake mode now (read on every wake, so a change of the environment needs no restart of the loop)."""
    value = os.environ.get("FINBOT_DUTY_MODE", DEFAULT_MODE).strip().lower()
    return value if value in MODES else DEFAULT_MODE


# --- the event ------------------------------------------------------------------------------------------------------

def _clip(value, depth: int = 0):
    if isinstance(value, str):
        return value[:VALUE_MAX]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if depth < 2 and isinstance(value, (list, tuple)):
        return [_clip(item, depth + 1) for item in list(value)[:50]]
    if depth < 2 and isinstance(value, dict):
        return {str(key)[:40]: _clip(item, depth + 1) for key, item in list(value.items())[:20]}
    return str(value)[:VALUE_MAX]


def clean_event(payload) -> dict:
    """The alert as the sentinel posted it, bounded.  ``alert_id`` (an int), ``symbol`` and ``text`` (strings) are required; every
    other field, known or not, is kept as data and never trusted as an instruction.  Raises ValueError for anything else."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_event")
    alert_id, symbol, text = payload.get("alert_id"), payload.get("symbol"), payload.get("text")
    if isinstance(alert_id, bool) or not isinstance(alert_id, int) or alert_id < 0 or alert_id > MAX_ALERT_ID:
        raise ValueError("invalid_event")
    if not isinstance(symbol, str) or not symbol.strip() or not isinstance(text, str) or not text.strip():
        raise ValueError("invalid_event")
    event = {str(key)[:40]: _clip(value) for key, value in list(payload.items())[:40]}
    event["text"] = text[:TEXT_MAX]
    return event


# --- what the kernel is told about the owner ------------------------------------------------------------------------------

def _facts(owner: str, event: dict) -> tuple[dict, list[dict], list[dict]]:
    """(the owner's relation to this event, the last ``tell_now`` messages, the last outbox messages) as plain data."""
    from ..agent_chat_models import AgentResearchQueue, AgentTelegramMessage
    from ..database import SessionLocal
    symbols = [s for s in (event.get("members") or [event.get("symbol")]) if isinstance(s, str)]
    relation = {"symbols": symbols, "held": bool(event.get("held")), "weight_pct": event.get("weight_pct"),
                "in_research_queue": None, "research_queue": []}
    relation["already_sent"] = not bool(event.get("deferred"))      # a night-held alert (deferred) has not reached him yet
    tier = event.get("tier")
    if isinstance(tier, int) and not isinstance(tier, bool) and tier in TIER_LABELS:
        relation["tier_label"] = TIER_LABELS[tier]      # only the two tiers that ask for a cause; no key otherwise
    outbox: list[dict] = []
    try:
        with SessionLocal() as db:
            row = db.get(AgentResearchQueue, owner)
            queue = [s for s in (row.symbols if row else []) if isinstance(s, str)]
            relation["research_queue"] = queue[:40]
            relation["in_research_queue"] = any(s in queue for s in symbols)
            rows = db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source != "reply")
                              .order_by(AgentTelegramMessage.created_at.desc()).limit(RECENT))
            outbox = [{"at": r.created_at.isoformat(), "source": r.source, "text": r.text[:RECENT_TEXT]} for r in rows]
    except Exception:
        logger.exception("wake: the owner's context could not be read")
    # Only messages that really went out: shadow, capped, unbound-channel and night-held ones never reached him (a held one the morning
    # brief carried did: ``briefed``).
    sent = [r for r in duty_log.recent(owner, RECENT * 5, decision="tell_now") if r["mode"] == "on" and r["delivery"] in ("queued", "briefed")]
    told = [{"at": r["created_at"], "symbol": (r["event"] or {}).get("symbol"), "message": r["message"]} for r in sent[:RECENT]]
    return relation, told, outbox


# --- the stored turn (the backstage opens it by its turn id) -----------------------------------------------------------------

def _wake_conversation(owner: str, bot_id) -> str:
    """The owner's one hidden conversation for wake turns (made on first use, archived so no list shows it)."""
    from ..agent_chat_models import AgentConversation, AgentConversationTitle
    from ..database import SessionLocal
    with SessionLocal() as db:
        found = db.scalar(select(AgentConversation.id).join(AgentConversationTitle, AgentConversationTitle.conversation_id == AgentConversation.id)
                          .where(AgentConversation.owner_hash == owner, AgentConversationTitle.title == DUTY_TITLE, AgentConversation.archived_at.is_not(None))
                          .order_by(AgentConversation.created_at).limit(1))
        if found is not None:
            return str(found)
        conversation = AgentConversation(owner_hash=owner, bot_id=bot_id, archived_at=datetime.now(UTC))
        db.add(conversation)
        db.flush()
        db.add(AgentConversationTitle(conversation_id=conversation.id, title=DUTY_TITLE))
        db.commit()
        return str(conversation.id)


class Recorder:
    """The turn's tool rounds as the loop emits them (the routine runner keeps the same two kinds of event)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.genuine: set = set()

    async def emit(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "assistant_tool_request":
            self.events.append(event)
            self.genuine.update(call.get("id") for call in event["protocol"].get("calls", []) if isinstance(call, dict))
        elif kind == "tool_result" and event.get("call_id") in self.genuine:
            self.events.append(event)


def _question(event: dict) -> str:
    from ..agent_recall import TASK_POST_HEAD       # keeps the alert text out of the past-conversation index, as routine posts are
    head = f"{TASK_POST_HEAD}盯盘提醒 #{event['alert_id']}"
    return f"{head}（{event.get('kind') or '未分类'}）{event.get('symbol')}：{event['text']}"[:QUESTION_MAX]


def _store_turn(owner: str, cid: str, turn_id: str, question: str, recorder: Recorder, protocol: dict, answer: str, failed: bool) -> None:
    from sqlalchemy import func
    from ..agent_chat_models import AgentMessage
    from ..database import SessionLocal
    conversation, turn = uuid.UUID(cid), uuid.UUID(turn_id)
    with SessionLocal() as db:
        sequence = db.scalar(select(func.coalesce(func.max(AgentMessage.sequence), 0)).where(AgentMessage.conversation_id == conversation))

        def add(role, content, **fields):
            nonlocal sequence
            sequence += 1
            db.add(AgentMessage(conversation_id=conversation, turn_id=turn, sequence=sequence, role=role, content=content, **fields))
        add("user", question)
        for item in recorder.events:
            if item["event"] == "assistant_tool_request":
                add("assistant", "", tool_calls=item["protocol"])
            else:
                add("tool", json.dumps(item["result"], ensure_ascii=False, separators=(",", ":"), default=str), tool_call_id=item["call_id"])
        add("assistant", answer, tool_calls=protocol, status="failed" if failed else "complete")
        db.commit()


# --- delivery (mode on) -----------------------------------------------------------------------------------------------

def _deliver(owner: str, text: str, *, source: str = "duty", cap: bool = True) -> tuple[uuid.UUID | None, str]:
    """Queue the kernel's message for the owner through the outbox (the owner's channel preference applies).  Duty messages (source ``duty``)
    have a daily count of their own (``daily_cap``, per UTC day) and neither use up nor wait on the bot's notify cap; ``cap=False`` (the
    morning brief, source ``brief``) skips that count.  Returns the outbox group and ``"queued"``, or None and why nothing was queued
    (``capped``, ``telegram_not_bound``)."""
    from sqlalchemy import func
    from .. import agent_bots as bots
    from .. import agent_telegram as telegram
    from ..agent_chat_models import AgentTelegramMessage
    from ..database import SessionLocal
    bot = bots.ensure_default_bot(owner)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        if cap:
            mine = (AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source == source,
                    AgentTelegramMessage.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
            sent = int(db.scalar(select(func.count(func.distinct(func.coalesce(AgentTelegramMessage.group_id, AgentTelegramMessage.id)))).where(*mine)) or 0)
            if sent >= daily_cap():
                return None, "capped"
        try:
            telegram.enqueue(db, owner, bot.id, telegram.render(bot.name, text), source=source, now=now)
        except telegram.NotifyError as failure:
            db.rollback()
            return None, str(failure)
        rows = list(db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source == source,
                                                                  AgentTelegramMessage.created_at == now, AgentTelegramMessage.bot_id == bot.id)))
        group = next((row.group_id for row in rows if row.group_id), None) or uuid.uuid4()
        for row in rows:
            row.group_id = group         # one group per message, also when only one channel took it
        db.commit()
    return group, "queued"


# --- the wake -----------------------------------------------------------------------------------------------------------

class WakeFailure(Exception):
    """Why a wake could not start (no owner login, no bot, no model): ``detail`` is the short code the log shows."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _code(failure: Exception) -> str:
    detail = getattr(failure, "detail", None)
    return detail if isinstance(detail, str) and detail else type(failure).__name__


async def duty_context(owner: str, held: dict):
    """The unattended context a duty turn (a wake, the morning brief) runs in, and the owner's default bot.  ``held`` receives the hidden
    conversation's id as soon as it exists (the stored turn needs it even if the turn fails).  Raises WakeFailure (no owner, bot or model)."""
    from .. import agent_bots as bots
    from .. import agent_task_runner as runner
    from ..agent_chat_store import owner_hash as hash_of
    from ..agent_chat_stream import _profile_block
    from ..agent_workflow.state import AgentRuntimeContext
    credential = runner.owner_credential()
    if not credential or hash_of(credential) != owner:
        raise WakeFailure("no_owner")
    bot = await asyncio.to_thread(bots.ensure_default_bot, owner)
    settings = await asyncio.to_thread(bots.turn_settings, owner, bot.id)
    if settings is None:
        raise WakeFailure("no_bot")
    model = await asyncio.to_thread(runner.task_model, owner, settings.get("model"))
    if model is None:
        raise WakeFailure("no_model")
    cid = held["conversation"] = await asyncio.to_thread(_wake_conversation, owner, bot.id)
    # The settings are the routine runner's: the owner's default bot (its instruction, tool scope, effort), the catalog model that bot names
    # (else the background model), the owner's profile block, an unattended context.  No token budget: the runner passes none either, and
    # a duty turn is bounded by the loop's step cap and its caller's wall clock.
    context = AgentRuntimeContext(
        provider=model["provider"], model=model["model"], api_key=model["api_key"], base_url=model.get("base_url"), owner_hash=owner,
        conversation_id=cid, identity_credential=credential, profile_block=await _profile_block(credential, settings), unattended=True,
        bot_id=settings.get("bot_id"), bot_name=settings.get("bot_name"), bot_is_default=bool(settings.get("is_default")),
        bot_block=settings.get("block"), tool_scope=settings.get("tool_scope"), reasoning_effort=settings.get("reasoning_effort"),
        engine="v2", default_company=settings.get("default_company"), catalog_name=model.get("name"))
    return bot, context


async def _judge(event: dict, owner: str, turn_id: str, recorder: Recorder, held: dict) -> dict:
    """The wake turn itself.  ``held`` receives the conversation id as soon as it exists (the stored turn needs it even if the turn fails)."""
    bot, context = await duty_context(owner, held)
    cid = held["conversation"]
    relation, told, outbox = await asyncio.to_thread(_facts, owner, event)
    # The alert's company always gets its block (its own symbol as the focus; the other members of a group alert follow).
    symbols = [s for s in (event.get("members") or []) if isinstance(s, str)]
    block, shown = None, []
    try:
        block, shown = await latest_known.block_for(" ".join([event["symbol"], *symbols]), previous=None, focus=event["symbol"], owner_hash=owner)
    except Exception:
        logger.exception("wake latest-known block failed")
    messages = prompt.build_wake_messages(context, event, relation, told, outbox, block)
    with model_usage.purpose("duty", owner_hash=owner, conversation_id=cid, bot_id=bot.id, turn_id=turn_id, job=str(event["alert_id"])):
        return await loop.run_wake(context, recorder.emit, messages, turn_id=turn_id, latest_symbols=shown if block else None)


async def wake(event: dict, *, owner_hash: str) -> dict:
    """Judge one alert: run one wake turn and write the alert's ``duty_log`` row, whatever happens.  Returns the row.  An alert that already
    has a row is not judged again."""
    event = clean_event(event)
    alert_id = event["alert_id"]
    existing = await asyncio.to_thread(duty_log.get, owner_hash, alert_id)
    if existing is not None:
        return existing
    current = mode()
    if current == "off":
        return await asyncio.to_thread(lambda: duty_log.record(owner_hash, alert_id, event=event, mode="off", outcome="skipped_off",
                                                               reason="唤醒功能关着（FINBOT_DUTY_MODE=off），没有评判。"))
    began = time.monotonic()
    turn_id = str(uuid.uuid4())
    recorder, held, result, failure = Recorder(), {}, None, None
    try:
        result = await asyncio.wait_for(_judge(event, owner_hash, turn_id, recorder, held), WALL_SECONDS)
    except TimeoutError:
        failure = f"超过 {WALL_SECONDS} 秒还没有结果，这次唤醒中止了。"
    except Exception as exc:
        logger.warning("wake of alert %s failed: %s", alert_id, _code(exc), exc_info=not hasattr(exc, "detail"))
        failure = f"这次唤醒没有完成：{_code(exc)}。"
    audit = (result or {}).get("audit") or {}
    chosen = audit.get("decision") if isinstance(audit.get("decision"), dict) else None
    fields: dict = {"outcome": "failed", "reason": failure}
    if chosen:
        fields = {"outcome": "decided", "decision": chosen["decision"], "reason": chosen["reason"], "message": chosen.get("message")}
    elif result is not None:
        said = (result.get("answer") or "").strip()
        fields = {"outcome": "no_decision", "reason": "模型没有调用 decide。" + (f"它的回答：{said[:300]}" if said and result.get("reason") != "empty_answer" else "")}
    if fields.get("decision") == "tell_now" and current == "on":
        if event.get("deferred"):
            fields["delivery"] = HELD_NIGHT         # the sentinel holds this alert until the morning digest; nothing is sent at night
        else:
            group, why = await asyncio.to_thread(_deliver, owner_hash, fields["message"])
            fields["delivery"] = why
            if group is not None:
                fields["delivery_group"] = group
    answer = (result or {}).get("answer") or fields["reason"] or "没有结果。"
    protocol = {"route": "K", **((result or {}).get("final_protocol") or {}), "audit": audit or {"engine": "v2", "terminal_status": "failed", "model_calls": 0, "calls": []},
                "citations": (result or {}).get("citations") or [], "unattended": True, "wake": True}
    if held.get("conversation"):
        try:
            await asyncio.to_thread(_store_turn, owner_hash, held["conversation"], turn_id, _question(event), recorder, protocol, answer, result is None)
        except Exception:
            logger.exception("wake: the turn of alert %s could not be stored", alert_id)
    return await asyncio.to_thread(lambda: duty_log.record(
        owner_hash, alert_id, event=event, mode=current, turn_id=uuid.UUID(turn_id) if held.get("conversation") else None,
        ms=round((time.monotonic() - began) * 1000), model_calls=int(audit.get("model_calls") or 0), **fields))


# --- the queue and its one worker ---------------------------------------------------------------------------------------

class WakeQueue:
    """At most ``QUEUE_MAX`` events wait; a new one on a full queue pushes the oldest out, which is logged as ``dropped`` (never judged)."""

    def __init__(self, maxsize: int = QUEUE_MAX) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.keys: set = set()          # (owner, alert id) waiting or being judged: the same alert twice is one wake-up

    async def submit(self, event: dict, owner: str) -> None:
        key = (owner, event["alert_id"])
        if key in self.keys:
            return
        self.keys.add(key)
        if await asyncio.to_thread(duty_log.get, owner, event["alert_id"]) is not None:
            self.keys.discard(key)          # judged before (the sentinel re-sent it): nothing to do
            return
        while True:
            try:
                self.queue.put_nowait((event, owner))
                return
            except asyncio.QueueFull:
                old, old_owner = self.queue.get_nowait()
                self.keys.discard((old_owner, old["alert_id"]))
                try:
                    await asyncio.to_thread(lambda: duty_log.record(
                        old_owner, old["alert_id"], event=old, mode=mode(), outcome="dropped",
                        reason=f"等待的提醒超过 {QUEUE_MAX} 条，这一条最旧，被丢弃，没有评判。"))
                except Exception:
                    logger.exception("wake: a dropped alert could not be logged")

    async def work(self) -> None:
        """Take events one at a time for ever; a wake that goes wrong never stops the worker."""
        while True:
            event, owner = await self.queue.get()
            try:
                await wake(event, owner_hash=owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("wake: alert %s was not judged", event.get("alert_id"))
            finally:
                self.keys.discard((owner, event["alert_id"]))


_STATE: dict = {"queue": None, "task": None, "loop": None}


def start() -> None:
    """Start the one worker on the running loop (the API's startup)."""
    current = asyncio.get_running_loop()
    task = _STATE["task"]
    if task is not None and not task.done() and _STATE["loop"] is current:
        return
    _STATE["queue"], _STATE["loop"] = WakeQueue(), current
    _STATE["task"] = current.create_task(_STATE["queue"].work(), name="wake-worker")


async def stop() -> None:
    task = _STATE["task"]
    _STATE.update(queue=None, task=None, loop=None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def submit(event: dict, owner: str) -> None:
    """Put an alert on the queue (starting the worker if the API's startup did not)."""
    start()
    await _STATE["queue"].submit(clean_event(event), owner)
