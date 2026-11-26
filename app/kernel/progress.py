"""Live progress: the optional ``say`` sentence on every tool, and the kernel's own ``plan`` checklist tool.

``say`` is shown to the user as a step starts; ``plan`` publishes a checklist.  Neither is required of the model: the
system prompt asks, this code never blocks on their absence.
"""
from __future__ import annotations

import copy
import json

SAY_MAX = 80
PLAN_MAX_ITEMS = 12
PLAN_TEXT_MAX = 60
SAY_DESCRIPTION = "用一句话告诉用户你发现了什么、接下来做什么。像人说话，不要出现工具名。"
ITEM_DESCRIPTION = "有清单时，写这次调用是为清单的第几项（从 1 数）。没有清单不用填。"
PLAN = "plan"
STATUSES = ("pending", "doing", "done", "failed")
PLAN_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": PLAN,
        "description": "复杂任务（已切换到 high 档）开始时，把要做的事列成清单。之后清单要增、删、改时再带着完整清单调用一次；打勾不用你管，调用工具时在 item 里写第几项即可。status 可以不填：新项默认 pending，没改动的项保持原来的状态；只有要把某项标成 failed 或 done 时才写。简单任务不要用。",
        "parameters": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)}},
                "required": ["text"], "additionalProperties": False}}},
            "required": ["items"], "additionalProperties": False,
        },
    },
}


def _sentence(text, limit: int) -> str | None:
    """Trimmed, on one line, cut to ``limit`` characters; empty or not a string means nothing."""
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    return cleaned[:limit] or None


def with_say(schema: dict) -> dict:
    """A copy of a tool schema with an optional ``say`` and ``item`` as its first two properties."""
    shown = copy.deepcopy(schema)
    parameters = shown["function"].setdefault("parameters", {"type": "object"})
    parameters["properties"] = {"say": {"type": "string", "description": SAY_DESCRIPTION},
                                "item": {"type": "integer", "description": ITEM_DESCRIPTION}, **parameters.get("properties", {})}
    return shown


def take_progress(arguments: dict) -> tuple[str | None, int | None, dict]:
    """The cleaned ``say``, the checklist ``item`` (an int >= 1, else None) and the arguments without either."""
    rest = dict(arguments)
    say = _sentence(rest.pop("say", None), SAY_MAX)
    item = rest.pop("item", None)
    return say, (item if isinstance(item, int) and not isinstance(item, bool) and item >= 1 else None), rest


def take_say(arguments: dict) -> tuple[str | None, dict]:
    say, _, rest = take_progress(arguments)
    return say, rest


def clean_plan(items, previous=()) -> list[dict]:
    """The checklist as sent.  An item with no valid ``status`` keeps the one the item with the same text had in ``previous``, else ``pending``."""
    before = {entry["text"]: entry["status"] for entry in previous}
    cleaned = []
    for item in items if isinstance(items, list) else []:
        text = _sentence(item.get("text"), PLAN_TEXT_MAX) if isinstance(item, dict) else None
        if text:
            status = item.get("status")
            cleaned.append({"text": text, "status": status if status in STATUSES else before.get(text, "pending")})
    return cleaned[:PLAN_MAX_ITEMS]


def settle_plan(run, args: dict) -> dict:
    """Handle one ``plan`` call: keep the latest checklist on the run; the result is the list as the kernel now holds it, numbered as ``item`` counts."""
    run.checklist = clean_plan((args or {}).get("items"), run.checklist)
    return {"ok": True, "items": [{"n": n, **entry} for n, entry in enumerate(run.checklist, 1)]}


def mark_items(run, numbers: list[int]) -> bool:
    """Tick the checklist from the item numbers a step's calls carried: those become ``doing``, the ``doing`` ones before them ``done``."""
    named = {n for n in numbers if 1 <= n <= len(run.checklist)}
    if not named:
        return False
    changed = False
    for number, entry in enumerate(run.checklist, 1):
        if number in named and entry["status"] in ("pending", "doing"):
            new = "doing"
        elif entry["status"] == "doing":
            new = "done"
        else:
            continue
        if new != entry["status"]:
            entry["status"] = new
            changed = True
    return changed


def close_checklist(run) -> bool:
    """The turn ended with an answer: what was being done is done, and so is whatever lies after the last item worked on.

    Items before it that were never worked on stay unticked; ``failed`` stays.
    """
    last = max((n for n, entry in enumerate(run.checklist, 1) if entry["status"] != "pending"), default=0)
    changed = False
    for number, entry in enumerate(run.checklist, 1):
        if entry["status"] == "doing" or (entry["status"] == "pending" and number > last):
            entry["status"] = "done"
            changed = True
    return changed


TOOL_PHRASES = {
    "ask": "向你提问", "use_skill": "取技能步骤",
    "query_financials": "查财务数据", "query_stock_prices": "查历史行情", "query_market_quote": "查最新报价",
    "query_sec_filings": "查 SEC 备案", "search_knowledge": "翻资料库", "web_research": "上网搜索",
    "search_configured_news": "查新闻", "search_x": "搜 X", "calculate": "算数", "calculate_formula": "算数", "query_portfolio": "看持仓",
    "recall_conversations": "翻之前的对话", "read_past_conversation": "翻之前的对话", "read_history_citation": "翻之前的对话",
    "read_turn": "翻看之前那一轮",
    "query_latest_forecast": "看已存的预测", "query_materials": "翻已存材料", "query_material_analysis": "看已存的 AI 分析",
    "search_material_analysis": "看已存的 AI 分析", "read_workspace": "读工作区记录", "query_research_queue": "看研究队列",
    "query_research_faq": "翻问答库", "query_system_status": "看任务状态", "query_holdings_overview": "看持仓总览",
    "query_alerts": "看提醒记录", "list_routines": "看例行任务", "list_models": "看可用模型", "list_work": "看手上的事", "list_watch_rules": "看盯着什么",
}


def _phrases(names: list[str]) -> list[str]:
    return list(dict.fromkeys(TOOL_PHRASES[name] for name in names if name in TOOL_PHRASES))


def plain_sentence(names: list[str]) -> str | None:
    """What the kernel says when the model said nothing: the first three things being looked up, in call order."""
    phrases = _phrases(names)[:3]
    return "正在" + "、".join(phrases) + "。" if phrases else None


def slow_sentence(names: list[str]) -> str | None:
    """What the kernel says when a step is slow: what it is still waiting for."""
    phrases = _phrases(names)
    return "、".join(phrases) + "还没回来，还在等。" if phrases else None


def step_narration(calls: list[dict], text: str | None) -> tuple[str | None, int | None, bool]:
    """The one sentence a tool step shows, its checklist item, and whether the kernel wrote it.

    The first call's ``say``; with none, the text the model wrote before the calls; with none, a plain sentence of what is looked up.
    """
    names = []
    found = None
    for call in calls:
        function = call.get("function") or {}
        names.append(function.get("name") or "")
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except ValueError:
            continue
        if found is None and isinstance(arguments, dict):
            say, item, _ = take_progress(arguments)
            if say:
                found = (say, item, False)
    if found:
        return found
    preamble = _sentence(text, SAY_MAX)
    if preamble:
        return preamble, None, False
    plain = plain_sentence(names)
    return (plain, None, True) if plain else (None, None, False)
