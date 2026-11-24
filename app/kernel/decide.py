"""The kernel's ``decide``: how a wake turn (see ``wake``) says what it concluded about an alert.

It writes nothing and reads nothing, like ``ask``.  The first valid call keeps the decision on the run's ``wake`` state and the
loop ends the turn there; later calls are refused.  Only a wake turn offers it.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agent_workflow import tools

DECIDE = "decide"
DECISIONS = ("tell_now", "digest", "record", "ignore")
REASON_MAX = 500
MESSAGE_MAX = 1500
DECIDED = "这一轮已经做出决定了，不能再改。"
NOTE = "决定已记录，这一轮结束。"
NEEDS_MESSAGE = "选 tell_now 时必须用 message 写出你要对用户说的话（1 到 1500 字）。"
NO_MESSAGE = "只有 tell_now 才带 message；其余选择请去掉 message 再调用 decide。"
LONG_REASON = f"reason 最多 {REASON_MAX} 个字，请缩短后重新调用 decide。"
LONG_MESSAGE = f"message 最多 {MESSAGE_MAX} 个字，请缩短后重新调用 decide。"

DECIDE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": DECIDE,
        "description": "对这条提醒做出决定，整轮只调用一次，调用后这一轮结束。"
                       "tell_now：现在再对用户说一次（必须带 message）；digest：留到下一次简报；record：只留个记录；ignore：不用让用户知道。",
        "parameters": {
            "type": "object",
            "properties": {"decision": {"type": "string", "enum": list(DECISIONS)},
                           "reason": {"type": "string", "minLength": 1, "maxLength": REASON_MAX},
                           "message": {"type": "string", "maxLength": MESSAGE_MAX}},
            "required": ["decision", "reason"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class WakeState:
    """What a wake turn has concluded so far (``run.wake``): None until the first valid ``decide``."""
    decision: dict | None = None


def _refused(reason: str) -> dict:
    return {**tools.error("invalid_arguments"), "reason": reason}


def settle(run, args: dict) -> dict:
    """One ``decide`` call: keep the decision on the run, or say why not."""
    if run.wake.decision is not None:
        return {"ok": False, "data": [], "error_code": "already_decided", "reason": DECIDED}
    if set(args) - {"decision", "reason", "message"}:
        return tools.error("invalid_arguments")
    decision, reason, message = args.get("decision"), args.get("reason"), args.get("message")
    if decision not in DECISIONS or not isinstance(reason, str) or not reason.strip():
        return tools.error("invalid_arguments")
    if message is not None and not isinstance(message, str):
        return tools.error("invalid_arguments")
    reason, message = reason.strip(), (message or "").strip()
    if len(reason) > REASON_MAX:
        return _refused(LONG_REASON)
    if decision == "tell_now":
        if not message:
            return _refused(NEEDS_MESSAGE)
        if len(message) > MESSAGE_MAX:
            return _refused(LONG_MESSAGE)
    elif message:
        return _refused(NO_MESSAGE)
    run.wake.decision = {"decision": decision, "reason": reason, "message": message or None}
    return {"ok": True, "data": [{"status": "decided", "note": NOTE}]}
