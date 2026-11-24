"""The kernel's ``ask``: a question, with optional choices, put to the user as a card.

It writes nothing and reads nothing.  The first ``ask`` of a turn keeps the card on the run; the loop hands it to the user
when the turn ends, and the model's last sentence restates the question.  A button press (``reply:<text>``) or a typed
message is then an ordinary turn whose question is the answer (see ``press``).  One card per turn: ``act`` shares the rule.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from ..agent_workflow import tools

ASK = "ask"
QUESTION_MAX = 400
OPTIONS_MAX = 8
EXPIRES_MINUTES = 10
ONE_CARD = "这一轮已经有一张卡片了。"
NOTE = "问题已经作为卡片发给用户，这一轮到此结束。现在用一句话把问题对用户再说一遍，不要再调用工具。"

ASK_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": ASK,
        "description": "真缺一条只有用户知道的信息时才用。给出问题和（可选的）几个选项，问题会作为一张卡片发给用户，这一轮到此结束。能自己查到的不要问。",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "minLength": 1, "maxLength": QUESTION_MAX},
                           "options": {"type": "array", "items": {"type": "string"}, "maxItems": OPTIONS_MAX}},
            "required": ["question"],
            "additionalProperties": False,
        },
    },
}


def card(question: str, options: list[str], original_question: str) -> dict:
    """The old engine's question card (``Turn.card``): each option is a button whose value is ``reply:<option>``."""
    return {"id": str(uuid.uuid4()), "reason": "missing_information", "question": question, "original_question": original_question,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=EXPIRES_MINUTES)).isoformat(),
            "choices": [{"label": option, "value": "reply:" + option} for option in options]}


def refusal() -> dict:
    """What the second card of a turn (an ``ask`` or an ``act`` proposal) gets back."""
    return {"ok": False, "data": [], "error_code": "one_card_per_turn", "reason": ONE_CARD}


def _checked(args: dict) -> tuple[str, list[str]] | None:
    question, options = args.get("question"), args.get("options", [])
    if not isinstance(question, str) or not question.strip() or len(question.strip()) > QUESTION_MAX:
        return None
    if not isinstance(options, list) or len(options) > OPTIONS_MAX or not all(isinstance(o, str) and o.strip() for o in options):
        return None
    return question.strip(), [o.strip() for o in options]


def settle(run, args: dict) -> dict:
    """One ``ask`` call: keep the card on the run, or say why not."""
    checked = _checked(args)
    if checked is None:
        return tools.error("invalid_arguments")
    if run.question_card or run.proposals:
        return refusal()
    run.question_card = card(*checked, run.question)
    run.audit["asked"] = True
    return {"ok": True, "data": [{"status": "waiting_for_input", "note": NOTE}]}
