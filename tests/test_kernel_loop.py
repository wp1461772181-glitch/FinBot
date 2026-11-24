"""Kernel loop: one append-only tool loop with streamed answer text.

No network, no database: ``stream_decision`` and ``tools.invoke`` are replaced by scripts.
"""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
from app.agent_workflow import tools
from app.kernel import loop, prompt

ROW = {"id": "r1", "symbol": "AAPL", "source_type": "official_filing", "excerpt": "Revenue was 100 and cost was 40 (USD billions)."}
OK_ROWS = {"ok": True, "data": [ROW], "source": "saved"}


def call(call_id, name, args):
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def step(text="", pieces=None, calls=(), usage=None):
    """One scripted model step: ``pieces`` are streamed through on_text, ``text`` is the final content."""
    return {"text": text, "pieces": pieces if pieces is not None else ([text] if text else []), "calls": list(calls),
            "usage": usage or {"total_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}


class Script:
    """A fake ``stream_decision``: records what each call received, answers from the script."""

    def __init__(self, steps, repeat_last=False):
        self.steps = list(steps)
        self.repeat_last = repeat_last
        self.calls = []

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": [s["function"]["name"] for s in schemas], "kwargs": kwargs})
        item = self.steps[0] if self.repeat_last and len(self.steps) == 1 else self.steps.pop(0)
        if isinstance(item, Exception):
            raise item
        for piece in item["pieces"]:
            await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": item["text"]}
        if item["calls"]:
            message["tool_calls"] = item["calls"]
        return {"usage": item["usage"]}, message


def make_context(owner=True, **extra):
    base = dict(provider="anthropic", model="m", api_key="k", base_url=None, reasoning_effort=None, tool_scope=None,
                bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash="o")
    return SimpleNamespace(**{**base, **extra})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: bool(value))
    invoked = []

    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        invoked.append((name, args))
        return copy.deepcopy(OK_ROWS)

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    return SimpleNamespace(invoked=invoked, monkeypatch=monkeypatch)


def script(env, steps, **kwargs):
    fake = Script(steps, **kwargs)
    env.monkeypatch.setattr(provider, "stream_decision", fake)
    return fake


def run(question="问题", context=None, messages=None):
    events = []

    async def emit(event):
        events.append(event)

    history = messages if messages is not None else [{"role": "system", "content": "endpoint"}, {"role": "user", "content": question}]
    result = asyncio.run(loop.run_turn(question, context or make_context(), emit, history, {}))
    return result, events


def kinds(events):
    return [e["event"] for e in events]


def test_direct_answer_streams_and_returns(env):
    script(env, [step(pieces=["你", "好"], text="你好")])
    result, events = run()
    assert kinds(events) == ["delta", "delta"]
    assert result["answer"] == "你好"
    assert result["status"] == "succeeded" and result["streamed"] is True
    assert result["audit"]["model_calls"] == 1 and result["audit"]["engine"] == "v2"
    assert result["route"] == "K" and result["citations"] == [] and result["reason"] is None
    # Checkpointed by the graph and read by the old turn later: types it can read, meaning "nothing carried over".
    assert result["previous_scope"] == {} and result["result_sets"] == [] and result["previous_category"] is None


def test_tool_then_answer(env):
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="收入 100 [1]")])
    result, events = run()
    assert kinds(events) == ["assistant_tool_request", "tool_start", "tool_result", "delta"]
    last = fake.calls[1]["messages"][-2:]
    assert [m["role"] for m in fake.calls[1]["messages"][-2:]] == ["assistant", "tool"]
    assert last[0]["tool_calls"][0]["id"] == "c1" and last[1]["tool_call_id"] == "c1"
    assert len(result["citations"]) == 1 and result["citations"][0]["ordinal"] == 1
    assert json.loads(last[1]["content"])["data"][0]["citation"] == "[1]"
    assert result["answer"] == "收入 100 [1]"


def test_messages_only_grow(env):
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[call("c2", "web_research", {"query": "x"})]), step(text="done")])
    run()
    first, second, third = (c["messages"] for c in fake.calls)
    assert second[:len(first)] == first and third[:len(second)] == second
    assert len(third) > len(second) > len(first)


def test_text_before_tool_call_is_reset(env):
    script(env, [step(text="我查一下", calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="结果")])
    result, events = run()
    names = kinds(events)
    assert names.index("answer_reset") < names.index("assistant_tool_request")
    assert "我查一下" not in result["answer"] and result["answer"] == "结果"


def test_tool_error_is_given_back_to_the_model(env):
    async def failing(name, args, context, *, emit=None, page_chars=None):
        return {"ok": False, "data": [], "error_code": "no_reported_figures", "hint": "h"}

    env.monkeypatch.setattr(tools, "invoke", failing)
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="没查到")])
    result, _ = run()
    assert result["status"] == "succeeded"
    assert json.loads(fake.calls[1]["messages"][-1]["content"])["error_code"] == "no_reported_figures"


def test_tool_exception_becomes_tool_failed(env):
    async def boom(*args, **kwargs):
        raise RuntimeError("secret detail")

    env.monkeypatch.setattr(tools, "invoke", boom)
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    result, events = run()
    shown = next(e for e in events if e["event"] == "tool_result")
    assert shown["result"]["error_code"] == "tool_failed"
    assert "secret" not in fake.calls[1]["messages"][-1]["content"]
    assert result["status"] == "succeeded"


def test_bad_json_arguments(env):
    fake = script(env, [step(calls=[call("c1", "query_financials", "{oops")]), step(text="好")])
    result, events = run()
    assert next(e for e in events if e["event"] == "tool_result")["result"]["error_code"] == "invalid_arguments"
    assert env.invoked == [] and result["status"] == "succeeded"


def test_step_cap_forces_a_final_answer(env):
    steps = [step(calls=[call(f"c{i}", "query_financials", {"symbol": "AAPL"})]) for i in range(loop.MAX_STEPS)]
    fake = script(env, steps + [step(text="只能这样")])
    result, _ = run()
    assert len(fake.calls) == loop.MAX_STEPS + 1
    assert fake.calls[-1]["tools"] == fake.calls[0]["tools"] and all(c["tools"] for c in fake.calls)
    assert result["answer"] == "只能这样" and result["audit"]["stop_reason"] == "step_cap"
    assert fake.calls[-1]["messages"][-1]["role"] == "system"


def test_time_cap_forces_a_final_answer(env):
    env.monkeypatch.setattr(loop, "SOFT_SECONDS", -1)
    fake = script(env, [step(text="直接答")])
    result, _ = run()
    assert fake.calls[0]["tools"] and result["audit"]["stop_reason"] == "time_cap"
    assert fake.calls[0]["messages"][-1] == {"role": "system", "content": loop.CAP_NOTE}


def test_tools_are_fixed_and_scoped(env):
    scope = frozenset({"query_financials", "web_research"})
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    run(context=make_context(tool_scope=scope))
    assert [set(c["tools"]) for c in fake.calls] == [set(scope) | {"plan", "escalate"}] * 2
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="好")])
    run()
    assert "query_portfolio" not in fake.calls[0]["tools"] and "recall_conversations" not in fake.calls[0]["tools"]
    assert fake.calls[0]["tools"]


def test_no_write_tool_is_ever_offered(env):
    for owner in (True, False):
        env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value, owner=owner: owner)
        fake = script(env, [step(text="好")])
        run()
        assert set(fake.calls[0]["tools"]) <= set(loop.READ_TOOLS) | {"plan", "escalate"}


def test_retryable_provider_failure_is_retried_once(env):
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    failure = provider.ProviderFailure("http_5xx", stage="decision", retryable=True)
    fake = script(env, [failure, step(text="好")])
    result, _ = run()
    assert result["status"] == "succeeded" and result["audit"]["model_calls"] == 1 and len(fake.calls) == 2
    script(env, [failure, failure])
    with pytest.raises(provider.ProviderFailure):
        run()
    script(env, [provider.ProviderFailure("bad", stage="decision", retryable=False), step(text="好")])
    with pytest.raises(provider.ProviderFailure):
        run()


def test_retry_after_streamed_text_resets_the_answer(env):
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)

    class Dropping(Script):
        async def __call__(self, *args, **kwargs):
            if not self.calls:
                self.calls.append({})
                await kwargs["on_text"]("半句")
                raise provider.ProviderFailure("http_5xx", stage="decision", retryable=True)
            return await super().__call__(*args, **kwargs)

    env.monkeypatch.setattr(provider, "stream_decision", Dropping([step(text="整句")]))
    result, events = run()
    assert kinds(events) == ["delta", "answer_reset", "delta"] and result["answer"] == "整句"


def test_calculate_registers_a_citation(env):
    inputs = [{"name": "a", "value": "100", "source_ordinal": 1}, {"name": "b", "value": "40", "source_ordinal": 1}]
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[call("c2", "calculate", {"expression": "a-b", "inputs": inputs})]), step(text="利润 60 [2]")])
    result, events = run()
    assert [c["source_type"] for c in result["citations"]] == ["official_filing", "calculation"]
    assert [name for name, _ in env.invoked] == ["query_financials"]
    assert json.loads(fake.calls[2]["messages"][-1]["content"])["data"][0]["citation"] == "[2]"


def test_invalid_markers_are_stripped(env):
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="收入 100 [1]，另一个 [9]")])
    result, _ = run()
    assert "[9]" not in result["answer"] and "[1]" in result["answer"]


def test_usage_is_summed(env):
    first = {"total_tokens": 100, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 5}
    second = {"total_tokens": 50, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 0}
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})], usage=first), step(text="好", usage=second)])
    audit = run()[0]["audit"]
    assert (audit["token_usage"], audit["cache_read_tokens"], audit["cache_write_tokens"]) == (150, 50, 5)
    assert audit["model_calls"] == 2 and audit["decision_steps"] == 2 and audit["tool_calls"] == 1
    assert [(c["tier"], c["tokens"], c["cache_read"], c["cache_write"]) for c in audit["calls"]] == [("low", 100, 30, 5), ("low", 50, 20, 0)]
    assert all(isinstance(c["ms"], int) and c["ms"] >= 0 for c in audit["calls"])


def test_system_prompt_is_first_and_stable(env):
    context = make_context(bot_block="BOT", profile_block="PROFILE")
    fake = script(env, [step(text="a"), step(text="b")])
    run("问题一", context)
    run("问题二", context)
    first, second = (c["messages"][0] for c in fake.calls)
    assert first == second and first["role"] == "system" and first["content"].startswith(prompt.SYSTEM)
    assert "BOT" in first["content"] and "PROFILE" in first["content"]


def test_profile_block_is_owner_only(env):
    env.monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    env.monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: False)
    fake = script(env, [step(text="a")])
    run(context=make_context(bot_block="BOT", profile_block="PROFILE"))
    content = fake.calls[0]["messages"][0]["content"]
    assert "BOT" in content and "PROFILE" not in content


def test_current_question_is_not_duplicated(env):
    fake = script(env, [step(text="a")])
    run("问题", messages=[{"role": "system", "content": "e"}, {"role": "user", "content": "前"}, {"role": "assistant", "content": "答"},
                           {"role": "user", "content": "问题"}])
    assert [m["role"] for m in fake.calls[0]["messages"]] == ["system", "user", "assistant", "user"]


def test_unbound_calculation_input_is_explained_to_the_model(env):
    bad = [{"name": "a", "value": "999", "source_ordinal": 1}]
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[call("c2", "calculate", {"expression": "a*2", "inputs": bad})]), step(text="好")])
    result, _ = run()
    shown = json.loads(fake.calls[2]["messages"][-1]["content"])
    assert shown["ok"] is False and shown["error_code"] == "calculation_input_unbound" and shown["input_receipts"]
    assert [c["source_type"] for c in result["citations"]] == ["official_filing"]


def streamed_after_last_reset(events):
    text = ""
    for event in events:
        if event["event"] == "answer_reset":
            text = ""
        elif event["event"] == "delta":
            text += event["text"]
    return text


def test_stripped_marker_is_also_cleaned_in_the_stream(env):
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="收入 100 [1]，另一个 [9]")])
    result, events = run()
    assert "[9]" not in result["answer"]
    assert streamed_after_last_reset(events) == result["answer"]
    assert kinds(events)[-2:] == ["answer_reset", "delta"]


def test_clean_answer_adds_no_extra_reset(env):
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="收入 100 [1]")])
    result, events = run()
    assert "answer_reset" not in kinds(events) and streamed_after_last_reset(events) == result["answer"]


def test_empty_reply_gets_one_more_call(env):
    fake = script(env, [step(text=""), step(text="补上的回答")])
    result, _ = run()
    assert result["status"] == "succeeded" and result["answer"] == "补上的回答"
    assert fake.calls[1]["tools"] == fake.calls[0]["tools"] and fake.calls[1]["messages"][-1] == {"role": "system", "content": loop.EMPTY_NOTE}
    assert result["audit"]["model_calls"] == 2


def test_empty_twice_fails_with_a_fixed_text(env):
    script(env, [step(text="  "), step(text="")])
    result, events = run()
    assert result["status"] == "failed" and result["reason"] == "empty_answer"
    assert result["answer"] == loop.EMPTY_ANSWER and result["audit"]["terminal_status"] == "failed"
    assert streamed_after_last_reset(events) == loop.EMPTY_ANSWER


def test_empty_cap_call_goes_straight_to_the_fixed_text(env):
    steps = [step(calls=[call(f"c{i}", "query_financials", {"symbol": "AAPL"})]) for i in range(loop.MAX_STEPS)]
    fake = script(env, steps + [step(text="")])
    result, _ = run()
    assert len(fake.calls) == loop.MAX_STEPS + 1
    assert result["status"] == "failed" and result["answer"] == loop.EMPTY_ANSWER and result["audit"]["stop_reason"] == "step_cap"


def test_tool_outside_the_offered_set_is_refused(env):
    script(env, [step(calls=[call("c1", "create_routine", {"x": 1})]), step(text="好")])
    result, events = run()
    assert next(e for e in events if e["event"] == "tool_result")["result"]["error_code"] == "tool_not_in_bot_scope"
    assert env.invoked == [] and result["status"] == "succeeded"


def test_value_error_inside_a_tool_is_tool_failed(env):
    async def broken(*args, **kwargs):
        raise ValueError("inside the tool")

    env.monkeypatch.setattr(tools, "invoke", broken)
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert next(e for e in events if e["event"] == "tool_result")["result"]["error_code"] == "tool_failed"


def test_invalid_calculation_arguments_are_invalid_arguments(env):
    script(env, [step(calls=[call("c1", "calculate", {"expression": "a"})]), step(text="好")])
    _, events = run()
    assert next(e for e in events if e["event"] == "tool_result")["result"]["error_code"] == "invalid_arguments"


def failing_after(pieces, failures):
    """A stream_decision that streams ``pieces`` and then raises, once per entry of ``failures``."""
    queue = list(failures)

    async def fake(provider_name, model, api_key, messages, schemas, **kwargs):
        for piece in pieces:
            await kwargs["on_text"](piece)
        raise queue.pop(0)

    return fake


def test_final_failure_after_streamed_text_resets_the_answer(env):
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    cases = [[provider.ProviderFailure("bad", stage="decision", retryable=False)],
             [provider.ProviderFailure("http_5xx", stage="decision", retryable=True)] * 2,
             [RuntimeError("boom")]]
    for failures in cases:
        env.monkeypatch.setattr(provider, "stream_decision", failing_after(["部分"], failures))
        events = []

        async def emit(event):
            events.append(event)

        with pytest.raises(Exception):
            asyncio.run(loop.run_turn("问题", make_context(), emit, [{"role": "system", "content": "e"}], {}))
        assert kinds(events)[-1] == "answer_reset" and streamed_after_last_reset(events) == ""


def test_failure_without_streamed_text_emits_no_reset(env):
    env.monkeypatch.setattr(provider, "stream_decision", failing_after([], [RuntimeError("boom")]))
    events = []

    async def emit(event):
        events.append(event)

    with pytest.raises(RuntimeError):
        asyncio.run(loop.run_turn("问题", make_context(), emit, [{"role": "system", "content": "e"}], {}))
    assert events == []


def cap_steps():
    return [step(calls=[call(f"c{i}", "query_financials", {"symbol": "AAPL"})]) for i in range(loop.MAX_STEPS)]


def test_closing_call_with_text_and_tool_call_uses_the_text(env):
    fake = script(env, cap_steps() + [step(text="只能这样", calls=[call("cx", "web_research", {"query": "x"})])])
    result, events = run()
    assert result["status"] == "succeeded" and result["answer"] == "只能这样"
    assert len(env.invoked) == loop.MAX_STEPS and streamed_after_last_reset(events) == "只能这样"
    assert "cx" not in json.dumps(events)
    assert result["audit"]["stop_reason"] == "step_cap"


def test_closing_call_with_only_a_tool_call_fails_with_the_fixed_text(env):
    script(env, cap_steps() + [step(calls=[call("cx", "web_research", {"query": "x"})])])
    result, events = run()
    assert result["status"] == "failed" and result["reason"] == "empty_answer" and result["answer"] == loop.EMPTY_ANSWER
    assert len(env.invoked) == loop.MAX_STEPS and streamed_after_last_reset(events) == loop.EMPTY_ANSWER


def test_forced_call_after_empty_reply_with_only_a_tool_call_fails(env):
    fake = script(env, [step(text=""), step(calls=[call("cx", "web_research", {"query": "x"})])])
    result, _ = run()
    assert result["status"] == "failed" and env.invoked == [] and len(fake.calls) == 2


def test_closing_notes_tell_the_model_not_to_call_tools():
    assert "不要再调用工具" in loop.CAP_NOTE and "不要再调用工具" in loop.EMPTY_NOTE


def test_question_is_not_appended_again_after_trailing_system_notes(env):
    fake = script(env, [step(text="a")])
    history = [{"role": "system", "content": "e"}, {"role": "user", "content": "前"}, {"role": "assistant", "content": "答"},
               {"role": "user", "content": "问题"}, {"role": "system", "content": "记忆摘要"}, {"role": "system", "content": "引用目录"}]
    run("问题", messages=history)
    sent = fake.calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user", "system", "system"]
    assert [m["content"] for m in sent].count("问题") == 1 and sent[-2]["content"] == "记忆摘要"


def test_question_missing_from_history_is_appended_once_at_the_end(env):
    fake = script(env, [step(text="a")])
    run("问题", messages=[{"role": "system", "content": "e"}, {"role": "user", "content": "前"}, {"role": "system", "content": "记忆摘要"}])
    sent = fake.calls[0]["messages"]
    assert sent[-1] == {"role": "user", "content": "问题"} and [m["content"] for m in sent].count("问题") == 1


def test_numbers_only_in_a_system_note_are_not_what_the_user_typed():
    history = [{"role": "user", "content": "前一句 100"}, {"role": "system", "content": "摘要里有 7777"}]
    text = loop._user_text("问题 40", history)
    assert "100" in text and "40" in text and "7777" not in text


def test_non_string_stream_pieces_are_ignored(env):
    class Odd(Script):
        async def __call__(self, *args, **kwargs):
            await kwargs["on_text"](None)
            await kwargs["on_text"](5)
            return await super().__call__(*args, **kwargs)

    env.monkeypatch.setattr(provider, "stream_decision", Odd([step(text="好")]))
    result, events = run()
    assert result["answer"] == "好" and streamed_after_last_reset(events) == "好"


def test_http_exception_provider_timeout_is_retried_once(env):
    from fastapi import HTTPException
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    fake = script(env, [HTTPException(504, "provider_timeout"), step(text="好")])
    result, _ = run()
    assert result["status"] == "succeeded" and len(fake.calls) == 2
    fake = script(env, [HTTPException(504, "provider_timeout"), HTTPException(504, "provider_timeout")])
    with pytest.raises(HTTPException):
        run()
    assert len(fake.calls) == 2


def test_too_large_and_unlisted_failures_are_not_retried(env):
    from fastapi import HTTPException
    env.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    fake = script(env, [HTTPException(413, "provider_protocol_too_large"), step(text="好")])
    with pytest.raises(HTTPException):
        run()
    assert len(fake.calls) == 1
    fake = script(env, [provider.ProviderFailure("bad", stage="decision", retryable=False), step(text="好")])
    with pytest.raises(provider.ProviderFailure):
        run()
    assert len(fake.calls) == 1
