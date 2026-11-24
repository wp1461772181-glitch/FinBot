"""Live progress: ``say`` on every tool, narration events, and the ``plan`` checklist."""
import copy
import json

from app.agent_workflow import tools
from app.kernel import loop, progress
from tests.test_kernel_loop import Script, call, env, kinds, make_context, run, script, step  # noqa: F401  (env is a fixture)

SAY = progress.SAY_DESCRIPTION


def test_with_say_adds_an_optional_first_property_and_copies():
    original = {"type": "function", "function": {"name": "t", "description": "d", "parameters": {
        "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}}}
    before = copy.deepcopy(original)
    shown = progress.with_say(original)
    assert original == before                       # not modified
    parameters = shown["function"]["parameters"]
    assert list(parameters["properties"]) == ["say", "a"]
    assert parameters["properties"]["say"] == {"type": "string", "description": SAY}
    assert parameters["required"] == ["a"]          # say is optional
    assert SAY == "用一句话告诉用户你发现了什么、接下来做什么。像人说话，不要出现工具名。"


def test_take_say_cleans_and_strips():
    assert progress.take_say({"say": "  第一行\n第二行  ", "x": 1}) == ("第一行 第二行", {"x": 1})
    said, rest = progress.take_say({"say": "字" * 100})
    assert said == "字" * progress.SAY_MAX == "字" * 80 and rest == {}
    assert progress.take_say({"say": "  \n "}) == (None, {})
    assert progress.take_say({"a": 1}) == (None, {"a": 1})
    assert progress.take_say({"say": 5, "a": 1}) == (None, {"a": 1})
    arguments = {"say": "x"}
    progress.take_say(arguments)
    assert arguments == {"say": "x"}


def test_clean_plan_tolerates_garbage():
    assert progress.clean_plan("nope") == [] and progress.clean_plan(None) == [] and progress.clean_plan({"text": "a"}) == []
    assert progress.clean_plan([{"status": "done"}, "x", 3, {"text": "  "}]) == []
    assert progress.clean_plan([{"text": " 查财报 ", "status": "weird"}, {"text": "写结论"}, {"text": "好", "status": "done"}]) == [
        {"text": "查财报", "status": "pending"}, {"text": "写结论", "status": "pending"}, {"text": "好", "status": "done"}]
    many = progress.clean_plan([{"text": f"项目{i}", "status": "doing"} for i in range(30)])
    assert len(many) == progress.PLAN_MAX_ITEMS == 12
    assert len(progress.clean_plan([{"text": "长" * 100}])[0]["text"]) == 60


def test_first_say_of_a_step_becomes_narration_before_tool_start(env):
    script(env, [step(calls=[call("c1", "query_financials", {"say": "先看财报", "symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert kinds(events) == ["narration", "assistant_tool_request", "tool_start", "tool_result", "delta"]
    assert events[0] == {"event": "narration", "text": "先看财报"}


def test_only_one_narration_per_step(env):
    script(env, [step(calls=[call("c1", "query_financials", {"say": "", "symbol": "AAPL"}),
                             call("c2", "web_research", {"say": "查新闻", "query": "x"}),
                             call("c3", "query_stock_prices", {"say": "看行情", "symbol": "AAPL"})]),
                 step(calls=[call("c4", "query_financials", {"say": "再看一眼", "symbol": "AAPL"})]), step(text="好")])
    result, events = run()
    assert [e["text"] for e in events if e["event"] == "narration"] == ["查新闻", "再看一眼"]
    assert result["final_protocol"]["narration"] == ["查新闻", "再看一眼"]


def test_say_never_reaches_the_tool(env):
    inputs = [{"name": "a", "value": "100", "source_ordinal": 1}, {"name": "b", "value": "40", "source_ordinal": 1}]
    script(env, [step(calls=[call("c1", "query_financials", {"say": "看财报", "symbol": "AAPL"})]),
                 step(calls=[call("c2", "calculate", {"say": "算利润", "expression": "a-b", "inputs": inputs})]), step(text="好")])
    result, events = run()
    assert env.invoked == [("query_financials", {"symbol": "AAPL"})]
    results = {e["call_id"]: e["result"] for e in events if e["event"] == "tool_result"}
    assert results["c1"]["ok"] is True and results["c2"]["ok"] is True      # strict validation did not trip on say
    assert [c["source_type"] for c in result["citations"]] == ["official_filing", "calculation"]
    assert all("say" not in e["arguments"] for e in events if e["event"] == "tool_start")


def test_preamble_text_becomes_narration_when_no_say(env):
    script(env, [step(pieces=["我先", "查一下"], text="我先查一下", calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                 step(text="结果")])
    result, events = run()
    assert kinds(events) == ["delta", "delta", "answer_reset", "narration", "assistant_tool_request", "tool_start", "tool_result", "delta"]
    assert next(e for e in events if e["event"] == "narration")["text"] == "我先查一下"
    deltas = "".join(e["text"] for e in events if e["event"] == "delta")
    assert result["answer"] == "结果" and deltas.endswith("结果")
    assert result["final_protocol"]["narration"] == ["我先查一下"]


def test_say_wins_over_preamble_text(env):
    script(env, [step(text="我先查一下", calls=[call("c1", "query_financials", {"say": "看财报", "symbol": "AAPL"})]), step(text="结果")])
    result, events = run()
    assert [e["text"] for e in events if e["event"] == "narration"] == ["看财报"]
    assert "answer_reset" in kinds(events) and result["answer"] == "结果"


def test_plan_emits_checklist_and_is_not_invoked_as_a_tool(env):
    items = [{"text": "查财报", "status": "doing"}, {"text": "写结论", "status": "pending"}, {"text": "", "status": "done"}]
    fake = script(env, [step(calls=[call("c1", "plan", {"say": "列清单", "items": items})]), step(text="好")])
    result, events = run()
    assert env.invoked == [] and result["citations"] == []
    checklist = next(e for e in events if e["event"] == "checklist")
    assert checklist["items"] == [{"text": "查财报", "status": "doing"}, {"text": "写结论", "status": "pending"}]
    assert kinds(events).index("checklist") < kinds(events).index("tool_result")
    assert json.loads(fake.calls[1]["messages"][-1]["content"]) == {"ok": True, "items": 2}


def test_checklist_is_shown_before_the_reads_of_the_same_step_run(env):
    seen = []

    async def slow_read(name, args, context, *, emit=None, page_chars=None):
        seen.append("read")
        return copy.deepcopy(tools_ok())

    env.monkeypatch.setattr(tools, "invoke", slow_read)
    items = [{"text": "查财报", "status": "doing"}]
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "plan", {"items": items})]), step(text="好")])
    events = []

    async def emit(event):
        events.append(event)
        if event["event"] == "checklist":
            seen.append("checklist")

    import asyncio
    asyncio.run(loop.run_turn("问题", make_context(), emit, [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "问题"}], {}))
    assert seen == ["checklist", "read"]
    assert [e["call_id"] for e in events if e["event"] == "tool_result"] == ["c1", "c2"]


def tools_ok():
    from tests.test_kernel_loop import OK_ROWS
    return OK_ROWS


def test_plan_updates_replace_the_list(env):
    first = [{"text": "甲", "status": "doing"}, {"text": "乙", "status": "pending"}]
    second = [{"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}]
    script(env, [step(calls=[call("c1", "plan", {"items": first})]), step(calls=[call("c2", "plan", {"items": second})]), step(text="好")])
    result, events = run()
    assert [e["items"] for e in events if e["event"] == "checklist"] == [first, second]
    assert result["final_protocol"]["checklist"] == second


def test_final_protocol_carries_narration_checklist_and_tier(env):
    plan = [{"text": "甲", "status": "done"}]
    script(env, [step(calls=[call("c1", "escalate", {"depth": "high", "say": "这题要深想"})]),
                 step(calls=[call("c2", "plan", {"items": plan}), call("c3", "query_financials", {"say": "查财报", "symbol": "AAPL"})]),
                 step(text="好")])
    result, _ = run()
    assert result["final_protocol"] == {"tier": "high", "narration": ["这题要深想", "查财报"], "checklist": plan}
    plain, _ = run_plain(env)
    assert plain["final_protocol"] == {"tier": "low", "narration": [], "checklist": []}


def run_plain(env):
    script(env, [step(text="好")])
    return run()


def test_every_offered_tool_has_say_and_the_set_is_stable(env):
    seen = []

    class Recording(Script):
        async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
            seen.append(copy.deepcopy(schemas))
            return await super().__call__(provider_name, model, api_key, messages, schemas, **kwargs)

    fake = Recording([step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    env.monkeypatch.setattr(loop.provider, "stream_decision", fake)
    run()
    assert len(seen) == 2 and seen[0] == seen[1]
    for schemas in seen:
        for schema in schemas:
            properties = schema["function"]["parameters"]["properties"]
            assert next(iter(properties)) == "say" and properties["say"]["description"] == SAY
            assert "say" not in schema["function"]["parameters"].get("required", [])
        names = [s["function"]["name"] for s in schemas]
        assert names[-2:] == ["plan", "escalate"] and set(names[:-2]) <= set(loop.READ_TOOLS) and names[:-2]
    assert fake.calls[0]["tools"] == fake.calls[1]["tools"]
