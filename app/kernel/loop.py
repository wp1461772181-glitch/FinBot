"""The kernel turn: one append-only tool loop.

A fixed system prompt and fixed tool definitions stay at the front; each model step and each tool result is appended
after them, never edited, and the answer text is streamed out as the model writes it.  Reads run concurrently by
``toolrun``; ``act`` calls are released by tier (tier 1 at once, the rest collected onto one card that ends the turn); no
gate before the answer.
"""
from __future__ import annotations

import asyncio
import copy
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
from .. import latest_known
from ..agent_context import is_catalogue_message, is_memory_message
from ..agent_tool_catalog import schemas
from ..agent_workflow import consent
from ..agent_workflow.evidence import strip_invalid_markers
from . import act, ask, decide, helper, notify, press, progress, prompt, skills, tiers
from . import inbox as inboxes
from .toolrun import mark_timeline, number_attached, run_step_tools

READ_TOOLS: tuple[str, ...] = ("query_financials", "query_stock_prices", "query_market_quote", "query_sec_filings",
    "search_knowledge", "web_research", "search_configured_news", "search_x", "calculate", "calculate_formula",
    "query_portfolio", "recall_conversations", "read_past_conversation", "read_history_citation", "read_turn",
    "query_latest_forecast", "query_materials", "query_research_faq", "query_material_analysis", "search_material_analysis",
    "query_alerts", "query_holdings_overview", "read_workspace", "query_system_status", "query_research_queue", "list_routines", "list_models", "list_work", "list_watch_rules")
logger = logging.getLogger(__name__)
MAX_STEPS = 12
DEEP_MAX_STEPS = 40   # a deep-research turn (tier max): the owner asked for it and is not waiting on the page
MAX_SETS = 6          # as the old engine: the last six result sets of a conversation
SOFT_SECONDS = 180
DEEP_SOFT_SECONDS = 600   # well inside the stream's own MAX_TURN_SECONDS (1200): a last step and the closing call (each up to the
                          # provider's 180 s, plus a retry) still end before it, so the wrap-up comes first
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
    start_tier: str = "low"            # where the turn began (``tiers.start_tier``); "gone up" means above it
    permission_mode: str | None = None
    typed_this_turn: str = ""
    outside_in_prompt: bool = False    # outside text came in without a read (a latest-known block, a skill): see act._runs_at_once
    done_at_once: dict = field(default_factory=dict)          # what he sent while this turn ran (``question`` is what began it); never an earlier turn   # his permission mode, read once a turn by ``act`` (``app.permission_mode``)
    started: float = field(default_factory=time.monotonic)
    citations: list = field(default_factory=list)
    web_rows: dict = field(default_factory=dict)      # url -> the raw row of a page this turn's web reads returned (what ``act`` may save)
    carried_sets: list = field(default_factory=list)  # the conversation's earlier result sets (the graph state's ``result_sets``): pages earlier turns' reads returned
    new_sets: list = field(default_factory=list)      # this turn's web reads, as result sets to carry on
    proposals: list = field(default_factory=list)     # tier-2/3 operations collected this turn, put on one card when it ends
    writes: list = field(default_factory=list)       # one audit line per act call
    read_results: int = 0            # read or calculation results received this turn: after the first, tier 1 goes onto the card
    noticed_count: int = 0           # guesses remember wrote this turn (act keeps it to NOTICED_PER_TURN)
    question_card: dict | None = None    # the card of this turn's ``ask``, given to the user when the turn ends
    wake: decide.WakeState | None = None  # a wake turn (``run_wake``): what it has decided; None for every other turn
    pending: dict | None = None      # the card minted this turn
    carried: dict | None = None      # the conversation's own card, still waiting after this turn
    sent_text: bool = False
    step_text: str = ""
    narration: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    inbox: object | None = None      # the running turn's inbox (``inbox.Inbox``): what the owner says while it works; None for a turn without one
    is_helper: bool = False          # a helper's run (``helper.run``): the kernel's own tools are not its to call
    pausable: bool = True            # a message arriving while the answer is being written stops the writing (not in the closing steps)
    partial: str = ""                # the half-written answer an arriving message cut off: kept for a stop, which ends the turn with it
    paused_partial: bool = False     # that text is still on the user's screen: the next thing written replaces it
    cut: bool = False                # the next intake follows a cut-off answer
    must_say: str = ""               # what code must tell the user whatever else happens (the executed report of a card press): a stop keeps it
    audit: dict = field(default_factory=lambda: {
        "engine": "v2", "model_calls": 0, "decision_steps": 0, "tool_calls": 0, "token_usage": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "calls": [], "stop_reason": None})


def _tool_schemas(context) -> list[dict]:
    owner = owner_credential_matches(getattr(context, "identity_credential", ""))
    unattended = bool(getattr(context, "unattended", False))
    # search_x costs the owner money per post and needs his token: it is offered only where the server has one, and a scheduled run
    # (nobody watching) does not spend it, as the old turn's scheduled runs did not.
    # open_page changes nothing: it opens a page of the web app for him, or hands back its link on a bridge (design 4.2); a scheduled run has no page.
    names = [n for n in READ_TOOLS if n != "search_x" or (x_search.configured() and not unattended)] + (["open_page"] if owner and not unattended else [])
    available = schemas(owner=owner, kernel=True, names=names)
    scope = getattr(context, "tool_scope", None)
    # The kernel's own tools go last whatever the ceiling is, so the list is the same for the whole turn.
    # A skill is offered to an owner who has any enabled (the endpoint puts their list on the context); a bot's scope does not take it away.
    # A scheduled run has nobody to ask and no messages arriving, so no ``ask`` and no ``handle_message``; its ``act`` puts what it
    # proposes in the owner's inbox (``_mint_card``), and it may send him a message (``notify_telegram``) when its instruction says so.
    offered = [*(s for s in available if scope is None or s["function"]["name"] in scope), *([act.ACT_SCHEMA] if owner else []),
               *([notify.schema()] if owner and unattended else []), *([] if unattended else [ask.ASK_SCHEMA]),
               *([skills.USE_SKILL_SCHEMA] if owner and getattr(context, "skill_block", None) else []),
               progress.PLAN_SCHEMA, tiers.ESCALATE_SCHEMA, *([inboxes.HANDLE_SCHEMA] if getattr(context, "inbox", None) is not None else [])]
    if helper.offered(s["function"]["name"] for s in offered):      # behind the switch, after everything else: the list is unchanged with it off
        offered.append(helper.DELEGATE_SCHEMA)
    return [progress.with_say(s) for s in offered]


def _wake_schemas(context) -> list[dict]:
    """A wake turn's tools: the reads an owner's turn has (no ``search_x``: it costs per post and an unattended run does not
    spend it), ``decide``, and the kernel's ``plan`` / ``escalate``.  No ``act``, no ``ask``, no ``use_skill``."""
    owner = owner_credential_matches(getattr(context, "identity_credential", ""))
    available = schemas(owner=owner, kernel=True, names=[n for n in READ_TOOLS if n != "search_x"])
    scope = getattr(context, "tool_scope", None)
    offered = [*(s for s in available if scope is None or s["function"]["name"] in scope),
               decide.DECIDE_SCHEMA, progress.PLAN_SCHEMA, tiers.ESCALATE_SCHEMA]
    return [progress.with_say(s) for s in offered]


def _user_text(question: str, history: list[dict]) -> str:
    """What the person typed in this conversation: the user's own figures may be bound by ``calculate``."""
    typed = [m["content"] for m in history if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return "\n".join([*typed, question])


def _add_usage(run: _Run, data: dict, began: float, tier: str | None = None) -> None:
    """Add one model call to the totals and keep its own line: which tier it ran at, how long, what the cache gave."""
    usage = (data or {}).get("usage") or {}
    tokens, read, written = (usage.get(key) or 0 for key in ("total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    run.audit["token_usage"] += tokens
    run.audit["cache_read_tokens"] += read
    run.audit["cache_write_tokens"] += written
    run.audit["calls"].append({"tier": tier or run.tier, "ms": round((time.monotonic() - began) * 1000), "tokens": tokens,
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
        mark_timeline(run, "say", index=len(run.narration) - 1, step=run.audit["decision_steps"] + 1)     # said on the step whose call is made again
        await run.emit({"event": "narration", "text": sentence, "system": True})
    except Exception as secondary:
        # The provider's failure is what the turn reports; the switch's own trouble is only logged (never the key).
        logger.error("kernel backup switch failed: %s", type(secondary).__name__)
        raise failure from None
    return True


async def _model_step(run: _Run, tool_schemas: list[dict], *, tier: str | None = None, quiet: bool = False) -> dict:
    """One model call; when it fails after its retry, the same step is made again on the backup model."""
    while True:
        try:
            return await _call_model(run, tool_schemas, tier=tier, quiet=quiet)
        except Exception as failure:
            if run.fallback_used:
                run.audit["fallback"]["failed"] = True
                logger.warning("kernel backup model failed too: model=%s reason=%s", run.fallback_used, _failure_code(failure))
                raise
            if not await _switch_to_backup(run, failure):
                raise


def _streams(use: "ModelUse") -> bool:
    """Whether this model's answer text arrives piece by piece (Anthropic native); the others report the whole text once, after the call."""
    from .. import anthropic_native
    return anthropic_native.use_native(use.provider)


class TryDropped(Exception):
    """Raised from a lookup try's text callback once it is plainly writing (or the owner spoke): the try stops there, unused."""


QUIET_TEXT_LIMIT = 160    # characters of visible text a lookup try may stream before it counts as writing (a line before a call is fine)


class AnswerPaused(Exception):
    """Raised from the text callback when the owner says something while the answer is being written: the call stops there."""


async def _call_model(run: _Run, tool_schemas: list[dict], *, tier: str | None = None, quiet: bool = False) -> dict:
    """One model call whose text is streamed out.  One retry on a retryable provider failure.  When the owner sends a message while
    the answer is being written, the call stops within one piece of text and returns what was written as ``{"paused": True, ...}``.

    ``tier`` runs this one call at another tier than the turn's; ``quiet`` keeps its text off the screen (a lookup try, ``_step``)."""
    use = run.model
    tier = tier or run.tier
    streaming = _streams(use)      # only a provider that streams can be stopped within a piece of text; the others finish the call first

    quiet_chars = 0

    async def on_text(piece: str) -> None:
        nonlocal quiet_chars
        if quiet:       # nothing reaches the screen; a streaming try that has started writing, or that the owner spoke over, stops here
            if piece and isinstance(piece, str):
                quiet_chars += len(piece)
            if quiet_chars > QUIET_TEXT_LIMIT or (run.inbox is not None and run.inbox.has_fresh()):
                raise TryDropped()
            return
        if piece and isinstance(piece, str):
            if run.paused_partial:      # the text the owner's message cut off is still on his screen: this replaces it
                run.paused_partial = False
                run.partial = ""
                await run.emit({"event": "answer_reset"})
            run.sent_text = True
            run.step_text += piece
            await run.emit({"event": "delta", "text": piece})
            if streaming and run.pausable and run.inbox is not None and run.inbox.has_fresh():
                raise AnswerPaused()

    run.sent_text = False
    run.step_text = ""
    for attempt in (0, 1):
        began = time.monotonic()
        try:
            # The ledger: this attempt is a row of its own, under the catalog name of the model that is answering (the backup's, once switched).
            with model_usage.attempt(attempt + 1):
                data, message = await provider.stream_decision(
                    use.provider, use.model, use.api_key, run.messages, tool_schemas, base_url=use.base_url,
                    reasoning_effort=tiers.EFFORT[tier], on_text=on_text, keep_thinking=True, cache=True,
                    **({"catalog_name": use.name} if use.name else {}))
        except TryDropped:
            run.audit["model_calls"] += 1
            run.audit["decision_steps"] += 1          # taken back by ``_step`` with every dropped try
            run.audit["calls"].append({"tier": tier, "ms": round((time.monotonic() - began) * 1000), "tokens": 0, "cache_read": 0,
                                       "cache_write": 0, "model": run.model.label, "kept": False, "cut": True})
            return {"role": "assistant", "content": "", "dropped": True}
        except AnswerPaused:
            run.audit["model_calls"] += 1
            run.audit["decision_steps"] += 1
            return {"role": "assistant", "content": run.step_text, "paused": True}
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
            if tier == tiers.DEEP and _failure_code(failure) == "provider_incomplete_response":
                # Shadow 11-28: at max the model spent all 32768 output tokens thinking, twice, and wrote nothing (300 s lost).  The
                # same step again is made at high: the research goes on, this one step thinks less deeply.
                tier = "high"
                run.audit["deep_step_down"] = run.audit.get("deep_step_down", 0) + 1
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            continue
        run.audit["model_calls"] += 1
        run.audit["decision_steps"] += 1
        _add_usage(run, data, began, tier)
        return message


LOOKUP_CALLS = frozenset(READ_TOOLS) | {helper.DELEGATE}     # a step made only of these is legwork: what to look up, not what to conclude


def _lookup_tier_now(run: _Run) -> str | None:
    """The tier to try this step at first, or None for the turn's own.  Only once the turn has gone up, only right after a step that
    looked things up (not the step after ``escalate``: the higher tier makes its own first move, its plan), and never right after the
    owner spoke (what he said is the turn's tier to weigh)."""
    lookup = tiers.lookup_tier()
    if lookup is None or run.is_helper or TIERS_INDEX[lookup] >= TIERS_INDEX[run.tier] or TIERS_INDEX[run.tier] <= TIERS_INDEX[run.start_tier]:
        return None
    if run.audit.get("lookup_redone"):
        # One dropped try says the lookup tier misjudges this turn (it wanted to conclude while the turn's tier went on looking):
        # the rest of the turn runs at its own tier.  Shadow 11-28: a deep-research turn dropped five tries, 185 s of answers nobody saw.
        return None
    if not run.messages or run.messages[-1].get("role") != "tool":
        return None
    for message in reversed(run.messages):
        if message.get("role") == "assistant":
            names = {(call.get("function") or {}).get("name") for call in message.get("tool_calls") or []}
            return lookup if names and names <= LOOKUP_CALLS else None
    return None


TIERS_INDEX = {name: index for index, name in enumerate(tiers.TIERS)}


async def _step(run: _Run) -> dict:
    """One step of the turn.  Once the turn has gone up, a step after a lookup is first tried at the lookup tier, its text kept off
    the screen: when all it asks for is more lookups, that is the step (fetching does not need the higher tier); when it wants to
    conclude, write, act or anything else, the try is dropped and the step is made at the turn's tier, which decides for itself
    whether to look further (design 4.4)."""
    lookup = _lookup_tier_now(run)
    if lookup is not None:
        tried = await _model_step(run, run.schemas, tier=lookup, quiet=True)
        names = [(call.get("function") or {}).get("name") for call in tried.get("tool_calls") or []]
        spoke = run.inbox is not None and run.inbox.has_fresh()      # what he said is the turn's tier to weigh, not a lookup's
        if not tried.get("dropped") and names and all(name in LOOKUP_CALLS for name in names) and not spoke:
            run.audit["lookup_steps"] = run.audit.get("lookup_steps", 0) + 1
            return tried
        run.audit["lookup_redone"] = run.audit.get("lookup_redone", 0) + 1
        run.audit["decision_steps"] -= 1                # a dropped try is a model call, not a step of the turn
        if not tried.get("dropped") and run.audit["calls"]:
            run.audit["calls"][-1]["kept"] = False
        if spoke:
            await _intake(run)
    return await _model_step(run, run.schemas)


async def _tool_step(run: _Run, message: dict) -> None:
    """The model asked for tools: drop the text it streamed, announce the request, run the calls."""
    deciding = any((c.get("function") or {}).get("name") == inboxes.HANDLE for c in message["tool_calls"])
    if run.sent_text or (run.paused_partial and not deciding):      # the half-written text stays on screen while the model decides about the message
        run.paused_partial = False
        await run.emit({"event": "answer_reset"})
    sentence, item, system = progress.step_narration(message["tool_calls"], message.get("content"))
    if sentence:
        run.narration.append(sentence)
        mark_timeline(run, "say", index=len(run.narration) - 1)
        await run.emit({"event": "narration", "text": sentence, **({"item": item} if item else {}), **({"system": True} if system else {})})
    reasoning = {k: v for k, v in message.items() if k.startswith("reasoning_")}
    await run.emit({"event": "assistant_tool_request", "protocol": {"calls": message["tool_calls"], **reasoning}})
    run.messages.extend(await run_step_tools(run, message["tool_calls"]))


def _result(run: _Run, answer: str, stop_reason: str | None, failure: str | None = None, status: str | None = None) -> dict:
    status = status or ("failed" if failure else "waiting_for_input" if run.pending or run.carried else "succeeded")
    if run.pending and not run.question_card:
        run.audit.setdefault("write_outcome", "proposed")     # a press's own outcome (executed, failed) stays the turn's word
    run.audit["stop_reason"] = stop_reason
    run.audit["tier"] = run.tier
    run.audit["escalated"] = run.tier != run.start_tier
    run.audit["terminal_status"] = status
    run.audit["writes"] = run.writes
    return {"answer": answer, "citations": run.citations, "status": status,
            "reason": failure, "route": "K", "audit": run.audit, "final_protocol": {"tier": run.tier, "narration": run.narration, "checklist": run.checklist, **run.final_extra}, "pending_request": run.pending or run.carried,
            "result_sets": [*run.carried_sets, *run.new_sets][-MAX_SETS:], "previous_category": None, "previous_scope": {}, "unverified_lines": [], "streamed": True}


def _decided(run: _Run) -> dict:
    """A wake turn that has called ``decide``: its answer is the decision in words; the decision itself is on the audit."""
    chosen = run.wake.decision
    run.audit["decision"] = dict(chosen)
    text = f"{chosen['decision']}：{chosen['reason']}" + (f"\n\n{chosen['message']}" if chosen["message"] else "")
    return _result(run, text, "decided")


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


SUGGESTION_TITLE = "这是 Agent 的建议，不是你的要求："      # the old turn's words for a scheduled run's suggestion in the inbox
NO_INBOX = "（这是无人值守的运行，提出的操作没有地方放，没有保存。）"


def _to_inbox(run: _Run) -> str:
    """A scheduled run's proposals: nobody is here to press a card (and a card lives ten minutes), so they go to the owner's inbox
    (待你确认) through the runner's ``action_sink``, as one item holding them all, the way a live turn puts them on one card; he makes
    the card there later (``agent_tasks.mint_card``) and presses it.  One item, not one per proposal: a conversation holds one card at a
    time, so separate items would make each other's cards stale."""
    sink = getattr(run.context, "action_sink", None)
    if sink is None:
        return NO_INBOX
    display = copy.deepcopy(_card_display(run.proposals))
    display["title"] = SUGGESTION_TITLE + str(display.get("title") or run.proposals[0].operation["name"])
    display["agent_suggestion"] = True
    operations = [copy.deepcopy(p.operation) for p in run.proposals]
    sink.append({"operation": operations[0], "operations": operations, "display": display, "question": run.question})
    run.audit["write_outcome"] = "queued_for_owner"
    return ""


async def _mint_card(run: _Run) -> str:
    """Put the turn's proposals on one card.  Returns a sentence to append to the answer when the card could not be made."""
    proposals = run.proposals
    if not proposals:
        return ""
    context = run.context
    if getattr(context, "unattended", False):
        return _to_inbox(run)
    if inboxes.other_card_since(context.conversation_id, run.turn_id, run.started):
        return f"（确认卡没有生成：{ask.WRITE_CARD_WAITING} 请先处理那张卡片，再重新提出这项操作。）"
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
        run.audit["card_minted"] = run.pending["id"]
        inboxes.note_minted(context.conversation_id, run.turn_id, run.pending)
        return ""
    return f"（确认卡没有生成：{reason}。请重新提出这项操作。）"


async def _finish(run: _Run, message: dict, stop_reason: str | None, may_ask_again: bool) -> dict:
    """The step's text is the answer.  An empty one gets one more call (unless the cap call just failed to answer).

    A closing call is offered the same tools as every step (a valid request, a warm cache), but the system note tells the
    model to answer; tool calls it makes anyway are not run and not kept, only its text counts.
    """
    run.pausable = False      # the closing steps are not interrupted: a message that comes now gets its own answer
    answer = message.get("content") or ""
    if not answer.strip() and may_ask_again:
        run.messages.append(message)
        run.messages.append({"role": "system", "content": EMPTY_NOTE})
        if run.sent_text:
            await run.emit({"event": "answer_reset"})
        message = await _model_step(run, run.schemas)
        answer = message.get("content") or ""
    if run.inbox is not None:
        run.inbox.close()      # no await since the last look at the inbox: whatever nobody decided is its own turn from here
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
    steps = 0
    while steps < (DEEP_MAX_STEPS if run.tier == tiers.DEEP else MAX_STEPS):
        steps += 1
        if time.monotonic() - run.started > (DEEP_SOFT_SECONDS if run.tier == tiers.DEEP else SOFT_SECONDS):
            stop = "time_cap"
            break
        await _intake(run)
        message = await _step(run)
        if not message.get("tool_calls"):
            if message.get("paused") or (run.inbox is not None and run.inbox.has_fresh()):
                await _pause(run, message)      # the owner spoke while the answer was being written: decide with the half-written text in hand
                continue
            return await _finish(run, message, None, may_ask_again=True)
        run.messages.append(message)
        await _tool_step(run, message)
        if run.inbox is not None and run.inbox.stopping:
            return await _stopped(run)
        if run.wake is not None and run.wake.decision is not None:     # the first valid ``decide`` ends a wake turn: no more model calls
            return _decided(run)
    run.messages.append({"role": "system", "content": CAP_NOTE})
    run.pausable = False
    final = await _model_step(run, run.schemas)
    return await _finish(run, final, stop, may_ask_again=False)


async def _intake(run: _Run) -> None:
    """The messages the owner sent since the last look, as his own words after the work so far, and the one fixed note about them."""
    box = run.inbox
    if box is None or not box.has_fresh():
        return
    fresh = box.fresh()
    for message in fresh:
        message.shown = True
        message.withdraws = tuple(id(p) for p in run.proposals)
        run.messages.append({"role": "user", "content": prompt.neutralise(message.text)})
    run.messages.append({"role": "system", "content": prompt.interjection_note([m.id[:inboxes.SHORT_ID] for m in fresh], paused=run.cut)})
    run.cut = False
    run.user_text += "\n" + "\n".join(m.text for m in fresh)      # his figures may be bound by ``calculate`` like any he typed
    run.typed_this_turn += "\n" + "\n".join(m.text for m in fresh)
    mark_timeline(run, "interjection", count=len(fresh))
    mark_progress()


async def _pause(run: _Run, message: dict) -> None:
    """The answer was cut off (or was ready when a message came): the text so far is the model's own, and it decides with it in hand."""
    text = message.get("content") or ""
    if text.strip():
        run.messages.append({"role": "assistant", "content": text})
        run.partial = text
        run.cut = True
    if run.sent_text:
        run.paused_partial = True
        await run.emit({"event": "answer_paused"})
    mark_timeline(run, "answer_paused")


async def _stopped(run: _Run) -> dict:
    """The owner said stop: the turn ends with whatever it had written and the model's one sentence; nothing it proposed becomes a card."""
    sentence = run.inbox.stop_note or inboxes.DEFAULT_STOP_SENTENCE
    run.proposals.clear()
    run.pending = None
    run.question_card = None
    partial = run.partial.strip()
    text = "\n\n".join(part for part in (run.must_say.strip(), partial, sentence) if part)
    await run.emit({"event": "answer_reset"})
    await run.emit({"event": "delta", "text": text})
    await run.emit({"event": "stopped"})
    run.audit["stopped_by_message"] = True
    return _result(run, text, "stopped_by_message", status="stopped")


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


def _previous_user_message(history: list[dict], question: str, *, original: bool = False) -> str | None:
    """The user message before this question: what a follow-up like 「那它的现金流呢」 refers back to.  Only what the person typed counts
    (never the endpoint's memory note or citation catalogue), and the question is located the way ``build_messages`` does: it is in the
    history only when a user message equal to it follows the last assistant message; otherwise (a reply press, a card press) the previous
    message is simply the last one the person typed.  After a card press ``original`` is true: the question is the card's own, asked
    before the card, so it is the last matching user message wherever it stands."""
    body = [m for m in history if not is_memory_message(m) and not is_catalogue_message(m)]
    after = next((i for i in range(len(body) - 1, -1, -1) if body[i].get("role") == "assistant"), -1)
    asked = next((i for i in range(len(body) - 1, -1 if original else after, -1) if body[i].get("role") == "user" and body[i].get("content") == question), None)
    typed = [m["content"] for m in (body[:asked] if asked is not None else body) if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return typed[-1] if typed else None


async def _latest_block(run: "_Run", text: str, previous: str | None, focus: str | None, owner: bool) -> str | None:
    """The "latest known" block of this turn (``latest_known.block_for``: code writes it, no model call, bounded, never raises).  A failure of
    any kind means the turn goes on without it.  The companies it covers go on the audit and the timeline for the backstage."""
    rows: list[dict] = []
    try:
        found, symbols = await latest_known.block_for(text, previous=previous, focus=focus, rows=rows,
                                                      owner_hash=getattr(run.context, "owner_hash", None) if owner else None,
                                                      conversation_id=getattr(run.context, "conversation_id", None))
        if found:      # its lines are the turn's first citations: the model can answer from them without reading them again
            found = number_attached(run, found, rows)
    except Exception:
        logger.exception("kernel latest-known block failed")
        return None
    if not found:
        return None
    # News titles are third-party text, and 往来 and notices carry earlier answers that may retell a page; not every line is a cited
    # row, so any block counts (fails shut; 11-28 review).
    run.outside_in_prompt = True
    note_latest(run, symbols)
    return found


async def _scene(run, context, owner: bool) -> str | None:
    """「此刻」 for this turn (``prompt.scene_line``), and for the owner how long it has been since he last wrote here and what it sent him
    meanwhile (「这段时间」, plan D2), and what it keeps to look at again (``follow_ups.open_lines``).  ``FINBOT_KERNEL_SCENE=off`` leaves
    it all out (the kernel's tests describe the messages without it).  Nothing here may stop a turn: a part that cannot be read is left out."""
    from ..agent_workflow.fp_flags import flag
    if not flag("FINBOT_KERNEL_SCENE", True):
        return None
    parts = [prompt.scene_line(getattr(context, "via", None))]
    if owner:
        try:
            since = await asyncio.to_thread(_since_last, getattr(context, "owner_hash", ""), getattr(context, "conversation_id", ""), run.turn_id)
            if since:
                parts.append(since)
        except Exception:
            logger.exception("kernel scene: the time since the last message could not be read")
        from .. import follow_ups
        kept = await asyncio.to_thread(follow_ups.open_lines, getattr(context, "owner_hash", ""))
        if kept:
            parts.append(kept)
    return "\n".join(parts)


GAP_HOURS = 6


def _since_last(owner_hash: str, conversation_id: str, turn_id: str) -> str | None:
    """「这段时间」: his previous message in this conversation, if it was GAP_HOURS or more ago, and how many messages it sent him since."""
    import uuid as _uuid
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from ..agent_chat_models import AgentMessage, AgentTelegramMessage
    from ..database import SessionLocal
    try:
        conversation = _uuid.UUID(str(conversation_id))
    except ValueError:
        return None
    current = None
    try:
        current = _uuid.UUID(str(turn_id)) if turn_id else None
    except ValueError:
        pass
    with SessionLocal() as db:
        query = select(func.max(AgentMessage.created_at)).where(AgentMessage.conversation_id == conversation, AgentMessage.role == "user")
        if current is not None:
            query = query.where(AgentMessage.turn_id != current)
        last = db.scalar(query)
        if last is None:
            return None
        now = datetime.now(UTC)
        hours = (now - last).total_seconds() / 3600
        if hours < GAP_HOURS:
            return None
        sent = int(db.scalar(select(func.count(func.distinct(func.coalesce(AgentTelegramMessage.group_id, AgentTelegramMessage.id)))).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.created_at > last, AgentTelegramMessage.status == "sent",
            AgentTelegramMessage.source.notin_(("reply", "sentinel")))) or 0)
    gap = f"{int(hours // 24)} 天" if hours >= 48 else f"{int(hours)} 小时"
    told = f"这期间你主动发给过他 {sent} 条消息（异动解读、简报这类）。" if sent else ""
    return f"他上次在这个对话里说话是 {gap}前。{told}觉得值得就自然地接上（比如之前聊的事有了变化），不用强行寒暄。"


def note_latest(run: "_Run", symbols: list[str]) -> None:
    run.audit["latest_known"] = list(symbols)
    mark_timeline(run, "latest_known", symbols=list(symbols))


async def run_turn(question: str, context, emit, messages: list[dict] | None = None, state: dict | None = None) -> dict:
    """One kernel turn.  A turn with an inbox ends by closing it (what nobody decided is ``separate``) and says which user messages
    its answer answers (``final_protocol["reply_to"]``) and what each interjection came to (``audit["interjections"]``)."""
    box = getattr(context, "inbox", None)
    if box is not None:
        box.started = True
    try:
        result = await _run_turn(question, context, emit, messages, state)
    finally:
        if box is not None:
            box.close()
    if box is not None:
        result["final_protocol"] = {**result.get("final_protocol", {}), "reply_to": box.reply_to()}
        if box.messages:
            result.setdefault("audit", {})["interjections"] = box.record()
    return result


def _ceiling(context) -> str:
    """The server's top tier, except that deep research (max) is the owner's own, asked for in a turn he is in: a guest, a scheduled
    run or a brief stops at high (nobody there to come back to)."""
    top = tiers.ceiling()
    if top != tiers.DEEP:
        return top
    if getattr(context, "unattended", False) or not owner_credential_matches(getattr(context, "identity_credential", "") or ""):
        return "high"
    return top


async def _run_turn(question: str, context, emit, messages: list[dict] | None = None, state: dict | None = None) -> dict:
    state = state or {}
    history = list(messages or [])[1:]   # the first message is the endpoint's own system prompt
    pressed = press.read(question, state)
    raw = question      # a card button's value, which never reaches the model
    tool_schemas = _tool_schemas(context)
    run = _Run(context=context, emit=emit, messages=[], user_text="", schemas=tool_schemas,
               tool_names=frozenset(s["function"]["name"] for s in tool_schemas),
               model=ModelUse(context.provider, context.model, context.api_key, context.base_url, getattr(context, "catalog_name", None)),
               ceiling=_ceiling(context),
               question=question, turn_id=str(state.get("turn_id") or ""), inbox=getattr(context, "inbox", None),
               carried_sets=[x for x in state.get("result_sets") or [] if isinstance(x, dict) and x.get("owner") == context.owner_hash
                             and x.get("conversation") == context.conversation_id and isinstance(x.get("rows"), list)][-MAX_SETS:])
    run.tier = run.start_tier = tiers.start_tier(run.ceiling)
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
        # The companies the user's words (or the previous message, for a follow-up, or the bot's own company) point at: the card's original
        # question for a card press and the option's text for a reply, never a button's raw value.
        owner = owner_credential_matches(getattr(context, "identity_credential", ""))
        company = getattr(context, "default_company", None)
        latest = await _latest_block(run, run.question if fact else question, _previous_user_message(history, run.question if fact else question, original=bool(fact)),
                                     company.get("symbol") if isinstance(company, dict) else None, owner)
        run.messages = prompt.build_messages(question, context, history, fact=fact, skill=started, latest=latest, helper=helper.DELEGATE in run.tool_names,
                                           tier=run.start_tier, scene=await _scene(run, context, owner))
        if started:
            run.outside_in_prompt = True     # a skill's steps can be imported text
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
        run.must_say = settled.report + (settled.note or "")      # a stop must not hide that the write ran
        try:
            result = await _loop(run)
        except Exception:
            logger.exception("kernel turn after an executed press failed")
            result = None
        if result is None or result.get("reason") == "empty_answer":
            return await _report_fallback(run, settled.report + (settled.note or ""))
        if settled.note and result.get("status") != "stopped":      # where a saved page landed (a stop's text already holds it): a link written by code, not left to the model
            await run.emit({"event": "delta", "text": settled.note})
            result["answer"] += settled.note
        return result


async def run_wake(context, emit, messages: list[dict], *, turn_id: str, latest_symbols: list[str] | None = None, decide_tool: bool = True) -> dict:
    """One wake turn (``wake.wake``): the same append-only loop with the restricted tools and no history; it ends at the first valid
    ``decide`` (``audit["decision"]``), or at an answer without one.  Nothing is streamed to anyone: ``emit`` is the caller's recorder.
    With ``decide_tool=False`` (the morning brief) ``decide`` is not offered: the turn ends at its answer."""
    tool_schemas = [s for s in _wake_schemas(context) if decide_tool or s["function"]["name"] != decide.DECIDE]
    run = _Run(context=context, emit=emit, messages=messages, user_text="", schemas=tool_schemas,
               tool_names=frozenset(s["function"]["name"] for s in tool_schemas),
               model=ModelUse(context.provider, context.model, context.api_key, context.base_url, getattr(context, "catalog_name", None)),
               ceiling=tiers.clamp(tiers.ceiling(), "high"), turn_id=turn_id, wake=decide.WakeState())     # nobody asked for deep research
    if latest_symbols:
        note_latest(run, latest_symbols)
    async with progress_watchdog(IDLE_SECONDS), provider.decision_session(context.base_url):
        return await _loop(run)
