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
PLAN = "plan"
STATUSES = ("pending", "doing", "done", "failed")
PLAN_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": PLAN,
        "description": "复杂任务（已切换到 high 档）开始时，把要做的事列成清单；之后每完成一项，带着完整清单再调用一次，更新各项的状态。简单任务不要用。",
        "parameters": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)}},
                "required": ["text", "status"], "additionalProperties": False}}},
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
    """A copy of a tool schema with an optional ``say`` as its first property."""
    shown = copy.deepcopy(schema)
    parameters = shown["function"].setdefault("parameters", {"type": "object"})
    parameters["properties"] = {"say": {"type": "string", "description": SAY_DESCRIPTION}, **parameters.get("properties", {})}
    return shown


def take_say(arguments: dict) -> tuple[str | None, dict]:
    """The cleaned ``say`` (or None) and the arguments without it; the tool itself never sees ``say``."""
    rest = dict(arguments)
    return _sentence(rest.pop("say", None), SAY_MAX), rest


def clean_plan(items) -> list[dict]:
    cleaned = []
    for item in items if isinstance(items, list) else []:
        text = _sentence(item.get("text"), PLAN_TEXT_MAX) if isinstance(item, dict) else None
        if text:
            status = item.get("status")
            cleaned.append({"text": text, "status": status if status in STATUSES else "pending"})
    return cleaned[:PLAN_MAX_ITEMS]


def settle_plan(run, args: dict) -> dict:
    """Handle one ``plan`` call: keep the latest checklist on the run; the result the model sees."""
    run.checklist = clean_plan((args or {}).get("items"))
    return {"ok": True, "items": len(run.checklist)}


def step_narration(calls: list[dict], text: str | None) -> str | None:
    """The one sentence a tool step shows: the first call's ``say``; with none, the text the model wrote before the calls."""
    for call in calls:
        try:
            arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
        except ValueError:
            continue
        say = take_say(arguments)[0] if isinstance(arguments, dict) else None
        if say:
            return say
    return _sentence(text, SAY_MAX)
