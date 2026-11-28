"""Thinking tiers: every turn starts low; the model raises the tier with the kernel's own ``escalate`` tool."""
import json

import pytest

from app.agent_workflow import tools
from app.kernel import loop, prompt, tiers
from tests.test_kernel_loop import call, env, make_context, run, script, step  # noqa: F401  (env is a fixture)


def tool_message(fake, index):
    """The tool message sent to the model in call ``index`` (the last message of that call)."""
    last = fake.calls[index]["messages"][-1]
    assert last["role"] == "tool"
    return json.loads(last["content"])


def test_every_turn_starts_low_whatever_the_bot_says(env):
    fake = script(env, [step(text="好")])
    run(context=make_context(reasoning_effort="high"))
    assert fake.calls[0]["kwargs"]["reasoning_effort"] == "low"


def test_escalate_changes_effort_from_the_next_step(env):
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="high"))
    assert [c["kwargs"]["reasoning_effort"] for c in fake.calls] == ["low", "high"]
    assert result["audit"]["tier"] == "high" and result["audit"]["escalated"] is True
    assert result["final_protocol"]["tier"] == "high"
    assert tool_message(fake, 1) == {"ok": True, "tier": "high", "note": "已切换到 high 档，请继续。之后只是查资料的步骤按 low 档跑，判断和写回答都在 high 档。"}


@pytest.mark.parametrize("stored", ["low", "medium", "minimal", "none", None])
def test_a_bots_stored_effort_is_not_a_ceiling(env, stored):
    """How hard to think is the model's call (owner 11-22): an effort a bot still carries from the old picker changes nothing (11-28)."""
    env.monkeypatch.delenv("FINBOT_KERNEL_TOP_TIER", raising=False)
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort=stored))
    assert [c["kwargs"]["reasoning_effort"] for c in fake.calls] == ["low", "high"]
    assert result["audit"]["tier"] == "high" and result["audit"]["escalated"] is True


def test_the_servers_top_tier_is_the_only_ceiling(env):
    env.monkeypatch.setenv("FINBOT_KERNEL_TOP_TIER", "mid")
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="high"))
    assert fake.calls[1]["kwargs"]["reasoning_effort"] == "medium"
    assert result["audit"]["tier"] == "mid"
    assert tool_message(fake, 1)["note"] == "服务器设置的上限是 mid 档，已按 mid 档继续。之后只是查资料的步骤按 low 档跑，判断和写回答都在 mid 档。"


@pytest.mark.parametrize("args", [{"depth": "low"}, {"depth": "ultra"}, {}, "not json"])
def test_bad_depth_is_invalid_arguments(env, args):
    fake = script(env, [step(calls=[call("c1", "escalate", args)]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="high"))
    assert tool_message(fake, 1)["error_code"] == "invalid_arguments"
    assert result["audit"]["tier"] == "low" and fake.calls[1]["kwargs"]["reasoning_effort"] == "low"


def test_tier_never_goes_down(env):
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]),
                        step(calls=[call("c2", "escalate", {"depth": "mid"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="high"))
    assert [c["kwargs"]["reasoning_effort"] for c in fake.calls] == ["low", "high", "high"]
    assert result["audit"]["tier"] == "high"


def test_escalate_is_always_last_in_the_tool_list_and_never_invoked_through_tools(env):
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "mid"}), call("c2", "query_financials", {"symbol": "AAPL"})]),
                        step(text="好")])
    result, events = run(context=make_context(reasoning_effort="low"))
    assert all(c["tools"][-1] == "escalate" and c["tools"].count("escalate") == 1 for c in fake.calls)
    assert fake.calls[0]["tools"] == fake.calls[1]["tools"]
    assert [name for name, _ in env.invoked] == ["query_financials"]
    assert len(result["citations"]) == 1       # only the read made a citation
    # Results come back in call order, escalate first.
    sent = fake.calls[1]["messages"][-2:]
    assert [m["tool_call_id"] for m in sent] == ["c1", "c2"]


def test_ceiling_and_clamp_tables(monkeypatch):
    monkeypatch.delenv("FINBOT_KERNEL_TOP_TIER", raising=False)
    assert tiers.ceiling() == "high"
    for value, top in (("low", "low"), ("MID", "mid"), ("high", "high"), ("max", "high"), ("", "high")):
        monkeypatch.setenv("FINBOT_KERNEL_TOP_TIER", value)
        assert tiers.ceiling() == top
    assert tiers.clamp("high", "mid") == "mid"
    assert tiers.clamp("mid", "high") == "mid"


def test_no_escalation_reports_low(env):
    result, _ = run_direct(env)
    assert result["audit"]["tier"] == "low" and result["audit"]["escalated"] is False
    assert result["final_protocol"]["tier"] == "low"


def test_system_prompt_ends_the_how_to_section_with_the_fast_tier_and_say_lines():
    assert prompt.FAST_TIER_LINE in prompt.SYSTEM
    how, _, rest = prompt.SYSTEM.partition("\n\n怎么说话")
    assert how.endswith(prompt.FAST_TIER_LINE + "\n" + prompt.SAY_LINE) and rest
    assert prompt.SAY_LINE.endswith("切换到 high 档后，先用 plan 列出清单，再逐项去做；之后每次调用工具时在 item 里写上这是清单的第几项，勾由系统来打。")


def run_direct(env):
    script(env, [step(text="好")])
    return run()


def test_tier_event_only_when_the_tier_rises(env):
    script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]), step(calls=[call("c2", "escalate", {"depth": "high"})]), step(text="好")])
    _, events = run(context=make_context(reasoning_effort="high"))
    assert [e for e in events if e["event"] == "tier"] == [{"event": "tier", "tier": "high"}]
    env.monkeypatch.setenv("FINBOT_KERNEL_TOP_TIER", "low")      # a turn held at low by the server never rises
    script(env, [step(calls=[call("c3", "escalate", {"depth": "high"})]), step(text="好")])
    _, events = run(context=make_context(reasoning_effort="high"))
    assert not [e for e in events if e["event"] == "tier"]
    env.monkeypatch.delenv("FINBOT_KERNEL_TOP_TIER")
    script(env, [step(calls=[call("c4", "escalate", {"depth": "mid"})]), step(calls=[call("c5", "escalate", {"depth": "high"})]), step(text="好")])
    _, events = run(context=make_context(reasoning_effort="high"))
    assert [e["tier"] for e in events if e["event"] == "tier"] == ["mid", "high"]


# --- design 4.4: 「查资料的步骤始终用低档，不管最后由哪一档来写」 ------------------------------------------------------------------

def _efforts(fake):
    return [c["kwargs"]["reasoning_effort"] for c in fake.calls]


def test_after_going_up_lookups_run_low_and_the_answer_is_written_high(env):
    env.monkeypatch.delenv("FINBOT_KERNEL_LOOKUP_TIER", raising=False)
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]),
                        step(calls=[call("c2", "query_financials", {"symbol": "AAPL"})]),       # high's own first move
                        step(calls=[call("c3", "query_stock_prices", {"symbol": "AAPL"})]),     # a low try: only a lookup, kept
                        step(text="草稿"),                                                       # a low try that wants to write: dropped
                        step(text="正式回答")])                                                  # the same step at high
    result, events = run(context=make_context())
    assert _efforts(fake) == ["low", "high", "low", "low", "high"]
    assert [name for name, _ in env.invoked] == ["query_financials", "query_stock_prices"]
    assert result["answer"] == "正式回答"
    assert "草稿" not in "".join(e.get("text", "") for e in events if e.get("event") == "delta")      # never on the screen
    assert result["audit"]["lookup_steps"] == 1 and result["audit"]["lookup_redone"] == 1
    assert [c["tier"] for c in result["audit"]["calls"]] == ["low", "high", "low", "low", "high"]
    assert result["audit"]["tier"] == "high"


def test_a_low_try_that_wants_anything_but_lookups_is_made_again_at_the_turns_tier(env):
    env.monkeypatch.delenv("FINBOT_KERNEL_LOOKUP_TIER", raising=False)
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "mid"})]),
                        step(calls=[call("c2", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[call("c3", "query_stock_prices", {"symbol": "AAPL"}), call("c4", "plan", {"items": ["a"]})]),
                        step(text="好")])
    result, _ = run(context=make_context())
    assert _efforts(fake) == ["low", "medium", "low", "medium"]
    assert [name for name, _ in env.invoked] == ["query_financials"]       # the dropped try ran nothing
    assert result["audit"]["lookup_redone"] == 1 and "lookup_steps" not in result["audit"]


def test_lookup_tier_same_keeps_every_step_at_the_turns_tier(env):
    env.monkeypatch.setenv("FINBOT_KERNEL_LOOKUP_TIER", "same")
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]),
                        step(calls=[call("c2", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    result, _ = run(context=make_context())
    assert _efforts(fake) == ["low", "high", "high"]
    assert tool_message(fake, 1)["note"] == "已切换到 high 档，请继续。"


def test_a_turn_that_stays_low_makes_no_extra_calls(env):
    env.monkeypatch.delenv("FINBOT_KERNEL_LOOKUP_TIER", raising=False)
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    run(context=make_context())
    assert _efforts(fake) == ["low", "low"]


def test_lookup_tier_setting():
    import os
    for value, expected in (("", "low"), ("mid", "mid"), ("same", None), ("bogus", "low")):
        os.environ["FINBOT_KERNEL_LOOKUP_TIER"] = value
        assert tiers.lookup_tier() == expected
    os.environ.pop("FINBOT_KERNEL_LOOKUP_TIER")
