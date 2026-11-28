"""Stage 6a: a scheduled run (``context.unattended``) and a guest's turn on the kernel.

A scheduled run has nobody to ask and nobody to press a card: no ``ask``, no ``search_x``; ``act`` puts every proposal in the owner's
inbox (the runner's ``action_sink``) and runs nothing at once; ``notify_telegram`` sends him a message when its instruction says so.
A guest is told what only the owner can do.  No network, no database.
"""
import json

import pytest

from app import agent_telegram as telegram
from app.kernel import act, loop, notify, prompt
from tests.test_kernel_loop import (TOKEN, act_call, call, env, fake_consent, make_context, run, script, step,  # noqa: F401
                                    tool_results)


def routine(sink=None, **extra):
    return make_context(conversation_id="conv", unattended=True, action_sink=sink, bot_id=None, **extra)


def test_a_scheduled_run_is_offered_act_and_notify_but_not_ask_or_search_x(env, monkeypatch):
    monkeypatch.setattr(loop.x_search, "configured", lambda: True)
    fake = script(env, [step(text="无新消息")])
    run(context=routine([]))
    offered = fake.calls[0]["tools"]
    assert "act" in offered and notify.NOTIFY in offered
    assert "ask" not in offered and "search_x" not in offered and "handle_message" not in offered


def test_a_live_owner_turn_keeps_ask_and_gets_no_notify(env, monkeypatch):
    monkeypatch.setattr(loop.x_search, "configured", lambda: True)
    fake = script(env, [step(text="好")])
    run(context=make_context(conversation_id="conv"))
    offered = fake.calls[0]["tools"]
    assert "ask" in offered and "search_x" in offered and notify.NOTIFY not in offered


def test_a_scheduled_run_puts_a_proposal_in_the_inbox_and_makes_no_card(env, fake_consent):
    sink = []
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="建议给 AAPL 做一份新预测")])
    result, _ = run(context=routine(sink))
    assert fake_consent.proposed == [] and fake_consent.executed == []
    (row,) = tool_results(fake)
    assert row["data"][0]["status"] == "queued_for_owner_review" and "待你确认" in row["data"][0]["note"]
    (item,) = sink
    assert item["operation"]["name"] == "forecast" and item["operation"]["arguments"]["symbol"] == "AAPL"
    assert item["display"]["title"].startswith(loop.SUGGESTION_TITLE) and item["display"]["agent_suggestion"] is True
    assert item["question"] == "问题"
    assert result["pending_request"] is None and result["audit"]["write_outcome"] == "queued_for_owner"
    assert TOKEN not in json.dumps(sink)


def test_a_scheduled_run_never_runs_tier_one_at_once(env, fake_consent):
    sink = []
    script(env, [step(calls=[act_call("c1", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="建议加进研究队列")])
    result, _ = run(context=routine(sink))
    assert fake_consent.executed == [] and fake_consent.reversible == []
    assert [item["operation"]["name"] for item in sink] == ["add_to_research_queue"]
    assert result["audit"]["writes"] == [{"operation": "add_to_research_queue", "tier": 1, "outcome": "proposed"}]


def test_a_scheduled_run_without_an_inbox_says_the_proposal_was_not_kept(env, fake_consent):
    script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="建议做预测")])
    result, _ = run(context=routine(None))
    assert fake_consent.proposed == []
    assert result["answer"].endswith(loop.NO_INBOX)


def test_a_revision_that_needs_picks_is_refused_in_a_scheduled_run(env, fake_consent, monkeypatch):
    async def picking(run_, name, arguments):
        return act.Prepared(operation={"name": name, "arguments": dict(arguments)}, display={"title": "修订预测"}, tier=3,
                            options=[{"id": "m1", "label": "新财报"}])

    monkeypatch.setattr(act, "prepare", picking)
    sink = []
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="建议修订")])
    result, _ = run(context=routine(sink))
    (row,) = tool_results(fake)
    assert row["error_code"] == "unattended_needs_owner" and "放不进收件箱" in row["hint"]
    assert sink == [] and fake_consent.proposed == []
    assert result["audit"]["writes"][0]["outcome"] == "refused:unattended_needs_owner"


def test_notify_queues_the_message_with_this_turns_citations(env, monkeypatch):
    sent = []

    def fake_notify(owner, bot_id, text, evidence_ids, citations):
        sent.append((owner, bot_id, text, evidence_ids, [c["ordinal"] for c in citations]))
        return {"status": "queued_for_telegram", "remaining_today": 4}

    monkeypatch.setattr(telegram, "notify", fake_notify)
    fake = script(env, [step(calls=[call("r1", "query_sec_filings", {"symbol": "AAPL"})]),
                        step(calls=[call("n1", notify.NOTIFY, {"text": "苹果有新公告 [1]", "evidence_ids": [1]})]), step(text="已通知")])
    result, _ = run(context=routine([]))
    assert sent == [("o", None, "苹果有新公告 [1]", [1], [1])]
    assert tool_results(fake)[-1]["data"][0]["status"] == "queued_for_telegram"
    assert result["audit"]["telegram"] == "queued" and result["audit"]["telegram_sent"] == 1


def test_a_refused_notify_is_given_back_to_the_model(env, monkeypatch):
    def refuse(*args, **kwargs):
        raise telegram.NotifyError("unsupported_number")

    monkeypatch.setattr(telegram, "notify", refuse)
    fake = script(env, [step(calls=[call("n1", notify.NOTIFY, {"text": "涨了 5%"})]), step(text="好")])
    result, _ = run(context=routine([]))
    assert tool_results(fake)[0]["error_code"] == "unsupported_number"
    assert result["audit"]["telegram"] == "refused:unsupported_number"


def test_ask_and_notify_outside_what_was_offered_are_refused(env, monkeypatch):
    called = []
    monkeypatch.setattr(telegram, "notify", lambda *a, **k: called.append(a))
    fake = script(env, [step(calls=[call("a1", "ask", {"question": "要哪家？"})]), step(text="好")])
    result, _ = run(context=routine([]))
    assert tool_results(fake)[0]["error_code"] == "tool_not_in_bot_scope" and result["pending_request"] is None
    fake = script(env, [step(calls=[call("n1", notify.NOTIFY, {"text": "你好"})]), step(text="好")])
    run(context=make_context(conversation_id="conv"))
    assert tool_results(fake)[0]["error_code"] == "tool_not_in_bot_scope" and called == []


@pytest.mark.parametrize("kind", ["routine", "live", "guest"])
def test_the_prompt_says_which_kind_of_turn_this_is(env, monkeypatch, kind):
    if kind == "guest":
        monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: False)
        monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="好")])
    run(context=routine([]) if kind == "routine" else make_context(conversation_id="conv"))
    system = fake.calls[0]["messages"][0]["content"]
    assert (prompt.UNATTENDED_NOTE in system) == (kind == "routine")
    assert (prompt.GUEST_NOTE in system) == (kind == "guest")
