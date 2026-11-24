"""The kernel turn records an ordered timeline of what happened (``audit["timeline"]``): small entries, no text, no arguments."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
from app.agent_workflow import tools
from app.kernel import act, loop, prompt, toolrun

ROW = {"id": "r1", "symbol": "AAPL", "source_type": "official_filing", "excerpt": "Revenue was 100 and cost was 40 (USD billions)."}
INPUTS = [{"name": "a", "value": "100", "source_ordinal": 1}, {"name": "b", "value": "40", "source_ordinal": 1}]


def call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Script:
    def __init__(self, steps):
        self.steps = list(steps)

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        calls, text = self.steps.pop(0)
        for piece in ([text] if text else []):
            await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": text}
        if calls:
            message["tool_calls"] = calls
        return {"usage": {"total_tokens": 10}}, message


def run_turn(monkeypatch, steps):
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(act, "owner_credential_matches", lambda value: bool(value))

    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        await asyncio.sleep(0.01)
        return {"ok": True, "data": [copy.deepcopy(ROW)], "source": "saved"}

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    monkeypatch.setattr(provider, "stream_decision", Script(steps))
    context = SimpleNamespace(provider="anthropic", model="m", api_key="k", base_url=None, reasoning_effort=None, tool_scope=None,
                              bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash="o")
    events = []

    async def emit(event):
        events.append(event)

    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "问题"}]
    return asyncio.run(loop.run_turn("问题", context, emit, history, {})), events


def test_a_turn_with_narration_parallel_reads_a_calculation_and_a_second_call_is_recorded_in_order(monkeypatch):
    result, events = run_turn(monkeypatch, [
        ([call("c1", "query_financials", {"symbol": "AAPL"}), call("c2", "query_sec_filings", {"symbol": "AAPL"}),
          call("c3", "calculate", {"expression": "a-b", "inputs": INPUTS})], ""),
        ([], "收入 100 [1]"),
    ])
    audit = result["audit"]
    timeline = audit["timeline"]
    assert [(e["kind"], e.get("index"), e.get("call_id")) for e in timeline][:5] == [
        ("call", 0, None), ("say", 0, None), ("tool", None, "c1"), ("tool", None, "c2"), ("tool", None, "c3")]
    kinds = [e["kind"] for e in timeline]
    assert kinds[0] == "call" and kinds[1] == "say" and kinds.count("tool") == 3 and kinds.count("tool_done") == 3 and kinds[-1] == "call"
    assert kinds.index("tool_done") > max(i for i, k in enumerate(kinds) if k == "tool")
    assert [e["index"] for e in timeline if e["kind"] == "call"] == [0, 1] and len(audit["calls"]) == 2
    assert [e["index"] for e in timeline if e["kind"] == "say"] == [0] and len(result["final_protocol"]["narration"]) == 1
    assert [e["step"] for e in timeline] == [1, 1, 1, 1, 1, 1, 1, 1, 2]
    stamps = [e["at_ms"] for e in timeline]
    assert stamps == sorted(stamps) and all(isinstance(v, int) and v >= 0 for v in stamps)
    assert all(set(e) <= {"kind", "at_ms", "step", "index", "call_id", "name"} for e in timeline)
    assert {e["name"] for e in timeline if e["kind"] == "tool"} == {"query_financials", "query_sec_filings", "calculate"}
    assert "arguments" not in json.dumps(timeline) and "AAPL" not in json.dumps(timeline)
    # nothing else changed shape
    assert [c["tier"] for c in audit["calls"]] == ["low", "low"] and result["answer"] == "收入 100 [1]"


def test_the_timeline_is_capped_at_500_entries():
    run = SimpleNamespace(audit={"decision_steps": 1}, started=0.0)
    for i in range(700):
        toolrun.mark_timeline(run, "say", index=i)
    assert len(run.audit["timeline"]) == 500


def test_marking_tolerates_a_run_without_an_audit():
    toolrun.mark_timeline(SimpleNamespace(), "say", index=0)


def test_a_failed_read_still_gets_its_tool_done(monkeypatch):
    async def boom(name, args, context, *, emit=None, page_chars=None):
        raise RuntimeError("x")

    monkeypatch.setattr(tools, "invoke", boom)
    events = []

    async def emit(event):
        events.append(event)

    run = SimpleNamespace(context=SimpleNamespace(query_expander=None, owner_hash="o", conversation_id="c"), emit=emit, user_text="",
                          tool_names=frozenset({"query_financials"}), citations=[], audit={"tool_calls": 0, "decision_steps": 1}, read_results=0,
                          web_rows={}, new_sets=[], narration=[])
    asyncio.run(toolrun.run_step_tools(run, [call("c1", "query_financials", {"symbol": "A"})]))
    assert [(e["kind"], e["call_id"]) for e in run.audit["timeline"]] == [("tool", "c1"), ("tool_done", "c1")]


def test_the_backup_switch_sentence_belongs_to_the_step_of_the_call_that_replaces_the_failed_one(monkeypatch):
    import time
    from app.kernel import loop as kernel_loop

    async def found(run):
        return {"provider": "openrouter", "model": "b", "api_key": "k", "base_url": None, "name": "reserve"}

    monkeypatch.setattr(kernel_loop, "_backup_for", found)
    events = []

    async def emit(event):
        events.append(event)

    run = SimpleNamespace(model=kernel_loop.ModelUse("anthropic", "m", "k"), narration=[], audit={"decision_steps": 2}, started=time.monotonic(), emit=emit,
                          messages=[], fallback_used=None, context=SimpleNamespace(owner_hash="o"))
    assert asyncio.run(kernel_loop._switch_to_backup(run, RuntimeError("x"))) is True
    assert [(e["kind"], e["index"], e["step"]) for e in run.audit["timeline"]] == [("say", 0, 3)]
