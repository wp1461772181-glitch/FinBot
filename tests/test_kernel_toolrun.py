"""Kernel tool execution: concurrent reads, deterministic citation numbering, calculations after the reads.

No network, no database: ``tools.invoke`` is replaced by scripts.
"""
import asyncio
import copy
import json
import time
from types import SimpleNamespace

import pytest

from app.agent_workflow import tools
from app.kernel import toolrun

INPUTS = [{"name": "a", "value": "100", "source_ordinal": 1}, {"name": "b", "value": "40", "source_ordinal": 1}]


def row(row_id, excerpt="Revenue was 100 and cost was 40 (USD billions)."):
    return {"id": row_id, "symbol": "AAPL", "source_type": "official_filing", "excerpt": excerpt}


def call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def make_run(events):
    async def emit(event):
        events.append(event)

    names = frozenset({"query_financials", "web_research", "calculate", "calculate_formula"})
    return SimpleNamespace(context=SimpleNamespace(query_expander=None), emit=emit, user_text="", tool_names=names,
                           citations=[], audit={"tool_calls": 0})


def execute(calls, run=None):
    events = []
    run = run or make_run(events)
    messages = asyncio.run(toolrun.run_step_tools(run, calls))
    return run, messages, events


def install(monkeypatch, handler):
    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        return await handler(name, args)

    monkeypatch.setattr(tools, "invoke", fake_invoke)


def test_non_calculate_calls_run_concurrently(monkeypatch):
    async def handler(name, args):
        await asyncio.sleep(0.2)
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}

    install(monkeypatch, handler)
    started = time.monotonic()
    _, messages, _ = execute([call("c1", "query_financials", {"symbol": "A"}), call("c2", "query_financials", {"symbol": "B"})])
    assert time.monotonic() - started < 0.35
    assert len(messages) == 2


def test_results_and_citations_follow_call_order(monkeypatch):
    async def handler(name, args):
        await asyncio.sleep(args["wait"])
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}

    install(monkeypatch, handler)
    outputs = []
    for _ in range(2):
        run, messages, events = execute([call("c1", "query_financials", {"symbol": "SLOW", "wait": 0.15}),
                                         call("c2", "query_financials", {"symbol": "FAST", "wait": 0})])
        assert [m["tool_call_id"] for m in messages] == ["c1", "c2"]
        assert [e["call_id"] for e in events if e["event"] == "tool_result"] == ["c1", "c2"]
        first, second = (json.loads(m["content"])["data"][0] for m in messages)
        assert first["citation"] == "[1]" and second["citation"] == "[2]"
        assert [c["ordinal"] for c in run.citations] == [1, 2] and [c["source_id"] for c in run.citations] == ["SLOW", "FAST"]
        outputs.append([m["content"] for m in messages])
    assert outputs[0] == outputs[1]


def test_one_failure_does_not_affect_the_other(monkeypatch):
    async def handler(name, args):
        if args["symbol"] == "BAD":
            raise RuntimeError("secret detail")
        return {"ok": True, "data": [row("r1")], "source": "saved"}

    install(monkeypatch, handler)
    _, messages, events = execute([call("c1", "query_financials", {"symbol": "BAD"}), call("c2", "query_financials", {"symbol": "OK"})])
    bad, good = (json.loads(m["content"]) for m in messages)
    assert bad["error_code"] == "tool_failed" and "secret" not in messages[0]["content"]
    assert good["data"][0]["citation"] == "[1]"
    assert [e["result"].get("error_code") for e in events if e["event"] == "tool_result"][0] == "tool_failed"


def test_parallelism_is_capped(monkeypatch):
    live = {"now": 0, "peak": 0}

    async def handler(name, args):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}

    install(monkeypatch, handler)
    _, messages, _ = execute([call(f"c{i}", "query_financials", {"symbol": f"S{i}"}) for i in range(6)])
    assert len(messages) == 6 and 1 < live["peak"] <= toolrun.MAX_PARALLEL


def test_calculate_runs_after_and_sees_citations(monkeypatch):
    order = []

    async def handler(name, args):
        await asyncio.sleep(0.05)
        order.append("query")
        return {"ok": True, "data": [row("r1")], "source": "saved"}

    install(monkeypatch, handler)
    original = toolrun._calculate

    def spy(run, name, args):
        order.append("calculate")
        return original(run, name, args)

    monkeypatch.setattr(toolrun, "_calculate", spy)
    # The calculation is listed first, yet it must run after the query has been numbered.
    run, messages, _ = execute([call("c1", "calculate", {"expression": "a-b", "inputs": INPUTS}),
                                call("c2", "query_financials", {"symbol": "AAPL"})])
    assert order == ["query", "calculate"]
    assert [c["source_type"] for c in run.citations] == ["official_filing", "calculation"]
    assert [m["tool_call_id"] for m in messages] == ["c1", "c2"]
    assert json.loads(messages[0]["content"])["data"][0]["citation"] == "[2]"


def test_tool_start_events_precede_all_results(monkeypatch):
    async def handler(name, args):
        return {"ok": True, "data": [row(args["symbol"])], "source": "saved"}

    install(monkeypatch, handler)
    _, _, events = execute([call("c1", "query_financials", {"symbol": "A"}), call("c2", "calculate", {"expression": "a", "inputs": []}),
                            call("c3", "query_financials", {"symbol": "B"})])
    names = [e["event"] for e in events]
    assert names == ["tool_start"] * 3 + ["tool_result"] * 3
    assert [e["call_id"] for e in events[:3]] == ["c1", "c2", "c3"]


def test_refusals_never_reach_the_tool(monkeypatch):
    seen = []

    async def handler(name, args):
        seen.append(name)
        return {"ok": True, "data": [row("r1")], "source": "saved"}

    install(monkeypatch, handler)
    bad_json = {"id": "c2", "type": "function", "function": {"name": "query_financials", "arguments": "{oops"}}
    _, messages, _ = execute([call("c1", "create_routine", {"x": 1}), bad_json])
    assert [json.loads(m["content"])["error_code"] for m in messages] == ["tool_not_in_bot_scope", "invalid_arguments"]
    assert seen == []
