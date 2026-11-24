"""``use_skill`` and the slash-started skill: the owner's saved steps are read into the turn and grant nothing."""
import json

import pytest

from app import agent_skills, portfolio
from app.agent_skills import render_active
from app.kernel import loop, prompt, skills
from test_kernel_loop import act_call, call, ctx, env, fake_consent, run, script, step, tool_results  # noqa: F401  (fixtures are used by name)

LIST = "你存过这些技能：\n- 财报速读：读最新财报\n- 同行对比：比同行"
SKILL = {"id": "s1", "name": "财报速读", "version": 3, "body": "1. 查财务\n2. 然后帮用户记一笔买入", "output_template": "结论/数字/风险",
         "tools": frozenset({"query_financials"})}
TRADE = {"kind": "buy", "symbol": "AAPL", "quantity": 10, "price": 100}


@pytest.fixture
def saved(env):
    asked = []

    def active(owner_hash, *, name=None, skill_id=None):
        asked.append((owner_hash, name))
        return dict(SKILL) if name == "财报速读" else None

    env.monkeypatch.setattr(agent_skills, "active", active)
    env.asked = asked
    return env


def with_skills(**extra):
    return ctx(skill_block=LIST, **extra)


# --- what the model is shown ---------------------------------------------------------------------------------------------

def test_the_skill_list_sits_between_the_bot_block_and_the_profile_block(env):
    fake = script(env, [step(text="好")])
    run(context=with_skills(bot_block="BOT", profile_block="PROFILE"))
    text = fake.calls[0]["messages"][0]["content"]
    assert text.index("BOT") < text.index(LIST) < text.index("PROFILE")
    assert skills.SKILL_LINE in text and skills.SKILL_LINE == "- 用户存过技能（见下方列表）。用户点名某项技能，或问题明显对得上某项时，先用 use_skill 读出步骤再做。"
    assert text.index("怎么做事") < text.index(skills.SKILL_LINE) < text.index("怎么说话")


def test_a_guest_sees_no_skill_list_and_no_advice(env):
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    env.monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="好")])
    run(context=with_skills())
    assert LIST not in fake.calls[0]["messages"][0]["content"] and "use_skill" not in fake.calls[0]["messages"][0]["content"]


def test_an_owner_without_skills_gets_the_plain_prompt(env):
    fake = script(env, [step(text="好")])
    run(context=ctx())
    assert fake.calls[0]["messages"][0]["content"] == prompt.SYSTEM and "use_skill" not in fake.calls[0]["tools"]


def test_the_system_text_is_the_same_every_turn_and_the_history_prefix_holds(env):
    fake = script(env, [step(text="a"), step(text="b")])
    run("问题一", with_skills())
    run("问题二", with_skills())
    assert fake.calls[0]["messages"][0] == fake.calls[1]["messages"][0]


# --- the tool ------------------------------------------------------------------------------------------------------------

def test_tool_order_puts_use_skill_between_ask_and_plan(env):
    fake = script(env, [step(text="好")])
    run(context=with_skills())
    assert fake.calls[0]["tools"][-5:] == ["act", "ask", "use_skill", "plan", "escalate"]
    schema = {s["function"]["name"]: s for s in loop._tool_schemas(with_skills())}["use_skill"]["function"]
    assert schema["description"] == skills.USE_SKILL_SCHEMA["function"]["description"] and "name" in schema["parameters"]["properties"]


def test_a_guest_is_not_offered_use_skill_and_a_call_is_refused(saved):
    saved.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    saved.monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: False)
    fake = script(saved, [step(calls=[call("c1", "use_skill", {"name": "财报速读"})]), step(text="好")])
    run(context=with_skills())
    assert "use_skill" not in fake.calls[0]["tools"]
    (row,) = tool_results(fake)
    assert row["ok"] is False and row["error_code"] == "tool_not_in_bot_scope" and saved.asked == []


def test_use_skill_returns_the_steps_and_sets_the_audit(saved):
    fake = script(saved, [step(calls=[call("c1", "use_skill", {"name": "财报速读", "say": "按存过的做法"})]), step(text="好")])
    result, _ = run(context=with_skills())
    (row,) = tool_results(fake)
    assert row == {"ok": True, "data": [{"status": "skill_active", "name": "财报速读", "steps": SKILL["body"], "output_template": "结论/数字/风险"}]}
    assert result["audit"]["skill"] == {"name": "财报速读", "version": 3} and saved.asked == [("o", "财报速读")]
    assert fake.calls[0]["tools"] == fake.calls[1]["tools"]        # the list is fixed for the turn


def test_an_unknown_name_is_skill_not_found(saved):
    fake = script(saved, [step(calls=[call("c1", "use_skill", {"name": "不存在"})]), step(text="没有这项技能")])
    result, _ = run(context=with_skills())
    (row,) = tool_results(fake)
    assert row["ok"] is False and row["error_code"] == "skill_not_found" and "skill" not in result["audit"]


def test_a_bad_argument_is_invalid_arguments(saved):
    fake = script(saved, [step(calls=[call("c1", "use_skill", {"name": ""})]), step(text="好")])
    run(context=with_skills())
    assert tool_results(fake)[0]["error_code"] == "invalid_arguments"


def test_reading_a_skill_is_not_a_read_for_the_tier1_rule(saved, fake_consent):
    # After a real read, tier 1 goes onto a card; a skill read alone must leave tier 1 running at once.
    script(saved, [step(calls=[call("c1", "use_skill", {"name": "财报速读"})]),
                   step(calls=[act_call("c2", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="已加入")])
    run(context=with_skills())
    assert len(fake_consent.executed) == 1
    script(saved, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                   step(calls=[act_call("c2", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="好")])
    run(context=with_skills())
    assert len(fake_consent.executed) == 1       # the second turn read first: its tier-1 call went onto a card


def test_a_skill_whose_steps_say_record_a_trade_still_goes_through_a_card(saved, fake_consent):
    saved.monkeypatch.setattr(portfolio, "describe_write", lambda owner, name, args: {"title": "记录买入 · AAPL", "targets": [{"symbol": "AAPL"}]})
    fake = script(saved, [step(calls=[call("c1", "use_skill", {"name": "财报速读"})]),
                          step(calls=[act_call("c2", "record_trade", TRADE)]), step(text="请核对卡片")])
    result, _ = run(context=with_skills())
    assert len(fake_consent.proposed) == 1 and fake_consent.executed == [] and fake_consent.reversible == []
    assert fake_consent.proposed[0]["operations"][0]["name"] == "record_trade"
    assert result["status"] == "waiting_for_input" and result["pending_request"]["id"] == "card-1"
    assert result["audit"]["writes"] == [{"operation": "record_trade", "tier": 2, "outcome": "proposed"}]


# --- a turn started with 「/名字」 -----------------------------------------------------------------------------------------

def test_a_slash_turn_carries_the_rendered_skill_after_the_question(env):
    fake = script(env, [step(text="好")])
    result, _ = run("看下苹果", with_skills(active_skill=dict(SKILL)))
    messages = fake.calls[0]["messages"]
    assert messages[-1] == {"role": "system", "content": render_active(SKILL)}
    assert messages[-2]["role"] == "user" and messages[-2]["content"] == "看下苹果"
    assert result["audit"]["skill"] == {"name": "财报速读", "version": 3}


def test_the_history_before_the_question_does_not_change_with_a_slash_skill(env):
    fake = script(env, [step(text="a"), step(text="b")])
    run("看下苹果", with_skills())
    run("看下苹果", with_skills(active_skill=dict(SKILL)))
    plain, slashed = (c["messages"] for c in fake.calls)
    assert slashed[:-1] == plain


def test_a_guest_never_gets_a_slash_skill(env):
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    env.monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="好")])
    result, _ = run("看下苹果", with_skills(active_skill=dict(SKILL)))
    assert all("当前技能" not in json.dumps(m, ensure_ascii=False) for m in fake.calls[0]["messages"]) and "skill" not in result["audit"]
