"""Kernel backup model: when the model fails after its one retry, the turn goes on with the model the owner named.

No network: ``stream_decision`` is a script that also records which provider, key and base URL each call used.
"""
import asyncio
import copy
import json

import pytest

import app.agent_chat_provider as provider
from app import agent_model_catalog as catalog
from app import anthropic_native
from app import agent_model_roles as roles
from app.agent_chat_models import AgentModelEntry, AgentModelRole
from app.database import SessionLocal
from app.kernel import loop
from test_kernel_loop import TOKEN, act_call, call, ctx, env, fake_consent, kinds, make_context, step  # noqa: F401  (env, fake_consent are used by name)
from test_kernel_press import FakeCards, cards, pending_card, pressed, turn  # noqa: F401  (cards is used by name)
from tests.test_agent_bots import KEY_A, OWNER_HASH, owner  # noqa: F401  (fixture)

BACKUP = {"name": "reserve", "provider": "openrouter", "model": "backup-model", "api_key": "backup-key-123",
          "base_url": "https://backup.example/v1", "context_window": 100000}
LABEL = "\n\n（这条由备用模型「reserve」回答。）"


def timeout():
    return provider.ProviderFailure("provider_timeout", stage="decision", retryable=True)


class Script:
    """Answers from a script per model: ``steps`` for the primary ("m"), ``backup`` for the backup model."""

    def __init__(self, steps, backup=()):
        self.steps, self.backup_steps, self.calls = list(steps), list(backup), []

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        self.calls.append({"provider": provider_name, "model": model, "key": api_key, "base_url": kwargs.get("base_url"),
                           "messages": copy.deepcopy(messages), "effort": kwargs.get("reasoning_effort"), "tools": [s["function"]["name"] for s in schemas]})
        item = (self.backup_steps if model == BACKUP["model"] else self.steps).pop(0)
        if isinstance(item, BaseException):
            raise item
        for piece in item["pieces"]:
            await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": item["text"], **item.get("extra", {})}
        if item["calls"]:
            message["tool_calls"] = item["calls"]
        return {"usage": item["usage"]}, message

    def on(self, model):
        return [c for c in self.calls if c["model"] == model]


def with_reasoning(item):
    return {**item, "extra": {"reasoning_content": "thinking of the primary", "reasoning_details": [{"x": 1}]}}


@pytest.fixture
def backup(env):
    """The owner has named a backup model; ``scripted(...)`` installs the script."""
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    env.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: dict(BACKUP))
    env.lookups = []

    def scripted(steps, backup_steps=()):
        fake = Script(steps, backup_steps)
        env.monkeypatch.setattr(provider, "stream_decision", fake)
        return fake

    env.scripted = scripted
    return env


def run_turn(context=None, question="问题"):
    events = []

    async def emit(event):
        events.append(event)

    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": question}]
    result = asyncio.run(loop.run_turn(question, context or make_context(), emit, history, {}))
    return result, events


# --- the role -----------------------------------------------------------------------------------------------------

@pytest.fixture
def two_models(owner):
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.commit()
    for name in ("alpha", "bravo"):
        catalog.save_entry(name, display_name=name, provider="deepseek", model=f"m-{name}", api_key=KEY_A,
                           is_default=name == "alpha", create=True)
    yield owner
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()


def test_roles_list_has_fallback_and_it_has_no_default(two_models):
    assert "fallback" in roles.ROLES and roles.all_roles(OWNER_HASH)["fallback"] is None
    assert roles.fallback_for(OWNER_HASH) is None            # unset is not "the server default"
    roles.set_role(OWNER_HASH, "fallback", "bravo")
    assert roles.fallback_for(OWNER_HASH)["name"] == "bravo" and roles.fallback_for(OWNER_HASH)["model"] == "m-bravo"
    roles.set_role(OWNER_HASH, "fallback", None)
    assert roles.fallback_for(OWNER_HASH) is None


def test_fallback_for_ignores_an_entry_that_left_the_catalog(two_models):
    roles.set_role(OWNER_HASH, "fallback", "bravo")
    catalog.delete_entry("bravo")
    assert roles.get(OWNER_HASH, "fallback") == "bravo"      # the row stays; nothing is silently substituted
    assert roles.fallback_for(OWNER_HASH) is None


# --- the switch ---------------------------------------------------------------------------------------------------

def test_primary_failure_hands_over_to_the_backup(backup):
    two = [call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "query_financials", {"symbol": "MSFT"})]
    fake = backup.scripted([with_reasoning(step(calls=two)), timeout(), timeout()], [step(pieces=["收入", "100"], text="收入100")])
    result, events = run_turn()
    assert len(backup.invoked) == 2                          # each tool ran once
    assert [c["model"] for c in fake.calls] == ["m", "m", "m", BACKUP["model"]]
    handed = fake.on(BACKUP["model"])[0]["messages"]
    assert [m["role"] for m in handed[-3:]] == ["assistant", "tool", "tool"]
    assert handed[-3]["tool_calls"] == two and not any(k.startswith("reasoning_") for m in handed for k in m)
    assert any(k.startswith("reasoning_") for k in fake.on("m")[1]["messages"][-3])      # the primary still had them
    sentence = "主模型这一步没有成功，改用备用模型「reserve」继续。"
    assert {"event": "narration", "text": sentence, "system": True} in events
    assert sentence in result["final_protocol"]["narration"]
    assert result["answer"] == "收入100" + LABEL and result["status"] == "succeeded"
    assert result["final_protocol"]["fallback_model"] == "reserve"
    assert result["audit"]["fallback"] == {"from": "anthropic/m", "to": "reserve", "reason": "provider_timeout"}
    assert [c["model"] for c in result["audit"]["calls"]] == ["anthropic/m", "reserve"]
    for secret in (BACKUP["api_key"], "k"):          # the fake backup's and the primary's actual keys
        assert f'"{secret}"' not in json.dumps([result["audit"], result["final_protocol"], events])
    assert BACKUP["api_key"] not in json.dumps(result)


def test_backup_is_called_with_its_own_provider_key_and_base_url(backup):
    fake = backup.scripted([timeout(), timeout()], [step(text="好")])
    run_turn(make_context(reasoning_effort="high"))
    first, last = fake.calls[0], fake.calls[-1]
    assert (first["provider"], first["key"], first["base_url"]) == ("anthropic", "k", None)
    assert (last["provider"], last["model"], last["key"], last["base_url"]) == ("openrouter", "backup-model", "backup-key-123", "https://backup.example/v1")
    assert last["effort"] == first["effort"] and last["tools"] == first["tools"]


def test_no_backup_fails_as_today(backup):
    backup.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: None)
    fake = backup.scripted([timeout(), timeout()])
    with pytest.raises(provider.ProviderFailure) as raised:
        run_turn()
    assert raised.value.detail == "provider_timeout" and len(fake.calls) == 2


def test_backup_equal_to_primary_fails_as_today(backup):
    backup.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: {**BACKUP, "provider": "anthropic", "model": "m"})
    fake = backup.scripted([timeout(), timeout()])
    with pytest.raises(provider.ProviderFailure) as raised:
        run_turn()
    assert raised.value.detail == "provider_timeout" and len(fake.calls) == 2


def test_a_lookup_that_breaks_fails_as_today(backup):
    def broken(owner_hash):
        raise RuntimeError("database is down")

    backup.monkeypatch.setattr(loop.roles, "fallback_for", broken)
    backup.scripted([timeout(), timeout()])
    with pytest.raises(provider.ProviderFailure):
        run_turn()


def test_backup_failing_too_fails_the_turn(backup):
    ours = Script([timeout(), timeout()], [timeout(), timeout()])
    backup.monkeypatch.setattr(provider, "stream_decision", ours)
    audits = []
    original = loop._Run

    def spy(*args, **kwargs):
        audits.append(original(*args, **kwargs))
        return audits[-1]

    backup.monkeypatch.setattr(loop, "_Run", spy)
    with pytest.raises(provider.ProviderFailure) as raised:
        run_turn()
    assert raised.value.detail == "provider_timeout" and len(ours.calls) == 4         # each model: its call and its one retry
    assert audits[0].audit["fallback"] == {"from": "anthropic/m", "to": "reserve", "reason": "provider_timeout", "failed": True}


def test_next_turn_starts_on_the_primary(backup):
    fake = backup.scripted([timeout(), timeout(), step(text="主模型回答")], [step(text="备用回答")])
    first, _ = run_turn()
    second, events = run_turn()
    assert first["answer"].endswith(LABEL) and second["answer"] == "主模型回答"
    assert fake.calls[-1]["model"] == "m" and "fallback" not in second["audit"] and "fallback_model" not in second["final_protocol"]
    assert not any(e.get("system") for e in events)


def test_the_backup_stays_for_the_rest_of_the_turn(backup):
    fake = backup.scripted([timeout(), timeout()], [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="完")])
    result, _ = run_turn()
    assert [c["model"] for c in fake.calls[2:]] == [BACKUP["model"], BACKUP["model"]] and result["answer"] == "完" + LABEL


def test_cancellation_is_not_a_failure(backup):
    fake = backup.scripted([asyncio.CancelledError()], [step(text="不该到这里")])
    with pytest.raises(asyncio.CancelledError):
        run_turn()
    assert fake.on(BACKUP["model"]) == []


def test_partial_text_of_the_failed_step_is_reset_not_repeated(backup):
    class Cut(Script):
        async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
            if model == "m":
                await kwargs["on_text"]("半句")
                raise timeout()
            return await super().__call__(provider_name, model, api_key, messages, schemas, **kwargs)

    cut = Cut([], [step(text="整句")])
    backup.monkeypatch.setattr(provider, "stream_decision", cut)
    result, events = run_turn()
    assert kinds(events).count("answer_reset") == 2          # one per failed attempt
    tail = events[[i for i, e in enumerate(events) if e["event"] == "answer_reset"][-1] + 1:]
    assert "".join(e["text"] for e in tail if e["event"] == "delta") == result["answer"] == "整句" + LABEL


def test_label_is_part_of_the_stored_answer(backup):
    backup.scripted([timeout(), timeout()], [step(pieces=["看", "[9]"], text="看[9]")])    # a marker with no source is cleaned away
    result, events = run_turn()
    after = events[[i for i, e in enumerate(events) if e["event"] == "answer_reset"][-1] + 1:] if "answer_reset" in kinds(events) else events
    assert "".join(e["text"] for e in after if e["event"] == "delta") == result["answer"]
    assert result["answer"].endswith(LABEL) and result["answer"].count("这条由备用模型") == 1
    assert [e["text"] for e in events if e["event"] == "delta"].count(LABEL) == 1


def test_label_is_added_once_when_the_answer_streamed_clean(backup):
    backup.scripted([timeout(), timeout()], [step(pieces=["好"], text="好")])
    result, events = run_turn()
    assert [e["text"] for e in events if e["event"] == "delta"] == ["好", LABEL] and result["answer"] == "好" + LABEL


def test_post_press_report_is_not_labelled(cards, backup):
    backup.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    fake = Script([timeout(), timeout()], [timeout(), timeout()])
    backup.monkeypatch.setattr(provider, "stream_decision", fake)
    card = pending_card(cards)
    result, events = turn(f"confirm:{TOKEN}", pressed(card))
    assert result["answer"] == "已执行：生成研究预测。" and result["audit"]["report"] == "fallback"
    assert "备用模型" not in result["answer"] and events[-1] == {"event": "delta", "text": "已执行：生成研究预测。"}
    assert result["audit"]["fallback"]["failed"] is True


def test_signed_anthropic_thinking_is_dropped_but_the_calls_and_text_stay(backup):
    calls = [call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "query_financials", {"symbol": "MSFT"})]
    blocks = [{"type": "thinking", "thinking": "hm", "signature": "sig"}, {"type": "text", "text": "我先查一下"},
              {"type": "tool_use", "id": "c1", "name": "query_financials", "input": {"symbol": "AAPL"}},
              {"type": "tool_use", "id": "c2", "name": "query_financials", "input": {"symbol": "MSFT"}}]
    first = {**step(text="我先查一下", calls=calls), "extra": {"_anthropic_content": blocks, "reasoning_content": "r"}}
    fake = backup.scripted([first, timeout(), timeout()], [step(text="好")])
    result, _ = run_turn()
    assert any("_anthropic_content" in m for m in fake.on("m")[1]["messages"])
    handed = fake.on(BACKUP["model"])[0]["messages"]
    assert not any(k == "_anthropic_content" or k.startswith("reasoning_") for m in handed for k in m)
    assert handed[-3]["tool_calls"] == calls and [m["tool_call_id"] for m in handed[-2:]] == ["c1", "c2"]
    _, converted = anthropic_native.convert_messages(handed, keep_thinking=True)
    uses = [b for m in converted if m["role"] == "assistant" for b in m["content"]]
    assert [b["type"] for b in uses] == ["text", "tool_use", "tool_use"] and [b["id"] for b in uses[1:]] == ["c1", "c2"]
    assert result["answer"] == "好" + LABEL


def test_a_card_proposed_after_the_switch_is_minted_and_the_answer_is_labelled(backup, fake_consent):
    backup.scripted([timeout(), timeout()], [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="请核对卡片")])
    result, events = run_turn(ctx())
    assert len(fake_consent.proposed) == 1 and result["status"] == "waiting_for_input" and result["pending_request"]["id"] == "card-1"
    assert result["answer"] == "请核对卡片" + LABEL and {"event": "delta", "text": LABEL} in events


def test_the_closing_call_after_the_step_cap_can_be_the_backups(backup):
    tools = [step(calls=[call(f"c{i}", "query_financials", {"symbol": "AAPL"})]) for i in range(loop.MAX_STEPS)]
    fake = backup.scripted([*tools, timeout(), timeout()], [step(text="只能这样")])
    result, events = run_turn()
    assert result["audit"]["stop_reason"] == "step_cap" and result["answer"] == "只能这样" + LABEL
    assert result["answer"].count("这条由备用模型") == 1 and [e["text"] for e in events if e["event"] == "delta"].count(LABEL) == 1
    assert fake.calls[-1]["model"] == BACKUP["model"] and fake.calls[-1]["messages"][-1]["content"] == loop.CAP_NOTE


def test_a_successful_post_press_turn_answered_by_the_backup_is_labelled(cards, backup):
    backup.scripted([timeout(), timeout()], [step(text="预测已提交")])
    card = pending_card(cards)
    result, events = turn(f"confirm:{TOKEN}", pressed(card))
    assert len(cards.costly) == 1 and result["status"] == "succeeded" and result["answer"] == "预测已提交" + LABEL
    assert result["audit"]["write_outcome"] == "executed" and "report" not in result["audit"]
    assert result["final_protocol"]["fallback_model"] == "reserve"


def test_fallback_model_is_only_set_when_the_label_was_added(cards, backup):
    backup.scripted([timeout(), timeout()], [timeout(), timeout()])
    result, _ = turn(f"confirm:{TOKEN}", pressed(pending_card(cards)))
    assert result["audit"]["report"] == "fallback" and "fallback_model" not in result["final_protocol"]


def test_a_broken_switch_leaves_the_providers_failure_as_the_turns_error(backup):
    backup.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: {"provider": "x"})   # incomplete settings
    fake = backup.scripted([timeout(), timeout()])
    with pytest.raises(provider.ProviderFailure) as raised:
        run_turn()
    assert raised.value.detail == "provider_timeout" and len(fake.calls) == 2


def test_a_narration_that_cannot_be_sent_leaves_the_providers_failure_as_the_turns_error(backup):
    fake = backup.scripted([timeout(), timeout()], [step(text="不该到这里")])

    async def emit(event):
        if event.get("system"):
            raise OSError("client went away")

    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "问题"}]
    with pytest.raises(provider.ProviderFailure) as raised:
        asyncio.run(loop.run_turn("问题", make_context(), emit, history, {}))
    assert raised.value.detail == "provider_timeout" and fake.on(BACKUP["model"]) == []
