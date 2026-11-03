"""Task 13: tools are disclosed by category (names + one line in the prompt, full schemas after load_tools).

* every catalogue tool belongs to exactly one category (or is always on);
* a default owner turn carries at most 8 KB of tool definitions;
* load_tools: the chosen categories' schemas ride on the NEXT model call, never the same one;
* what a bot's tool_scope removes can not be loaded; a write is still refused without a grant and a card.
"""
import asyncio
import json
import uuid

import pytest

from app import agent_context as layers
from app.agent_tool_catalog import ALWAYS_ON, TOOL_CATEGORIES, definitions

OWNER = "o" * 40
OWNER_HASH = "h" * 64
FIN = "财报与SEC"
PRICES = "行情"
PORTFOLIO = "持仓"
WORKSPACE = "工作区"
NEWS = "新闻与网页"


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    from app.agent_workflow import consent, direct, tools
    import app.agent_chat_identity as identity
    for module in (consent, direct, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)


def _turn(*, decider=None, recognizer=None, executor=None, tool_scope=None, question="q", state=None):
    from app.agent_workflow import direct
    from app.agent_workflow.state import AgentRuntimeContext
    context = AgentRuntimeContext("custom", "m", "k", owner_hash=OWNER_HASH, identity_credential=OWNER,
                                  conversation_id=str(uuid.uuid4()), tool_scope=tool_scope,
                                  decider=decider, intent_recognizer=recognizer, executor=executor)

    async def quiet(_event):
        pass
    return direct, direct.Turn(question, context, quiet, [], state or {}), context, quiet


def _names(schemas):
    return [t["function"]["name"] for t in schemas]


def _call(call_id, name, **args):
    return {"tool_calls": [{"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_every_tool_has_category():
    owned = {}
    for category, info in TOOL_CATEGORIES.items():
        for tool in info.tools:
            owned.setdefault(tool, []).append(category)
    for tool in ALWAYS_ON:
        owned.setdefault(tool, []).append("always_on")
    names = set(definitions())
    assert names == set(owned), (names ^ set(owned))
    assert {t: c for t, c in owned.items() if len(c) != 1} == {}
    assert all(info.summary and info.tools for info in TOOL_CATEGORIES.values())
    assert {"load_tools"} <= ALWAYS_ON <= names
    # The seven news-source management tools are one tool with an action now.
    assert not names & {"list_news_sources", "dry_run_news_source", "diagnose_news_source", "upsert_news_source",
                        "disable_news_source", "set_news_source_alternate", "repair_news_source_with_rea"}
    assert "manage_news_source" in names


def test_default_payload_under_8kb():
    _, turn, *_ = _turn()
    schemas = turn.exposed_tools()
    size = len(json.dumps(schemas, ensure_ascii=False, separators=(",", ":")).encode())
    assert size <= 8 * 1024, size
    assert set(_names(schemas)) == set(ALWAYS_ON)


def test_load_tools_adds_schemas_next_call():
    seen = []
    steps = iter([_call("l1", "load_tools", categories=[PRICES]), {"content": "好了。"}])

    def decider(_messages, schemas):
        seen.append(_names(schemas))
        return next(steps)
    direct, turn, context, quiet = _turn(decider=decider, executor=lambda n, a: {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    asyncio.run(direct.run_direct_turn("随便看看", context, emit=quiet))
    assert len(seen) >= 2
    assert "query_stock_prices" not in seen[0] and "load_tools" in seen[0]
    assert "query_stock_prices" in seen[1]
    # Tool definitions keep a stable order, so the provider's prefix cache survives the extra category.
    assert seen[1][:len(seen[0])] == seen[0]


def test_load_cannot_exceed_bot_scope():
    seen = []
    scope = frozenset({"query_sec_filings"}) | ALWAYS_ON
    steps = iter([_call("l1", "load_tools", categories=[PRICES, FIN]),
                  _call("p1", "query_stock_prices", symbol="AAPL"), {"content": "不行。"}])

    def decider(_messages, schemas):
        seen.append(_names(schemas))
        return next(steps)
    executed = []
    direct, turn, context, quiet = _turn(decider=decider, tool_scope=scope,
                                         executor=lambda n, a: executed.append(n) or {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    result = asyncio.run(direct.run_direct_turn("看看行情", context, emit=quiet))
    assert "query_stock_prices" not in seen[1] and "query_sec_filings" in seen[1]
    assert "query_stock_prices" not in executed
    assert "query_stock_prices" in result["audit"].get("out_of_scope_calls", [])


@pytest.fixture
def database(disposable_database):
    from app.database import Base, engine
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_")
                                             and t.name not in skipped])


def test_writes_still_need_card(database):
    # Loading the category shows reads only; the write stays refused without the owner's words ...
    seen = []
    steps = iter([_call("l1", "load_tools", categories=[WORKSPACE]),
                  _call("t1", "add_to_research_queue", symbol="AMD"), {"content": "未执行。"}])

    def decider(_messages, schemas):
        seen.append(_names(schemas))
        return next(steps)
    executed = []
    direct, turn, context, quiet = _turn(decider=decider, executor=lambda n, a: executed.append(n) or {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    result = asyncio.run(direct.run_direct_turn("看看持仓", context, emit=quiet))
    assert "query_research_queue" in seen[1] and "add_to_research_queue" not in seen[1]
    assert executed == [] and result.get("pending_request") is None
    # ... and with them it makes a confirmation card, still not executed (its category rode along on the intent).
    steps = iter([_call("t2", "add_to_research_queue", symbol="AMD"), {"content": "请确认。"}])
    direct, turn, context, quiet = _turn(decider=lambda _m, _s: next(steps), executor=lambda n, a: executed.append(n) or {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": None, "requested_actions": ["add_to_research_queue"]})
    result = asyncio.run(direct.run_direct_turn("把 AMD 加入研究队列", context, emit=quiet))
    assert executed == [] and result["pending_request"]["reason"] == "write_confirmation"


def test_intent_preloads_categories_without_load_step():
    direct, turn, *_ = _turn()
    turn.route = "A"
    turn.scope = {"mode": "prices", "requested_actions": []}
    assert PRICES in turn.preload_categories()
    assert "query_stock_prices" in _names(turn.exposed_tools())
    direct, turn, *_ = _turn()
    turn.scope = {"mode": "none", "requested_actions": ["record_trade"]}
    turn.granted_actions = {"record_trade"}
    assert PORTFOLIO in turn.preload_categories()
    # The last turn's categories carry over.
    direct, turn, *_ = _turn(state={"previous_scope": {"_tool_categories": [FIN]}})
    assert FIN in turn.preload_categories() and "query_financials" in _names(turn.exposed_tools())


def test_news_window_preloads_news_category():
    # The classifier sets days_back only when the request is about news; that is the news intent signal.
    direct, turn, *_ = _turn()
    turn.route = "D"
    turn.scope = {"mode": "none", "days_back": 7, "requested_actions": []}
    assert NEWS in turn.preload_categories()
    assert "web_research" in _names(turn.exposed_tools())
    # No window, no news preload; B/C routes never preload; a bot scope without the news tools loads nothing.
    direct, turn, *_ = _turn()
    turn.route = "D"
    turn.scope = {"mode": "none", "days_back": None, "requested_actions": []}
    assert NEWS not in turn.preload_categories()
    direct, turn, *_ = _turn()
    turn.route = "B"
    turn.scope = {"days_back": 7}
    assert NEWS not in turn.preload_categories()
    direct, turn, *_ = _turn(tool_scope=["query_stock_prices"])
    turn.route = "D"
    turn.scope = {"days_back": 7}
    assert NEWS not in turn.preload_categories()


def test_news_turn_needs_no_load_tools_step():
    seen = []
    steps = iter([_call("n1", "web_research", query="美光 新闻", days_back=7), {"content": "好。"}])

    def decider(_messages, schemas):
        seen.append(_names(schemas))
        return next(steps)
    direct, turn, context, quiet = _turn(decider=decider, executor=lambda n, a: {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": 7, "requested_actions": []})
    asyncio.run(direct.run_direct_turn("搜一下美光最近的新闻", context, emit=quiet))
    assert "web_research" in seen[0] and "load_tools" in seen[0]


def test_manage_news_source_validates_action():
    from app.agent_tool_catalog import validate
    assert validate("manage_news_source", {"action": "list"})["action"] == "list"
    with pytest.raises(Exception):
        validate("manage_news_source", {"action": "diagnose"})  # needs source_id
    with pytest.raises(Exception):
        validate("manage_news_source", {"action": "upsert", "source_id": "abc"})  # needs url
    assert validate("manage_news_source", {"action": "set_enabled", "source_id": "abc", "enabled": False})["enabled"] is False


def test_fixed_tokens_is_measured_not_written_down():
    assert layers.FIXED_TOKENS != 8_000
    measured = layers.measure_fixed_tokens()
    assert layers.FIXED_TOKENS == measured
    assert 4_000 < measured < 16_000


def test_unattended_run_starts_with_notify():
    from app.agent_workflow import direct
    from app.agent_workflow.state import AgentRuntimeContext
    context = AgentRuntimeContext("custom", "m", "k", owner_hash=OWNER_HASH, identity_credential=OWNER,
                                  conversation_id=str(uuid.uuid4()), unattended=True)

    async def quiet(_event):
        pass
    turn = direct.Turn("q", context, quiet, [], {})
    turn.preload_categories()
    names = _names(turn.exposed_tools())
    assert "notify_telegram" in names and "create_routine" not in names


def test_calling_a_scoped_tool_that_was_not_loaded_runs_and_loads_its_category():
    seen = []
    steps = iter([_call("p1", "query_stock_prices", symbol="AAPL"), {"content": "好。"}])

    def decider(_messages, schemas):
        seen.append(_names(schemas))
        return next(steps)
    ran = []
    direct, turn, context, quiet = _turn(decider=decider, executor=lambda n, a: ran.append(n) or {"ok": True, "data": []},
                                         recognizer=lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    result = asyncio.run(direct.run_direct_turn("看看股价", context, emit=quiet))
    assert ran == ["query_stock_prices"] and "query_stock_prices" in seen[1]
    assert result["audit"]["implicit_loads"] == ["query_stock_prices"]
    assert result["previous_scope"]["_tool_categories"] == [PRICES]


def test_retired_news_tool_names_in_old_scopes_mean_the_merged_tool():
    from app.agent_tool_catalog import expand_legacy
    assert "manage_news_source" in expand_legacy({"upsert_news_source", "web_research"})
    assert expand_legacy({"web_research"}) == {"web_research"}
