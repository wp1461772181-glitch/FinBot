"""Unit tests for Batch 9b fixes:
1. Retrieval query expansion: avoid stealth model calls unless query_expander is explicitly configured in context.
2. Soft time budget closing: when elapsed >= 180s, citations is non-empty, and decision_steps >= 1,
   agent_loop stops gathering and enters closing_answer with stop_reason='soft_time_budget_closing'.
"""
import asyncio
import time
import pytest
from app.agent_workflow.direct import Turn
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge import query_understanding
from app.agent_workflow import tools


def test_default_query_expander_none_avoids_model_call(monkeypatch):
    """When context.query_expander is None (default), execute_read installs None,
    Turn.expander is never invoked, and retrieval falls back to local dictionary expansion."""
    expander_called = 0

    async def fake_expander(query):
        nonlocal expander_called
        expander_called += 1
        return ["fake_variant"]

    observed_expander = "unset"
    observed_variants = None

    async def fake_invoke(name, args, context, emit=None):
        nonlocal observed_expander, observed_variants
        observed_expander = query_understanding._EXPANDER.get()
        # query_variants called within this block should see _EXPANDER as None
        observed_variants = await query_understanding.query_variants("营收 和 现金流")
        return {"ok": True, "data": []}

    monkeypatch.setattr(tools, "invoke", fake_invoke)

    context = AgentRuntimeContext(
        provider="custom",
        model="test",
        api_key="dummy",
        query_expander=None,  # default
    )
    async def emit(_): pass
    turn = Turn("查一下营收和现金流", context, emit, [], {})
    turn.route = "A"
    monkeypatch.setattr(turn, "expander", fake_expander)

    outcome = asyncio.run(turn.execute_read("search_knowledge", {"query": "营收 和 现金流"}))

    assert outcome["ok"] is True
    assert expander_called == 0, "Turn.expander must not be called when query_expander is None"
    assert observed_expander is None, "_EXPANDER in ContextVar must be None"
    # Local dictionary expansion splits two-topic financial queries into ["营收 和 现金流", "营收", "现金流"]
    assert observed_variants == ["营收 和 现金流", "营收", "现金流"]


def test_explicit_query_expander_is_used_when_provided(monkeypatch):
    """When context.query_expander is explicitly provided, execute_read installs it into ContextVar."""
    custom_called = 0

    async def custom_expander(query):
        nonlocal custom_called
        custom_called += 1
        return ["营业收入", "经营现金流"]

    observed_expander = None
    observed_variants = None

    async def fake_invoke(name, args, context, emit=None):
        nonlocal observed_expander, observed_variants
        observed_expander = query_understanding._EXPANDER.get()
        observed_variants = await query_understanding.query_variants("营收")
        return {"ok": True, "data": []}

    monkeypatch.setattr(tools, "invoke", fake_invoke)

    context = AgentRuntimeContext(
        provider="custom",
        model="test",
        api_key="dummy",
        query_expander=custom_expander,
    )
    async def emit(_): pass
    turn = Turn("查一下营收", context, emit, [], {})
    turn.route = "A"

    outcome = asyncio.run(turn.execute_read("search_knowledge", {"query": "营收"}))

    assert outcome["ok"] is True
    assert observed_expander is custom_expander
    assert custom_called == 1
    assert "营业收入" in observed_variants


def test_agent_loop_soft_time_budget_closing(monkeypatch):
    """When decision_steps >= 1, citations is non-empty, and elapsed >= 180s,
    agent_loop exits with stop_reason='soft_time_budget_closing' and enters closing."""
    decide_count = 0

    async def fake_decide():
        nonlocal decide_count
        decide_count += 1
        return {"content": "should not be called"}

    closing_called = 0

    async def fake_closing():
        nonlocal closing_called
        closing_called += 1
        return "根据已有证据 [1]，提前收尾回答。"

    context = AgentRuntimeContext(
        provider="custom",
        model="test",
        api_key="dummy",
        owner_hash="owner_001",
        conversation_id="conv_001",
        identity_credential="owner",
    )

    async def emit(_): pass
    turn = Turn("计算财务指标", context, emit, [], {})
    turn.route = "A"
    turn.citations = [{
        "ordinal": 1,
        "source_type": "official_filing",
        "title": "SEC 10-K",
        "quote": "营收 100 亿",
        "section": "Part I",
    }]
    turn.observations = [{
        "name": "search_knowledge",
        "arguments": {},
        "result": {"ok": True, "data": [{"id": "doc1"}]},
        "accepted_evidence": True,
    }]

    monkeypatch.setattr(turn, "decision", fake_decide)
    monkeypatch.setattr(turn, "closing_answer", fake_closing)

    # Simulate at least 1 decision step already completed, and elapsed time >= 180s
    turn.audit["decision_steps"] = 1
    turn.started = time.monotonic() - 185

    result = asyncio.run(turn.agent_loop())

    # Assertions:
    # 1. No new decision was made in this iteration
    assert decide_count == 0, "Should not make a new decision when soft budget exceeded"
    # 2. Entered closing answer
    assert closing_called == 1, "Should enter closing_answer"
    # 3. Audit stop_reason is recorded as soft_time_budget_closing
    assert turn.audit.get("stop_reason") == "soft_time_budget_closing"
    assert result.get("reason") == "soft_time_budget_closing"


def test_agent_loop_does_not_soft_stop_when_elapsed_under_180s(monkeypatch):
    """When elapsed < 180s, agent_loop does not trigger soft_time_budget_closing."""
    decide_count = 0

    async def fake_decide():
        nonlocal decide_count
        decide_count += 1
        return {"content": "正常决策作答 [1]"}

    context = AgentRuntimeContext(
        provider="custom",
        model="test",
        api_key="dummy",
        owner_hash="owner_001",
        conversation_id="conv_001",
        identity_credential="owner",
    )
    async def emit(_): pass
    turn = Turn("普通提问", context, emit, [], {})
    turn.route = "A"
    turn.citations = [{
        "ordinal": 1,
        "source_type": "official_filing",
        "title": "SEC 10-K",
        "quote": "营收 100 亿",
    }]
    turn.observations = [{
        "name": "search_knowledge",
        "arguments": {},
        "result": {"ok": True, "data": [{"id": "doc1"}]},
        "accepted_evidence": True,
    }]

    monkeypatch.setattr(turn, "decision", fake_decide)
    turn.audit["decision_steps"] = 1
    turn.started = time.monotonic() - 10  # Only 10s elapsed

    result = asyncio.run(turn.agent_loop())
    assert decide_count == 1, "Should proceed to decision when under 180s"
    assert turn.audit.get("stop_reason") != "soft_time_budget_closing"


def test_agent_loop_does_not_soft_stop_without_citations(monkeypatch):
    """When citations is empty, soft_time_budget_closing is not triggered."""
    decide_count = 0

    async def fake_decide():
        nonlocal decide_count
        decide_count += 1
        return {"content": "没有搜到相关资料"}

    context = AgentRuntimeContext(
        provider="custom",
        model="test",
        api_key="dummy",
        owner_hash="owner_001",
        conversation_id="conv_001",
        identity_credential="owner",
    )
    async def emit(_): pass
    turn = Turn("提问无证据", context, emit, [], {})
    turn.route = "A"
    turn.citations = []  # Empty citations

    monkeypatch.setattr(turn, "decision", fake_decide)
    turn.audit["decision_steps"] = 1
    turn.started = time.monotonic() - 185  # Over 180s

    result = asyncio.run(turn.agent_loop())
    assert decide_count == 1, "Should proceed to decision when citations is empty"
    assert turn.audit.get("stop_reason") != "soft_time_budget_closing"
