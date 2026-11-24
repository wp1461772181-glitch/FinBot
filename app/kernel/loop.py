"""The kernel turn: one append-only tool loop.

A fixed system prompt and fixed tool definitions stay at the front; each model step and each tool result is appended
after them, never edited, and the answer text is streamed out as the model writes it.  Read tools only, run
concurrently by ``toolrun``; no gate before the answer.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .. import agent_chat_provider as provider
from ..agent_chat_identity import owner_credential_matches
from ..agent_progress import progress_watchdog
from ..agent_tool_catalog import schemas
from ..agent_workflow.evidence import strip_invalid_markers
from . import prompt, tiers
from .toolrun import run_step_tools

READ_TOOLS: tuple[str, ...] = ("query_financials", "query_stock_prices", "query_market_quote", "query_sec_filings",
    "search_knowledge", "web_research", "search_configured_news", "calculate", "calculate_formula",
    "query_portfolio", "recall_conversations", "read_past_conversation", "read_history_citation")
MAX_STEPS = 12
SOFT_SECONDS = 180
IDLE_SECONDS = 300
RETRY_WAIT_SECONDS = 1
# Mirrors the old turn's RETRYABLE_PROVIDER list minus provider_protocol_too_large (resending the same request cannot cure it).
RETRYABLE_DETAILS = frozenset({"provider_incomplete_stream", "provider_incomplete_response", "provider_timeout",
                               "provider_network_error", "provider_error", "provider_incompatible_response"})
EMPTY_NOTE = "系统事实：上一步没有给出回答。请现在直接回答用户，不要再调用工具。"
EMPTY_ANSWER = "这次没能生成回答，请再发一次。"
CAP_NOTE = "系统事实：已达到本轮的查询上限。请用现有资料直接回答，不要再调用工具；资料不足的部分明说。"


@dataclass
class _Run:
    context: object
    emit: object
    messages: list
    user_text: str
    schemas: list
    tool_names: frozenset
    ceiling: str = "high"
    tier: str = "low"
    started: float = field(default_factory=time.monotonic)
    citations: list = field(default_factory=list)
    sent_text: bool = False
    step_text: str = ""
    audit: dict = field(default_factory=lambda: {
        "engine": "v2", "model_calls": 0, "decision_steps": 0, "tool_calls": 0, "token_usage": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "stop_reason": None})


def _tool_schemas(context) -> list[dict]:
    owner = owner_credential_matches(getattr(context, "identity_credential", ""))
    available = schemas(owner=owner, names=READ_TOOLS)
    scope = getattr(context, "tool_scope", None)
    # The kernel's own tool goes last whatever the ceiling is, so the list is the same for the whole turn.
    return [*(s for s in available if scope is None or s["function"]["name"] in scope), tiers.ESCALATE_SCHEMA]


def _user_text(question: str, history: list[dict]) -> str:
    """What the person typed in this conversation: the user's own figures may be bound by ``calculate``."""
    typed = [m["content"] for m in history if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return "\n".join([*typed, question])


def _add_usage(run: _Run, data: dict) -> None:
    usage = (data or {}).get("usage") or {}
    run.audit["token_usage"] += usage.get("total_tokens") or 0
    run.audit["cache_read_tokens"] += usage.get("cache_read_input_tokens") or 0
    run.audit["cache_write_tokens"] += usage.get("cache_creation_input_tokens") or 0


async def _model_step(run: _Run, tool_schemas: list[dict]) -> dict:
    """One model call whose text is streamed out.  One retry on a retryable provider failure."""
    context = run.context

    async def on_text(piece: str) -> None:
        if piece and isinstance(piece, str):
            run.sent_text = True
            run.step_text += piece
            await run.emit({"event": "delta", "text": piece})

    run.sent_text = False
    run.step_text = ""
    for attempt in (0, 1):
        try:
            data, message = await provider.stream_decision(
                context.provider, context.model, context.api_key, run.messages, tool_schemas, base_url=context.base_url,
                reasoning_effort=tiers.EFFORT[run.tier], on_text=on_text, keep_thinking=True, cache=True)
        except Exception as failure:
            # Whatever was streamed in this step is a cut-off: never leave it behind as the answer.
            if run.sent_text:
                await run.emit({"event": "answer_reset"})
                run.sent_text = False
                run.step_text = ""
            retryable = (isinstance(failure, provider.ProviderFailure) and failure.retryable) or getattr(failure, "detail", None) in RETRYABLE_DETAILS
            if attempt or not retryable:
                raise
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            continue
        run.audit["model_calls"] += 1
        run.audit["decision_steps"] += 1
        _add_usage(run, data)
        return message


async def _tool_step(run: _Run, message: dict) -> None:
    """The model asked for tools: drop the text it streamed, announce the request, run the calls."""
    if run.sent_text:
        await run.emit({"event": "answer_reset"})
    reasoning = {k: v for k, v in message.items() if k.startswith("reasoning_")}
    await run.emit({"event": "assistant_tool_request", "protocol": {"calls": message["tool_calls"], **reasoning}})
    run.messages.extend(await run_step_tools(run, message["tool_calls"]))


def _result(run: _Run, answer: str, stop_reason: str | None, failure: str | None = None) -> dict:
    status = "failed" if failure else "succeeded"
    run.audit["stop_reason"] = stop_reason
    run.audit["tier"] = run.tier
    run.audit["escalated"] = run.tier != "low"
    run.audit["terminal_status"] = status
    return {"answer": answer, "citations": run.citations, "status": status,
            "reason": failure, "route": "K", "audit": run.audit, "final_protocol": {"tier": run.tier}, "pending_request": None,
            "result_sets": [], "previous_category": None, "previous_scope": {}, "unverified_lines": [], "streamed": True}


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


async def run_turn(question: str, context, emit, messages: list[dict] | None = None, state: dict | None = None) -> dict:
    history = list(messages or [])[1:]   # the first message is the endpoint's own system prompt
    tool_schemas = _tool_schemas(context)
    run = _Run(context=context, emit=emit, messages=prompt.build_messages(question, context, history),
               user_text=_user_text(question, history), schemas=tool_schemas,
               tool_names=frozenset(s["function"]["name"] for s in tool_schemas),
               ceiling=tiers.ceiling(getattr(context, "reasoning_effort", None)))
    async with progress_watchdog(IDLE_SECONDS), provider.decision_session(context.base_url):
        return await _loop(run)
