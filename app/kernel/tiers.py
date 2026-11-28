"""Thinking tiers.  A turn starts at ``low``; the model raises the tier with the kernel's own ``escalate`` tool.

How hard to think is the model's call, question by question (owner 11-22): a bot's stored effort is not read (11-28: it had become a
ceiling the owner set by hand).  The only ceiling is the server's ``FINBOT_KERNEL_TOP_TIER`` (low / mid / high, default high: none), a
spending setting, not a user choice.  The tier is kept on the run object, never in module state.
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


def ceiling() -> str:
    """The highest tier a turn may reach: the server's ``FINBOT_KERNEL_TOP_TIER``, else ``high`` (an unknown value counts as unset)."""
    import os
    value = (os.environ.get("FINBOT_KERNEL_TOP_TIER") or "").strip().lower()
    return value if value in TIERS else "high"


def lookup_tier() -> str | None:
    """The tier a lookup step runs at once a turn has gone up (design 4.4: 「查资料的步骤始终用低档，不管最后由哪一档来写」):
    ``FINBOT_KERNEL_LOOKUP_TIER`` (low / mid / high), default ``low``; ``same`` turns it off (every step at the turn's tier)."""
    import os
    value = (os.environ.get("FINBOT_KERNEL_LOOKUP_TIER") or "").strip().lower()
    if value == "same":
        return None
    return value if value in TIERS else "low"


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
        note = f"服务器设置的上限是 {tier} 档，已按 {tier} 档继续。"
    else:
        note = f"已切换到 {tier} 档，请继续。"
    lookup = lookup_tier()
    if lookup is not None and TIERS.index(lookup) < TIERS.index(run.tier):
        note += f"之后只是查资料的步骤按 {lookup} 档跑，判断和写回答都在 {run.tier} 档。"
    return {"ok": True, "tier": run.tier, "note": note}
