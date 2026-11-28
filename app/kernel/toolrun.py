"""Run one model step's tool calls.

Reads run at the same time (at most ``MAX_PARALLEL``); everything that touches this turn's citations happens afterwards,
one call at a time in the model's call order, so citation numbers never depend on which tool finished first.  The run
object is used by attribute only (this module never imports ``loop``).
"""
from __future__ import annotations

import logging
import asyncio
import re
import copy
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ..agent_progress import mark_progress, progress_watchdog
from ..agent_tool_catalog import definitions, validate
from ..agent_workflow import tools
from ..agent_workflow.evidence import number_rows
from .. import source_authority
from . import act, ask, decide, helper, notify, progress, skills, tiers
from . import inbox as inboxes

MAX_PARALLEL = 4
MAX_TIMELINE = 500     # entries of ``audit["timeline"]`` kept per turn
TOOL_IDLE_SECONDS = 180
SLOW_SECONDS = 10     # a step whose reads are still out after this long gets one plain sentence saying so
RECEIPT_HINT = "有输入没有绑定到来源，逐项原因见 input_receipts。只需改正其中 found 为 false 的输入，其余保持不变；不要把数值改写成更长的小数去试。closest_in_source 与 bindable_values 都只是不完整的候选。"
# Results of these tools are the model's memory, a computation, or state about the system and the owner's own lists, not
# saved evidence: they are never numbered as rows.  The last three mirror the old engine's ``admin_tools`` (direct.py).
_UNNUMBERED = {"recall_conversations", "read_past_conversation", "read_turn", "query_system_status", "query_research_queue", "list_routines", "list_models", "list_work", "list_watch_rules"}
# The pages these reads return can be saved with ``act``; a post found on X is not a web page.
_WEB_PAGE_READS = ("web_research", "search_configured_news")
# These return the owner's own data, not text from outside: they do not make a tier-1 write go onto a card.  The system
# status is not one of them: job and document names and error text in it come from outside.
# query_alerts: the sentinel's own alert lines (prices, his rules, the code's words), nothing from outside; asking which alert he means
# before rating it (rate_alert) must not put the verdict on a card, which WeChat cannot press.
_OWN_STATE_READS = frozenset({"query_research_queue", "list_routines", "list_models", "list_work", "list_watch_rules", "query_alerts"})
_SOURCE_TYPES = {"web_research": "web", "search_configured_news": "configured_news", "query_sec_filings": "official_filing",
                "search_x": "x_post"}
# Run one at a time after every read has been numbered, in call order: calculations work on the citations the reads just
# registered, and an ``act`` call may rest on what this step's reads found.
DEEP_SENTENCE = "这是深度研究，我转到后台慢慢做（最多约 15 分钟），你可以先去忙别的，做完我会推送告诉你。"
_CALCULATIONS = ("calculate", "calculate_formula")

logger = logging.getLogger(__name__)


def mark_timeline(run, kind: str, **fields) -> None:
    """Add one entry to the turn's ordered record of what happened (``audit["timeline"]``): the kind, milliseconds since the turn began, the model
    step it belongs to, and a reference (an index into narration or calls, or a call id).  No text and no arguments: those are kept elsewhere.
    Only the backstage reads it, so a run without an audit, or a full list, is simply skipped."""
    audit = getattr(run, "audit", None)
    if not isinstance(audit, dict):
        return
    entries = audit.setdefault("timeline", [])
    if len(entries) >= MAX_TIMELINE:
        return
    started = getattr(run, "started", None)
    at = round((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else 0
    entries.append({"kind": kind, "at_ms": max(0, at), "step": int(audit.get("decision_steps") or 0), **fields})


@dataclass
class _Call:
    id: str
    name: str
    args: dict | None
    result: dict | None = None      # set once known; a call with a result needs no further work
    raw: dict | None = None         # a read's outcome before numbering
    started: bool = False           # a read that holds a place under ``MAX_PARALLEL`` (not one still waiting for it)
    done: bool = False              # its ``tool_done`` is on the timeline


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
    numbered = number_rows(name, prepared, run.citations, {})
    source_authority.rank(run.citations)
    for row in numbered:
        match = _MARK_ORDINAL.fullmatch(str(row.get("citation") or ""))
        cited = match and 0 < int(match[1]) <= len(run.citations) and run.citations[int(match[1]) - 1]
        if cited and cited.get("authority_label"):
            row["来源等级"] = cited["authority_label"]
    shown = {"ok": True, "data": numbered, "source": outcome.get("source")}
    meta = {**outcome["meta"]} if isinstance(outcome.get("meta"), dict) else {}
    meta.update(source_authority.freshness(numbered, _now()))
    if meta:
        shown["meta"] = meta
    return shown


_MARK_ORDINAL = re.compile(r"\[(\d+)\]")


def _now() -> datetime:
    return datetime.now(UTC)


HEADING_PREFIX = "  最新一季："
_MARK = re.compile(r"\[#(\d+)\]( ?)")


def _calculated(run, row: dict, ordinals: dict[int, str]) -> str | None:
    """A derived figure of the block as a citation of the shape ``calculate`` makes (``source_type: calculation``, ``derived``, ``parents`` =
    the citation numbers of its inputs), built straight from the stored row: the facts were checked when they were stored, so nothing here
    re-binds numbers to text (that is for numbers a model supplies; it cannot take a negative input).  ``None`` (and no citation) when an
    input was not numbered."""
    spec = row["_calc"]
    inputs, parents = [], []
    for item in spec["inputs"]:
        text = ordinals.get(item["k"])
        if not text:
            return None
        number = int(text.strip("[]"))
        inputs.append({"name": item["name"], "value": item["value"], "source_ordinal": number})
        parents.append(number)
    value = {"value": spec["value"], "expression": spec["expression"], "inputs": inputs, "parents": sorted(set(parents)), "derived": True}
    ordinal = len(run.citations) + 1
    run.citations.append({"ordinal": ordinal, "source_type": "calculation", "derived": True, "title": row.get("title") or "可复核计算",
                          "quote": json.dumps(value, ensure_ascii=False), "calculation": value, "symbol": row.get("symbol")})
    source_authority.rank(run.citations)
    return f"[{ordinal}]"


def number_attached(run, text: str, rows: list[dict]) -> str:
    """The "latest known" block's lines as this turn's first citations, through the numbering the read results take: each row that
    ``number_rows`` accepts gets its ordinal, and the block's ``[#k]`` marker becomes ``[ordinal]``.  A marker whose row was not accepted
    (a news item without a real link) is removed, so no line shows a number that cites nothing.

    A row with ``_calc`` is a figure the code derived from other rows of the block: once its inputs are numbered it becomes a ``calculation``
    citation pointing at them (rows are in dependency order).  A row with ``_figures`` keeps the exact figures its line rounds."""
    prepared = [copy.deepcopy(row) for row in rows if isinstance(row, dict) and isinstance(row.get("_k"), int)]
    ordinals: dict[int, str] = {}
    if prepared:
        try:
            plain = [row for row in prepared if "_calc" not in row]
            for accepted in number_rows("latest_known", plain, run.citations, {}) if plain else []:
                ordinals[accepted["_k"]] = accepted["citation"]
                if accepted.get("_figures"):
                    run.citations[int(accepted["citation"].strip("[]")) - 1]["figures"] = accepted["_figures"]
            for row in sorted((row for row in prepared if "_calc" in row), key=lambda row: row["_k"]):
                made = _calculated(run, row, ordinals)
                if made:
                    ordinals[row["_k"]] = made
        except Exception:
            logger.exception("latest-known citations could not be numbered")
            ordinals = {}
        source_authority.rank(run.citations)
    def number(match):
        return f"{ordinals[int(match[1])]}{match[2]}" if int(match[1]) in ordinals else ""
    if HEADING_PREFIX not in text:
        return _MARK.sub(number, text)
    # A figure of the facts section is printed only with its citation: a line of that section (the indented lines after a quarter's heading)
    # with a number that could not be numbered is dropped whole, and the heading with it when no line of the section is left.
    kept, heading, inside = [], None, False
    for line in text.split("\n"):
        if line.startswith(HEADING_PREFIX):
            heading, inside = line, True
            continue
        if inside and line.startswith("  "):
            if any(int(k) not in ordinals for k in re.findall(r"\[#(\d+)\]", line)):
                continue
            if heading is not None:
                kept.append(heading)
                heading = None
        else:
            heading, inside = None, False
        kept.append(line)
    return _MARK.sub(number, "\n".join(kept))


def _calculate(run, name: str, args: dict) -> dict:
    """``calculate`` / ``calculate_formula`` run in-process; a result is registered as a ``calculation`` citation."""
    try:
        if name == "calculate":
            from ..agent_workflow.calculation import calculate
            value = calculate(args, run.citations, run.user_text)
            ordinal = len(run.citations) + 1
            run.citations.append({"ordinal": ordinal, "source_type": "calculation", "derived": True, "title": "可复核计算",
                                  "quote": json.dumps(value, ensure_ascii=False), "calculation": value})
            source_authority.rank(run.citations)
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
    """Only the in-process calculations are validated here; ``tools.invoke`` validates the others itself.  A failure is returned (the
    validation error, for ``tools.argument_error``), not raised."""
    if name not in _CALCULATIONS:
        return args
    try:
        return validate(name, args)
    except ValueError as exc:
        return exc


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
        item.started = True
        try:
            async with progress_watchdog(TOOL_IDLE_SECONDS):
                with use_expander(getattr(run.context, "query_expander", None)):
                    item.raw = await tools.invoke(item.name, item.args, run.context, emit=run.emit)
        except (TimeoutError, ConnectionError):
            item.result = tools.error("tool_timeout")
        except Exception:
            # The model only learns that the read failed; the cause has to be findable in the log.
            logger.exception("kernel read %s failed", item.name)
            item.result = tools.error("tool_failed")
        mark_progress()
        _done(run, item)       # the read is back (or failed): the time is when it finished, not when it was numbered


def _done(run, item: _Call) -> None:
    """Note on the timeline that this call's result is settled (once)."""
    if not item.done:
        item.done = True
        mark_timeline(run, "tool_done", call_id=item.id)


def _keep_pages(run, name: str, outcome: dict) -> None:
    """The raw rows of a web read, by URL, as ``act`` needs them to save one (before numbering adds anything to them).

    They are also kept as one result set of the conversation (the old engine's ``result_sets``, which the graph stores
    with the checkpoint), so "save the first one" works in the next message."""
    rows = outcome.get("data") if outcome.get("data") is not None else (outcome.get("items") or [])
    kept = [copy.deepcopy(row) for row in (rows if isinstance(rows, list) else [rows]) if isinstance(row, dict) and isinstance(row.get("url"), str) and row["url"]]
    for row in kept:
        run.web_rows[row["url"]] = row
    if kept:
        run.new_sets.append({"id": uuid.uuid4().hex, "owner": run.context.owner_hash, "conversation": run.context.conversation_id,
                             "rows": copy.deepcopy(kept), "scope": {}, "tool": name, "created_at": datetime.now(UTC).isoformat()})


def _settle_read(run, item: _Call) -> None:
    """Number a finished read into the turn's citations.  Called in call order, never concurrently."""
    outcome = item.raw
    if outcome.get("ok") and item.name in _WEB_PAGE_READS:
        _keep_pages(run, item.name, outcome)
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
    """Calls the kernel runs itself, in call order: its own tools before the reads, calculations after every read is numbered."""
    if item.name == tiers.ESCALATE:
        item.result = tiers.escalate(run, item.args)
    elif item.name == progress.PLAN:
        item.result = progress.settle_plan(run, item.args)
    elif item.name == ask.ASK:
        item.result = ask.settle(run, item.args)
    elif item.name == decide.DECIDE:
        item.result = decide.settle(run, item.args)
    else:
        item.result = _calculate(run, item.name, item.args)


def _guard(settle, run, item: _Call) -> None:
    try:
        settle(run, item)
    except (TimeoutError, ConnectionError):
        item.result = tools.error("tool_timeout")
    except Exception:
        item.result = tools.error("tool_failed")


async def _settle_act(run, item: _Call) -> None:
    """One ``act`` call.  It never goes through ``tools.invoke``; the model's operation arguments pass through untouched."""
    try:
        item.result = await act.handle(run, item.args)
    except (TimeoutError, ConnectionError):
        item.result = tools.error("tool_timeout")
    except Exception:
        item.result = tools.error("tool_failed")


async def _settle_notify(run, item: _Call) -> None:
    try:
        item.result = await notify.settle(run, item.args)
    except Exception:
        logger.exception("kernel notify_telegram failed")
        item.result = tools.error("tool_failed")


async def _settle_skill(run, item: _Call) -> None:
    """One ``use_skill`` call: the owner's saved text, read from the database; it is not evidence and not a read."""
    try:
        item.result = await skills.settle(run, item.args)
    except (TimeoutError, ConnectionError):
        item.result = tools.error("tool_timeout")
    except Exception:
        item.result = tools.error("tool_failed")


async def _fetch_all(run, reads: list[_Call]) -> None:
    """Run the reads at the same time; if some are still out after ``SLOW_SECONDS``, say what is awaited (once) and keep waiting."""
    gate = asyncio.Semaphore(MAX_PARALLEL)
    tasks = [asyncio.ensure_future(_fetch(run, gate, item)) for item in reads]
    try:
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=SLOW_SECONDS)
            if pending:
                sentence = progress.slow_sentence([item.name for item, task in zip(reads, tasks) if task in pending and item.started])
                if sentence:
                    run.narration.append(sentence)
                    mark_timeline(run, "say", index=len(run.narration) - 1)
                    await run.emit({"event": "narration", "text": sentence, "system": True})
                await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()


async def _settle_delegate(run, item: _Call) -> None:
    """One ``delegate`` call: the helper's own run (its reads are numbered into this turn's citations as it makes them; the result is not numbered)."""
    try:
        item.result = await helper.run(run, item.id, item.args)
    except (TimeoutError, ConnectionError):
        item.result = tools.error("tool_timeout")
    except Exception:
        logger.exception("kernel helper run failed")
        item.result = tools.error("tool_failed")
    mark_progress()
    _done(run, item)


async def run_step_tools(run, calls: list[dict]) -> list[dict]:
    """Execute one step's tool calls; return one tool message per call, in call order."""
    from ..agent_chat_stream import bounded_tool_result
    items = []
    numbers = []
    for call in calls:
        name = (call.get("function") or {}).get("name") or ""
        args = _parse_arguments(call.get("function") or {})
        if args is not None:
            _, number, args = progress.take_progress(args)     # the sentence was shown by the loop; the tool never sees say or item
            if number:
                numbers.append(number)
        items.append(_Call(call["id"], name, args))
        mark_timeline(run, "tool", call_id=call["id"], name=name)
        await run.emit({"event": "tool_start", "call_id": call["id"], "name": name, "arguments": args or {}})
        run.audit["tool_calls"] += 1
    own, asks, reads, serial, handles, delegates = [], [], [], [], [], []
    for item in items:
        if item.args is None:
            item.result = tools.error("invalid_arguments")
        elif getattr(run, "is_helper", False) and item.name not in run.tool_names:
            item.result = tools.error("tool_not_in_bot_scope")      # a helper has only the reads it was given: never ``act``, ``ask``, ``delegate``…
        elif item.name == helper.DELEGATE:
            refused = helper.check(run, item.args) if item.name in run.tool_names else tools.error("tool_not_in_bot_scope")
            if isinstance(refused, dict):
                item.result = refused           # refused before it runs: no slot, not a read
            elif len(delegates) >= helper.MAX_HELPERS:
                item.result = {"ok": False, "error_code": "too_many_helpers", "hint": f"一步里最多同时交给小助手 {helper.MAX_HELPERS} 件事；这件下一步再交，或者自己查。"}
            else:
                delegates.append(item)     # runs beside the reads, outside their gate
        elif getattr(run, "wake", None) is not None and item.name in (act.ACT, ask.ASK):
            item.result = tools.error("tool_not_in_bot_scope")      # a wake turn changes nothing and asks nobody
        elif item.name == decide.DECIDE:
            if item.name in run.tool_names:
                own.append(item)      # offered to a wake turn only
            else:
                item.result = tools.error("tool_not_in_bot_scope")
        elif item.name == inboxes.HANDLE:
            if item.name in run.tool_names:
                handles.append(item)  # the owner's messages sent while the turn works: settled first (a stop cancels the rest of the step)
            else:
                item.result = tools.error("tool_not_in_bot_scope")
        elif item.name in (tiers.ESCALATE, progress.PLAN):
            own.append(item)          # the kernel's own tools: never go through tools.invoke, make no citation
        elif item.name == ask.ASK:
            if item.name in run.tool_names:
                asks.append(item)     # also its own, but settled after the reads of its step: the model has seen what they found
            else:
                item.result = tools.error("tool_not_in_bot_scope")      # a scheduled run has nobody to ask
        elif item.name == notify.NOTIFY:
            if item.name in run.tool_names:
                serial.append(item)   # a scheduled run's message to the owner: after the reads, so it can cite what they found
            else:
                item.result = tools.error("tool_not_in_bot_scope")
        elif item.name == act.ACT:
            serial.append(item)       # the kernel's own, but it can take time and may rest on this step's reads: with the calculations
        elif item.name == skills.USE_SKILL:
            if item.name in run.tool_names:
                serial.append(item)   # the kernel's own, read from the owner's saved skills; offered to an owner who has any
            else:
                item.result = tools.error("tool_not_in_bot_scope")
        elif item.name not in run.tool_names or item.name not in definitions():
            item.result = tools.error("tool_not_in_bot_scope")
        elif item.name in _CALCULATIONS:
            checked = _valid_arguments(item.name, item.args)
            if isinstance(checked, Exception):
                item.result = tools.argument_error(item.name, checked)
                continue
            item.args = checked
            serial.append(item)
        else:
            reads.append(item)
    for item in handles:
        try:
            item.result = await inboxes.settle(run, item.args)
        except Exception:
            logger.exception("kernel handle_message failed")
            item.result = tools.error("tool_failed")
        _done(run, item)
    if handles and run.inbox is not None and run.inbox.stopping:
        # The owner said stop: nothing else this step asked for runs (no read, no write, no question).
        for pending in (own, asks, reads, serial, delegates):
            for item in pending:
                item.result = {"ok": False, "data": [], "error_code": "turn_stopped"}
            pending.clear()
    # The kernel's own calls take no time and read nothing: settle them first, so a checklist is on screen while the
    # reads are still out, not after the slowest of them.
    planned = False
    for item in own:
        tier = run.tier
        _guard(_settle_serial, run, item)
        _done(run, item)
        if item.name == progress.PLAN and item.result.get("ok"):
            planned = True
        if item.name == tiers.ESCALATE and run.tier != tier:
            await run.emit({"event": "tier", "tier": run.tier})
            if run.tier == tiers.DEEP:      # the system's own sentence: where this turn goes and that it will come back to him
                run.narration.append(DEEP_SENTENCE)
                await run.emit({"event": "narration", "text": DEEP_SENTENCE, "system": True})
    # One checklist event per step: after a plan and the ticks the step's labels ask for, before the reads.
    if progress.mark_items(run, numbers) or planned:
        await run.emit({"event": "checklist", "items": [dict(entry) for entry in run.checklist]})
    helpers = [asyncio.ensure_future(_settle_delegate(run, item)) for item in delegates]
    try:
        await asyncio.gather(_fetch_all(run, reads), *helpers)
    finally:
        for task in helpers:
            task.cancel()
    # A read's result (even a failed one) has come back: tier 1 no longer runs at once, unless it only showed the owner's own state.
    # It counts from the next step on: an ``act`` call of this very step was made before the model had seen it.
    gained = sum(1 for item in reads if item.name not in _OWN_STATE_READS)
    for item in reads:
        if item.result is None:
            _guard(_settle_read, run, item)
    for item in asks:
        _guard(_settle_serial, run, item)
        _done(run, item)
    for item in serial:
        if item.name == act.ACT:
            await _settle_act(run, item)
        elif item.name == notify.NOTIFY:
            await _settle_notify(run, item)
        elif item.name == skills.USE_SKILL:
            await _settle_skill(run, item)
        else:
            _guard(_settle_serial, run, item)
            gained += 1
        _done(run, item)
        mark_progress()
    run.read_results += gained + len(delegates)      # a helper that ran has seen outside text, whatever it came back with
    messages = []
    for item in items:
        _done(run, item)       # a call that was never run (bad arguments, not in scope) is settled too
        await run.emit({"event": "tool_result", "call_id": item.id, "name": item.name, "result": bounded_tool_result(item.result)})
        messages.append({"role": "tool", "tool_call_id": item.id,
                         "content": json.dumps(bounded_tool_result(item.result, whole_items=True), ensure_ascii=False, default=str)})
    return messages
