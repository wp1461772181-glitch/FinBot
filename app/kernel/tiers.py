"""Thinking tiers.  A turn starts at ``low``; the model raises the tier with the kernel's own ``escalate`` tool.

The bot's configured effort is only a ceiling.  The tier is kept on the run object, never in module state.
"""
from __future__ import annotations

TIERS = ("low", "mid", "high")
EFFORT = {"low": "low", "mid": "medium", "high": "high"}     # what is sent as reasoning_effort
ESCALATE = "escalate"
ESCALATE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": ESCALATE,
        "description": "切换到更深的思考档位再继续。问题需要多步推理、比较权衡、给出判断，或者你拿不准时调用。"
                       "mid 用于一般的分析，high 用于复杂的研究。简单的问题不要调用，直接回答或查一下就答。",
        "parameters": {"type": "object", "properties": {"depth": {"type": "string", "enum": ["mid", "high"]}},
                       "required": ["depth"], "additionalProperties": False},
    },
}


def ceiling(bot_effort: str | None) -> str:
    """The highest tier this bot may use."""
    if bot_effort is None:
        return "high"
    effort = str(bot_effort).strip().lower()
    if effort in ("none", "minimal", "low"):
        return "low"
    return "mid" if effort == "medium" else "high"


def clamp(requested: str, top: str) -> str:
    return TIERS[min(TIERS.index(requested), TIERS.index(top))]


def escalate(run, args: dict) -> dict:
    """Handle one ``escalate`` call: raise ``run.tier`` (never lower it) and return the result the model sees."""
    depth = (args or {}).get("depth")
    if depth not in ("mid", "high"):
        return {"ok": False, "error_code": "invalid_arguments", "hint": "depth 必须是 mid 或 high。"}
    tier = clamp(depth, run.ceiling)
    if TIERS.index(tier) > TIERS.index(run.tier):
        run.tier = tier
    if tier != depth:
        note = f"这个助手最高只到 {tier} 档，已按 {tier} 档继续。"
    else:
        note = f"已切换到 {tier} 档，请继续。"
    return {"ok": True, "tier": run.tier, "note": note}
