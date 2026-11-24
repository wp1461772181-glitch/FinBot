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
    assert tool_message(fake, 1) == {"ok": True, "tier": "high", "note": "已切换到 high 档，请继续。"}


def test_escalate_is_clamped_to_the_bot_ceiling(env):
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "high"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="medium"))
    assert fake.calls[1]["kwargs"]["reasoning_effort"] == "medium"
    assert result["audit"]["tier"] == "mid"
    message = tool_message(fake, 1)
    assert message["tier"] == "mid" and "最高只到" in message["note"]
    assert message["note"] == "这个助手最高只到 mid 档，已按 mid 档继续。"


def test_bot_ceiling_low_never_escalates(env):
    fake = script(env, [step(calls=[call("c1", "escalate", {"depth": "mid"})]), step(text="好")])
    result, _ = run(context=make_context(reasoning_effort="low"))
    assert result["audit"]["tier"] == "low" and result["audit"]["escalated"] is False
    assert fake.calls[1]["kwargs"]["reasoning_effort"] == "low"
    assert tool_message(fake, 1)["tier"] == "low"


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


def test_ceiling_and_clamp_tables():
    assert tiers.ceiling(None) == "high"
    assert tiers.ceiling("low") == "low"
    assert tiers.ceiling("medium") == "mid"
    assert tiers.ceiling("max") == "high"
    assert tiers.ceiling("none") == "low"
    assert tiers.ceiling("minimal") == "low"
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


def run_direct(env):
    script(env, [step(text="好")])
    return run()
