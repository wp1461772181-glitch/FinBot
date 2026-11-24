"""Live progress: ``say`` on every tool, narration events, and the ``plan`` checklist."""
import copy
import json

from app.agent_workflow import tools
from app.kernel import loop, progress, toolrun
from tests.test_kernel_loop import Script, call, env, kinds, make_context, run, script, step  # noqa: F401  (env is a fixture)

SAY = progress.SAY_DESCRIPTION


def test_with_say_adds_say_then_item():
    original = {"type": "function", "function": {"name": "t", "description": "d", "parameters": {
        "type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}}}
    before = copy.deepcopy(original)
    shown = progress.with_say(original)
    assert original == before                       # not modified
    parameters = shown["function"]["parameters"]
    assert list(parameters["properties"]) == ["say", "item", "a"]
    assert parameters["properties"]["say"] == {"type": "string", "description": SAY}
    assert parameters["properties"]["item"] == {"type": "integer", "description": progress.ITEM_DESCRIPTION}
    assert parameters["required"] == ["a"]          # say and item are optional
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


def test_take_progress_cleans_item():
    assert progress.take_progress({"say": " 查 ", "item": 2, "symbol": "A"}) == ("查", 2, {"symbol": "A"})
    for bad in (0, -1, "2", True, 2.5, None):
        assert progress.take_progress({"item": bad, "k": 1}) == (None, None, {"k": 1})
    arguments = {"say": "x", "item": 1}
    progress.take_progress(arguments)
    assert arguments == {"say": "x", "item": 1}


def test_clean_plan_tolerates_garbage():
    assert progress.clean_plan("nope") == [] and progress.clean_plan(None) == [] and progress.clean_plan({"text": "a"}) == []
    assert progress.clean_plan([{"status": "done"}, "x", 3, {"text": "  "}]) == []
    assert progress.clean_plan([{"text": " 查财报 ", "status": "weird"}, {"text": "写结论"}, {"text": "好", "status": "done"}]) == [
        {"text": "查财报", "status": "pending"}, {"text": "写结论", "status": "pending"}, {"text": "好", "status": "done"}]
    many = progress.clean_plan([{"text": f"项目{i}", "status": "doing"} for i in range(30)])
    assert len(many) == progress.PLAN_MAX_ITEMS == 12
    assert len(progress.clean_plan([{"text": "长" * 100}])[0]["text"]) == 60


def test_plan_status_is_optional_and_described():
    item = progress.PLAN_SCHEMA["function"]["parameters"]["properties"]["items"]["items"]
    assert item["required"] == ["text"] and "status" in item["properties"]
    assert "status 可以不填：新项默认 pending，没改动的项保持原来的状态；只有要把某项标成 failed 或 done 时才写。" in progress.PLAN_SCHEMA["function"]["description"]


def test_clean_plan_keeps_previous_status_by_text():
    previous = [{"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}]
    assert progress.clean_plan([{"text": "甲"}, {"text": "乙"}, {"text": "丙"}], previous) == [
        {"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}, {"text": "丙", "status": "pending"}]
    assert progress.clean_plan([{"text": "甲", "status": "failed"}, {"text": "乙", "status": "bogus"}], previous) == [
        {"text": "甲", "status": "failed"}, {"text": "乙", "status": "doing"}]
    assert progress.clean_plan([{"text": "甲"}]) == [{"text": "甲", "status": "pending"}]


def test_replan_without_statuses_keeps_ticks_and_shows_the_numbered_list(env):
    first = [{"text": "甲", "status": "pending"}, {"text": "乙", "status": "pending"}]
    again = [{"text": "甲"}, {"text": "乙"}, {"text": "丙"}]
    fake = script(env, [step(calls=[call("c1", "plan", {"items": first})]),
                        step(calls=[call("c2", "query_financials", {"item": 1, "symbol": "AAPL"})]),
                        step(calls=[call("c3", "query_financials", {"item": 2, "symbol": "AAPL"})]),
                        step(calls=[call("c4", "plan", {"items": again})]), step(text="好")])
    result, events = run()
    lists = [e["items"] for e in events if e["event"] == "checklist"]
    assert lists[-2] == [{"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}, {"text": "丙", "status": "pending"}]
    seen = json.loads(fake.calls[4]["messages"][-1]["content"])
    assert seen == {"ok": True, "items": [{"n": 1, "text": "甲", "status": "done"}, {"n": 2, "text": "乙", "status": "doing"},
                                          {"n": 3, "text": "丙", "status": "pending"}]}


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
    assert json.loads(fake.calls[1]["messages"][-1]["content"]) == {
        "ok": True, "items": [{"n": 1, "text": "查财报", "status": "doing"}, {"n": 2, "text": "写结论", "status": "pending"}]}


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
    assert seen[:2] == ["checklist", "read"]
    assert [e["call_id"] for e in events if e["event"] == "tool_result"] == ["c1", "c2"]


def tools_ok():
    from tests.test_kernel_loop import OK_ROWS
    return OK_ROWS


def test_plan_updates_replace_the_list(env):
    first = [{"text": "甲", "status": "doing"}, {"text": "乙", "status": "pending"}]
    second = [{"text": "甲", "status": "done"}, {"text": "乙", "status": "doing"}]
    script(env, [step(calls=[call("c1", "plan", {"items": first})]), step(calls=[call("c2", "plan", {"items": second})]), step(text="好")])
    result, events = run()
    assert [e["items"] for e in events if e["event"] == "checklist"][:2] == [first, second]
    # the turn ends with an answer: the item still "doing" is closed
    assert result["final_protocol"]["checklist"] == [{"text": "甲", "status": "done"}, {"text": "乙", "status": "done"}]


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
            assert list(properties)[:2] == ["say", "item"] and properties["say"]["description"] == SAY
            assert "say" not in schema["function"]["parameters"].get("required", [])
        names = [s["function"]["name"] for s in schemas]
        assert names[-2:] == ["plan", "escalate"] and set(names[:-2]) <= set(loop.READ_TOOLS) and names[:-2]
    assert fake.calls[0]["tools"] == fake.calls[1]["tools"]


def checklists(events):
    return [[i["status"] for i in e["items"]] for e in events if e["event"] == "checklist"]


def plan3(*statuses):
    return [{"text": t, "status": st} for t, st in zip("甲乙丙", statuses or ("pending",) * 3)]


def test_item_never_reaches_the_tool(env):
    script(env, [step(calls=[call("c1", "query_financials", {"say": "看", "item": 1, "symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert env.invoked == [("query_financials", {"symbol": "AAPL"})]
    assert all(set(e["arguments"]) == {"symbol"} for e in events if e["event"] == "tool_start")


def test_labelled_calls_tick_the_list(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3()}), call("c2", "query_financials", {"item": 1, "symbol": "AAPL"})]),
                 step(calls=[call("c3", "query_financials", {"item": 2, "symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert checklists(events) == [["doing", "pending", "pending"], ["done", "doing", "pending"], ["done", "done", "done"]]


def test_first_checklist_event_of_a_step_is_single_and_before_the_reads(env):
    order = []

    async def read(name, args, context, *, emit=None, page_chars=None):
        order.append("read")
        return copy.deepcopy(tools_ok())

    env.monkeypatch.setattr(tools, "invoke", read)
    script(env, [step(calls=[call("c1", "plan", {"items": plan3()}), call("c2", "query_financials", {"item": 1, "symbol": "AAPL"})]), step(text="好")])
    events = []

    async def emit(event):
        events.append(event)
        if event["event"] == "checklist":
            order.append("checklist")

    import asyncio
    asyncio.run(loop.run_turn("问题", make_context(), emit, [{"role": "system", "content": "e"}, {"role": "user", "content": "问题"}], {}))
    first_step = events[:[e["event"] for e in events].index("tool_result")]
    assert [e["event"] for e in first_step].count("checklist") == 1
    assert order[:2] == ["checklist", "read"]


def test_unlabelled_turn_closes_the_whole_list(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3("doing", "pending", "pending")})]),
                 step(calls=[call("c2", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    result, events = run()
    assert checklists(events) == [["doing", "pending", "pending"], ["done", "done", "done"]]
    assert [i["status"] for i in result["final_protocol"]["checklist"]] == ["done"] * 3


def test_item_skipped_stays_unticked(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3()})]),
                 step(calls=[call("c2", "query_financials", {"item": 1, "symbol": "AAPL"})]),
                 step(calls=[call("c3", "query_financials", {"item": 3, "symbol": "AAPL"})]), step(text="好")])
    result, events = run()
    assert [i["status"] for i in result["final_protocol"]["checklist"]] == ["done", "pending", "done"]


def test_failed_item_is_kept(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3("doing", "failed", "pending")})]), step(text="好")])
    result, _ = run()
    assert [i["status"] for i in result["final_protocol"]["checklist"]] == ["done", "failed", "done"]


def test_invalid_item_numbers_change_nothing(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3()})]),
                 step(calls=[call("c2", "query_financials", {"item": 9, "symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    second = events[[e["event"] for e in events].index("checklist") + 1:]
    assert [e["event"] for e in second].count("checklist") == 1      # only the closing one
    assert checklists(events)[0] == ["pending"] * 3


def test_no_checklist_no_checklist_events(env):
    script(env, [step(calls=[call("c1", "query_financials", {"item": 1, "symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert "checklist" not in kinds(events)


def test_failure_does_not_close_the_list(env):
    script(env, [step(calls=[call("c1", "plan", {"items": plan3("doing", "pending", "pending")})]), step(text=""), step(text="")])
    result, events = run()
    assert result["status"] == "failed"
    assert checklists(events) == [["doing", "pending", "pending"]]


def test_plain_sentence_when_the_model_says_nothing(env):
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "query_market_quote", {"symbol": "AAPL"})]),
                 step(text="好")])
    result, events = run()
    assert events[0] == {"event": "narration", "text": "正在查财务数据、查最新报价。", "system": True}
    assert result["final_protocol"]["narration"] == ["正在查财务数据、查最新报价。"]


def test_no_plain_sentence_for_own_calls_only(env):
    script(env, [step(calls=[call("c1", "escalate", {"depth": "mid"})]), step(text="好")])
    _, events = run()
    assert "narration" not in kinds(events)


def test_narration_carries_the_item_of_the_call_that_spoke(env):
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"}),
                             call("c2", "web_research", {"say": "上网看看", "item": 2, "query": "x"})]), step(text="好")])
    _, events = run()
    assert events[0] == {"event": "narration", "text": "上网看看", "item": 2}


def test_phrase_helpers():
    assert progress.plain_sentence(["plan", "escalate"]) is None
    assert progress.slow_sentence(["escalate"]) is None
    assert progress.plain_sentence(["query_financials", "query_financials", "web_research", "calculate", "query_portfolio"]) == "正在查财务数据、上网搜索、算数。"
    assert progress.slow_sentence(["web_research", "web_research", "query_financials"]) == "上网搜索、查财务数据还没回来，还在等。"


def test_every_read_tool_has_a_phrase():
    assert set(loop.READ_TOOLS) <= set(progress.TOOL_PHRASES)


def test_slow_step_says_what_it_waits_for(env):
    import asyncio

    async def read(name, args, context, *, emit=None, page_chars=None):
        if name == "web_research":
            await asyncio.sleep(0.3)
        return copy.deepcopy(tools_ok())

    env.monkeypatch.setattr(tools, "invoke", read)
    env.monkeypatch.setattr(toolrun, "SLOW_SECONDS", 0.05)
    script(env, [step(calls=[call("c1", "web_research", {"say": "上网查", "query": "x"}), call("c2", "query_financials", {"symbol": "AAPL"})]),
                 step(calls=[call("c3", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    result, events = run()
    system = [(i, e) for i, e in enumerate(events) if e["event"] == "narration" and "还在等" in e["text"]]
    assert [e["text"] for _, e in system] == ["上网搜索还没回来，还在等。"]
    first_narration = next(i for i, e in enumerate(events) if e["event"] == "narration")
    first_result = next(i for i, e in enumerate(events) if e["event"] == "tool_result")
    assert first_narration < system[0][0] < first_result
    assert [e["call_id"] for e in events if e["event"] == "tool_result"][:2] == ["c1", "c2"]
    assert result["final_protocol"]["narration"] == ["上网查", "上网搜索还没回来，还在等。", "正在查财务数据。"]


def test_fast_step_has_no_slow_sentence(env):
    env.monkeypatch.setattr(toolrun, "SLOW_SECONDS", 5)
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]), step(text="好")])
    _, events = run()
    assert not [e for e in events if e["event"] == "narration" and "还在等" in e["text"]]


def test_slow_sentence_names_only_reads_that_have_started(env):
    import asyncio

    async def read(name, args, context, *, emit=None, page_chars=None):
        await asyncio.sleep(0.3)
        return copy.deepcopy(tools_ok())

    env.monkeypatch.setattr(tools, "invoke", read)
    env.monkeypatch.setattr(toolrun, "SLOW_SECONDS", 0.05)
    env.monkeypatch.setattr(toolrun, "MAX_PARALLEL", 2)
    names = ["query_financials", "web_research", "search_knowledge", "query_stock_prices", "query_market_quote"]
    script(env, [step(calls=[call(f"c{i}", name, {"symbol": "AAPL"}) for i, name in enumerate(names)]), step(text="好")])
    _, events = run()
    slow = [e["text"] for e in events if e["event"] == "narration" and "还在等" in e["text"]]
    assert slow == ["查财务数据、上网搜索还没回来，还在等。"]
