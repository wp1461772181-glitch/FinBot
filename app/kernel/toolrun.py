"""Run one model step's tool calls.

Reads run at the same time (at most ``MAX_PARALLEL``); everything that touches this turn's citations happens afterwards,
one call at a time in the model's call order, so citation numbers never depend on which tool finished first.  The run
object is used by attribute only (this module never imports ``loop``).
"""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass

from ..agent_progress import mark_progress, progress_watchdog
from ..agent_tool_catalog import definitions, validate
from ..agent_workflow import tools
from ..agent_workflow.evidence import number_rows

MAX_PARALLEL = 4
TOOL_IDLE_SECONDS = 180
RECEIPT_HINT = "有输入没有绑定到来源，逐项原因见 input_receipts。只需改正其中 found 为 false 的输入，其余保持不变；不要把数值改写成更长的小数去试。closest_in_source 与 bindable_values 都只是不完整的候选。"
# Results of these tools are the model's memory or a computation, not saved evidence: they are never numbered as rows.
_UNNUMBERED = {"recall_conversations", "read_past_conversation"}
_SOURCE_TYPES = {"web_research": "web", "search_configured_news": "configured_news", "query_sec_filings": "official_filing"}
# Run one at a time after every read has been numbered: they work on the citations the reads just registered.
_CALCULATIONS = ("calculate", "calculate_formula")


@dataclass
class _Call:
    id: str
    name: str
    args: dict | None
    result: dict | None = None      # set once known; a call with a result needs no further work
    raw: dict | None = None         # a read's outcome before numbering


def _number_evidence(run, name: str, outcome: dict) -> dict:
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


def _calculate(run, name: str, args: dict) -> dict:
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


def _valid_arguments(name: str, args: dict) -> dict | None:
    """Only the in-process calculations are validated here; ``tools.invoke`` validates the others itself."""
    if name not in _CALCULATIONS:
        return args
    try:
        return validate(name, args)
    except ValueError:
        return None


def _parse_arguments(function: dict) -> dict | None:
    try:
        args = json.loads(function.get("arguments") or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        return args
    except ValueError:
        return None


async def _fetch(run, gate: asyncio.Semaphore, item: _Call) -> None:
    """One read, run apart from its siblings: whatever goes wrong becomes this call's own ``tool_failed``."""
    from ..knowledge.query_understanding import use_expander
    async with gate:
        try:
            async with progress_watchdog(TOOL_IDLE_SECONDS):
                with use_expander(getattr(run.context, "query_expander", None)):
                    item.raw = await tools.invoke(item.name, item.args, run.context, emit=run.emit)
        except (TimeoutError, ConnectionError):
            item.result = tools.error("tool_timeout")
        except Exception:
            item.result = tools.error("tool_failed")
        mark_progress()


def _settle_read(run, item: _Call) -> None:
    """Number a finished read into the turn's citations.  Called in call order, never concurrently."""
    outcome = item.raw
    if not outcome.get("ok"):
        item.result = outcome
    elif item.name == "read_history_citation":
        from ..agent_workflow.history_citations import bind_history_citation
        item.result = bind_history_citation(outcome, run.citations)
    elif item.name in _UNNUMBERED:
        item.result = outcome
    else:
        item.result = _number_evidence(run, item.name, outcome)


def _settle_serial(run, item: _Call) -> None:
    """Calls the kernel runs itself, in call order, after every read is numbered."""
    item.result = _calculate(run, item.name, item.args)


def _guard(settle, run, item: _Call) -> None:
    try:
        settle(run, item)
    except (TimeoutError, ConnectionError):
        item.result = tools.error("tool_timeout")
    except Exception:
        item.result = tools.error("tool_failed")


async def run_step_tools(run, calls: list[dict]) -> list[dict]:
    """Execute one step's tool calls; return one tool message per call, in call order."""
    from ..agent_chat_stream import bounded_tool_result
    items = []
    for call in calls:
        name = (call.get("function") or {}).get("name") or ""
        args = _parse_arguments(call.get("function") or {})
        items.append(_Call(call["id"], name, args))
        await run.emit({"event": "tool_start", "call_id": call["id"], "name": name, "arguments": args or {}})
        run.audit["tool_calls"] += 1
    reads, serial = [], []
    for item in items:
        if item.args is None:
            item.result = tools.error("invalid_arguments")
        elif item.name not in run.tool_names or item.name not in definitions():
            item.result = tools.error("tool_not_in_bot_scope")
        elif item.name in _CALCULATIONS:
            item.args = _valid_arguments(item.name, item.args)
            if item.args is None:
                item.result = tools.error("invalid_arguments")
                continue
            serial.append(item)
        else:
            reads.append(item)
    gate = asyncio.Semaphore(MAX_PARALLEL)
    await asyncio.gather(*(_fetch(run, gate, item) for item in reads))
    for item in reads:
        if item.result is None:
            _guard(_settle_read, run, item)
    for item in serial:
        _guard(_settle_serial, run, item)
        mark_progress()
    messages = []
    for item in items:
        await run.emit({"event": "tool_result", "call_id": item.id, "name": item.name, "result": bounded_tool_result(item.result)})
        messages.append({"role": "tool", "tool_call_id": item.id,
                         "content": json.dumps(bounded_tool_result(item.result, whole_items=True), ensure_ascii=False, default=str)})
    return messages
