"""The kernel turn: one append-only tool loop.

A fixed system prompt and fixed tool definitions stay at the front; each model step and each tool result is appended
after them, never edited, and the answer text is streamed out as the model writes it.  Read tools only, run one
after another; no gate before the answer.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import dataclass, field

from .. import agent_chat_provider as provider
from ..agent_chat_identity import owner_credential_matches
from ..agent_progress import mark_progress, progress_watchdog
from ..agent_tool_catalog import definitions, schemas, validate
from ..agent_workflow import tools
from ..agent_workflow.evidence import number_rows, strip_invalid_markers
from . import prompt

READ_TOOLS: tuple[str, ...] = ("query_financials", "query_stock_prices", "query_market_quote", "query_sec_filings",
    "search_knowledge", "web_research", "search_configured_news", "calculate", "calculate_formula",
    "query_portfolio", "recall_conversations", "read_past_conversation", "read_history_citation")
MAX_STEPS = 12
SOFT_SECONDS = 180
IDLE_SECONDS = 300
TOOL_IDLE_SECONDS = 180
RETRY_WAIT_SECONDS = 1
# Mirrors the old turn's RETRYABLE_PROVIDER list minus provider_protocol_too_large (resending the same request cannot cure it).
RETRYABLE_DETAILS = frozenset({"provider_incomplete_stream", "provider_incomplete_response", "provider_timeout",
                               "provider_network_error", "provider_error", "provider_incompatible_response"})
RECEIPT_HINT = "有输入没有绑定到来源，逐项原因见 input_receipts。只需改正其中 found 为 false 的输入，其余保持不变；不要把数值改写成更长的小数去试。closest_in_source 与 bindable_values 都只是不完整的候选。"
EMPTY_NOTE = "系统事实：上一步没有给出回答。请现在直接回答用户，不要再调用工具。"
EMPTY_ANSWER = "这次没能生成回答，请再发一次。"
CAP_NOTE = "系统事实：已达到本轮的查询上限。请用现有资料直接回答，不要再调用工具；资料不足的部分明说。"
# Results of these tools are the model's memory or a computation, not saved evidence: they are never numbered as rows.
_UNNUMBERED = {"recall_conversations", "read_past_conversation"}
_SOURCE_TYPES = {"web_research": "web", "search_configured_news": "configured_news", "query_sec_filings": "official_filing"}


@dataclass
class _Run:
    context: object
    emit: object
    messages: list
    user_text: str
    schemas: list
    tool_names: frozenset
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
    return [s for s in available if scope is None or s["function"]["name"] in scope]


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
                reasoning_effort=context.reasoning_effort, on_text=on_text, keep_thinking=True, cache=True)
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


def _number_evidence(run: _Run, name: str, outcome: dict) -> dict:
    """The rows of an evidence tool, numbered into this turn's citations; the numbered rows are what the model sees."""
    rows = outcome.get("data") if outcome.get("data") is not None else (outcome.get("items") or [])
    rows = [rows] if not isinstance(rows, list) else rows
    prepared = []
    for original in rows:
        if not isinstance(original, dict):
            continue
        row = copy.deepcopy(original)
        row["_citations"] = [c for c in outcome.get("_citations", []) if row.get("id") and str(c.get("source_id", "")) == str(row["id"])]
        if row.get("material_type"):
            row.setdefault("source_type", row["material_type"])
        if name in _SOURCE_TYPES:
            row.setdefault("source_type", _SOURCE_TYPES[name])
        prepared.append(row)
    if not prepared:
        return outcome
    shown = {"ok": True, "data": number_rows(name, prepared, run.citations, {}), "source": outcome.get("source")}
    if isinstance(outcome.get("meta"), dict):
        shown["meta"] = outcome["meta"]
    return shown


def _calculate(run: _Run, name: str, args: dict) -> dict:
    """``calculate`` / ``calculate_formula`` run in-process; a result is registered as a ``calculation`` citation."""
    try:
        if name == "calculate":
            from ..agent_workflow.calculation import calculate
            value = calculate(args, run.citations, run.user_text)
            ordinal = len(run.citations) + 1
            run.citations.append({"ordinal": ordinal, "source_type": "calculation", "derived": True, "title": "可复核计算",
                                  "quote": json.dumps(value, ensure_ascii=False), "calculation": value})
            return {"ok": True, "data": [{**value, "citation": f"[{ordinal}]"}]}
        from ..agent_workflow.formula_replay import execute_calculate_formula
        return execute_calculate_formula(args, run.citations)
    except ValueError as exc:
        # The reason is actionable (which input is unbound, which numbers the source holds): hand it back as it is.
        code = getattr(exc, "code", None) or str(exc) or "invalid_calculation"
        outcome = {"ok": False, "error_code": code}
        if hasattr(exc, "hint"):
            outcome["hint"] = exc.hint
        if hasattr(exc, "receipts"):
            outcome.update({"input_receipts": exc.receipts, "candidates_complete": False, "hint": RECEIPT_HINT})
        if code == "calculation_input_unbound":
            from ..agent_workflow.calculation import bindable_values
            available = bindable_values(run.citations, args)
            if available:
                outcome["bindable_values"] = available
        return outcome


async def _execute(run: _Run, name: str, args: dict, emit) -> dict:
    if name in ("calculate", "calculate_formula"):
        return _calculate(run, name, args)
    from ..knowledge.query_understanding import use_expander
    with use_expander(getattr(run.context, "query_expander", None)):
        outcome = await tools.invoke(name, args, run.context, emit=emit)
    if not outcome.get("ok"):
        return outcome
    if name == "read_history_citation":
        from ..agent_workflow.history_citations import bind_history_citation
        return bind_history_citation(outcome, run.citations)
    if name in _UNNUMBERED:
        return outcome
    return _number_evidence(run, name, outcome)


def _valid_arguments(name: str, args: dict) -> dict | None:
    """Only the in-process calculations are validated here; ``tools.invoke`` validates the others itself."""
    if name not in ("calculate", "calculate_formula"):
        return args
    try:
        return validate(name, args)
    except ValueError:
        return None


async def _run_tool(run: _Run, call: dict) -> dict:
    """One tool call.  Whatever goes wrong becomes a result the model can read; nothing here raises."""
    from ..agent_chat_stream import bounded_tool_result
    function = call.get("function") or {}
    name = function.get("name") or ""
    try:
        args = json.loads(function.get("arguments") or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
    except ValueError:
        args = None
    await run.emit({"event": "tool_start", "call_id": call["id"], "name": name, "arguments": args or {}})
    run.audit["tool_calls"] += 1
    if args is None:
        result = tools.error("invalid_arguments")
    elif name not in run.tool_names or name not in definitions():
        result = tools.error("tool_not_in_bot_scope")
    elif (args := _valid_arguments(name, args)) is None:
        result = tools.error("invalid_arguments")
    else:
        try:
            async with progress_watchdog(TOOL_IDLE_SECONDS):
                result = await _execute(run, name, args, run.emit)
        except (TimeoutError, ConnectionError):
            result = tools.error("tool_timeout")
        except Exception:
            result = tools.error("tool_failed")
        mark_progress()
    await run.emit({"event": "tool_result", "call_id": call["id"], "name": name, "result": bounded_tool_result(result)})
    return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(bounded_tool_result(result, whole_items=True), ensure_ascii=False, default=str)}


async def _tool_step(run: _Run, message: dict) -> None:
    """The model asked for tools: drop the text it streamed, announce the request, run the calls in order."""
    if run.sent_text:
        await run.emit({"event": "answer_reset"})
    reasoning = {k: v for k, v in message.items() if k.startswith("reasoning_")}
    await run.emit({"event": "assistant_tool_request", "protocol": {"calls": message["tool_calls"], **reasoning}})
    for call in message["tool_calls"]:
        run.messages.append(await _run_tool(run, call))


def _result(run: _Run, answer: str, stop_reason: str | None, failure: str | None = None) -> dict:
    status = "failed" if failure else "succeeded"
    run.audit["stop_reason"] = stop_reason
    run.audit["terminal_status"] = status
    return {"answer": answer, "citations": run.citations, "status": status,
            "reason": failure, "route": "K", "audit": run.audit, "final_protocol": {}, "pending_request": None,
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
               tool_names=frozenset(s["function"]["name"] for s in tool_schemas))
    async with progress_watchdog(IDLE_SECONDS), provider.decision_session(context.base_url):
        return await _loop(run)
