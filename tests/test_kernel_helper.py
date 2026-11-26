"""3d Task 1: the helper — the kernel's ``delegate`` tool hands one several-step piece of legwork to a short low-tier child run.

No network, no database (except the role tests, which use the test database like the backup-model tests): ``stream_decision`` and
``tools.invoke`` are scripted.  Review Focus: 1 two helpers at the same time, 2 refused tools, 3 the owner speaks, 4 the helper's model
fails, 5 the switch off pins today's schemas and system text.
"""
import asyncio
import copy
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app import model_usage
from app.agent_chat_models import AgentModelEntry, AgentModelRole
from app.agent_workflow import tools
from app.database import SessionLocal
from app.kernel import helper, loop, prompt, toolrun
from app.kernel import inbox as inboxes
from tests.test_agent_bots import KEY_A, OWNER_HASH, owner  # noqa: F401  (fixture)
from tests.test_kernel_loop import FakeConsent, act_call, call, env, fake_consent, make_context, step  # noqa: F401  (fixtures by name)

# What the schemas and the system text hash to with the switch off (sorted keys, ensure_ascii off): the same as before the helper existed, except that
# the owner's role lists (set_model_role, list_models) now name the helper role, which exists whatever the switch.  Stage 4a: plus read_turn.  Stage 4b: the role lists also name the memory role.
GOLDEN = {
    # Memory writes (11-26): remember's basis and quote wording in the act tool; the memory lines of the system text.
    # 5b-1: the owner's tools gain set_watch_rule / delete_watch_rule in act and the list_watch_rules read (the system text is unchanged).
    "owner": ("2cddf917731c1072766dc7543f522bde9c84427911e4cd718cdb4733e4c38e85",
               "a8939601bb56f0e88c086dbccfe6e622e619b16b8c19b56d48e566b558928303"),
    "guest": ("cc697baf95543b43614509bb70ea10889ed11ab173f2089dd28e703b49fdaa4d", "a8939601bb56f0e88c086dbccfe6e622e619b16b8c19b56d48e566b558928303"),
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def guest_context(**extra):
    return make_context(identity_credential="", **extra)


def names(schemas) -> list[str]:
    return [s["function"]["name"] for s in schemas]


def row(symbol, **extra):
    return {"id": f"row-{symbol}", "symbol": symbol, "source_type": "official_filing", "excerpt": f"{symbol} capex was 10 (USD billions).", **extra}


class Model:
    """A scripted ``stream_decision`` for a parent turn and its helpers.  ``parent`` is the parent's steps; ``helpers`` maps a brief to that
    helper's steps (a step is a ``step(...)`` dict, an exception, or a function of the messages)."""

    def __init__(self, parent, helpers=None):
        self.parent, self.helpers, self.calls = list(parent), {k: list(v) for k, v in (helpers or {}).items()}, []

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        is_helper = messages[0]["role"] == "system" and messages[0]["content"].startswith(helper.SYSTEM_HEAD)
        self.calls.append({"helper": is_helper, "provider": provider_name, "model": model, "messages": copy.deepcopy(messages), "tools": names(schemas),
                           "tags": dict(model_usage._TAGS.get() or {}), "kwargs": kwargs})
        queue = self.helpers[messages[1]["content"]] if is_helper else self.parent
        item = queue.pop(0)
        item = item(messages) if callable(item) else item
        if isinstance(item, dict) and item.get("sleep"):
            await asyncio.sleep(item["sleep"])
        if isinstance(item, BaseException):
            raise item
        for piece in item["pieces"]:
            await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": item["text"]}
        if item["calls"]:
            message["tool_calls"] = item["calls"]
        return {"usage": item["usage"]}, message

    def helper_calls(self):
        return [c for c in self.calls if c["helper"]]

    def parent_calls(self):
        return [c for c in self.calls if not c["helper"]]


@pytest.fixture
def on(env):
    env.monkeypatch.setenv("FINBOT_HELPER", "on")
    env.monkeypatch.setattr(loop.roles, "get", lambda owner_hash, role: None, raising=False)     # no role row: the helper uses the parent's model
    env.monkeypatch.setattr(helper.roles, "helper_for", lambda owner_hash: None)
    return env


def install(env, parent, helpers=None):
    model = Model(parent, helpers)
    env.monkeypatch.setattr(provider, "stream_decision", model)
    return model


def run_turn(context=None, question="问题", state=None):
    events = []

    async def emit(event):
        events.append(event)

    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": question}]
    result = asyncio.run(loop.run_turn(question, context or make_context(), emit, history, state or {"turn_id": "t1"}))
    return result, events


def delegate(call_id, brief, **extra):
    return call(call_id, "delegate", {"brief": brief, **extra})


def reports(messages):
    """The delegate results the parent was given, by call id."""
    return {m["tool_call_id"]: json.loads(m["content"]) for m in messages if m["role"] == "tool"}


@pytest.fixture
def by_symbol(env):
    """``tools.invoke`` that returns one distinct row per symbol."""
    async def invoke(name, args, context, *, emit=None, page_chars=None):
        env.invoked.append((name, args))
        return {"ok": True, "data": [row(args.get("symbol", "X"))], "source": "saved"}
    env.monkeypatch.setattr(tools, "invoke", invoke)
    return env


# --- Review Focus 5: the switch off pins today's schemas and system text -------------------------------------------------------

@pytest.mark.parametrize("setting", [None, "off", "OFF", "", "no"])
def test_the_switch_off_leaves_schemas_and_system_text_as_they_were(env, setting):
    env.monkeypatch.setenv("FINBOT_KERNEL_INLINE_CATALOGUE", "off")     # the golden text is the one from before the inline-catalogue line
    if setting is None:
        env.monkeypatch.delenv("FINBOT_HELPER", raising=False)
    else:
        env.monkeypatch.setenv("FINBOT_HELPER", setting)
    for who, context in (("owner", make_context()), ("guest", guest_context())):
        schemas = loop._tool_schemas(context)
        messages = prompt.build_messages("q", context, [{"role": "user", "content": "q"}])
        assert "delegate" not in names(schemas)
        assert (digest(schemas), digest(messages)) == GOLDEN[who]


def test_the_switch_on_adds_the_tool_last_and_one_sentence_to_the_system_text(env):
    env.monkeypatch.delenv("FINBOT_HELPER", raising=False)
    for context in (make_context(), guest_context()):
        before = loop._tool_schemas(context)
        env.monkeypatch.setenv("FINBOT_HELPER", "on")
        after = loop._tool_schemas(context)
        assert after[:-1] == before and names(after)[-1] == "delegate"
        text_off = prompt.system_text()
        text_on = prompt.system_text(helper=True)
        assert text_on != text_off and prompt.HELPER_LINE in text_on and text_on.replace(prompt.HELPER_LINE + "\n", "") == text_off
        env.monkeypatch.delenv("FINBOT_HELPER")


def test_a_run_with_the_switch_off_sends_the_model_exactly_todays_schemas_and_system_text(env):
    env.monkeypatch.delenv("FINBOT_HELPER", raising=False)
    model = install(env, [step(text="好")])
    run_turn()
    (sent,) = model.calls
    assert "delegate" not in sent["tools"] and prompt.HELPER_LINE not in sent["messages"][0]["content"]
    assert digest(sent["messages"][:1]) == digest(prompt.build_messages("问题", make_context(), [{"role": "user", "content": "问题"}])[:1])


def test_the_switch_on_tells_the_model_in_one_sentence_and_in_the_tool_description(on):
    model = install(on, [step(text="好")])
    run_turn()
    (sent,) = model.calls
    assert sent["tools"][-1] == "delegate" and prompt.HELPER_LINE in sent["messages"][0]["content"]
    description = helper.DELEGATE_SCHEMA["function"]["description"]
    assert "several-step" in description and "self-contained" in description and "[n]" in description and "judgment" in description
    assert not any(ord(ch) > 0x2E80 for ch in description)         # English, like the catalogue


def test_the_tool_is_never_offered_to_a_wake_turn_or_to_a_turn_without_a_read_tool(on):
    assert "delegate" not in names(loop._wake_schemas(make_context()))
    only_writes = make_context(tool_scope=frozenset({"nothing"}))
    assert "delegate" not in names(loop._tool_schemas(only_writes))
    assert "delegate" in names(loop._tool_schemas(make_context(tool_scope=frozenset({"query_financials"}))))


# --- Review Focus 1: two helpers at the same time ------------------------------------------------------------------------------

def test_two_delegates_in_one_step_run_together_and_their_numbers_are_distinct_valid_citations(on):
    arrived = []

    def final(messages):
        got = reports(messages)
        return step(text=f"NVDA capex [{got['d1']['data']['sources'][0]}]，AMD capex [{got['d2']['data']['sources'][0]}]")

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        arrived.append(args["symbol"])
        deadline = asyncio.get_running_loop().time() + 2
        while len(arrived) < 2:             # sequential helpers would wait here for ever: the second never starts
            assert asyncio.get_running_loop().time() < deadline, "the helpers did not run at the same time"
            await asyncio.sleep(0.01)
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}
    on.monkeypatch.setattr(tools, "invoke", invoke)
    model = install(on, [
        step(calls=[delegate("d1", "NVDA 最近一次财报电话会的 capex", say="让小助手去读"), delegate("d2", "AMD 最近一次财报电话会的 capex")]),
        final],
        {"NVDA 最近一次财报电话会的 capex": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), step(text="NVDA capex 10 亿 [1]")],
         "AMD 最近一次财报电话会的 capex": [step(calls=[call("h2", "query_financials", {"symbol": "AMD"})]), step(text="AMD capex 10 亿 [1]")]})
    result, events = run_turn()
    assert result["status"] == "succeeded"
    got = reports(model.parent_calls()[1]["messages"])
    first, second = got["d1"]["data"], got["d2"]["data"]
    assert got["d1"]["ok"] and got["d2"]["ok"] and first["complete"] and second["complete"]
    assert sorted([first["sources"][0], second["sources"][0]]) == [1, 2]                   # distinct numbers of the parent's own list
    assert [c["symbol"] for c in result["citations"]] == [c["symbol"] for c in sorted(result["citations"], key=lambda c: c["ordinal"])]
    assert {c["ordinal"]: c["symbol"] for c in result["citations"]} == {first["sources"][0]: "NVDA", second["sources"][0]: "AMD"}
    assert first["report"] == "NVDA capex 10 亿 [1]" and first["steps"] == 2
    assert f"[{first['sources'][0]}]" in result["answer"] and f"[{second['sources'][0]}]" in result["answer"]    # the answer can cite them (not stripped)
    assert result["audit"]["tool_calls"] == 2        # the parent's own two calls: the helpers' reads are theirs


def test_a_delegate_result_is_unnumbered_and_counts_as_one_read_for_the_parent(on):
    run = loop._Run(context=make_context(), emit=lambda e: asyncio.sleep(0), messages=[], user_text="", schemas=loop._tool_schemas(make_context()),
                    tool_names=frozenset(names(loop._tool_schemas(make_context()))), model=loop.ModelUse("anthropic", "m", "k"))

    async def fake(parent, call_id, args):
        return {"ok": True, "data": {"report": "r", "sources": [1], "steps": 1, "complete": True}} if args["brief"] == "good" else \
               {"ok": False, "error_code": "helper_failed", "hint": "h", "data": {"sources": []}}
    on.monkeypatch.setattr(helper, "run", fake)
    for brief, expected in (("good", 1), ("bad", 1)):      # a helper that ran counts whatever it came back with (it has seen outside text)
        run.read_results = 0
        messages = asyncio.run(toolrun.run_step_tools(run, [delegate("d", brief)]))
        assert run.read_results == expected and json.loads(messages[0]["content"])["data"].get("sources") is not None
        assert run.citations == []
    run.read_results = 0
    for refused in ({}, {"brief": "x", "tools": ["act"]}):      # refused before running: not a read
        asyncio.run(toolrun.run_step_tools(run, [call("d", "delegate", refused)]))
    assert run.read_results == 0


def test_at_most_three_helpers_run_in_a_step_the_rest_are_refused_without_running(on, by_symbol):
    briefs = [f"查 S{n}" for n in range(4)]
    model = install(on, [step(calls=[delegate(f"d{n}", brief) for n, brief in enumerate(briefs)]), step(text="好")],
                    {brief: [step(text="没什么")] for brief in briefs})
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])
    assert [got[f"d{n}"]["ok"] for n in range(4)] == [True, True, True, False]
    assert got["d3"]["error_code"] == "too_many_helpers" and got["d3"]["hint"]
    assert {c["messages"][1]["content"] for c in model.helper_calls()} == set(briefs[:3])       # the fourth never ran


# --- Review Focus 2: what a helper may not do ----------------------------------------------------------------------------------

def test_a_helper_asking_for_act_ask_or_delegate_in_tools_is_refused_before_anything_runs(on, fake_consent):
    wanted = [["act"], ["ask"], ["delegate"], ["plan"], ["escalate"], ["use_skill"], ["handle_message"], ["query_financials", "act"], ["not_a_tool"]]
    on.monkeypatch.setattr(helper, "MAX_HELPERS", 20)
    model = install(on, [step(calls=[delegate(f"d{n}", f"b{n}", tools=tools_) for n, tools_ in enumerate(wanted)]), step(text="好")])
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])
    assert all(not got[f"d{n}"]["ok"] and got[f"d{n}"]["error_code"] == "tool_not_in_bot_scope" for n in range(len(wanted)))
    assert model.helper_calls() == [] and fake_consent.proposed == [] and fake_consent.executed == []


def test_a_helper_that_calls_act_ask_delegate_anyway_gets_a_refusal_and_nothing_is_written(on, by_symbol, fake_consent):
    asked = [call("a1", "act", {"operation": "add_to_research_queue", "arguments": {"symbol": "NVDA"}}),
             call("a2", "ask", {"question": "要哪一个？", "options": ["a", "b"]}), call("a3", "delegate", {"brief": "递归"}),
             call("a4", "escalate", {"tier": "high"}), call("a5", "plan", {"items": [{"text": "x"}]}), call("a6", "web_research", {"query": "x"})]
    model = install(on, [step(calls=[delegate("d1", "做点事", tools=["query_financials"])]), step(text="好")],
                    {"做点事": [step(calls=asked), step(text="没做成")]})
    result, events = run_turn()
    seen = reports(model.helper_calls()[1]["messages"])
    assert all(seen[f"a{n}"].get("error_code") == "tool_not_in_bot_scope" for n in range(1, 7))        # web_research was not among the helper's tools
    assert fake_consent.proposed == [] and fake_consent.executed == [] and result["pending_request"] is None and result["audit"]["writes"] == []
    assert result["status"] == "succeeded" and model.helper_calls()[0]["tools"] == ["query_financials"]


def test_the_helper_is_offered_the_parents_reads_and_calculations_without_the_kernels_own_tools(on):
    model = install(on, [step(calls=[delegate("d1", "查一查")]), step(text="好")], {"查一查": [step(text="没有")]})
    run_turn()
    offered = model.helper_calls()[0]["tools"]
    parent = model.parent_calls()[0]["tools"]
    banned = {"act", "ask", "use_skill", "plan", "escalate", "handle_message", "delegate", "decide"}
    assert offered and not banned & set(offered) and set(offered) == set(parent) - banned
    assert "calculate" in offered and "query_financials" in offered


def test_a_guests_helper_gets_only_the_guests_reads(on):
    model = install(on, [step(calls=[delegate("d1", "查一查")]), step(text="好")], {"查一查": [step(text="没有")]})
    run_turn(guest_context())
    offered, parent = model.helper_calls()[0]["tools"], model.parent_calls()[0]["tools"]
    assert "query_portfolio" not in offered and "act" not in offered
    assert set(offered) == set(parent) - {"act", "ask", "use_skill", "plan", "escalate", "handle_message", "delegate"}
    assert "query_portfolio" in names(loop._tool_schemas(make_context()))        # the owner's list does have it


def test_tools_narrows_the_helpers_reads_and_a_call_outside_them_is_refused(on, by_symbol):
    model = install(on, [step(calls=[delegate("d1", "只许查财务", tools=["query_financials", "calculate"])]), step(text="好")],
                    {"只许查财务": [step(calls=[call("h1", "web_research", {"query": "x"}), call("h2", "query_financials", {"symbol": "NVDA"})]), step(text="查到了 [1]")]})
    run_turn()
    (first, second) = model.helper_calls()
    assert first["tools"] == ["query_financials", "calculate"]
    seen = reports(second["messages"])
    assert seen["h1"]["error_code"] == "tool_not_in_bot_scope" and seen["h2"]["ok"]
    assert by_symbol.invoked == [("query_financials", {"symbol": "NVDA"})]


# --- what comes back --------------------------------------------------------------------------------------------------------------

def test_a_finished_helper_returns_its_report_sources_in_order_steps_and_complete(on, by_symbol):
    model = install(on, [step(calls=[delegate("d1", "两家公司")]), step(text="好")],
                    {"两家公司": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"}), call("h2", "query_financials", {"symbol": "AMD"})]),
                                step(calls=[call("h3", "query_financials", {"symbol": "NVDA"})]), step(text="NVDA [1]，AMD [2]")]})
    result, _ = run_turn()
    got = reports(model.parent_calls()[1]["messages"])["d1"]
    assert got == {"ok": True, "data": {"report": "NVDA [1]，AMD [2]", "sources": [1, 2], "steps": 3, "complete": True}}
    assert [c["symbol"] for c in result["citations"]] == ["NVDA", "AMD"]


def test_the_step_cap_makes_one_closing_step_that_answers_from_what_it_has(on, by_symbol):
    on.monkeypatch.setattr(helper, "HELPER_MAX_STEPS", 2)
    model = install(on, [step(calls=[delegate("d1", "查不完")]), step(text="好")],
                    {"查不完": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), step(calls=[call("h2", "query_financials", {"symbol": "AMD"})]),
                              step(text="只看到这些 [1][2]")]})
    run_turn()
    closing = model.helper_calls()[2]["messages"]
    assert closing[-1] == {"role": "system", "content": loop.CAP_NOTE}
    got = reports(model.parent_calls()[1]["messages"])["d1"]["data"]
    assert got["report"] == "只看到这些 [1][2]" and got["sources"] == [1, 2] and got["complete"] is False and got["steps"] == 3


def test_the_time_cap_also_ends_in_a_closing_step(on, by_symbol):
    on.monkeypatch.setattr(helper, "HELPER_SECONDS", 0)
    model = install(on, [step(calls=[delegate("d1", "没时间")]), step(text="好")], {"没时间": [step(text="来不及查，没有资料")]})
    run_turn()
    (only,) = model.helper_calls()
    assert only["messages"][-1] == {"role": "system", "content": loop.CAP_NOTE}
    got = reports(model.parent_calls()[1]["messages"])["d1"]["data"]
    assert got["complete"] is False and got["report"] == "来不及查，没有资料"


def test_an_empty_closing_step_gives_a_report_built_by_code_from_the_sources(on, by_symbol):
    on.monkeypatch.setattr(helper, "HELPER_MAX_STEPS", 1)
    model = install(on, [step(calls=[delegate("d1", "x")]), step(text="好")],
                    {"x": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), step(text="")]})
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])["d1"]["data"]
    assert got["complete"] is False and got["sources"] == [1] and got["report"] == "还没写总结，已拿到的资料见 [1]。"


# --- Review Focus 4: the helper's model fails ----------------------------------------------------------------------------------

def test_a_helper_whose_model_fails_gives_helper_failed_and_the_turn_answers_on_its_own_without_a_backup_switch(on, by_symbol):
    asked = []
    on.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: asked.append(owner_hash) or {"provider": "x", "model": "y", "api_key": "k", "name": "reserve"})
    on.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    failing = provider.ProviderFailure("provider_error", stage="decision", retryable=False)
    model = install(on, [step(calls=[delegate("d1", "会失败")]), step(text="自己查了：没有。")],
                    {"会失败": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), failing]})
    result, _ = run_turn()
    got = reports(model.parent_calls()[1]["messages"])["d1"]
    assert got == {"ok": False, "error_code": "helper_failed", "hint": "小助手没有做成，可以自己查。", "data": {"sources": [1]}}
    assert result["status"] == "succeeded" and result["answer"] == "自己查了：没有。"
    assert "fallback" not in result["audit"] and "fallback_model" not in result["final_protocol"] and asked == []
    assert [c["symbol"] for c in result["citations"]] == ["NVDA"]            # what it read before the failure stays usable
    assert {c["model"] for c in model.calls} == {"m"}


def test_a_provider_timeout_inside_the_helper_does_not_ask_for_or_switch_to_a_backup(on):
    on.monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)
    on.monkeypatch.setattr(loop.roles, "fallback_for", lambda owner_hash: {"provider": "openrouter", "model": "backup", "api_key": "k", "name": "reserve"})
    timeout = provider.ProviderFailure("provider_timeout", stage="decision", retryable=True)
    model = install(on, [step(calls=[delegate("d1", "超时")]), step(text="自己答")], {"超时": [timeout]})
    result, _ = run_turn()
    assert reports(model.parent_calls()[1]["messages"])["d1"]["error_code"] == "helper_failed"
    assert "fallback" not in result["audit"] and {c["model"] for c in model.calls} == {"m"}


# --- Review Focus 3: the owner speaks while a helper works ---------------------------------------------------------------------

def test_a_message_from_the_owner_stops_the_helper_before_its_next_step_and_the_turn_ends_stopped(on):
    box = inboxes.Inbox("t1", "own-1")
    held = []

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        if not held:       # 「算了」 arrives while the helper's first read is out
            message = inboxes.Message(id="m0000000-0000-0000-0000-000000000001", text="算了", turn_id="t2", future=asyncio.get_running_loop().create_future())
            assert box.put(message)
            held.append(message)
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}
    on.monkeypatch.setattr(tools, "invoke", invoke)
    model = install(on, [
        step(calls=[delegate("d1", "三步的活")]),
        lambda messages: step(calls=[call("h", inboxes.HANDLE, {"message_id": held[0].id[:8], "decision": "stop", "note": "好的，不查了。"})])],
        {"三步的活": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), step(calls=[call("h2", "query_financials", {"symbol": "AMD"})]), step(text="不会走到")]})
    result, events = run_turn(make_context(inbox=box, conversation_id="conv", bot_id="bot-1"))
    assert len(model.helper_calls()) == 1                                    # it did not take its second step
    got = reports(model.parent_calls()[1]["messages"])["d1"]["data"]
    assert got["complete"] is False and got["sources"] == [1] and got["steps"] == 1 and "[1]" in got["report"]
    assert result["status"] == "stopped" and result["answer"].endswith("好的，不查了。")
    assert [c["symbol"] for c in result["citations"]] == ["NVDA"]            # a stop discards nothing the helper read
    (call_made,) = model.helper_calls()
    assert call_made["tags"] == {"purpose": "helper", "owner_hash": "o", "conversation_id": "conv", "turn_id": "t1", "bot_id": "bot-1"}
    assert result["audit"]["helpers"][0]["complete"] is False


# --- records -------------------------------------------------------------------------------------------------------------------

def test_the_audit_lists_each_helper_and_the_totals_include_its_model_calls_and_tokens(on, by_symbol):
    usage = {"total_tokens": 7, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1}
    model = install(on, [step(calls=[delegate("d1", "查")]), step(text="好")],
                    {"查": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"}), call("h2", "calculate", {"operation": "add", "inputs": []})], usage=usage),
                            step(text="完 [1]", usage=usage)]})
    result, _ = run_turn()
    audit = result["audit"]
    (line,) = audit["helpers"]
    assert set(line) == {"call_id", "model", "steps", "model_calls", "token_usage", "complete", "seconds", "tools"}
    assert (line["call_id"], line["model"], line["steps"], line["model_calls"], line["token_usage"], line["complete"]) == ("d1", "anthropic/m", 2, 2, 14, True)
    assert line["tools"] == ["query_financials", "calculate"] and isinstance(line["seconds"], (int, float))
    assert audit["model_calls"] == 4 and audit["token_usage"] == 10 + 10 + 7 + 7      # the parent's two calls and the helper's two
    assert audit["cache_read_tokens"] == 0 + 4 and audit["cache_write_tokens"] == 2
    assert len(audit["calls"]) == 2                  # the parent's own model lines (the backstage matches them to chat rows)
    timeline = [(e["kind"], e.get("call_id")) for e in audit["timeline"] if e["kind"].startswith("helper")]
    assert timeline == [("helper_start", "d1"), ("helper_done", "d1")]


def test_the_helpers_model_calls_are_tagged_for_the_ledger_with_the_parents_owner_and_turn(on):
    model = install(on, [step(calls=[delegate("d1", "查")]), step(text="好")], {"查": [step(text="无")]})
    run_turn(make_context(conversation_id="conv", bot_id="bot-9"))
    (made,) = model.helper_calls()
    assert made["tags"] == {"purpose": "helper", "owner_hash": "o", "conversation_id": "conv", "turn_id": "t1", "bot_id": "bot-9"}
    assert all(c["tags"].get("purpose") != "helper" for c in model.parent_calls())
    assert "helper" in model_usage.PURPOSES
    assert made["kwargs"]["reasoning_effort"] == loop.tiers.EFFORT["low"]


def test_nothing_of_the_helper_but_its_narration_reaches_the_client(on, by_symbol):
    model = install(on, [step(calls=[delegate("d1", "查财务", say="让小助手查一下")]), step(text="好")],
                    {"查财务": [step(text="我先想想", pieces=["我先", "想想"], calls=[call("h1", "query_financials", {"symbol": "NVDA"})]),
                              step(pieces=["最终", "报告"], text="最终报告 [1]")]})
    result, events = run_turn()
    seen = [e["event"] for e in events]
    tool_starts = [e["call_id"] for e in events if e["event"] == "tool_start"]
    assert tool_starts == ["d1"] and [e["call_id"] for e in events if e["event"] == "tool_result"] == ["d1"]
    assert "最终" not in "".join(e.get("text", "") for e in events if e["event"] == "delta")
    assert "我先" not in json.dumps([e for e in events if e["event"] != "tool_result"], ensure_ascii=False)       # (the report itself is in the delegate's result)
    helper_lines = [e["text"] for e in events if e["event"] == "narration" and e["text"].startswith("小助手：")]
    assert helper_lines == ["小助手：正在查财务数据。"] and "小助手：正在查财务数据。" in result["final_protocol"]["narration"]
    assert [e["text"] for e in events if e["event"] == "narration"][0] == "让小助手查一下"        # the delegate call's own say, like any tool's
    assert "answer_reset" not in seen            # the helper's text, written and dropped inside the helper, never reaches the page


def test_the_helper_does_not_pause_its_text_for_the_parents_inbox(on):
    box = inboxes.Inbox("t1")
    on.monkeypatch.setattr(loop, "_streams", lambda use: True)
    model = install(on, [step(calls=[delegate("d1", "写")]), step(text="好")], {"写": [step(pieces=["a", "b"], text="ab")]})
    run_turn(make_context(inbox=box))
    assert reports(model.parent_calls()[1]["messages"])["d1"]["data"]["report"] == "ab"


def test_a_bad_delegate_call_is_refused_without_running_a_helper(on):
    model = install(on, [step(calls=[call("d1", "delegate", {}), call("d2", "delegate", {"brief": "  "}), call("d3", "delegate", {"brief": "x", "extra": 1}),
                                    call("d4", "delegate", "{not json")]), step(text="好")])
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])
    assert all(got[f"d{n}"]["ok"] is False and got[f"d{n}"]["error_code"] == "invalid_arguments" for n in range(1, 5))
    assert model.helper_calls() == []


def test_the_helper_gets_a_fixed_chinese_system_text_with_the_date_and_the_brief_as_the_user_message(on):
    model = install(on, [step(calls=[delegate("d1", "查 NVDA 的 capex，只要数字")]), step(text="好")], {"查 NVDA 的 capex，只要数字": [step(text="无")]})
    run_turn()
    (made,) = model.helper_calls()
    system, user = made["messages"]
    assert system["role"] == "system" and system["content"].startswith("你是 FinBot 的小助手") and "[n]" in system["content"]
    from datetime import date
    assert date.today().isoformat() in system["content"]
    assert user == {"role": "user", "content": "查 NVDA 的 capex，只要数字"}


# --- the model of the helper ---------------------------------------------------------------------------------------------------

@pytest.fixture
def two_models(owner):
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.commit()
    for name in ("alpha", "bravo"):
        catalog.save_entry(name, display_name=name, provider="deepseek", model=f"m-{name}", api_key=KEY_A, is_default=name == "alpha", create=True)
    yield owner
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()


def parent_run(model=None, owner_hash=OWNER_HASH):
    return loop._Run(context=make_context(owner_hash=owner_hash), emit=lambda e: asyncio.sleep(0), messages=[], user_text="", schemas=[], tool_names=frozenset(),
                     model=model or loop.ModelUse("anthropic", "m", "k", None, None))


def test_the_helper_role_is_a_role_with_no_default_unset_means_the_parents_model(two_models):
    assert "helper" in roles.ROLES and roles.all_roles(OWNER_HASH)["helper"] is None
    assert roles.helper_for(OWNER_HASH) is None
    with pytest.raises(roles.RoleError, match="role_has_no_default"):
        roles.resolve_with_source(OWNER_HASH, "helper")
    parent = parent_run(loop.ModelUse("anthropic", "parent-model", "pk", None, "parent"))
    assert asyncio.run(helper.model_for(parent)) is parent.model
    roles.set_role(OWNER_HASH, "helper", "bravo")
    chosen = asyncio.run(helper.model_for(parent))
    assert (chosen.provider, chosen.model, chosen.name) == ("deepseek", "m-bravo", "bravo")
    with SessionLocal() as db:           # the entry leaves the catalog: the row stays, the parent's model is used again
        db.query(AgentModelEntry).filter_by(name="bravo").delete()
        db.commit()
    assert roles.get(OWNER_HASH, "helper") == "bravo" and roles.helper_for(OWNER_HASH) is None
    assert asyncio.run(helper.model_for(parent)) is parent.model
    roles.set_role(OWNER_HASH, "helper", None)


def test_once_the_turn_is_on_its_backup_the_helper_uses_the_backup(two_models):
    backup = loop.ModelUse("openrouter", "backup-model", "bk", "https://b.example/v1", "reserve")
    assert asyncio.run(helper.model_for(parent_run(backup))) is backup


def test_the_role_is_settable_by_the_set_model_role_tool_and_has_a_row_in_the_lists(two_models):
    from app.agent_tool_catalog import validate
    assert validate("set_model_role", {"role": "helper", "model": "bravo"})["role"] == "helper"
    roles.check_role("helper", "bravo")
    from app.agent_workflow import directory_ops
    assert "helper" in directory_ops.ROLE_WORDS and directory_ops.ROLE_WORDS["helper"][0] == "小助手"
    info = asyncio.run(tools._dispatch("list_models", {}, SimpleNamespace(owner_hash=OWNER_HASH), True, None))
    assert info["data"][0]["roles"]["helper"]["model"] is None and "note" in info["data"][0]["roles"]["helper"]


def test_the_helper_runs_on_the_roles_model_when_the_owner_has_set_one(on, by_symbol):
    on.monkeypatch.setattr(helper.roles, "helper_for", lambda owner_hash: {"provider": "deepseek", "model": "m-bravo", "api_key": "bk", "base_url": None, "name": "bravo"})
    model = install(on, [step(calls=[delegate("d1", "查")]), step(text="好")], {"查": [step(text="无")]})
    result, _ = run_turn()
    (made,) = model.helper_calls()
    assert (made["provider"], made["model"], made["kwargs"].get("catalog_name")) == ("deepseek", "m-bravo", "bravo")
    assert {c["model"] for c in model.parent_calls()} == {"m"} and result["audit"]["helpers"][0]["model"] == "bravo"


# --- the backstage turn detail -------------------------------------------------------------------------------------------------

def test_the_backstage_lists_each_helper_in_one_line_and_does_not_expect_chat_rows_for_its_calls():
    from app import backstage_api
    audit = {"model_calls": 5, "calls": [{}, {}, {}], "helpers": [
        {"call_id": "d1", "model": "bravo", "steps": 3, "model_calls": 2, "token_usage": 10, "complete": True, "seconds": 4.2, "tools": ["query_financials"]},
        "junk"]}
    lines = backstage_api._helpers(audit)
    assert lines == [{"call_id": "d1", "model": "bravo", "steps": 3, "model_calls": 2, "tokens": 10, "complete": True, "seconds": 4.2, "tools": ["query_financials"]}]
    assert backstage_api._expected_chat_calls(audit, audit["calls"]) == 3
    assert backstage_api._expected_chat_calls({"model_calls": 4, "calls": [{}] * 4}, [{}] * 4) == 4
    assert backstage_api._expected_chat_calls({"calls": [{}] * 2}, [{}] * 2) == 2 and backstage_api._helpers({}) == []


# --- fix round 1 -----------------------------------------------------------------------------------------------------------------

def test_a_helper_that_ran_a_web_read_and_then_failed_still_puts_a_later_tier_1_write_on_the_card(on, by_symbol, fake_consent):
    failing = provider.ProviderFailure("provider_error", stage="decision", retryable=False)
    model = install(on, [step(calls=[delegate("d1", "上网看看")]),
                         step(calls=[act_call("a1", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="已放进确认卡。")],
                    {"上网看看": [step(calls=[call("h1", "web_research", {"query": "NVDA"})]), failing]})
    result, _ = run_turn(make_context(conversation_id="conv"))
    assert reports(model.parent_calls()[1]["messages"])["d1"]["error_code"] == "helper_failed"
    assert fake_consent.executed == [] and len(fake_consent.proposed) == 1          # it went onto the card, not out at once
    assert result["status"] == "waiting_for_input" and result["pending_request"]


def test_a_delegate_refused_before_running_does_not_make_a_later_tier_1_write_wait(on, fake_consent):
    model = install(on, [step(calls=[call("d1", "delegate", {"brief": "x", "tools": ["act"]})]),
                         step(calls=[act_call("a1", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="好")])
    run_turn(make_context(conversation_id="conv"))
    assert model.helper_calls() == [] and len(fake_consent.executed) == 1       # ran at once


def test_a_refused_delegate_takes_no_slot(on, by_symbol):
    briefs = ["查一", "查二", "查三"]
    calls = [call("bad", "delegate", {"brief": "x", "tools": ["act"]}), *(delegate(f"d{n}", b) for n, b in enumerate(briefs))]
    model = install(on, [step(calls=calls), step(text="好")], {b: [step(text="无")] for b in briefs})
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])
    assert got["bad"]["error_code"] == "tool_not_in_bot_scope" and all(got[f"d{n}"]["ok"] for n in range(3))


def test_the_time_cap_is_hard_a_slow_model_call_ends_in_a_bounded_closing_step_and_a_built_report(on, by_symbol):
    on.monkeypatch.setattr(helper, "HELPER_SECONDS", 0.3)
    on.monkeypatch.setattr(helper, "CLOSING_SECONDS", 0.3)
    model = install(on, [step(calls=[delegate("d1", "慢")]), step(text="好")],
                    {"慢": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), {**step(text="太慢了"), "sleep": 5}, {**step(text="也太慢"), "sleep": 5}]})
    began = time.monotonic()
    result, _ = run_turn()
    assert time.monotonic() - began < 3
    got = reports(model.parent_calls()[1]["messages"])["d1"]
    assert got == {"ok": True, "data": {"report": "还没写总结，已拿到的资料见 [1]。", "sources": [1], "steps": got["data"]["steps"], "complete": False}}
    assert result["status"] == "succeeded"


def test_a_slow_tool_step_is_cut_and_the_closing_step_sees_a_valid_message_list(on):
    on.monkeypatch.setattr(helper, "HELPER_SECONDS", 0.3)

    async def slow(name, args, context, *, emit=None, page_chars=None):
        await asyncio.sleep(5)
    on.monkeypatch.setattr(tools, "invoke", slow)
    model = install(on, [step(calls=[delegate("d1", "慢工具")]), step(text="好")],
                    {"慢工具": [step(calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), step(text="没查到")]})
    run_turn()
    closing = model.helper_calls()[-1]["messages"]
    assert closing[-1]["content"] == loop.CAP_NOTE and all(m.get("tool_calls") is None for m in closing if m["role"] == "assistant")
    got = reports(model.parent_calls()[1]["messages"])["d1"]["data"]
    assert got["report"] == "没查到" and got["complete"] is False


def test_mid_step_chatter_is_not_a_report_and_a_failed_closing_step_gives_the_built_report(on, by_symbol):
    on.monkeypatch.setattr(helper, "HELPER_MAX_STEPS", 1)
    failing = provider.ProviderFailure("provider_error", stage="decision", retryable=False)
    model = install(on, [step(calls=[delegate("d1", "x"), delegate("d2", "y")]), step(text="好")],
                    {"x": [step(text="让我搜一下", calls=[call("h1", "query_financials", {"symbol": "NVDA"})]), failing],
                     "y": [step(text="让我搜一下", calls=[call("h2", "query_financials", {"symbol": "AMD"})]), step(text="")]})
    run_turn()
    got = reports(model.parent_calls()[1]["messages"])
    assert got["d1"]["ok"] and got["d1"]["data"]["complete"] is False and got["d1"]["data"]["report"].startswith("还没写总结")
    assert got["d2"]["data"]["report"].startswith("还没写总结") and "让我搜一下" not in json.dumps(got, ensure_ascii=False)


def test_a_failed_closing_step_without_any_source_is_helper_failed(on):
    on.monkeypatch.setattr(helper, "HELPER_SECONDS", 0)
    failing = provider.ProviderFailure("provider_error", stage="decision", retryable=False)
    model = install(on, [step(calls=[delegate("d1", "x")]), step(text="好")], {"x": [failing]})
    run_turn()
    assert reports(model.parent_calls()[1]["messages"])["d1"]["error_code"] == "helper_failed"


def test_the_helper_is_given_the_read_schemas_without_say_and_item(on):
    model = install(on, [step(calls=[delegate("d1", "x")]), step(text="好")], {"x": [step(text="无")]})
    run_turn()
    seen = {}

    async def spy(*args, **kwargs):
        seen["schemas"] = args[4]
        return {"usage": {}}, {"role": "assistant", "content": "无"}
    schemas = helper.helper_schemas(loop._tool_schemas(make_context()), None)
    assert schemas and all(not {"say", "item"} & set(s["function"]["parameters"].get("properties", {})) for s in schemas)
    assert names(schemas) == [n for n in names(loop._tool_schemas(make_context())) if n not in helper.OWN_TOOLS]
