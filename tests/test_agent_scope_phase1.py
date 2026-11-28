"""Scope model Phase 1 (.local/design-scope-model.md §4): the classifier's prediction stops being a precondition.

A carried entity is a hint, a read may use what the turn discovers, a name the model maps to a ticker goes ahead with
the mapping stated, tools can be preloaded from a hint, and C has to be positively out of scope.  Model decisions are
injected; these tests do not measure real-model behaviour.
"""
import asyncio
import copy
import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.agent_tool_catalog import TOOL_CATEGORIES, Empty, ToolPolicy, definitions as real_definitions
from app.agent_workflow import entities, tools
from app.agent_workflow.state import AgentRuntimeContext

OWNER = "o" * 40
OWNER_HASH = "h" * 64
NOW = datetime.now(UTC)
AFTER_AAPL = {"previous_scope": {"symbol": "AAPL", "company": "Apple"}}
AAPL_TURN = [{"role": "user", "content": "AAPL 的营收"}]
INTC_HOLDING = {"id": "portfolio:INTC", "source_type": "portfolio", "title": "INTC 持仓", "symbol": "INTC",
                "excerpt": "INTC 持仓 100 股；平均成本 80。"}
INTC_FORECAST = {"id": "forecast-intc", "symbol": "INTC", "title": "INTC 预测", "excerpt": "INTC 已保存预测。", "status": "ready"}
SECTOR_PAGE = {"url": "https://example.org/pharma", "title": "Pharma sector", "excerpt": "Pharma sector leaders rallied this week.",
               "published_at": (NOW - timedelta(days=1)).isoformat(), "fetched_at": NOW.isoformat(), "body_provenance": "public_page_fetch"}
LILLY_RECORDS = [{"ticker": "LLY", "title": "ELI LILLY & Co"}, {"ticker": "MU", "title": "MICRON TECHNOLOGY INC"}]
HOLDING_READS = [("query_portfolio", {"symbol": None}), ("query_latest_forecast", {"symbol": "INTC"})]


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    import app.agent_chat_identity as identity
    from app.agent_workflow import consent
    for module in (consent, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)


def _step(name, **args):
    return {"tool_calls": [{"id": uuid.uuid4().hex, "function": {"name": name, "arguments": json.dumps(args)}}]}


def _rewrite(relationship, canonical=None):
    return lambda payload: {"relationship": relationship, "canonical_question": canonical or payload["question"]}


def _context(*, classified=None, steps=(), rows=None, resolver=None, **kwargs):
    """A turn whose model decisions are the given steps.  Records what ran, what the model was told and offered."""
    ran, replies, offered = [], [], []
    plan = iter(steps)

    def decide(messages, schemas):
        offered.append([t["function"]["name"] for t in schemas])
        replies[:] = [m["content"] for m in messages if m.get("role") == "tool"]
        return next(plan, {"content": "没有可核验资料。"})

    def execute(name, args):
        ran.append((name, args))
        return {"ok": True, "data": copy.deepcopy((rows or {}).get(name, []))}

    context = AgentRuntimeContext("custom", "test", "dummy", owner_hash=OWNER_HASH, identity_credential=OWNER, conversation_id=str(uuid.uuid4()),
                                  classifier=lambda _q: {"category": "A", "mode": "none", **(classified or {})}, decider=decide, executor=execute,
                                  resolver=resolver or _rewrite("new"), **kwargs)
    return context, ran, replies, offered


def _run(question, context, *, messages=None, state=None):
    async def quiet(_event):
        pass
    return asyncio.run(direct.run_direct_turn(question, context, emit=quiet, messages=messages, state=state))


def _portfolio_then_forecast():
    return [_step("query_portfolio"), _step("query_latest_forecast", symbol="INTC"), {"content": "INTC 持仓 100 股 [1]。"}]


# --- 1. A carried entity stops binding ------------------------------------------------------------------------------

# --- 2. Discovered reads -------------------------------------------------------------------------------------------

def _observed(name, row):
    return {"name": name, "arguments": {}, "result": {"ok": True, "data": [row]}, "accepted_evidence": True}


# --- 3. mapped, with the server's line -----------------------------------------------------------------------------

def _lilly(monkeypatch, company, *, symbol="LLY", mention="礼来", question="礼来的营收是多少", steps=(), rows=None):
    monkeypatch.setattr(entities, "ticker_records", lambda: LILLY_RECORDS)
    context, *_ = _context(classified={"company": company, "symbol": symbol, "company_mention": mention}, steps=steps, rows=rows)
    return _run(question, context)


def test_a_name_fits_a_title_by_its_distinctive_words():
    assert entities.name_fits_title("Eli Lilly and Company", "ELI LILLY & Co")
    assert not entities.name_fits_title("Bank of America", "BANK OF NOVA SCOTIA")
    assert entities.name_fits_title("Eli Lilly Pharmaceuticals", "ELI LILLY & Co")


# --- PCE 和 FOMC: the ticker-shaped backfill stops filtering rows ----------------------------------------------------

# --- 4. load_hint --------------------------------------------------------------------------------------------------

# --- 5. Prompt and identity ----------------------------------------------------------------------------------------

# --- The kind-agnostic test ----------------------------------------------------------------------------------------

def _with_fixture_tool(monkeypatch, policy):
    def definitions():
        return {**real_definitions(), policy.name: policy}
    import app.agent_tool_catalog as catalogue
    for module in (catalogue, tools):
        monkeypatch.setattr(module, "definitions", definitions)


def _kind_nobody_designed_for():
    context, ran, _, _ = _context(steps=[_step("query_made_up_ledger"), {"content": "这个月手续费合计 12 美元 [1]。"}],
                                  rows={"query_made_up_ledger": [{"id": "fee-1", "title": "手续费账本", "excerpt": "这个月手续费合计 12 美元。"}]})
    result = _run("这个月交易手续费花了多少", context)
    assert ran == [("query_made_up_ledger", {})]
    assert result["status"] == "succeeded" and [c.get("title") for c in result["citations"]] == ["手续费账本"]


