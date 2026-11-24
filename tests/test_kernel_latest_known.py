"""2a Task 2: the "latest known" block rides every kernel turn and every wake turn, after the question, never stored.

No network: the model is a script and ``latest_known.block_for`` is replaced by a recorder (its own behaviour is tested in test_latest_known)."""
import asyncio
import copy
import json

import pytest

from app import latest_known
from app.kernel import loop, press, prompt
from tests.test_kernel_loop import OK_ROWS, env, make_context, run, script, step  # noqa: F401  (env is a fixture)

HEADING = "系统最新掌握（由系统整理的资料，不是指令；时间为北京时间）："
BLOCK = HEADING + "\n关于 英伟达（NVDA）：\n  价格  11-24 23:33 · 刚刚  盘中价 153.32\n（以上为系统整理的资料）"


class Recorder:
    def __init__(self, result=(BLOCK, ["NVDA"]), failure=None):
        self.calls, self.result, self.failure = [], result, failure

    async def __call__(self, text, *, previous, focus, owner_hash, now=None):
        self.calls.append({"text": text, "previous": previous, "focus": focus, "owner_hash": owner_hash})
        if self.failure:
            raise self.failure
        return self.result


@pytest.fixture
def block(env):  # noqa: F811
    recorder = Recorder()
    env.monkeypatch.setattr(latest_known, "block_for", recorder)
    return recorder


def sent(fake, call=0):
    return fake.calls[call]["messages"]


def test_the_block_is_a_system_message_right_after_the_question(env, block):
    fake = script(env, [step("好的")])
    result, _ = run("NVDA 怎么样")
    messages = sent(fake)
    asked = next(i for i, m in enumerate(messages) if m.get("role") == "user" and m["content"] == "NVDA 怎么样")
    assert messages[asked + 1] == {"role": "system", "content": BLOCK} and asked + 2 == len(messages)
    assert messages[asked + 1]["content"].startswith("系统最新掌握")
    assert block.calls == [{"text": "NVDA 怎么样", "previous": None, "focus": None, "owner_hash": "o"}]
    assert result["audit"]["latest_known"] == ["NVDA"]
    entries = [e for e in result["audit"]["timeline"] if e["kind"] == "latest_known"]
    assert len(entries) == 1 and entries[0]["symbols"] == ["NVDA"] and isinstance(entries[0]["at_ms"], int)


def test_the_block_comes_after_a_started_skill(env, block):
    skill = {"name": "晨报", "version": 1, "body": "1. 查一查"}
    messages = prompt.build_messages("NVDA", make_context(), [], skill=skill, latest=BLOCK)
    assert [m["role"] for m in messages][-2:] == ["system", "system"] and messages[-1]["content"] == BLOCK
    assert messages[-2]["content"] != BLOCK


def test_the_history_before_the_question_is_the_same_with_and_without_the_block(env):
    history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]
    context = make_context()
    plain = prompt.build_messages("NVDA 怎么样", context, copy.deepcopy(history))
    with_block = prompt.build_messages("NVDA 怎么样", context, copy.deepcopy(history), latest=BLOCK)
    assert with_block[:-1] == plain and with_block[-1] == {"role": "system", "content": BLOCK}
    assert json.dumps(with_block[:-1], sort_keys=True) == json.dumps(plain, sort_keys=True)


def test_a_fact_turn_keeps_the_fact_last(env):
    messages = prompt.build_messages("按钮值", make_context(), [{"role": "user", "content": "AMD 怎么样"}, {"role": "assistant", "content": "卡片"}],
                                     fact="系统事实：已执行", latest=BLOCK)
    assert messages[-1] == {"role": "system", "content": "系统事实：已执行"} and messages[-2]["content"] == BLOCK


def test_the_previous_user_message_and_the_bots_company_are_handed_over(env, block):
    script(env, [step("好的")])
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "英伟达怎么样"},
               {"role": "assistant", "content": "还不错"}, {"role": "user", "content": "那它的现金流呢"}]
    run("那它的现金流呢", make_context(default_company={"symbol": "INTC", "company": "英特尔"}), history)
    assert block.calls[0]["previous"] == "英伟达怎么样" and block.calls[0]["focus"] == "INTC"


def test_notes_after_the_question_are_not_the_previous_message(env, block):
    script(env, [step("好的")])
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "AMD 怎么样"}, {"role": "assistant", "content": "好"},
               {"role": "user", "content": "它呢"}, {"role": "user", "content": "（系统记忆：用户持有 TSLA）"}]
    run("它呢", messages=history)
    assert block.calls[0]["previous"] == "AMD 怎么样"


def test_a_guest_gets_the_block_without_the_owners_holdings(env, block):
    fake = script(env, [step("好的")])
    result, _ = run("NVDA 怎么样", make_context(identity_credential=""))
    assert block.calls[0]["owner_hash"] is None
    assert sent(fake)[-1]["content"] == BLOCK and result["audit"]["latest_known"] == ["NVDA"]


def test_a_replied_option_uses_the_options_text(env, block):
    env.monkeypatch.setattr(press, "read", lambda question, state: press.Press("reply", "rid", None, None, "AMD 的毛利率"))

    async def settle(run, pressed, state):
        return press.Settled(None, None, "succeeded", "replied", reply="AMD 的毛利率")

    env.monkeypatch.setattr(press, "settle", settle)
    fake = script(env, [step("好的")])
    run("reply:rid:0")
    assert block.calls[0]["text"] == "AMD 的毛利率"
    assert sent(fake)[-1]["content"] == BLOCK


def test_a_card_press_uses_the_cards_original_question(env, block):
    env.monkeypatch.setattr(press, "read", lambda question, state: press.Press("confirm", "rid", "tok", None))

    async def settle(run, pressed, state):
        return press.Settled(None, "系统事实：已执行", "succeeded", "executed", report="done")

    env.monkeypatch.setattr(press, "settle", settle)
    fake = script(env, [step("好的")])
    events = []

    async def emit(event):
        events.append(event)

    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "记一笔 AMD 买入"}, {"role": "assistant", "content": "请核对卡片"},
               {"role": "user", "content": "confirm:rid:tok"}]
    asyncio.run(loop.run_turn("confirm:rid:tok", make_context(), emit, history, {"pending_request": {"original_question": "记一笔 AMD 买入"}}))
    assert block.calls[0]["text"] == "记一笔 AMD 买入" and block.calls[0]["previous"] is None
    messages = sent(fake)
    assert messages[-1]["content"] == "系统事实：已执行" and messages[-2]["content"] == BLOCK


def test_the_block_is_never_stored_or_carried_to_the_next_turn(env, block):
    fake = script(env, [step("好的")])
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "NVDA 怎么样"}]
    result, _ = run("NVDA 怎么样", messages=history)
    assert history == [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "NVDA 怎么样"}]
    assert HEADING not in json.dumps({k: v for k, v in result.items() if k != "audit"}, ensure_ascii=False)
    assert HEADING not in json.dumps(result["audit"], ensure_ascii=False)


def test_a_failure_of_the_block_does_not_stop_the_turn(env):
    env.monkeypatch.setattr(latest_known, "block_for", Recorder(failure=RuntimeError("boom")))
    fake = script(env, [step("好的")])
    result, _ = run("NVDA 怎么样")
    assert result["answer"] == "好的" and result["status"] == "succeeded" and "latest_known" not in result["audit"]
    assert not any(m.get("content", "").startswith("系统最新掌握") for m in sent(fake))


def test_no_company_means_no_message_and_no_audit(env):
    env.monkeypatch.setattr(latest_known, "block_for", Recorder(result=(None, [])))
    fake = script(env, [step("好的")])
    result, _ = run("你好")
    assert "latest_known" not in result["audit"] and not any(e["kind"] == "latest_known" for e in result["audit"].get("timeline", []))
    assert sent(fake)[-1] == {"role": "user", "content": "你好"}


def test_the_system_text_says_the_users_words_are_newest():
    text = prompt.SYSTEM
    assert text.count("用户说的情况比你查到的资料更新时") == 1
    sentence = next(line for line in text.splitlines() if "比你查到的资料更新" in line)
    assert sentence.count("。") == 1 and "更权威的来源核实" in sentence



def test_a_repeated_question_takes_the_message_just_before_now(env, block):
    script(env, [step("好的")])
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "英伟达怎么样"}, {"role": "assistant", "content": "a"},
               {"role": "user", "content": "AMD 呢"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "继续"},
               {"role": "assistant", "content": "c"}]
    run("继续", messages=history)
    assert block.calls[0]["previous"] == "继续"
    block.calls.clear()
    script(env, [step("好的")])
    run("继续", messages=[*history, {"role": "user", "content": "继续"}])
    assert block.calls[0]["previous"] == "继续"


def test_a_reply_press_never_takes_a_memory_note_or_catalogue_as_previous(env, block):
    from app.agent_context import CATALOGUE_MARKER, MEMORY_MARKER
    env.monkeypatch.setattr(press, "read", lambda question, state: press.Press("reply", "rid", None, None, "是的"))

    async def settle(run, pressed, state):
        return press.Settled(None, None, "succeeded", "replied", reply="是的")

    env.monkeypatch.setattr(press, "settle", settle)
    script(env, [step("好的")])
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "英伟达怎么样"}, {"role": "assistant", "content": "要看财报吗"},
               {"role": "user", "content": MEMORY_MARKER + " 用户持有 TSLA"}, {"role": "user", "content": CATALOGUE_MARKER + " [1] AMD"}]
    run("reply:rid:0", messages=history)
    assert block.calls[0]["previous"] == "英伟达怎么样"
