"""The helper: the kernel's ``delegate`` tool hands one several-step piece of legwork to a short, low-tier child run.

The child is an ordinary ``loop._Run`` that shares the turn's citation list, web rows and result sets, so every row it reads is numbered into the
turn's own ``[n]`` list as it is read (by ``toolrun``, exactly as in a turn) and the turn can cite it.  It has its own messages, its own audit and
no inbox of its own; it takes the model calls and the tool steps of the loop itself (``_call_model``, ``run_step_tools``) and adds nothing to
them but its caps and its way of ending.  Nothing of its text reaches the client: only its tool steps, as narration lines.

Behind the switch ``FINBOT_HELPER`` (``on``; off by default: nothing about a turn changes).  Never offered to a wake turn, never inside a helper.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import time
from datetime import date

from .. import agent_model_roles as roles
from .. import model_usage
from ..agent_workflow import tools
from . import act, ask, decide, progress, skills, tiers
from . import inbox as inboxes

DELEGATE = "delegate"
SYSTEM_HEAD = "你是 FinBot 的小助手"
HELPER_MAX_STEPS = 6       # model steps (the closing step after a cap is one more)
HELPER_SECONDS = 120       # a hard cap: each model call and tool step is cut at the time left
CLOSING_SECONDS = 20       # the closing step's own allowance after a cap
MAX_HELPERS = 3            # ``delegate`` calls run in one step of a turn
BRIEF_MAX = 4000
FAILED_HINT = "小助手没有做成，可以自己查。"
NARRATION_PREFIX = "小助手："
# The kernel's own tools: none of them is the helper's (it reads, calculates and reports; it writes, asks and delegates nothing).
OWN_TOOLS = frozenset({act.ACT, ask.ASK, skills.USE_SKILL, progress.PLAN, tiers.ESCALATE, decide.DECIDE, DELEGATE, inboxes.HANDLE})
_CALCULATIONS = frozenset({"calculate", "calculate_formula"})
_ORDINAL = re.compile(r"\[(\d+)\]")
logger = logging.getLogger(__name__)

DELEGATE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": DELEGATE,
        "description": "Hand one several-step piece of legwork to a helper, for work that does not need this conversation: e.g. reading several filings or "
                       "earnings calls for one kind of fact. Write a self-contained brief: the helper sees only the brief, not the conversation. "
                       "Do not delegate comparison, judgment or the answer itself; you do those. It comes back with a short report and the [n] numbers "
                       "of the sources it read, which you can cite in your answer like any result. Up to three delegate calls in one step run at the same time.",
        "parameters": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "minLength": 1, "maxLength": BRIEF_MAX,
                          "description": "What to find out, which companies, periods and sources, and what to report back."},
                "tools": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "string"},
                          "description": "Optional: narrow the helper to these of your read tools (names you were offered). Omit to give it all of them."},
            },
            "required": ["brief"],
            "additionalProperties": False,
        },
    },
}


def enabled() -> bool:
    return os.environ.get("FINBOT_HELPER", "off").strip().lower() == "on"


def offered(names) -> bool:
    """``delegate`` goes to a turn that has the switch on and at least one read tool (a calculation alone is not one)."""
    return enabled() and any(name not in OWN_TOOLS and name not in _CALCULATIONS for name in names)


def system_text() -> str:
    return (f"{SYSTEM_HEAD}，替助手做一件跑腿的活。今天是 {date.today().isoformat()}。\n"
            "- 按任务说明，用工具查需要的资料。\n"
            "- 工具返回的每一行资料带一个编号 [n]，例如 [3]。报告里用到哪一行，就在那句话后面写上它的编号；没有编号的不要编造编号。\n"
            "- 没查到的地方直接说没查到，不要猜。\n"
            "- 只报告查到的事实，不做判断，不给建议。")


async def model_for(parent):
    """The helper's model: the owner's ``helper`` role when set (and still in the catalog, with a key), else the model the turn is on now."""
    from .loop import ModelUse
    try:
        found = await asyncio.to_thread(roles.helper_for, getattr(parent.context, "owner_hash", ""))
    except Exception:
        logger.exception("kernel helper model lookup failed")
        found = None
    if not found:
        return parent.model
    return ModelUse(found["provider"], found["model"], found["api_key"], found.get("base_url"), found["name"])


def _sources(messages: list[dict]) -> list[int]:
    """The ``[n]`` numbers the rows in these tool results carry."""
    found = []
    for message in messages:
        try:
            body = json.loads(message.get("content") or "")
        except ValueError:
            continue
        data = body.get("data") if isinstance(body, dict) else None
        for item in data if isinstance(data, list) else [data]:
            match = _ORDINAL.fullmatch(str(item.get("citation") or "")) if isinstance(item, dict) else None
            if match:
                found.append(int(match[1]))
    return found


def _built_report(sources: list[int]) -> str:
    return "还没写总结，已拿到的资料见 " + "".join(f"[{n}]" for n in sources) + "。" if sources else "还没写总结，也没有拿到资料。"


def _owner_spoke(parent) -> bool:
    box = getattr(parent, "inbox", None)
    return box is not None and (box.has_fresh() or box.stopping)


def helper_schemas(schemas: list[dict], wanted) -> list[dict]:
    """The helper's tool list from the parent's: no kernel tools, only ``wanted`` when given, and without the ``say`` / ``item`` fields (they are for talking to the user)."""
    kept = []
    for schema in schemas:
        name = schema["function"]["name"]
        if name in OWN_TOOLS or (wanted is not None and name not in wanted):
            continue
        shown = copy.deepcopy(schema)
        properties = shown["function"].get("parameters", {}).get("properties", {})
        for key in ("say", "item"):
            properties.pop(key, None)
        kept.append(shown)
    return kept


def check(parent, args) -> tuple[str, list | None] | dict:
    """(brief, schemas of the helper's tools) or the refusal to give back before anything runs."""
    if not isinstance(args, dict) or set(args) - {"brief", "tools"}:
        return tools.error("invalid_arguments")
    brief, wanted = args.get("brief"), args.get("tools")
    if not isinstance(brief, str) or not brief.strip() or len(brief) > BRIEF_MAX or (wanted is not None and (not isinstance(wanted, list) or not wanted)):
        return tools.error("invalid_arguments")
    if wanted is not None and any(not isinstance(name, str) for name in wanted):
        return tools.error("invalid_arguments")
    allowed = [s for s in parent.schemas if s["function"]["name"] not in OWN_TOOLS and s["function"]["name"] in parent.tool_names]
    if wanted is not None and any(name not in {s["function"]["name"] for s in allowed} for name in wanted):
        return {**tools.error("tool_not_in_bot_scope"), "hint": "tools 只能从你自己被提供的读取类工具里选，写入、提问、delegate 不行。"}
    return brief.strip(), helper_schemas(allowed, wanted)


async def run(parent, call_id: str, args: dict) -> dict:
    """One ``delegate`` call.  Returns the tool result the turn sees; never raises (but for a cancelled turn)."""
    from . import loop
    from .toolrun import mark_timeline, run_step_tools
    checked = check(parent, args)
    if isinstance(checked, dict):
        return checked
    brief, schemas = checked
    started = time.monotonic()
    deadline = started + HELPER_SECONDS
    model = await model_for(parent)

    async def emit(event: dict) -> None:
        # Only a tool step's sentence goes on, marked as the helper's; its text, tool events and answer resets are its own.
        if event.get("event") != "narration" or not isinstance(event.get("text"), str):
            return
        text = NARRATION_PREFIX + event["text"]
        parent.narration.append(text)
        mark_timeline(parent, "say", index=len(parent.narration) - 1)
        await parent.emit({"event": "narration", "text": text, **({"system": True} if event.get("system") else {})})

    child = loop._Run(
        context=parent.context, emit=emit, messages=[{"role": "system", "content": system_text()}, {"role": "user", "content": brief}],
        user_text=parent.user_text, schemas=schemas, tool_names=frozenset(s["function"]["name"] for s in schemas), model=model, ceiling="low",
        question=brief, turn_id=parent.turn_id, tier="low", citations=parent.citations, web_rows=parent.web_rows,
        carried_sets=parent.carried_sets, new_sets=parent.new_sets, inbox=None, pausable=False, is_helper=True)
    sources: list[int] = []
    used: list[str] = []
    state = {"complete": False, "steps": 0}
    mark_timeline(parent, "helper_start", call_id=call_id)

    def note(messages: list[dict]) -> None:
        for number in _sources(messages):
            if number not in sources:
                sources.append(number)

    tags = dict(owner_hash=getattr(parent.context, "owner_hash", None) or None, conversation_id=getattr(parent.context, "conversation_id", None) or None,
                turn_id=parent.turn_id or None, bot_id=getattr(parent.context, "bot_id", None) or None)
    try:
        with model_usage.purpose("helper", **tags):
            report = await _work(loop, child, parent, deadline, state, sources, used, note, run_step_tools)
        return {"ok": True, "data": {"report": report, "sources": list(sources), "steps": child.audit["decision_steps"], "complete": state["complete"]}}
    except Exception as failure:
        logger.warning("kernel helper failed: %s", getattr(failure, "detail", None) or type(failure).__name__)
        state["complete"] = False
        return {"ok": False, "error_code": "helper_failed", "hint": FAILED_HINT, "data": {"sources": list(sources)}}
    finally:
        _record(parent, child, call_id, started, state["complete"], used)
        mark_timeline(parent, "helper_done", call_id=call_id)


async def _work(loop, child, parent, deadline: float, state: dict, sources: list[int], used: list[str], note, run_step_tools) -> str:
    """The helper's steps; returns its report and sets ``state["complete"]``.  A model failure in an ordinary step raises.

    The report is the text of the final step (one without tool calls) or of the closing step; what a step wrote beside its tool calls is not one."""
    reason = None
    for _ in range(HELPER_MAX_STEPS):
        if _owner_spoke(parent):
            reason = "owner"      # the turn is to take his message at once: the helper stops here, with what it has read
            break
        left = deadline - time.monotonic()
        if left <= 0:
            reason = "time"
            break
        try:
            message = await asyncio.wait_for(loop._call_model(child, child.schemas), left)    # not ``_model_step``: no backup switch inside the helper
            calls = message.get("tool_calls")
            if not calls:
                text = (message.get("content") or "").strip()
                state["complete"] = bool(text)
                return text or _built_report(sources)
            child.messages.append(message)
            sentence = progress.plain_sentence([(c.get("function") or {}).get("name") or "" for c in calls])      # the kernel's phrase: never the helper's own words
            if sentence:
                await child.emit({"event": "narration", "text": sentence, "system": True})
            try:
                results = await asyncio.wait_for(run_step_tools(child, calls), max(deadline - time.monotonic(), 0.001))
            except TimeoutError:
                child.messages.pop()          # its tool calls got no results: the closing step must not see them
                raise
        except TimeoutError:
            reason = "time"
            break
        child.messages.extend(results)
        note(results)
        used.extend(name for name in ((c.get("function") or {}).get("name") for c in calls) if name and name not in used)
    else:
        reason = "steps"
    if reason == "owner":
        return _built_report(sources)
    child.messages.append({"role": "system", "content": loop.CAP_NOTE})      # one closing step, itself bounded: answer from what it has
    try:
        closing = await asyncio.wait_for(loop._call_model(child, child.schemas), CLOSING_SECONDS)
    except TimeoutError:
        return _built_report(sources)
    except Exception:
        if not sources:
            raise
        return _built_report(sources)
    return (closing.get("content") or "").strip() or _built_report(sources)


def _record(parent, child, call_id: str, started: float, complete: bool, used: list[str]) -> None:
    """The helper's line on the parent's audit, and its model calls and tokens in the parent's totals."""
    mine, audit = child.audit, parent.audit
    for key in ("model_calls", "token_usage", "cache_read_tokens", "cache_write_tokens"):
        audit[key] = audit.get(key, 0) + mine[key]
    audit.setdefault("helpers", []).append({
        "call_id": call_id, "model": child.model.label, "steps": mine["decision_steps"], "model_calls": mine["model_calls"],
        "token_usage": mine["token_usage"], "complete": complete, "seconds": round(time.monotonic() - started, 1), "tools": list(used)})
