"""The kernel turn: one append-only tool loop.

A fixed system prompt and fixed tool definitions stay at the front; each model step and each tool result is appended
after them, never edited, and the answer text is streamed out as the model writes it.  Reads run concurrently by
``toolrun``; ``act`` calls are released by tier (tier 1 at once, the rest collected onto one card that ends the turn); no
gate before the answer.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .. import agent_chat_provider as provider
from .. import agent_model_roles as roles
from .. import model_usage
from .. import x_search
from ..agent_chat_identity import owner_credential_matches
from ..agent_progress import mark_progress, progress_watchdog
from .. import agent_skills
from ..agent_tool_catalog import schemas
from ..agent_workflow import consent
from ..agent_workflow.evidence import strip_invalid_markers
from . import act, ask, press, progress, prompt, skills, tiers
from .toolrun import mark_timeline, run_step_tools

READ_TOOLS: tuple[str, ...] = ("query_financials", "query_stock_prices", "query_market_quote", "query_sec_filings",
    "search_knowledge", "web_research", "search_configured_news", "search_x", "calculate", "calculate_formula",
    "query_portfolio", "recall_conversations", "read_past_conversation", "read_history_citation",
    "query_latest_forecast", "query_materials", "query_research_faq", "query_material_analysis", "search_material_analysis",
    "query_alerts", "query_holdings_overview", "read_workspace", "query_system_status", "query_research_queue", "list_routines")
logger = logging.getLogger(__name__)
MAX_STEPS = 12
MAX_SETS = 6          # as the old engine: the last six result sets of a conversation
SOFT_SECONDS = 180
IDLE_SECONDS = 300
RETRY_WAIT_SECONDS = 1
# Mirrors the old turn's RETRYABLE_PROVIDER list minus provider_protocol_too_large (resending the same request cannot cure it).
RETRYABLE_DETAILS = frozenset({"provider_incomplete_stream", "provider_incomplete_response", "provider_timeout",
                               "provider_network_error", "provider_error", "provider_incompatible_response"})
EMPTY_NOTE = "系统事实：上一步没有给出回答。请现在直接回答用户，不要再调用工具。"
EMPTY_ANSWER = "这次没能生成回答，请再发一次。"
CAP_NOTE = "系统事实：已达到本轮的查询上限。请用现有资料直接回答，不要再调用工具；资料不足的部分明说。"


BACKUP_LINE = "\n\n（这条由备用模型「{name}」回答。）"
BACKUP_NARRATION = "主模型这一步没有成功，改用备用模型「{name}」继续。"
PRIVATE_KEYS = ("_anthropic_content",)    # what a native Anthropic reply keeps for itself (signed thinking): another model cannot take it


@dataclass
class ModelUse:
    """The model one turn is talking to.  ``name`` is its catalog entry (None for the context's own: not known by name)."""
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str | None = field(default=None, repr=False)
    name: str | None = None

    @property
    def label(self) -> str:
        return self.name or f"{self.provider}/{self.model}"

    def same_as(self, other: "ModelUse") -> bool:
        return (self.provider, self.model) == (other.provider, other.model)


@dataclass
class _Run:
    context: object
    emit: object
    messages: list
    user_text: str
    schemas: list
    tool_names: frozenset
    model: ModelUse      # the model in use: the context's own, until a failure hands the turn to the backup
    final_extra: dict = field(default_factory=dict)     # extra ``final_protocol`` keys of this turn
    fallback_used: str | None = None   # the backup's catalog name once the turn is on it
    ceiling: str = "high"
    question: str = ""      # this turn's user message, as typed
    turn_id: str = ""
    tier: str = "low"
    started: float = field(default_factory=time.monotonic)
    citations: list = field(default_factory=list)
    web_rows: dict = field(default_factory=dict)      # url -> the raw row of a page this turn's web reads returned (what ``act`` may save)
    carried_sets: list = field(default_factory=list)  # the conversation's earlier result sets (the graph state's ``result_sets``): pages earlier turns' reads returned
    new_sets: list = field(default_factory=list)      # this turn's web reads, as result sets to carry on
    proposals: list = field(default_factory=list)     # tier-2/3 operations collected this turn, put on one card when it ends
    writes: list = field(default_factory=list)       # one audit line per act call
    read_results: int = 0            # read or calculation results received this turn: after the first, tier 1 goes onto the card
    question_card: dict | None = None    # the card of this turn's ``ask``, given to the user when the turn ends
    pending: dict | None = None      # the card minted this turn
    carried: dict | None = None      # the conversation's own card, still waiting after this turn
    sent_text: bool = False
    step_text: str = ""
    narration: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    audit: dict = field(default_factory=lambda: {
        "engine": "v2", "model_calls": 0, "decision_steps": 0, "tool_calls": 0, "token_usage": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "calls": [], "stop_reason": None})


def _tool_schemas(context) -> list[dict]:
    owner = owner_credential_matches(getattr(context, "identity_credential", ""))
    # search_x costs the owner money per post and needs his token: it is offered only where the server has one.
    available = schemas(owner=owner, names=[n for n in READ_TOOLS if n != "search_x" or x_search.configured()])
    scope = getattr(context, "tool_scope", None)
    # The kernel's own tools go last whatever the ceiling is, so the list is the same for the whole turn.
    # A skill is offered to an owner who has any enabled (the endpoint puts their list on the context); a bot's scope does not take it away.
    offered = [*(s for s in available if scope is None or s["function"]["name"] in scope), *([act.ACT_SCHEMA] if owner else []),
               ask.ASK_SCHEMA, *([skills.USE_SKILL_SCHEMA] if owner and getattr(context, "skill_block", None) else []),
               progress.PLAN_SCHEMA, tiers.ESCALATE_SCHEMA]
    return [progress.with_say(s) for s in offered]


def _user_text(question: str, history: list[dict]) -> str:
    """What the person typed in this conversation: the user's own figures may be bound by ``calculate``."""
    typed = [m["content"] for m in history if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return "\n".join([*typed, question])


def _add_usage(run: _Run, data: dict, began: float) -> None:
    """Add one model call to the totals and keep its own line: which tier it ran at, how long, what the cache gave."""
    usage = (data or {}).get("usage") or {}
    tokens, read, written = (usage.get(key) or 0 for key in ("total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    run.audit["token_usage"] += tokens
    run.audit["cache_read_tokens"] += read
    run.audit["cache_write_tokens"] += written
    run.audit["calls"].append({"tier": run.tier, "ms": round((time.monotonic() - began) * 1000), "tokens": tokens,
                               "cache_read": read, "cache_write": written, "model": run.model.label})
    mark_timeline(run, "call", index=len(run.audit["calls"]) - 1)


def _failure_code(failure: Exception) -> str:
    detail = getattr(failure, "detail", None)
    return detail if isinstance(detail, str) and detail else type(failure).__name__


async def _backup_for(run: _Run) -> dict | None:
    """The owner's backup model settings, or None (a broken lookup counts as none)."""
    try:
        found = await asyncio.to_thread(roles.fallback_for, getattr(run.context, "owner_hash", ""))
    except Exception:
        logger.exception("kernel backup model lookup failed")
        return None
    return found or None


async def _switch_to_backup(run: _Run, failure: Exception) -> bool:
    """The model failed after its retry: move the turn to the owner's backup model, if there is one that differs.

    The message list is rebuilt once: kept reasoning belongs to the model that wrote it.  Returns whether it switched."""
    found = await _backup_for(run)
    if not found:
        return False
    try:
        backup = ModelUse(found["provider"], found["model"], found["api_key"], found.get("base_url"), found["name"])
        if backup.same_as(run.model):
            return False
        sentence = BACKUP_NARRATION.format(name=backup.name)
        run.audit["fallback"] = {"from": run.model.label, "to": backup.name, "reason": _failure_code(failure)}
        logger.warning("kernel backup switch: from=%s to=%s reason=%s", run.model.label, backup.name, _failure_code(failure))
        run.model = backup
        run.fallback_used = backup.name
        mark_progress()      # the backup gets a fresh idle budget
        run.messages[:] = [{k: v for k, v in m.items() if not (k.startswith("reasoning_") or k in PRIVATE_KEYS)} if m.get("role") == "assistant" else m
                           for m in run.messages]
        run.narration.append(sentence)
        mark_timeline(run, "say", index=len(run.narration) - 1)
        await run.emit({"event": "narration", "text": sentence, "system": True})
    except Exception as secondary:
        # The provider's failure is what the turn reports; the switch's own trouble is only logged (never the key).
        logger.error("kernel backup switch failed: %s", type(secondary).__name__)
        raise failure from None
    return True


async def _model_step(run: _Run, tool_schemas: list[dict]) -> dict:
    """One model call; when it fails after its retry, the same step is made again on the backup model."""
    while True:
        try:
            return await _call_model(run, tool_schemas)
        except Exception as failure:
            if run.fallback_used:
                run.audit["fallback"]["failed"] = True
                logger.warning("kernel backup model failed too: model=%s reason=%s", run.fallback_used, _failure_code(failure))
                raise
            if not await _switch_to_backup(run, failure):
                raise


async def _call_model(run: _Run, tool_schemas: list[dict]) -> dict:
    """One model call whose text is streamed out.  One retry on a retryable provider failure."""
    use = run.model

    async def on_text(piece: str) -> None:
        if piece and isinstance(piece, str):
            run.sent_text = True
            run.step_text += piece
            await run.emit({"event": "delta", "text": piece})

    run.sent_text = False
    run.step_text = ""
    for attempt in (0, 1):
        began = time.monotonic()
        try:
            # The ledger: this attempt is a row of its own, under the catalog name of the model that is answering (the backup's, once switched).
            with model_usage.attempt(attempt + 1):
                data, message = await provider.stream_decision(
                    use.provider, use.model, use.api_key, run.messages, tool_schemas, base_url=use.base_url,
                    reasoning_effort=tiers.EFFORT[run.tier], on_text=on_text, keep_thinking=True, cache=True,
                    **({"catalog_name": use.name} if use.name else {}))
        except Exception as failure:
            # Whatever was streamed in this step is a cut-off: never leave it behind as the answer.
            if run.sent_text:
                await run.emit({"event": "answer_reset"})
                run.sent_text = False
                run.step_text = ""
            retryable = (isinstance(failure, provider.ProviderFailure) and failure.retryable) or getattr(failure, "detail", None) in RETRYABLE_DETAILS
            if attempt or not retryable:
                raise
            # A call that hung for the whole request timeout is not tried again on the same model when a backup exists:
            # a second wait would run into the turn's idle watchdog, which cancels instead of switching.
            if _failure_code(failure) == "provider_timeout" and not run.fallback_used:
                found = await _backup_for(run)
                if found and (found.get("provider"), found.get("model")) != (use.provider, use.model):
                    raise
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            continue
        run.audit["model_calls"] += 1
        run.audit["decision_steps"] += 1
        _add_usage(run, data, began)
        return message


async def _tool_step(run: _Run, message: dict) -> None:
    """The model asked for tools: drop the text it streamed, announce the request, run the calls."""
    if run.sent_text:
        await run.emit({"event": "answer_reset"})
    sentence, item, system = progress.step_narration(message["tool_calls"], message.get("content"))
    if sentence:
        run.narration.append(sentence)
        mark_timeline(run, "say", index=len(run.narration) - 1)
        await run.emit({"event": "narration", "text": sentence, **({"item": item} if item else {}), **({"system": True} if system else {})})
    reasoning = {k: v for k, v in message.items() if k.startswith("reasoning_")}
    await run.emit({"event": "assistant_tool_request", "protocol": {"calls": message["tool_calls"], **reasoning}})
    run.messages.extend(await run_step_tools(run, message["tool_calls"]))


def _result(run: _Run, answer: str, stop_reason: str | None, failure: str | None = None) -> dict:
    status = "failed" if failure else "waiting_for_input" if run.pending or run.carried else "succeeded"
    if run.pending and not run.question_card:
        run.audit.setdefault("write_outcome", "proposed")     # a press's own outcome (executed, failed) stays the turn's word
    run.audit["stop_reason"] = stop_reason
    run.audit["tier"] = run.tier
    run.audit["escalated"] = run.tier != "low"
    run.audit["terminal_status"] = status
    run.audit["writes"] = run.writes
    return {"answer": answer, "citations": run.citations, "status": status,
            "reason": failure, "route": "K", "audit": run.audit, "final_protocol": {"tier": run.tier, "narration": run.narration, "checklist": run.checklist, **run.final_extra}, "pending_request": run.pending or run.carried,
            "result_sets": [*run.carried_sets, *run.new_sets][-MAX_SETS:], "previous_category": None, "previous_scope": {}, "unverified_lines": [], "streamed": True}


def _card_display(proposals: list) -> dict:
    """One card for everything proposed this turn: the old engine's way of merging several proposals."""
    if len(proposals) == 1:
        return proposals[0].display
    targets = [{**target, **{k: p.display[k] for k in ("title", "saved_date", "web_date") if p.display.get(k)}}
               for p in proposals for target in p.display.get("targets", [])]
    display = {"title": "确认以下操作", "targets": targets}
    alternatives = [p.display["alternative"] for p in proposals if p.display.get("alternative")]
    if alternatives:
        display["alternative"] = " ".join(dict.fromkeys(alternatives))
    return display


async def _mint_card(run: _Run) -> str:
    """Put the turn's proposals on one card.  Returns a sentence to append to the answer when the card could not be made."""
    proposals = run.proposals
    if not proposals:
        return ""
    context = run.context
    variants = [("保存并启用", None), ("存为草稿", "draft")] if all(p.operation["name"] == "save_skill" for p in proposals) else None
    try:
        run.pending = await asyncio.to_thread(consent.propose, context.identity_credential, context.conversation_id,
                                              [p.operation for p in proposals], _card_display(proposals), question=run.question, variants=variants,
                                              **({"options": proposals[0].options} if proposals[0].options is not None else {}))
    except consent.ConsentError as failure:
        reason = consent.failure_reason(str(getattr(failure, "code", None) or failure))
    except Exception:
        reason = consent.failure_reason("write_service_failed")
    else:
        return ""
    return f"（确认卡没有生成：{reason}。请重新提出这项操作。）"


async def _finish(run: _Run, message: dict, stop_reason: str | None, may_ask_again: bool) -> dict:
    """The step's text is the answer.  An empty one gets one more call (unless the cap call just failed to answer).

    A closing call is offered the same tools as every step (a valid request, a warm cache), but the system note tells the
    model to answer; tool calls it makes anyway are not run and not kept, only its text counts.
    """
    answer = message.get("content") or ""
    if not answer.strip() and may_ask_again:
        run.messages.append(message)
        run.messages.append({"role": "system", "content": EMPTY_NOTE})
        if run.sent_text:
            await run.emit({"event": "answer_reset"})
        message = await _model_step(run, run.schemas)
        answer = message.get("content") or ""
    if not answer.strip():
        if run.sent_text:
            await run.emit({"event": "answer_reset"})
        await run.emit({"event": "delta", "text": EMPTY_ANSWER})
        return _result(run, EMPTY_ANSWER, stop_reason, failure="empty_answer")
    cleaned = strip_invalid_markers(answer, run.citations)
    if cleaned != run.step_text:
        # What the client holds is the streamed text; make it the cleaned answer.
        if run.step_text:
            await run.emit({"event": "answer_reset"})
        await run.emit({"event": "delta", "text": cleaned})
    failed_card = await _mint_card(run)
    if run.question_card:
        run.pending = run.question_card
    if failed_card:
        cleaned = f"{cleaned}\n\n{failed_card}"
        await run.emit({"event": "delta", "text": f"\n\n{failed_card}"})
    if run.fallback_used:
        label = BACKUP_LINE.format(name=run.fallback_used)
        cleaned = f"{cleaned}{label}"
        await run.emit({"event": "delta", "text": label})
        run.final_extra["fallback_model"] = run.fallback_used
    if progress.close_checklist(run):
        await run.emit({"event": "checklist", "items": [dict(entry) for entry in run.checklist]})
    return _result(run, cleaned, stop_reason)


async def _loop(run: _Run) -> dict:
    stop = "step_cap"
    for _ in range(MAX_STEPS):
        if time.monotonic() - run.started > SOFT_SECONDS:
            stop = "time_cap"
            break
        message = await _model_step(run, run.schemas)
        if not message.get("tool_calls"):
            return await _finish(run, message, None, may_ask_again=True)
        run.messages.append(message)
        await _tool_step(run, message)
    run.messages.append({"role": "system", "content": CAP_NOTE})
    final = await _model_step(run, run.schemas)
    return await _finish(run, final, stop, may_ask_again=False)


async def _report_fallback(run: _Run, sentence: str) -> dict:
    await run.emit({"event": "answer_reset"})      # whatever was streamed (or the fixed failure text) is not the answer
    run.pending = None
    run.audit["report"] = "fallback"
    await run.emit({"event": "delta", "text": sentence})
    return _result(run, sentence, "press_report")


async def _answer_press(run: _Run, settled: press.Settled, state: dict) -> dict:
    """A press that is answered in a sentence: no model call."""
    if settled.status == "waiting_for_input":
        run.carried = state.get("pending_request")
    await run.emit({"event": "delta", "text": settled.answer})
    return _result(run, settled.answer, "press")


async def _skill_of_question(context, state: dict) -> dict | None:
    """The skill that was in force when the question being answered was asked (the server kept its name on the card), if it is still enabled."""
    name = (state.get("pending_request") or {}).get("skill")
    if not isinstance(name, str) or not name or not owner_credential_matches(getattr(context, "identity_credential", "")):
        return None
    try:
        return await asyncio.to_thread(agent_skills.active, getattr(context, "owner_hash", ""), name=name)
    except Exception:
        logger.exception("kernel skill lookup for an answer failed")
        return None


async def run_turn(question: str, context, emit, messages: list[dict] | None = None, state: dict | None = None) -> dict:
    state = state or {}
    history = list(messages or [])[1:]   # the first message is the endpoint's own system prompt
    pressed = press.read(question, state)
    raw = question      # a card button's value, which never reaches the model
    tool_schemas = _tool_schemas(context)
    run = _Run(context=context, emit=emit, messages=[], user_text="", schemas=tool_schemas,
               tool_names=frozenset(s["function"]["name"] for s in tool_schemas),
               model=ModelUse(context.provider, context.model, context.api_key, context.base_url, getattr(context, "catalog_name", None)),
               ceiling=tiers.ceiling(getattr(context, "reasoning_effort", None)),
               question=question, turn_id=str(state.get("turn_id") or ""),
               carried_sets=[x for x in state.get("result_sets") or [] if isinstance(x, dict) and x.get("owner") == context.owner_hash
                             and x.get("conversation") == context.conversation_id and isinstance(x.get("rows"), list)][-MAX_SETS:])
    async with progress_watchdog(IDLE_SECONDS), provider.decision_session(context.base_url):
        fact = None
        if pressed:
            settled = await press.settle(run, pressed, state)
            if settled.reply is None:      # an answer to a question is not a write: it leaves no write outcome
                run.audit["write_outcome"] = settled.outcome
            if settled.answer is not None:
                return await _answer_press(run, settled, state)
            if settled.reply is not None:
                # An ordinary turn whose question is the option's text.  The model wrote that text, perhaps from a page it
                # had read: like the turn after a write press, nothing runs at once in it.
                question = run.question = settled.reply
                run.read_results = 1
            else:
                run.audit["write_request_id"] = pressed.request_id
                fact = settled.fact
                run.read_results = 1     # execution results are in front of the model: nothing it asks for now runs at once
                # From here on the user's words are the card's original question, never the button's value.
                run.question = (state.get("pending_request") or {}).get("original_question") or ""
            # The button's raw value is not the user's message, whichever card it was on.
            history = [m for m in history if not (m.get("role") == "user" and m.get("content") == raw)]
        started = getattr(context, "active_skill", None)
        # The answer to a question the skill asked, pressed or typed (a channel without buttons can only type it), takes the
        # skill up again.  A question card is not carried past the next turn, so this reaches that one turn only.
        if not started and (settled.reply is not None if pressed else True):
            started = await _skill_of_question(context, state)
        run.messages = prompt.build_messages(question, context, history, fact=fact, skill=started)
        if started and owner_credential_matches(getattr(context, "identity_credential", "")):
            run.audit["skill"] = {"name": started["name"], "version": started["version"]}
        run.user_text = _user_text(run.question, history)
        note = None if pressed else press.typed_note(state)
        if note:
            run.messages.append({"role": "system", "content": note})
            run.carried = press.waiting_write_card(state)
        if not fact:
            return await _loop(run)
        # The write is done: whatever the model does next, the user is told what happened, so they do not ask for it twice.
        try:
            result = await _loop(run)
        except Exception:
            logger.exception("kernel turn after an executed press failed")
            result = None
        if result is None or result.get("reason") == "empty_answer":
            return await _report_fallback(run, settled.report + (settled.note or ""))
        if settled.note:      # where a saved page landed: a link written by code, not left to the model
            await run.emit({"event": "delta", "text": settled.note})
            result["answer"] += settled.note
        return result
