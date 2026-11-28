"""Thinking tiers.  A conversation turn starts at ``FINBOT_KERNEL_START_TIER`` (default ``mid``; 11-28, owner: the low tier decided
whether to think harder and rarely did); the model raises the tier with the kernel's own ``escalate`` tool.

How hard to think is the model's call, question by question (owner 11-22): a bot's stored effort is not read (11-28: it had become a
ceiling the owner set by hand).  The only ceiling is the server's ``FINBOT_KERNEL_TOP_TIER`` (low / mid / high / max, default max:
none), a spending setting, not a user choice.  ``max`` is for the deep research the owner asks for in so many words (design 4.4):
the turn gets more time and steps, says it is working in the background, and its end is pushed to his channel whether or not he
is still reading.  The tier is kept on the run object, never in module state.
"""
from __future__ import annotations

TIERS = ("low", "mid", "high", "max")
EFFORT = {"low": "low", "mid": "medium", "high": "high", "max": "max"}     # what is sent as reasoning_effort
DEEP = "max"
ESCALATE = "escalate"
ESCALATE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": ESCALATE,
        "description": "切换到更深的思考档位再继续。问题需要多步推理、比较权衡、给出判断，或者你拿不准时调用。"
                       "mid 用于一般的分析，high 用于复杂的研究。简单的问题不要调用，直接回答或查一下就答。"
                       "max 只在用户明确要深度研究时用（他自己说要深入、彻底、慢慢研究，愿意等）：这一轮会转到后台，"
                       "最多约 10 分钟，做完推送通知他。没明说的复杂问题用 high。",
        "parameters": {"type": "object", "properties": {"depth": {"type": "string", "enum": ["mid", "high", "max"]}},
                       "required": ["depth"], "additionalProperties": False},
    },
}


def ceiling() -> str:
    """The highest tier a turn may reach: the server's ``FINBOT_KERNEL_TOP_TIER``, else ``max`` (an unknown value counts as unset)."""
    import os
    value = (os.environ.get("FINBOT_KERNEL_TOP_TIER") or "").strip().lower()
    return value if value in TIERS else DEEP


def start_tier(top: str) -> str:
    """Where a conversation turn starts: ``FINBOT_KERNEL_START_TIER`` (low / mid / high), default ``mid``, never above the turn's ceiling.
    A helper and a wake turn keep starting at ``low`` (a helper's brief is a lookup; a wake turn is the frequent background check)."""
    import os
    value = (os.environ.get("FINBOT_KERNEL_START_TIER") or "").strip().lower()
    return clamp(value if value in ("low", "mid", "high") else "mid", top)


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
    if depth not in ("mid", "high", DEEP):
        return {"ok": False, "error_code": "invalid_arguments", "hint": "depth 必须是 mid、high 或 max。"}
    tier = clamp(depth, run.ceiling)
    before = run.tier
    if TIERS.index(tier) > TIERS.index(run.tier):
        run.tier = tier
    if tier != depth:
        note = f"服务器设置的上限是 {tier} 档，已按 {tier} 档继续。"
    elif before == run.tier:
        note = f"这一轮已经在 {run.tier} 档，请继续。"
    else:
        note = f"已切换到 {tier} 档，请继续。"
    if run.tier == DEEP and before != DEEP:
        note += "这是深度研究：已转到后台，时间放宽到约 10 分钟，他可以先去做别的，做完会告诉他。先列清单，再一项项做。"
    return {"ok": True, "tier": run.tier, "note": note}
