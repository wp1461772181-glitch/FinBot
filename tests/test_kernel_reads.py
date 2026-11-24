"""The read tools the kernel offers beyond the first set: which are numbered into citations and which are shown as state.

No network, no database: ``tools.invoke`` is replaced by a script returning each tool's real result shape.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agent_tool_catalog import schemas
from app.agent_workflow import tools
from app.kernel import loop, progress, toolrun

NEW_READS = ("query_latest_forecast", "query_materials", "query_material_analysis", "search_material_analysis", "read_workspace",
             "query_research_queue", "query_research_faq", "query_system_status", "query_holdings_overview", "query_alerts",
             "list_routines")
OWNER_ONLY_NEW = {"query_holdings_overview", "query_alerts", "list_routines"}
# The old engine numbers these (owner records and the gated saved-evidence path); it shows the other three as state.
NUMBERED = {"query_latest_forecast": "saved_forecast", "query_materials": "saved_material", "query_material_analysis": "official_filing",
            "search_material_analysis": "ai_analysis", "read_workspace": "saved_workspace", "query_research_faq": "research_faq",
            "query_holdings_overview": "portfolio", "query_alerts": "portfolio"}
UNNUMBERED = ("query_system_status", "query_research_queue", "list_routines")

# What each tool's real implementation returns: a list under ``data``.
RESULTS = {
    "query_latest_forecast": {"ok": True, "data": [{"id": "f1", "symbol": "AAPL", "version_no": 2, "probabilities": {"bullish": 0.5}}],
                              "source": "forecast_versions_v2 workspace current root"},
    "query_materials": {"ok": True, "data": [{"id": "m1", "symbol": "AAPL", "title": "年报", "excerpt": "Revenue was 100."}], "source": "saved"},
    "query_material_analysis": {"ok": True, "data": [{"source_type": "official_filing", "source_id": "s1", "symbol": "AAPL",
                                                      "excerpt": "收入 100"}], "source": "material_analysis_versions"},
    "search_material_analysis": {"ok": True, "data": [{"id": "a1", "symbol": "AAPL", "excerpt": "分析：收入 100"}], "source": "material_analysis_versions"},
    "read_workspace": {"ok": True, "data": [{"id": "w1", "symbol": "AAPL", "source_type": "saved_workspace", "title": "Workspace roots",
                                             "excerpt": "{}"}], "source": "workspace roots"},
    "query_research_faq": {"ok": True, "data": [{"id": "q1", "question": "什么是 X", "answer": "X 是 Y。"}], "source": "research_faq"},
    "query_holdings_overview": {"ok": True, "data": [{"id": "portfolio:AAPL", "source_type": "portfolio", "symbol": "AAPL",
                                                      "excerpt": "AAPL 持仓 10 股"}], "source": "portfolio"},
    "query_alerts": {"ok": True, "status": "ok", "data": [{"id": "alert:1", "source_type": "portfolio", "symbol": "AAPL", "kind": "price",
                                                           "text": "涨 5%", "excerpt": "[2026-11-24] AAPL price: 涨 5%"}], "source": "sentinel.db alerts"},
    "query_system_status": {"ok": True, "data": [{"id": "j1", "status": "running"}], "source": "jobs"},
    "query_research_queue": {"ok": True, "data": [{"symbols": ["AAPL", "MSFT"]}], "source": "owner queue"},
    "list_routines": {"ok": True, "data": [{"id": "r1", "name": "晨报", "enabled": True, "schedule": "每天 08:00"}], "source": "routines"},
}


def make_run():
    events = []

    async def emit(event):
        events.append(event)

    return SimpleNamespace(context=SimpleNamespace(query_expander=None), emit=emit, user_text="", citations=[],
                           audit={"tool_calls": 0}, read_results=0, tool_names=frozenset(NEW_READS))


def execute(monkeypatch, name):
    async def fake_invoke(called, args, context, *, emit=None, page_chars=None):
        assert called == name
        return json.loads(json.dumps(RESULTS[name]))

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    run = make_run()
    call = {"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}
    (message,) = asyncio.run(toolrun.run_step_tools(run, [call]))
    return run, json.loads(message["content"])


def offered(owner, monkeypatch, scope=None):
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: owner)
    context = SimpleNamespace(identity_credential="x", tool_scope=scope)
    return [s["function"]["name"] for s in loop._tool_schemas(context)]


def test_every_new_read_is_in_read_tools_in_catalogue_order():
    assert set(NEW_READS) <= set(loop.READ_TOOLS)
    order = [s["function"]["name"] for s in schemas(owner=True)]
    assert [n for n in loop.READ_TOOLS if n in NEW_READS] == [n for n in order if n in NEW_READS]


def test_owner_is_offered_all_new_reads_before_the_kernels_own_tools(monkeypatch):
    names = offered(True, monkeypatch)
    assert all(n in names for n in NEW_READS)
    assert names[-4:] == ["act", "ask", "plan", "escalate"] and all(names.index(n) < names.index("act") for n in NEW_READS)
    order = [s["function"]["name"] for s in schemas(owner=True)]
    assert [n for n in names if n in NEW_READS] == [n for n in order if n in NEW_READS]


def test_guest_is_offered_none_of_the_owner_only_new_reads(monkeypatch):
    names = offered(False, monkeypatch)
    assert not OWNER_ONLY_NEW & set(names)
    assert set(NEW_READS) - OWNER_ONLY_NEW <= set(names)
    assert "act" not in names


def test_a_bot_scope_still_limits_the_new_reads(monkeypatch):
    names = offered(True, monkeypatch, scope={"query_alerts", "query_financials"})
    assert [n for n in names if n in NEW_READS] == ["query_alerts"]
    assert "query_materials" not in names


def test_every_read_tool_has_a_progress_phrase():
    assert set(loop.READ_TOOLS) <= set(progress.TOOL_PHRASES)
    assert progress.TOOL_PHRASES["query_latest_forecast"] == "看已存的预测"


@pytest.mark.parametrize("name", sorted(NUMBERED))
def test_evidence_reads_are_numbered_with_their_source_type(monkeypatch, name):
    run, shown = execute(monkeypatch, name)
    assert shown["data"][0]["citation"] == "[1]"
    assert len(run.citations) == 1 and run.citations[0]["source_type"] == NUMBERED[name]
    assert run.read_results == 1


@pytest.mark.parametrize("name", UNNUMBERED)
def test_state_reads_are_shown_unnumbered(monkeypatch, name):
    run, shown = execute(monkeypatch, name)
    assert shown == RESULTS[name] and run.citations == []
    assert "citation" not in shown["data"][0]
    # the queue and the routines are the owner's own data: tier 1 still runs at once; the system status carries outside text
    assert run.read_results == (1 if name == "query_system_status" else 0)
