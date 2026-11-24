"""A pressed card: what the kernel does when the owner presses a button on a confirmation card.

The consent layer is faked (``FakeCards``); the model is the scripted ``stream_decision`` of test_kernel_loop.
"""
import asyncio
import copy
import json
import threading

import pytest

from app.agent_workflow import consent, tools
from app.kernel import loop, press
from test_kernel_loop import FakeConsent, TOKEN, act_call, call, ctx, env, kinds, script, step  # noqa: F401  (env is used by name)

QUESTION = "帮我预测 AAPL，再看看我的组合"
FORECAST = {"name": "forecast", "arguments": {"symbol": "AAPL"}}
SKILL = {"name": "save_skill", "arguments": {"name": "周报", "description": "每周总结", "body": "先看持仓", "allowed_tools": ["query_portfolio"]}}
SENTENCES = {
    "cancelled": "已取消，没有执行任何操作。",
    "stale": "这张卡片已经失效：之后有了新的消息，所以它没有执行。如果还需要，请重新提出这项操作。",
    "done_before": "这张确认卡已经执行过了，不会重复执行；结果见之前的回复。",
    "cancelled_before": "这张确认卡已经取消，没有执行。",
    "unsupported": "这张卡片现在处理不了，请换用其他 bot。",
}


class FakeCards(FakeConsent):
    """FakeConsent plus the rest of the consent layer a press touches: lookup, cancel, and an execute with a durable status."""

    def __init__(self):
        super().__init__()
        self.saved, self.cancelled, self.execute_error, self.block = {}, [], None, None

    def propose(self, credential, conversation, operations, display, *, question="", variants=None):
        card = super().propose(credential, conversation, operations, display, question=question, variants=variants)
        if variants:
            card["choices"] = [{"label": label, "value": f"confirm:{TOKEN}" + (f":{suffix}" if suffix else "")} for label, suffix in variants]
            card["variants"] = [suffix for _, suffix in variants if suffix]
        self.saved[card["id"]] = {"id": card["id"], "operations": copy.deepcopy(operations), "display": display, "status": "proposed"}
        return card

    def lookup(self, credential, conversation, request_id):
        if request_id not in self.saved:
            raise consent.ConsentError("confirmation_scope_mismatch")
        return copy.deepcopy(self.saved[request_id])

    def cancel(self, credential, conversation, request_id):
        self.cancelled.append(request_id)
        row = self.saved[request_id]
        row["status"] = {"proposed": "cancelled", "executing": "cancelling"}.get(row["status"], row["status"])
        return {"ok": True, "status": row["status"]}

    def execute(self, credential, conversation, token, operations, handler):
        if self.block:
            self.block[0].set()
            self.block[1].wait(5)
        if self.execute_error:
            raise self.execute_error
        card = next(row for row in self.saved.values() if row["operations"] == operations)
        if card["status"] == "complete":
            return card["result"]
        card["status"] = "executing"
        result = super().execute(credential, conversation, token, operations, handler)
        card.update(status="complete", result=result)
        return result


@pytest.fixture
def cards(env):  # noqa: F811
    fake = FakeCards()
    mp = env.monkeypatch
    for name in ("propose", "execute", "lookup", "cancel"):
        mp.setattr(consent, name, getattr(fake, name))
    fake.costly, fake.reversible_calls = [], []

    def costly(operation, key, context):
        fake.costly.append((operation, key))
        return fake.costly_result or {"ok": True, "status": "queued", "job_id": "job-1", "symbol": operation["arguments"].get("symbol")}

    async def reversible(operation, key, context, *, emit=None, overrides=None):
        fake.reversible_calls.append((operation["name"], overrides))
        return {"ok": True, "status": "saved"}

    fake.costly_result = None
    mp.setattr(tools, "execute_costly", costly)
    mp.setattr(tools, "execute_reversible", reversible)
    return fake


def pending_card(cards, operations=(FORECAST,), *, variants=None, title="生成研究预测", question=QUESTION):
    return cards.propose("x" * 64, "conv", list(operations), {"title": title, "targets": []}, question=question, variants=variants)


def turn(question, state, *, messages=None, context=None):
    events = []

    async def emit(event):
        events.append(event)

    history = messages if messages is not None else [{"role": "system", "content": "endpoint"}, {"role": "user", "content": QUESTION},
                                                     {"role": "assistant", "content": "我准备生成预测，请核对卡片"}, {"role": "user", "content": question}]
    result = asyncio.run(loop.run_turn(question, context or ctx(), emit, history, state))
    return result, events


def pressed(card, value=None, *, pending="same"):
    """The state the graph hands the kernel for a press on ``card``."""
    return {"requested_pending_id": card["id"], "pending_request": card if pending == "same" else pending}


# --- press.read -------------------------------------------------------------------------------------------------------

def test_read_each_button_form(cards):
    card = pending_card(cards)
    state = pressed(card)
    assert press.read(f"confirm:{TOKEN}", state) == press.Press("confirm", card["id"], TOKEN, None)
    assert press.read(f"cancel:{card['id']}", state) == press.Press("cancel", card["id"], None, None)
    assert press.read(f"change:{card['id']}", state).kind == "cancel"
    assert press.read(f"authorize:{card['id']}", state) == press.Press("confirm", card["id"], TOKEN, None)
    assert press.read("你好", {"pending_request": card}) is None
    assert press.read("同意", {"pending_request": card}) is None


def test_read_variant_must_be_one_the_card_lists(cards):
    card = pending_card(cards, [SKILL], variants=[("保存并启用", None), ("存为草稿", "draft")], title="保存技能")
    assert press.read(f"confirm:{TOKEN}:draft", pressed(card)).variant == "draft"
    assert press.read(f"confirm:{TOKEN}", pressed(card)).variant is None
    with pytest.raises(ValueError, match="confirmation_parameter_mismatch"):
        press.read(f"confirm:{TOKEN}:admin", pressed(card))


def test_read_a_mismatched_id_raises(cards):
    card = pending_card(cards)
    for value in ("cancel:other", "change:other", "authorize:other"):
        with pytest.raises(ValueError, match="pending_request_mismatch"):
            press.read(value, pressed(card))


def test_read_an_unknown_value_on_the_waiting_write_card_raises(cards):
    card = pending_card(cards)
    with pytest.raises(ValueError, match="confirmation_required"):
        press.read("reply:好", pressed(card))


# --- confirm ----------------------------------------------------------------------------------------------------------

def confirm_turn(cards, env, steps, *, operations=(FORECAST,), variant=None, **kw):
    fake = script(env, steps)
    card = pending_card(cards, operations, **kw)
    value = f"confirm:{TOKEN}" + (f":{variant}" if variant else "")
    result, events = turn(value, pressed(card))
    return fake, card, result, events


def test_confirm_executes_once_and_the_model_gets_the_facts_not_the_token(cards, env):
    fake, card, result, events = confirm_turn(cards, env, [step(text="预测已经提交，稍后在预测记录里看。")])
    assert len(cards.executed) == 1 and cards.executed[0][1] == [FORECAST]
    assert len(cards.costly) == 1 and cards.costly[0][0] == FORECAST
    (call_,) = fake.calls
    sent = json.dumps(call_["messages"], ensure_ascii=False)
    assert "confirm:" not in sent and TOKEN not in sent
    facts = [m["content"] for m in call_["messages"] if m["role"] == "system" and m["content"].startswith("系统事实：用户在确认卡")]
    assert len(facts) == 1 and call_["messages"][-1]["content"] == facts[0]
    fact = facts[0]
    assert fact.startswith("系统事实：用户在确认卡「生成研究预测」上点了「同意」，操作已经执行，结果如下（JSON）：[")
    assert '"job_id": "job-1"' in fact or '"job_id":"job-1"' in fact
    assert f"用户当时的原话是：「{QUESTION}」。请用一两句话告诉用户结果；失败的要说明原因。如果原话里还有没做完的事，现在接着做。" in fact
    assert [m["content"] for m in call_["messages"] if m["role"] == "user"] == [QUESTION]
    assert result["status"] == "succeeded" and result["pending_request"] is None
    assert result["audit"]["write_outcome"] == "executed" and TOKEN not in json.dumps(result["audit"], default=str)
    assert TOKEN not in json.dumps(events, default=str)


def test_after_the_press_the_turn_carries_on(cards, env):
    steps = [step(calls=[call("c1", "query_portfolio", {})]), step(text="预测已提交；你的组合里有 AAPL。")]
    fake, card, result, events = confirm_turn(cards, env, steps)
    assert len(cards.costly) == 1                                   # one write
    assert [name for name, _ in env.invoked] == ["query_portfolio"]  # one read, after the fact
    assert len(fake.calls) == 2 and result["status"] == "succeeded" and result["pending_request"] is None
    assert result["answer"] == "预测已提交；你的组合里有 AAPL。"
    assert fake.calls[0]["tools"] == fake.calls[1]["tools"] and "act" in fake.calls[0]["tools"]


def test_the_continuing_turn_can_propose_a_new_card(cards, env):
    steps = [step(calls=[act_call("c1", "forecast", {"symbol": "MSFT"})]), step(text="AAPL 已提交；MSFT 的预测请核对新卡片。")]
    fake, card, result, events = confirm_turn(cards, env, steps)
    assert result["status"] == "waiting_for_input" and result["pending_request"]["id"] != card["id"]
    assert result["audit"]["write_outcome"] == "executed"
    assert len(cards.costly) == 1                                   # the second operation did not run


def test_a_failed_execution_is_still_told_to_the_model(cards, env):
    cards.costly_result = {"ok": False, "error_code": "market_data_unavailable"}
    fake, card, result, events = confirm_turn(cards, env, [step(text="没成功。")])
    assert "market_data_unavailable" in fake.calls[0]["messages"][-1]["content"]
    assert result["audit"]["write_outcome"] == "failed" and result["status"] == "succeeded"


def test_save_skill_variant_reaches_the_handler(cards, env):
    confirm_turn(cards, env, [step(text="已存为草稿。")], operations=(SKILL,), variants=[("保存并启用", None), ("存为草稿", "draft")],
                 variant="draft", title="保存技能")
    assert cards.reversible_calls == [("save_skill", {"status": "draft"})]


def test_save_skill_without_a_variant_is_not_a_draft(cards, env):
    confirm_turn(cards, env, [step(text="已保存。")], operations=(SKILL,), variants=[("保存并启用", None), ("存为草稿", "draft")], title="保存技能")
    assert cards.reversible_calls == [("save_skill", {"status": None})]


def test_a_tier_two_operation_runs_through_the_reversible_handler(cards, env):
    trade = {"name": "set_available_funds", "arguments": {"amount": 1000, "currency": "USD"}}
    confirm_turn(cards, env, [step(text="已记录。")], operations=(trade,))
    assert cards.reversible_calls == [("set_available_funds", None)] and cards.costly == []


def test_expired_card_says_why(cards, env):
    cards.execute_error = consent.ConsentError("confirmation_expired")
    fake = script(env, [])
    card = pending_card(cards)
    result, events = turn(f"confirm:{TOKEN}", pressed(card))
    assert fake.calls == [] and cards.costly == []
    assert "过期" in result["answer"] and result["pending_request"] is None and result["status"] == "succeeded"
    assert result["audit"]["write_outcome"] == "refused:confirmation_expired"
    assert [e["text"] for e in events if e["event"] == "delta"] == [result["answer"]]


def test_other_consent_failures_use_the_consent_reason(cards, env):
    cards.execute_error = consent.ConsentError("owner_login_required")
    script(env, [])
    card = pending_card(cards)
    result, _ = turn(f"confirm:{TOKEN}", pressed(card))
    assert result["answer"] == consent.failure_reason("owner_login_required")
    assert result["audit"]["write_outcome"] == "refused:owner_login_required"


def test_cancelled_mid_execution_cancels_the_card(cards, env):
    script(env, [])
    card = pending_card(cards)
    started, release = threading.Event(), threading.Event()
    cards.block = (started, release)

    async def scenario():
        async def emit(event):
            pass

        history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": f"confirm:{TOKEN}"}]
        task = asyncio.create_task(loop.run_turn(f"confirm:{TOKEN}", ctx(), emit, history, pressed(card)))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

    asyncio.run(scenario())
    assert cards.cancelled == [card["id"]]


# --- cancel -----------------------------------------------------------------------------------------------------------

def test_cancel_answers_without_a_model_call(cards, env):
    fake = script(env, [])
    card = pending_card(cards)
    result, events = turn(f"cancel:{card['id']}", pressed(card))
    assert fake.calls == [] and cards.executed == [] and cards.cancelled == [card["id"]]
    assert result["answer"] == SENTENCES["cancelled"] and result["status"] == "succeeded" and result["pending_request"] is None
    assert result["audit"]["write_outcome"] == "cancelled" and result["audit"]["model_calls"] == 0
    assert kinds(events) == ["delta"] and events[0]["text"] == SENTENCES["cancelled"]


def test_change_is_a_cancel(cards, env):
    fake = script(env, [])
    card = pending_card(cards)
    result, _ = turn(f"change:{card['id']}", pressed(card))
    assert fake.calls == [] and cards.cancelled == [card["id"]] and result["answer"] == SENTENCES["cancelled"]


def test_cancel_while_executing_or_after_completion_says_so(cards, env):
    script(env, [])
    card = pending_card(cards)
    cards.saved[card["id"]]["status"] = "executing"
    result, _ = turn(f"cancel:{card['id']}", pressed(card))
    assert result["answer"] == "已请求停止后续操作；当前已经开始的操作可能仍在完成。"
    cards.saved[card["id"]]["status"] = "complete"
    result, _ = turn(f"cancel:{card['id']}", pressed(card))
    assert result["answer"] == "操作已经结束，无法撤回已经完成的结果。"


# --- a card that is not the one waiting -------------------------------------------------------------------------------

def test_pressing_a_superseded_card_writes_nothing(cards, env):
    fake = script(env, [])
    old = pending_card(cards)
    new = pending_card(cards, [{"name": "forecast", "arguments": {"symbol": "MSFT"}}])
    result, events = turn(f"confirm:{TOKEN}", {"requested_pending_id": old["id"], "pending_request": new})
    assert fake.calls == [] and cards.executed == [] and cards.costly == [] and cards.cancelled == []
    assert result["answer"] == SENTENCES["stale"] and result["audit"]["write_outcome"] == "stale_card"
    assert result["status"] == "waiting_for_input" and result["pending_request"] == new      # the waiting card stays on screen
    assert TOKEN not in json.dumps(events, default=str)


def test_pressing_twice_runs_once(cards, env):
    script(env, [step(text="已提交。")])
    card = pending_card(cards)
    first, _ = turn(f"confirm:{TOKEN}", pressed(card))
    assert first["pending_request"] is None
    fake = script(env, [])
    second, _ = turn(f"confirm:{TOKEN}", {"requested_pending_id": card["id"], "pending_request": None})
    assert len(cards.costly) == 1 and len(cards.executed) == 1 and fake.calls == []
    assert second["answer"] == SENTENCES["done_before"] and second["status"] == "succeeded"
    assert second["audit"]["write_outcome"] == "refused:already_complete"


def test_pressing_a_cancelled_card_says_so(cards, env):
    script(env, [])
    card = pending_card(cards)
    cards.cancel("x", "conv", card["id"])
    result, _ = turn(f"confirm:{TOKEN}", {"requested_pending_id": card["id"], "pending_request": None})
    assert result["answer"] == SENTENCES["cancelled_before"] and cards.executed == []


def test_pressing_an_unknown_card_is_stale(cards, env):
    script(env, [])
    result, _ = turn(f"confirm:{TOKEN}", {"requested_pending_id": "nope", "pending_request": None})
    assert result["answer"] == SENTENCES["stale"] and cards.executed == []


def test_a_card_that_is_not_a_write_card_is_refused(cards, env):
    fake = script(env, [])
    card = {**pending_card(cards), "reason": "choose_revision_sources"}
    result, _ = turn(f"confirm:{TOKEN}", pressed(card))
    assert fake.calls == [] and cards.executed == [] and cards.cancelled == []
    assert result["answer"] == SENTENCES["unsupported"] and result["audit"]["write_outcome"] == "refused:unsupported_card"
    assert result["status"] == "waiting_for_input" and result["pending_request"] == card


def test_a_mismatched_id_is_an_error_of_the_turn(cards, env):
    script(env, [])
    card = pending_card(cards)
    with pytest.raises(ValueError, match="pending_request_mismatch"):
        turn("cancel:other", pressed(card))


# --- typed words ------------------------------------------------------------------------------------------------------

def typed(cards, env, steps, text="同意"):
    fake = script(env, steps)
    card = pending_card(cards)
    messages = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": QUESTION},
                {"role": "assistant", "content": "我准备生成预测，请核对卡片"}, {"role": "user", "content": text}]
    result, events = turn(text, {"pending_request": card}, messages=messages)
    return fake, card, result


def test_typed_consent_runs_nothing_and_the_model_is_told_a_card_waits(cards, env):
    fake, card, result = typed(cards, env, [step(text="请点卡片上的「同意」。")])
    assert cards.executed == [] and cards.costly == [] and len(fake.calls) == 1
    note = fake.calls[0]["messages"][-1]
    assert note == {"role": "system", "content": "系统事实：有一张确认卡「生成研究预测」还在等用户点按钮，打字不能代替点按钮。"
                                                  "用户如果是想确认，请他点卡片上的「同意」；如果是在说别的事，照常回答。"}
    assert [m["content"] for m in fake.calls[0]["messages"] if m["role"] == "user"] == [QUESTION, "同意"]


def test_typed_message_keeps_the_card_pending(cards, env):
    fake, card, result = typed(cards, env, [step(text="好的，另一件事：……")], text="顺便问下 AAPL 的市值")
    assert result["status"] == "waiting_for_input" and result["pending_request"] == card
    assert result["audit"].get("write_outcome") is None


def test_a_new_proposal_replaces_the_waiting_card(cards, env):
    steps = [step(calls=[act_call("c1", "forecast", {"symbol": "MSFT"})]), step(text="我改成预测 MSFT，请核对新卡片。")]
    fake, card, result = typed(cards, env, steps, text="不，换成 MSFT")
    assert result["status"] == "waiting_for_input" and result["pending_request"]["id"] != card["id"]
    assert result["audit"]["write_outcome"] == "proposed"


def test_no_card_no_note(cards, env):
    fake = script(env, [step(text="你好")])
    result, _ = turn("你好", {}, messages=[{"role": "system", "content": "endpoint"}, {"role": "user", "content": "你好"}])
    assert all("还在等用户点按钮" not in m["content"] for m in fake.calls[0]["messages"]) and result["pending_request"] is None


# --- prompt.build_messages with a fact --------------------------------------------------------------------------------

def test_build_messages_with_a_fact_drops_the_button_value():
    from app.kernel import prompt
    raw = f"confirm:{TOKEN}"
    history = [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": "请核对"}, {"role": "user", "content": raw},
               {"role": "system", "content": "摘要"}]
    messages = prompt.build_messages(raw, ctx(), history, fact="系统事实：甲")
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "system", "system"]
    assert messages[-1] == {"role": "system", "content": "系统事实：甲"} and raw not in json.dumps(messages, ensure_ascii=False)
    # even when the history does not hold it, the question is never added
    assert raw not in json.dumps(prompt.build_messages(raw, ctx(), history[:2], fact="系统事实：甲"), ensure_ascii=False)
    assert prompt.build_messages("你好", ctx(), [])[-1] == {"role": "user", "content": "你好"}
