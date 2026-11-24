"""A pressed confirmation card: what the button said, and what the kernel does about it.

``read`` recognises the button's value (the only thing that carries a card's capability); ``settle`` runs it.  Cancelling,
a card that is no longer the waiting one, and every refusal end in a sentence for the user with no model call.  A confirm
executes through consent and hands the model the facts as a system message: the model never sees the button value or the
token, and the ordinary loop reports the result and carries on.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from ..agent_workflow import consent, direct
from . import act

WRITE_CARD = "write_confirmation"
UNSUPPORTED = "这张卡片现在处理不了，请换用其他 bot。"
CANCELLED = "已取消，没有执行任何操作。"
CANCELLING = "已请求停止后续操作；当前已经开始的操作可能仍在完成。"
ENDED = "操作已经结束，无法撤回已经完成的结果。"
ALREADY_DONE = "这张确认卡已经执行过了，不会重复执行；结果见之前的回复。"
ALREADY_CANCELLED = "这张确认卡已经取消，没有执行。"
STALE = "这张卡片已经失效：之后有了新的消息，所以它没有执行。如果还需要，请重新提出这项操作。"
# consent.failure_reason has no sentence for these two and would call an expired or used card a service error.
REASONS = {"confirmation_expired": "这张确认卡已经过期（10 分钟内有效），没有执行任何操作。如果还需要，请重新提出这项操作。",
           "confirmation_consumed": "这张确认卡已经用过了，不会重复执行。"}
FACT = ("系统事实：用户在确认卡「{title}」上点了「同意」，操作已经执行，结果如下（JSON）：{facts}。用户当时的原话是：「{question}」。"
        "请用一两句话告诉用户结果；失败的要说明原因。如果原话里还有没做完的事，现在接着做。")
TYPED_NOTE = ("系统事实：有一张确认卡「{title}」还在等用户点按钮，打字不能代替点按钮。"
              "用户如果是想确认，请他点卡片上的「同意」；如果是在说别的事，照常回答。")


@dataclass(frozen=True)
class Press:
    kind: str                # "confirm" | "cancel"
    request_id: str
    token: str | None
    variant: str | None


@dataclass
class Settled:
    answer: str | None       # a sentence for the user (no model call), or ``None`` when the model is to report
    fact: str | None         # the system message that replaces the button value
    status: str              # "succeeded", or "waiting_for_input" when the conversation's own card is still the pending one
    outcome: str             # "executed" | "cancelled" | "stale_card" | "refused:<code>" | "failed"


def card_title(card: dict) -> str:
    return str((card.get("display") or {}).get("title") or "")


def typed_note(state: dict) -> str | None:
    """The system message for a typed turn while a write card waits; ``None`` when none does."""
    card = (state or {}).get("pending_request")
    if isinstance(card, dict) and card.get("reason") == WRITE_CARD and not card.get("side"):
        return TYPED_NOTE.format(title=card_title(card))
    return None


def read(question: str, state: dict) -> Press | None:
    """The press this message is, or ``None`` for an ordinary typed message.  A value for another card raises ``pending_request_mismatch``."""
    request_id = (state or {}).get("requested_pending_id")
    if not request_id:
        return None
    pending = state.get("pending_request")
    waiting = pending if isinstance(pending, dict) and pending.get("id") == request_id else None
    kind, _, rest = question.partition(":")
    if kind in {"cancel", "change", "authorize"}:
        if rest != request_id:
            raise ValueError("pending_request_mismatch")
        if kind != "authorize":
            return Press("cancel", request_id, None, None)
        choice = next((c["value"] for c in (waiting or {}).get("choices", []) if str(c.get("value", "")).startswith("confirm:")), None)
        if waiting is not None and waiting.get("reason") == WRITE_CARD and not choice:
            raise ValueError("confirmation_required")
        return Press("confirm", request_id, choice.split(":", 1)[1].partition(":")[0] if choice else None, None)
    if kind == "confirm":
        token, _, ticked = rest.partition(":")
        if ticked and waiting is not None and ticked not in (waiting.get("variants") or []):
            raise ValueError("confirmation_parameter_mismatch")
        return Press("confirm", request_id, token, ticked if ticked and waiting is not None else None)
    if waiting is not None and waiting.get("reason") == WRITE_CARD:
        raise ValueError("confirmation_required")
    return Press("confirm", request_id, None, None)      # a button of a card this kernel does not own: settle refuses it


def _reason(code: str) -> str:
    return REASONS.get(code) or consent.failure_reason(code)


def _code(failure: Exception) -> str:
    return str(getattr(failure, "code", None) or failure)


async def _pressed_another_card(run, press: Press, pending) -> Settled:
    """A button on a card that is no longer the one waiting: say what became of it, and write nothing."""
    context = run.context
    try:
        status = (await asyncio.to_thread(consent.lookup, context.identity_credential, context.conversation_id, press.request_id)).get("status")
    except Exception:
        status = None
    waiting = "waiting_for_input" if pending else "succeeded"
    if status == "complete":
        return Settled(ALREADY_DONE, None, waiting, "refused:already_complete")
    if status in {"cancelled", "cancelling"}:
        return Settled(ALREADY_CANCELLED, None, waiting, "cancelled")
    return Settled(STALE, None, waiting, "stale_card")


async def settle(run, press: Press, state: dict) -> Settled:
    context = run.context
    pending = state.get("pending_request") if isinstance(state.get("pending_request"), dict) else None
    if not pending or pending.get("id") != press.request_id:
        return await _pressed_another_card(run, press, pending)
    if pending.get("reason") != WRITE_CARD:
        return Settled(UNSUPPORTED, None, "waiting_for_input", "refused:unsupported_card")
    try:
        saved = await asyncio.to_thread(consent.lookup, context.identity_credential, context.conversation_id, press.request_id)
    except consent.ConsentError as failure:
        return Settled(_reason(_code(failure)), None, "succeeded", f"refused:{_code(failure)}")
    if press.kind == "cancel":
        outcome = await asyncio.to_thread(consent.cancel, context.identity_credential, context.conversation_id, press.request_id)
        if outcome["status"] == "cancelling":
            return Settled(CANCELLING, None, "succeeded", "cancelled")
        if outcome["status"] == "complete":
            return Settled(ENDED, None, "succeeded", "refused:already_complete")
        return Settled(CANCELLED, None, "succeeded", "cancelled")
    operations = saved["operations"]
    try:
        value = await asyncio.to_thread(consent.execute, context.identity_credential, context.conversation_id, press.token, operations,
                                        act.execute_handler(context, variant=press.variant))
    except asyncio.CancelledError:
        # A thread's started side effect cannot be killed; revoke the later items of the batch before propagating.
        try:
            await asyncio.shield(asyncio.to_thread(consent.cancel, context.identity_credential, context.conversation_id, press.request_id))
        except Exception:
            pass
        raise
    except consent.ConsentError as failure:
        return Settled(_reason(_code(failure)), None, "succeeded", f"refused:{_code(failure)}")
    facts = json.dumps(direct.execution_facts(value, operations), ensure_ascii=False, default=str)
    fact = FACT.format(title=card_title(pending) or card_title(saved), facts=facts, question=pending.get("original_question") or "")
    return Settled(None, fact, "succeeded", "executed" if value.get("ok", True) else "failed")
