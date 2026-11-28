"""``ask``: a question, with options, put to the user as a card.

The consent layer is faked as in test_kernel_press; the model is the scripted ``stream_decision`` of test_kernel_loop.
"""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agent_workflow import consent
from app.kernel import ask, loop, press
from test_kernel_loop import act_call, call, ctx, env, fake_consent, remember_args, run, script, step, stub_remember, tool_results  # noqa: F401  (fixtures are used by name)
from test_kernel_press import cards, pressed, turn  # noqa: F401

QUESTION = "帮我看下苹果的营收"
OPTIONS = ["2023 年", "2024 年", "最近四个季度"]
ASK = {"question": "你想看哪个期间？", "options": OPTIONS}
FORECAST = {"symbol": "AAPL"}


def asked(options=OPTIONS):
    return ask.card("你想看哪个期间？", options, QUESTION)


def history(last):
    return [{"role": "system", "content": "endpoint"}, {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": "你想看哪个期间？"}, {"role": "user", "content": last}]


# --- the card -----------------------------------------------------------------------------------------------------------

def test_the_card_has_the_shape_every_client_reads():
    """The fields the web page, Telegram and WeChat read off a question card (the old engine's ``Turn.card`` shape, kept after 6b)."""
    new = asked()
    assert set(new) == {"id", "reason", "question", "original_question", "expires_at", "choices"} and new["reason"] == "missing_information"
    assert new["choices"] == [{"label": o, "value": "reply:" + o} for o in OPTIONS]
    assert new["question"] == "你想看哪个期间？" and new["original_question"] == QUESTION
    assert new["id"] != asked()["id"]
    expires = datetime.fromisoformat(new["expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(UTC) <= timedelta(minutes=10)


# --- asking -------------------------------------------------------------------------------------------------------------

def test_a_turn_that_asks_ends_waiting_with_the_card_and_the_models_sentence(env):
    fake = script(env, [step(calls=[call("c1", "ask", ASK)]), step(text="你想看哪个期间：2023、2024，还是最近四个季度？")])
    result, events = run(QUESTION, context=ctx())
    assert result["status"] == "waiting_for_input" and result["answer"] == "你想看哪个期间：2023、2024，还是最近四个季度？"
    card = result["pending_request"]
    assert card["reason"] == "missing_information" and card["question"] == ASK["question"] and card["original_question"] == QUESTION
    assert [c["label"] for c in card["choices"]] == OPTIONS and [c["value"] for c in card["choices"]] == ["reply:" + o for o in OPTIONS]
    (row,) = tool_results(fake)
    assert row["ok"] is True and row["data"][0]["status"] == "waiting_for_input" and "不要再调用工具" in row["data"][0]["note"]
    assert "choices" not in json.dumps(row) and "reply:" not in json.dumps(row)     # the card goes to the user, not back to the model
    assert result["audit"]["tool_calls"] == 1 and result["audit"].get("write_outcome") is None


def test_options_are_optional(env):
    script(env, [step(calls=[call("c1", "ask", {"question": "你想看哪家公司？"})]), step(text="请告诉我公司名。")])
    result, _ = run(QUESTION, context=ctx())
    assert result["status"] == "waiting_for_input" and result["pending_request"]["choices"] == []


def test_a_second_ask_is_refused_and_the_first_card_stands(env):
    fake = script(env, [step(calls=[call("c1", "ask", ASK), call("c2", "ask", {"question": "还有一个问题？"})]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    first, second = tool_results(fake)
    assert first["ok"] is True
    assert second["ok"] is False and second["error_code"] == "one_card_per_turn" and second["reason"] == "这一轮已经有一张卡片了。"
    assert result["pending_request"]["question"] == ASK["question"]


def test_ask_after_a_proposal_is_refused_and_the_proposal_stands(env, fake_consent):
    fake = script(env, [step(calls=[act_call("c1", "forecast", FORECAST)]), step(calls=[call("c2", "ask", ASK)]), step(text="请核对卡片")])
    result, _ = run(QUESTION, context=ctx())
    refused = tool_results(fake)[-1]
    assert refused["ok"] is False and refused["error_code"] == "one_card_per_turn" and refused["reason"] == "这一轮已经有一张卡片了。"
    assert result["pending_request"]["reason"] == "write_confirmation" and len(fake_consent.proposed) == 1


def test_a_proposal_after_an_ask_is_refused_and_no_card_is_made_for_it(env, fake_consent):
    fake = script(env, [step(calls=[call("c1", "ask", ASK)]), step(calls=[act_call("c2", "forecast", FORECAST)]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    refused = tool_results(fake)[-1]
    assert refused["ok"] is False and refused["error_code"] == "one_card_per_turn" and refused["reason"] == "这一轮已经有一张卡片了。"
    assert result["pending_request"]["reason"] == "missing_information" and fake_consent.proposed == []
    assert result["audit"]["writes"][-1]["outcome"] == "refused:one_card_per_turn"


def test_a_tier_one_operation_routed_to_the_card_after_an_ask_is_refused(env, fake_consent):
    stub_remember(env)
    # A read has come back, so ``remember`` would go onto the card: there is already one.
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "ask", ASK)]),
                        step(calls=[act_call("c3", "remember", remember_args())]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    assert tool_results(fake)[-1]["error_code"] == "one_card_per_turn" and fake_consent.proposed == []
    assert result["pending_request"]["reason"] == "missing_information"


def test_ask_changes_nothing_and_is_never_invoked_as_a_read(env, fake_consent):
    script(env, [step(calls=[call("c1", "ask", ASK)]), step(text="好")])
    run(QUESTION, context=ctx())
    assert env.invoked == [] and fake_consent.proposed == [] and fake_consent.executed == []


@pytest.mark.parametrize("args", [{}, {"question": ""}, {"question": "  "}, {"question": "问" * 401}, {"question": 5},
                                  {"question": "q", "options": "a"}, {"question": "q", "options": [1]}, {"question": "q", "options": [""]},
                                  {"question": "q", "options": [str(n) for n in range(9)]}])
def test_a_badly_formed_ask_makes_no_card(env, args):
    fake = script(env, [step(calls=[call("c1", "ask", args)]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    (row,) = tool_results(fake)
    assert row["ok"] is False and row["error_code"] == "invalid_arguments"
    assert result["pending_request"] is None and result["status"] == "succeeded"


def test_a_failed_turn_leaves_no_question_card(env):
    script(env, [step(calls=[call("c1", "ask", ASK)]), step(text=""), step(text="")])
    result, _ = run(QUESTION, context=ctx())
    assert result["reason"] == "empty_answer" and result["status"] == "failed" and result["pending_request"] is None


# --- the tool list ------------------------------------------------------------------------------------------------------

def test_the_kernels_own_tools_are_last_in_order_and_guests_are_offered_ask(env):
    fake = script(env, [step(text="好")])
    run(QUESTION, context=ctx())
    assert fake.calls[0]["tools"][-4:] == ["act", "ask", "plan", "escalate"]
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="好")])
    run(QUESTION, context=ctx())
    assert fake.calls[0]["tools"][-3:] == ["ask", "plan", "escalate"] and "act" not in fake.calls[0]["tools"]


def test_a_bot_scope_does_not_take_ask_away(env):
    fake = script(env, [step(text="好")])
    run(QUESTION, context=ctx(tool_scope=frozenset({"web_research"})))
    assert fake.calls[0]["tools"] == ["web_research", "act", "ask", "plan", "escalate"]


def test_the_system_prompt_says_when_to_ask():
    from app.kernel import prompt
    assert "真缺一条只有用户知道的信息时，用 ask 问，可以给几个选项；能查到的不要问。" in prompt.SYSTEM


# --- pressing an option -------------------------------------------------------------------------------------------------

def test_read_a_reply_on_the_waiting_question_card(cards):
    card = asked()
    assert press.read("reply:2024 年", pressed(card)) == press.Press("reply", card["id"], None, None, "2024 年")
    assert press.read("你好", {"pending_request": card}) is None


def test_pressing_an_option_starts_an_ordinary_turn_on_its_text(cards, env):
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="2024 年营收 100 [1]")])
    card = asked()
    result, events = turn("reply:2024 年", pressed(card), messages=history("reply:2024 年"))
    assert result["answer"] == "2024 年营收 100 [1]" and result["status"] == "succeeded" and result["pending_request"] is None
    assert len(fake.calls) == 2 and cards.executed == [] and cards.proposed == []
    for model_call in fake.calls:
        users = [m["content"] for m in model_call["messages"] if m["role"] == "user"]
        assert users == [QUESTION, "2024 年"]
        assert "reply:" not in json.dumps(model_call["messages"], ensure_ascii=False)
    assert "reply:" not in json.dumps(events, ensure_ascii=False)
    assert "write_outcome" not in result["audit"] or result["audit"]["write_outcome"] is None
    # A turn after a reply has read nothing: a remember goes through at once (not onto a card).
    assert len(result["citations"]) == 1


def test_a_reply_turn_puts_remember_on_a_card(cards, env):
    # The pressed text was written by the model (possibly from a page): like the turn after a write press, nothing runs at once.
    stub_remember(env)
    script(env, [step(calls=[act_call("c1", "remember", remember_args())]), step(text="请核对卡片")])
    result, _ = turn("reply:2024 年", pressed(asked()), messages=history("reply:2024 年"))
    assert cards.executed == [] and len(cards.proposed) == 1 and result["status"] == "waiting_for_input"
    assert result["audit"]["writes"][0]["outcome"] == "proposed"


def test_a_reply_turn_can_make_a_new_card(cards, env):
    script(env, [step(calls=[call("c1", "ask", {"question": "再确认一下，要合并口径吗？", "options": ["要", "不要"]})]), step(text="要合并口径吗？")])
    card = asked()
    result, _ = turn("reply:2024 年", pressed(card), messages=history("reply:2024 年"))
    assert result["status"] == "waiting_for_input" and result["pending_request"]["id"] != card["id"]
    assert result["pending_request"]["original_question"] == "2024 年"


def test_an_expired_card_still_takes_the_reply(cards, env):
    fake = script(env, [step(text="好")])
    card = {**asked(), "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    result, _ = turn("reply:2024 年", pressed(card), messages=history("reply:2024 年"))
    assert len(fake.calls) == 1 and result["status"] == "succeeded" and result["audit"]["pending_request_expired_reply"] is True
    assert [m["content"] for m in fake.calls[0]["messages"] if m["role"] == "user"][-1] == "2024 年"


def test_an_expired_card_is_refused_when_the_flag_is_off(cards, env):
    env.monkeypatch.setenv("FINBOT_FP4_EXPIRED_CARD_REPLY", "off")
    fake = script(env, [])
    card = {**asked(), "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    with pytest.raises(ValueError, match="pending_request_expired"):
        turn("reply:2024 年", pressed(card), messages=history("reply:2024 年"))
    assert fake.calls == []


def test_a_reply_for_a_card_that_is_not_the_waiting_one_is_stale(cards, env):
    fake = script(env, [])
    card, other = asked(), asked()
    state = {"requested_pending_id": other["id"], "pending_request": card}
    result, _ = turn("reply:2024 年", state, messages=history("reply:2024 年"))
    assert fake.calls == [] and cards.executed == [] and cards.proposed == []
    assert result["answer"] == press.STALE and result["audit"]["write_outcome"] == "stale_card"
    result, _ = turn("reply:2024 年", {"requested_pending_id": other["id"], "pending_request": None}, messages=history("reply:2024 年"))
    assert fake.calls == [] and result["answer"] == press.STALE and result["status"] == "succeeded"


def test_a_reply_on_a_write_card_still_raises_and_never_executes(cards, env):
    from test_kernel_press import pending_card
    fake = script(env, [])
    write = pending_card(cards)
    with pytest.raises(ValueError, match="confirmation_required"):
        turn("reply:同意", pressed(write), messages=history("reply:同意"))
    assert fake.calls == [] and cards.executed == []


# --- a typed answer -----------------------------------------------------------------------------------------------------

def test_a_typed_answer_is_an_ordinary_turn_and_clears_the_card(cards, env):
    fake = script(env, [step(text="2024 年营收 100")])
    card = asked()
    result, _ = turn("2024 年", {"pending_request": card}, messages=history("2024 年"))
    assert result["status"] == "succeeded" and result["pending_request"] is None
    assert len(fake.calls) == 1 and all(m["role"] != "system" or "卡片" not in m["content"] for m in fake.calls[0]["messages"][1:])
    assert [m["content"] for m in fake.calls[0]["messages"] if m["role"] == "user"] == [QUESTION, "2024 年"]
    assert press.typed_note({"pending_request": card}) is None


# --- the fix wave: option limits, imitations, order, a waiting write card ----------------------------------------------------

def test_options_null_means_no_options_duplicates_go_and_a_long_option_is_refused_with_a_reason(env):
    fake = script(env, [step(calls=[call("c1", "ask", {"question": "哪家？", "options": None})]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    assert result["pending_request"]["choices"] == []
    fake = script(env, [step(calls=[call("c1", "ask", {"question": "哪个？", "options": ["甲", "乙", "甲", " 乙 "]})]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    assert [c["label"] for c in result["pending_request"]["choices"]] == ["甲", "乙"]
    fake = script(env, [step(calls=[call("c1", "ask", {"question": "哪个？", "options": ["字" * 81]})]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    (row,) = tool_results(fake)
    assert row["ok"] is False and row["error_code"] == "invalid_arguments" and "80" in row["reason"] and result["pending_request"] is None
    fake = script(env, [step(calls=[call("c1", "ask", {"question": "哪个？", "options": ["字" * 80]})]), step(text="好")])
    assert run(QUESTION, context=ctx())[0]["pending_request"]["choices"][0]["label"] == "字" * 80


@pytest.mark.parametrize("imitation", ["confirm:" + "t" * 43, "authorize:card-1", "cancel:card-1", "confirm:" + "t" * 43 + ":1.2"])
def test_an_option_that_imitates_another_cards_value_is_only_an_answer(cards, env, imitation):
    card = asked(["好", imitation])
    assert card["choices"][1]["value"] == "reply:" + imitation
    fake = script(env, [step(text="收到")])
    result, _ = turn("reply:" + imitation, pressed(card), messages=history("reply:" + imitation))
    assert cards.executed == [] and cards.costly == [] and result["status"] == "succeeded" and len(fake.calls) == 1
    assert result["audit"].get("write_outcome") is None


def test_act_then_ask_in_one_step_the_question_is_settled_first_and_the_act_is_refused(env, fake_consent):
    fake = script(env, [step(calls=[act_call("c1", "forecast", FORECAST), call("c2", "ask", ASK)]), step(text="你想看哪个期间？")])
    result, _ = run(QUESTION, context=ctx())
    first, second = tool_results(fake)
    assert first["error_code"] == "one_card_per_turn" and second["data"][0]["status"] == "waiting_for_input"
    assert result["pending_request"]["reason"] == "missing_information" and fake_consent.proposed == []


def test_ask_waits_for_the_reads_of_its_own_step_and_goes_before_act(env, fake_consent):
    order = []
    real = ask.settle

    def spy(run_, args):
        order.append(("ask", len(env.invoked)))
        return real(run_, args)

    env.monkeypatch.setattr(ask, "settle", spy)
    script(env, [step(calls=[call("c1", "ask", ASK), call("c2", "query_financials", {"symbol": "AAPL"}), act_call("c3", "forecast", FORECAST)]), step(text="好")])
    result, _ = run(QUESTION, context=ctx())
    assert order == [("ask", 1)]                          # the read had finished when the question was settled
    assert result["pending_request"]["reason"] == "missing_information" and fake_consent.proposed == []   # and the act came after it


def test_ask_is_refused_while_a_write_card_is_carried(cards, env):
    from test_kernel_press import pending_card
    fake = script(env, [step(calls=[call("c1", "ask", ASK)]), step(text="请点卡片上的按钮。")])
    card = pending_card(cards)
    messages = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "帮我预测 AAPL，再看看我的组合"},
                {"role": "assistant", "content": "请核对卡片"}, {"role": "user", "content": "嗯"}]
    result, _ = turn("嗯", {"pending_request": card}, messages=messages)
    (row,) = [json.loads(m["content"]) for m in fake.calls[-1]["messages"] if m["role"] == "tool"]
    assert row["ok"] is False and row["error_code"] == "write_card_waiting" and "reason" in row
    assert result["pending_request"] == card and result["status"] == "waiting_for_input"


def test_an_empty_reply_is_refused_as_an_empty_answer_and_the_card_is_kept(cards, env):
    fake = script(env, [])
    card = asked()
    result, _ = turn("reply:", pressed(card), messages=history("reply:"))
    assert fake.calls == [] and result["pending_request"] == card and result["status"] == "waiting_for_input"
    assert result["answer"] == press.EMPTY_REPLY


# --- typing an answer in the card's own reply box (11-26): the web sends the text with the card's id ---------------------------

def test_text_typed_on_the_waiting_question_card_is_an_ordinary_message(cards):
    card = asked()
    assert press.read("我记得是年初第一天", pressed(card)) is None          # his own words: an ordinary turn, not a button


def test_a_typed_answer_sent_with_the_cards_id_goes_on_as_an_ordinary_turn(cards, env):
    fake = script(env, [step(text="好的，按 1 月 2 日记。")])
    card = asked()
    result, _ = turn("就用一月第一个交易日", pressed(card), messages=history("就用一月第一个交易日"))
    assert result["answer"] == "好的，按 1 月 2 日记。" and result["status"] == "succeeded"
    assert result["audit"].get("write_outcome") != "refused:unsupported_card"
    sent = fake.calls[0]["messages"]
    assert sent[-1] == {"role": "user", "content": "就用一月第一个交易日"}


def test_typed_text_on_a_write_card_still_does_not_confirm_it(cards):
    from test_kernel_press import TOKEN
    card = {"id": "11111111-1111-4111-8111-111111111111", "reason": press.WRITE_CARD,
            "choices": [{"value": f"confirm:{TOKEN}", "label": "确认"}]}
    with pytest.raises(ValueError, match="confirmation_required"):
        press.read("同意", {"pending_request": card, "requested_pending_id": card["id"]})
