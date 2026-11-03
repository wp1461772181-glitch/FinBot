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
from app.agent_workflow import direct, entities, tools
from app.agent_workflow.routing import Routing
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
    for module in (consent, direct, tools, identity):
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

def test_portfolio_after_a_company_turn_can_read_a_holdings_forecast():
    context, ran, replies, _ = _context(steps=_portfolio_then_forecast(), resolver=_rewrite("followup", "我的持仓今天怎么样"),
                                        rows={"query_portfolio": [INTC_HOLDING], "query_latest_forecast": [INTC_FORECAST]})
    result = _run("我的持仓今天怎么样", context, messages=AAPL_TURN, state=AFTER_AAPL)
    assert ran == HOLDING_READS
    assert "scope_not_grounded" not in " ".join(replies)
    # The hint survives for the next turn.
    assert result["previous_scope"]["symbol"] == "AAPL"


def test_sector_after_a_company_turn_keeps_a_page_that_does_not_name_the_old_company():
    context, _, _, _ = _context(steps=[_step("web_research", query="医药行业"), {"content": "医药板块走强 [1]。"}],
                                resolver=_rewrite("followup", "医药行业呢"), rows={"web_research": [SECTOR_PAGE]})
    result = _run("那医药行业呢", context, messages=AAPL_TURN, state=AFTER_AAPL)
    assert [c.get("title") for c in result["citations"]] == ["Pharma sector"]


def test_portfolio_on_a_default_company_bot_behaves_the_same():
    context, ran, replies, _ = _context(steps=_portfolio_then_forecast(), default_company={"symbol": "AAPL", "company": "Apple"},
                                        rows={"query_portfolio": [INTC_HOLDING], "query_latest_forecast": [INTC_FORECAST]})
    result = _run("我的持仓今天怎么样", context)
    assert ran == HOLDING_READS
    assert "scope_not_grounded" not in " ".join(replies)
    assert result["audit"]["default_company"]["symbol"] == "AAPL" and result["previous_scope"]["symbol"] == "AAPL"


def test_sector_on_a_default_company_bot_keeps_a_page_that_does_not_name_the_company():
    context, _, _, _ = _context(steps=[_step("web_research", query="医药行业"), {"content": "医药板块走强 [1]。"}],
                                default_company={"symbol": "AAPL", "company": "Apple"}, rows={"web_research": [SECTOR_PAGE]})
    assert [c.get("title") for c in _run("医药行业呢", context)["citations"]] == ["Pharma sector"]


def test_the_model_is_told_a_carried_entity_is_only_a_hint():
    context, _, _, _ = _context(resolver=_rewrite("followup", "我的持仓今天怎么样"))
    seen = []
    decide = context.decider

    def spy(messages, schemas):
        seen.extend(m["content"] for m in messages if m["role"] == "system")
        return decide(messages, schemas)
    _run("我的持仓今天怎么样", dataclasses.replace(context, decider=spy), messages=AAPL_TURN, state=AFTER_AAPL)
    understanding = next(text for text in seen if text.startswith(direct.UNDERSTANDING_NOTE))
    assert '"symbol": "AAPL"' in understanding and "scope_entity_note" in understanding


@pytest.mark.parametrize("resolver,question", [(_rewrite("refinement", "AAPL 的预测，只看最近"), "只看最近"),
                                               (lambda _payload: (_ for _ in ()).throw(ValueError("resolver_down")), "它的预测呢")],
                         ids=["refinement", "resolver_failed"])
def test_a_carried_entity_still_binds_on_a_refinement_or_when_the_resolver_failed(resolver, question):
    context, ran, replies, _ = _context(steps=[_step("query_latest_forecast", symbol="INTC"), {"content": "没有可核验资料。"}], resolver=resolver)
    _run(question, context, messages=AAPL_TURN, state=AFTER_AAPL)
    assert ran == []
    assert "scope_not_grounded" in " ".join(replies)


def test_a_carried_entity_still_filters_pages_on_a_refinement():
    context, _, _, _ = _context(steps=[_step("web_research", query="最近"), {"content": "没有可核验资料。"}],
                                resolver=_rewrite("refinement", "AAPL 新闻，只看最近"), rows={"web_research": [SECTOR_PAGE]})
    assert _run("只看最近", context, messages=AAPL_TURN, state=AFTER_AAPL)["citations"] == []


def test_a_rejected_rewrite_counts_as_a_failed_resolver():
    context, ran, replies, _ = _context(steps=[_step("query_latest_forecast", symbol="INTC"), {"content": "没有可核验资料。"}],
                                        resolver=_rewrite("followup", f"AAPL {datetime.now(UTC).year + 5} 财年的预测"))
    _run("它的预测呢", context, messages=AAPL_TURN, state=AFTER_AAPL)
    assert ran == [] and "scope_not_grounded" in " ".join(replies)


def test_a_named_company_still_filters_pages():
    context, _, _, _ = _context(classified={"symbol": "AAPL", "company": "Apple"}, steps=[_step("web_research", query="AAPL 新闻"), {"content": "没有可核验资料。"}],
                                rows={"web_research": [SECTOR_PAGE]})
    result = _run("Apple（AAPL）最近有什么新闻", context)
    assert not result["pending_request"] and result["citations"] == []


# --- 2. Discovered reads -------------------------------------------------------------------------------------------

def _turn_about(question, **attributes):
    context, *_ = _context()

    async def quiet(_event):
        pass
    turn = direct.Turn(question, context, quiet, [], {})
    turn.route = "A"
    turn.scope = {"symbol": "AAPL", "symbols": ["AAPL"], "company": "Apple"}
    for name, value in attributes.items():
        setattr(turn, name, value)
    return turn


def _observed(name, row):
    return {"name": name, "arguments": {}, "result": {"ok": True, "data": [row]}, "accepted_evidence": True}


def test_a_turn_naming_a_company_can_read_a_holding_only_once_the_owners_rows_list_it():
    turn = _turn_about("AAPL 和我的持仓比怎么样")
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_latest_forecast", {"symbol": "INTC"})
    turn.observations.append(_observed("query_portfolio", INTC_HOLDING))
    turn.ground_arguments("query_latest_forecast", {"symbol": "INTC"})
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_latest_forecast", {"symbol": "MSFT"})


def test_a_page_cannot_widen_a_turn_that_names_a_company():
    turn = _turn_about("AAPL 的竞争对手")
    turn.observations.append(_observed("web_research", {"url": "https://example.org/a", "excerpt": "MSFT competes with AAPL."}))
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "MSFT"})


def test_rejected_evidence_does_not_widen_a_read():
    turn = _turn_about("这些概念怎么样", classifier_named=False, entity_backfilled=True)
    turn.observations.append({**_observed("web_research", {"excerpt": "SPY rallied."}), "accepted_evidence": False})
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "SPY"})


def test_a_write_target_does_not_widen_with_reads():
    for attributes in ({}, {"classifier_named": False, "entity_carried": True}):
        turn = _turn_about("初始化行情", **attributes)
        turn.observations.append(_observed("query_portfolio", INTC_HOLDING))
        with pytest.raises(ValueError, match="scope_not_grounded"):
            turn.ground_arguments("initialize_prices", {"symbol": "INTC"})


def test_a_refused_symbol_reports_its_real_error_to_the_model():
    context, ran, replies, _ = _context(classified={"symbol": "AAPL"},
                                        steps=[_step("query_stock_prices", symbol="MSFT"), {"content": "没有可核验资料。"}])
    _run("AAPL 的股价", context)
    reply = json.loads(replies[0])
    assert ran == [] and reply["error_code"] == "scope_not_grounded" and "query_portfolio" in reply["hint"]


# --- 3. mapped, with the server's line -----------------------------------------------------------------------------

def _lilly(monkeypatch, company, *, symbol="LLY", mention="礼来", question="礼来的营收是多少", steps=(), rows=None):
    monkeypatch.setattr(entities, "ticker_records", lambda: LILLY_RECORDS)
    context, *_ = _context(classified={"company": company, "symbol": symbol, "company_mention": mention}, steps=steps, rows=rows)
    return _run(question, context)


@pytest.mark.parametrize("company", ["Eli Lilly", "Eli Lilly and Company", "礼来制药公司"])
def test_every_form_of_the_name_reaches_the_same_outcome(monkeypatch, company):
    page = {**SECTOR_PAGE, "title": "礼来财报", "excerpt": "礼来本季度营收增长。"}
    result = _lilly(monkeypatch, company, steps=[_step("web_research", query="礼来 营收"), {"content": "礼来营收增长 [1]。"}], rows={"web_research": [page]})
    assert not result["pending_request"] and result["previous_scope"]["symbol"] == "LLY"
    # A page that says only 礼来 is about the mapped company.
    assert [c.get("title") for c in result["citations"]] == ["礼来财报"]
    last_line = result["answer"].splitlines()[-1]
    assert last_line.startswith("按 礼来 = ") and "（LLY）理解" in last_line
    assert result["audit"]["entity_mapped"]["symbol"] == "LLY"


def test_the_line_shows_the_official_title_for_a_mapping_only_the_looser_check_accepts(monkeypatch):
    result = _lilly(monkeypatch, "Eli Lilly and Company")
    assert "按 礼来 = ELI LILLY & Co（LLY）理解" in result["answer"]
    assert result["previous_scope"]["company"] == "ELI LILLY & Co"


def test_the_line_survives_an_answer_at_the_length_limit(monkeypatch):
    page = {**SECTOR_PAGE, "title": "礼来财报", "excerpt": "礼来本季度营收增长。"}
    result = _lilly(monkeypatch, "礼来制药公司", steps=[_step("web_research", query="礼来 营收"), {"content": "礼来" * 20000}], rows={"web_research": [page]})
    assert len(result["answer"]) <= 30000 and "（LLY）理解" in result["answer"].splitlines()[-1]


def test_a_ticker_the_user_wrote_needs_no_mapping_line(monkeypatch):
    result = _lilly(monkeypatch, "礼来制药公司", question="礼来 LLY 的营收是多少")
    assert not result["pending_request"] and "理解；" not in result["answer"] and "entity_mapped" not in result["audit"]


@pytest.mark.parametrize("company,symbol,mention,question", [
    ("Pfizer", "LLY", "礼来", "礼来的营收是多少"),                 # the Latin name contradicts the ticker's title
    ("礼来制药公司", "LLY", "礼来（Pfizer）", "礼来的营收是多少"),  # so does a Latin part of the mention
    ("礼来制药公司", "ZZZQ", "礼来", "礼来的营收是多少"),           # SEC does not list the ticker
    ("礼来制药公司", "LLY", "辉瑞", "礼来的营收是多少"),            # the name is not in the user's words
    ("礼来制药公司", "LLY", None, "最近有什么新闻"),               # nor is any name at all
])
def test_a_mapping_that_cannot_stand_still_asks(monkeypatch, company, symbol, mention, question):
    # The empty card itself goes in Phase 2; what Phase 1 must not do is proceed on these.
    result = _lilly(monkeypatch, company, symbol=symbol, mention=mention, question=question)
    assert result["pending_request"] and "理解；" not in result["answer"]


def test_an_unreachable_registry_does_not_map(monkeypatch):
    def down():
        raise OSError("sec unreachable")
    monkeypatch.setattr(entities, "ticker_records", down)
    context, *_ = _context(classified={"company": "礼来制药公司", "symbol": "LLY", "company_mention": "礼来"})
    assert _run("礼来的营收是多少", context)["pending_request"]


def test_a_name_fits_a_title_by_its_distinctive_words():
    assert entities.name_fits_title("Eli Lilly and Company", "ELI LILLY & Co")
    assert not entities.name_fits_title("Bank of America", "BANK OF NOVA SCOTIA")
    assert entities.name_fits_title("Eli Lilly Pharmaceuticals", "ELI LILLY & Co")


def test_several_tickers_are_not_mapped_from_one_name(monkeypatch):
    monkeypatch.setattr(entities, "ticker_records", lambda: LILLY_RECORDS)
    context, *_ = _context(classified={"company": "礼来制药公司", "symbol": "LLY", "symbols": ["LLY", "MU"], "company_mention": "礼来"})
    assert _run("礼来的营收是多少", context)["pending_request"]


# --- PCE 和 FOMC: the ticker-shaped backfill stops filtering rows ----------------------------------------------------

def test_macro_terms_read_as_tickers_do_not_filter_pages():
    context, _, _, _ = _context(steps=[_step("web_research", query="通胀 利率"), {"content": "美股走强 [1]。"}], rows={"web_research": [SECTOR_PAGE]})
    result = _run("PCE 和 FOMC 最近对美股有什么影响", context)
    assert result["audit"]["classify_symbols_backfilled"] is True
    assert [c.get("title") for c in result["citations"]] == ["Pharma sector"]


def test_a_turn_with_only_backfilled_symbols_can_read_what_a_page_names():
    turn = _turn_about("PCE 和 FOMC 的影响", classifier_named=False, entity_backfilled=True)
    turn.scope = {"symbol": "PCE", "symbols": ["PCE", "FOMC"]}
    turn.observations.append(_observed("web_research", {"url": "https://example.org/a", "excerpt": "SPY rose after the FOMC."}))
    turn.ground_arguments("query_stock_prices", {"symbol": "SPY"})
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "QQQ"})


# --- 4. load_hint --------------------------------------------------------------------------------------------------

def test_load_hint_is_generated_from_the_catalogue_and_drops_what_it_does_not_know():
    assert Routing.model_json_schema()["properties"]["load_hint"]["items"]["enum"] == list(TOOL_CATEGORIES)
    parsed = Routing.model_validate({"category": "A", "days_back": None, "load_hint": ["持仓", "没有这个类别", "持仓"]})
    assert parsed.load_hint == ["持仓"]
    assert Routing.model_validate({"category": "A", "days_back": None}).load_hint == []


def test_load_hint_preloads_a_category_with_no_load_tools_step():
    context, ran, _, offered = _context(classified={"load_hint": ["持仓"]}, steps=[_step("query_portfolio"), {"content": "INTC 持仓 100 股 [1]。"}],
                                        rows={"query_portfolio": [INTC_HOLDING]})
    result = _run("我今天赚了多少", context)
    assert "query_portfolio" in offered[0] and "record_trade" not in offered[0]
    assert [name for name, _ in ran] == ["query_portfolio"] and "load_tools_calls" not in result["audit"]
    assert "持仓" in result["audit"]["preloaded_categories"]


def test_load_hint_cannot_reveal_what_this_identity_may_not_use():
    context, *_ = _context()
    context = dataclasses.replace(context, identity_credential="guest")

    async def quiet(_event):
        pass
    turn = direct.Turn("q", context, quiet, [], {})
    turn.route = "A"
    turn.scope = {"mode": "none", "load_hint": ["持仓"], "requested_actions": []}
    assert "持仓" not in turn.preload_categories()


def test_load_hint_does_nothing_on_a_route_without_tools():
    context, *_ = _context()

    async def quiet(_event):
        pass
    turn = direct.Turn("q", context, quiet, [], {})
    turn.route = "B"
    turn.scope = {"load_hint": ["持仓"]}
    assert turn.preload_categories() == []


# --- 5. Prompt and identity ----------------------------------------------------------------------------------------

def test_c_must_be_positively_out_of_scope_and_ties_go_to_the_loop():
    prompt = direct.CLASSIFY_PROMPT
    assert "C — anything else" not in prompt
    assert "C — only when the request is clearly unrelated" in prompt and 'when in doubt choose A with mode "none"' in prompt
    assert '"帮我写个 Python 快排" → C' in prompt and '"65 岁退休要存多少" → B' in prompt
    assert "clearly unrelated" in direct.ROUTE_SCHEMA[0]["function"]["description"]


def test_the_prompt_only_names_categories_that_exist():
    assert {"持仓", "新闻与网页"} <= set(TOOL_CATEGORIES)
    assert 'load_hint ["持仓","新闻与网页"]' in direct.CLASSIFY_PROMPT


def test_the_product_no_longer_describes_itself_as_only_a_research_tool():
    assert "个人股票研究助理" not in " ".join(direct.INSTRUCTION)
    assert "个人投资助理" in direct.INSTRUCTION[0]
    assert "持仓" in direct.SCOPE_NOTICE["zh"] and "holdings" in direct.SCOPE_NOTICE["en"]


def test_the_scope_notice_alternatives_name_the_holdings():
    context, *_ = _context()
    seen = []

    async def quiet(_event):
        pass
    turn = direct.Turn("写个快排", context, quiet, [], {})
    turn.route = "C"

    async def model(messages, _tools, **_kwargs):
        seen.extend(messages)
        return {"content": "可以查持仓。"}
    turn.model = model
    asyncio.run(turn.answer_c())
    assert "holdings and P&L" in seen[0]["content"]


# --- The kind-agnostic test ----------------------------------------------------------------------------------------

def _with_fixture_tool(monkeypatch, policy):
    def definitions():
        return {**real_definitions(), policy.name: policy}
    import app.agent_tool_catalog as catalogue
    for module in (catalogue, direct, tools):
        monkeypatch.setattr(module, "definitions", definitions)


def _kind_nobody_designed_for():
    context, ran, _, _ = _context(steps=[_step("query_made_up_ledger"), {"content": "这个月手续费合计 12 美元 [1]。"}],
                                  rows={"query_made_up_ledger": [{"id": "fee-1", "title": "手续费账本", "excerpt": "这个月手续费合计 12 美元。"}]})
    result = _run("这个月交易手续费花了多少", context)
    assert ran == [("query_made_up_ledger", {})]
    assert result["status"] == "succeeded" and [c.get("title") for c in result["citations"]] == ["手续费账本"]


def test_a_new_tool_answers_an_unseen_question_with_no_edit_to_the_workflow(monkeypatch):
    _with_fixture_tool(monkeypatch, ToolPolicy("query_made_up_ledger", "Read a ledger nobody designed for.", Empty, "read"))
    _kind_nobody_designed_for()


@pytest.mark.xfail(strict=True, raises=TypeError, reason="evidence_class arrives in Phase 2; drop this marker then")
def test_a_new_tool_with_a_made_up_evidence_class_answers_an_unseen_question(monkeypatch):
    policy = ToolPolicy("query_made_up_ledger", "Read a ledger nobody designed for.", Empty, "read", evidence_class="made_up")
    _with_fixture_tool(monkeypatch, policy)
    _kind_nobody_designed_for()
