"""Thinking tiers: every turn starts low; the model raises the tier with the kernel's own ``escalate`` tool."""
import json

import pytest

from app.agent_workflow import tools
from app.agent_workflow.tools import invoke as REAL_INVOKE
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
    assert tool_message(fake, 1)["note"] == "服务器设置的上限是 mid 档，已按 mid 档继续。"


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


def test_open_page_is_offered_and_opens_a_settings_page_with_its_link(env):
    """Design 4.2: a key or a token he puts in himself; the kernel can still open that page for him (on a bridge: the link)."""
    env.monkeypatch.delenv("FINBOT_WEB_URL", raising=False)
    env.monkeypatch.setattr(tools, "invoke", REAL_INVOKE)          # the real tool: it emits the client action and writes the link
    fake = script(env, [step(calls=[call("c1", "open_page", {"page": "settings_models"})]), step(text="已经替你打开了模型设置页。")])
    result, events = run(context=make_context(executor=None))
    assert "open_page" in fake.calls[0]["tools"]
    [action] = [e for e in events if e.get("event") == "client_action"]
    assert action["action"] == "open_page" and action["page"] == "settings_models"
    sent = tool_message(fake, 1)
    assert sent["data"][0]["link"] == "https://finbotai.me/#/settings/models"


def test_an_opened_page_is_not_a_source_and_a_guest_is_not_offered_it(env):
    """Review 11-28: the result of open_page was numbered as a source [n] and counted as a read; a guest has no settings to open."""
    env.monkeypatch.setattr(tools, "invoke", REAL_INVOKE)
    fake = script(env, [step(calls=[call("c1", "open_page", {"page": "settings_models"})]), step(text="好")])
    result, _ = run(context=make_context(executor=None))
    assert result["citations"] == [] and tool_message(fake, 1)["data"][0]["page"] == "settings_models"
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    guest = script(env, [step(text="好")])
    run(context=make_context(executor=None))
    assert "open_page" not in guest.calls[0]["tools"]
