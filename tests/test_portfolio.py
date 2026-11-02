"""Portfolio v1 (personal finance assistant plan, Task 6): the calculation rules with the plan's worked numbers,
the owner-only API and tools, and the confirmation-card path ("我买了 100 股 INTC，成本 80")."""
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import agent_bots as bots
from app import portfolio
from app.agent_chat_models import AgentBot, AgentConversation, PortfolioPlan, PortfolioTransaction
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import OWNER_ONLY, definitions, schemas
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.models import MarketPrice, MarketPriceRevision
from app.portfolio import PortfolioError, Quote, Txn, clean_entry, replay, summarize

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
DAY = date(2026, 10, 1)


def txn(kind, symbol="INTC", quantity=0, price=0, fee=0, amount=0, ratio=0, on=DAY, n=0):
    return Txn(kind=kind, symbol=symbol, quantity=D(str(quantity)), price=D(str(price)), fee=D(str(fee)), amount=D(str(amount)),
               ratio=D(str(ratio)), occurred_on=on, id=str(n), created_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=n))


def one(summary, symbol="INTC"):
    return next(p for p in summary["positions"] if p["symbol"] == symbol)


# --- pure rules (the plan's worked numbers) ------------------------------------------------------------------

def test_cost_and_realized():
    history = [txn("buy", quantity=100, price=80, fee=1, n=1), txn("sell", quantity=40, price=100, fee=1, n=2)]
    ledger = replay(history)
    position = ledger.positions["INTC"]
    assert position.shares == 60
    assert position.avg_cost == D("80.01")          # 8001 / 100: the average does not move on a sell
    assert round(position.realized, 2) == D("798.60")  # 3999 - 3200.40
    assert round(position.diluted_cost, 2) == D("66.70")  # (8001 - 3999) / 60
    view = one(summarize(history, {"INTC": Quote(D("90"), DAY)}))
    assert (view["shares"], view["avg_cost"], view["diluted_cost"], view["realized_pnl"]) == ("60", "80.0100", "66.7000", "798.60")
    assert view["floating_pnl"] == "599.40"        # 60 * (90 - 80.01)


def test_available_funds():
    history = [txn("deposit", symbol="", amount=10000, n=1), txn("buy", quantity=100, price=80, fee=1, n=2)]
    assert replay(history).funds == D("1999")
    # an opening position moves no cash, a dividend and a sell add, a withdrawal and a adjustment follow their sign
    assert replay([*history, txn("opening", symbol="AAPL", quantity=10, price=150, n=3)]).funds == D("1999")
    assert replay([*history, txn("dividend", amount=12.5, n=3)]).funds == D("2011.5")
    assert replay([*history, txn("withdraw", symbol="", amount=999, n=3), txn("cash_adjust", symbol="", amount=-500, n=4)]).funds == D("500")
    assert summarize(history)["available_funds"] == "1999.00"


def test_split_adjusts_position():
    before = [txn("buy", quantity=1, price=100, n=1)]
    after = [*before, txn("split", ratio=2, n=2)]
    # price halves with the split: the same market value, so the floating P&L does not move
    a = one(summarize(before, {"INTC": Quote(D("120"), DAY)}))
    b = one(summarize(after, {"INTC": Quote(D("60"), DAY)}))
    assert (a["shares"], b["shares"]) == ("1", "2")
    assert (a["avg_cost"], b["avg_cost"]) == ("100.0000", "50.0000")
    assert a["floating_pnl"] == b["floating_pnl"] == "20.00"
    with pytest.raises(PortfolioError) as caught:
        replay([txn("split", ratio=2)])
    assert caught.value.code == "no_position_to_split"


def test_today_pnl_is_reference_only_when_traded_that_day():
    quote = Quote(D("110"), date(2026, 10, 2), D("100"), date(2026, 10, 1))
    quiet = one(summarize([txn("buy", quantity=10, price=90, on=date(2026, 9, 1), n=1)], {"INTC": quote}))
    assert quiet["today_pnl"] == "100.00" and quiet["today_pnl_reference_only"] is False
    traded = one(summarize([txn("buy", quantity=10, price=90, on=date(2026, 10, 2), n=1)], {"INTC": quote}))
    assert traded["today_pnl"] == "100.00" and traded["today_pnl_reference_only"] is True


def test_weight_and_total_assets():
    summary = summarize([txn("deposit", symbol="", amount=1000, n=1), txn("buy", quantity=10, price=50, n=2)],
                        {"INTC": Quote(D("60"), DAY)})
    assert (summary["available_funds"], summary["positions_value"], summary["total_assets"]) == ("500.00", "600.00", "1100.00")
    assert one(summary)["weight_pct"] == "54.55"
    missing = summarize([txn("buy", quantity=10, price=50, n=1)], {})
    assert missing["total_assets"] is None and missing["unpriced"] == ["INTC"] and "price_missing" in missing["warnings"]


@pytest.mark.parametrize("fields,code", [
    ({"kind": "buy", "symbol": "INTC", "quantity": 0, "price": 80}, "invalid_quantity"),
    ({"kind": "buy", "symbol": "INTC", "quantity": 1, "price": -1}, "invalid_price"),
    ({"kind": "buy", "symbol": "INTC", "quantity": 1, "price": 1, "fee": -1}, "invalid_fee"),
    ({"kind": "buy", "symbol": "not a ticker!", "quantity": 1, "price": 1}, "invalid_symbol"),
    ({"kind": "split", "symbol": "INTC", "ratio": 1}, "invalid_ratio"),
    ({"kind": "deposit", "amount": -5}, "invalid_amount"),
    ({"kind": "gift", "symbol": "INTC"}, "invalid_kind"),
    ({"kind": "buy", "symbol": "INTC", "quantity": 1, "price": 1, "occurred_on": "2999-01-01"}, "invalid_date"),
])
def test_bad_entries_are_refused(fields, code):
    with pytest.raises(PortfolioError) as caught:
        clean_entry(fields)
    assert caught.value.code == code


# --- database ---------------------------------------------------------------------------------------------

@pytest.fixture
def owner(monkeypatch, disposable_database, tmp_path):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_")
                                             and t.name not in skipped])
    with SessionLocal() as db:
        for model in (PortfolioTransaction, PortfolioPlan, AgentConsent, AgentBot, AgentConversation):
            db.query(model).delete()
        # The test database is shared by the whole session: other modules leave market_price_revisions rows that
        # reference these prices (FK ondelete=RESTRICT), so drop the dependent revisions before the prices.
        owned = db.query(MarketPrice.id).filter(MarketPrice.symbol.in_(["INTC", "AAPL"]))
        db.query(MarketPriceRevision).filter(MarketPriceRevision.market_price_id.in_(owned.scalar_subquery())
                                             ).delete(synchronize_session=False)
        db.query(MarketPrice).filter(MarketPrice.symbol.in_(["INTC", "AAPL"])).delete(synchronize_session=False)
        db.commit()
    from app.agent_workflow import direct, tools
    import app.agent_chat_identity as identity
    for module in (consent, direct, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)
    import app.agent_chat_stream as stream
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda c: c == OWNER)
    monkeypatch.setattr(stream, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    monkeypatch.setenv("SENTINEL_CONFIG_PATH", str(tmp_path / "sentinel-config.json"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return OWNER


def price(symbol, on, close):
    with SessionLocal() as db:
        db.add(MarketPrice(symbol=symbol, trading_date=on, open=close, high=close, low=close, close=close, volume=1,
                           source="test", fetched_at=datetime.now(UTC)))
        db.commit()


def record(**fields):
    return portfolio.record_transaction(OWNER_HASH, fields, today=date(2026, 10, 5))


def count():
    with SessionLocal() as db:
        return db.query(PortfolioTransaction).filter_by(owner_hash=OWNER_HASH).count()


def test_sell_more_than_held_rejected(owner):
    record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    with pytest.raises(PortfolioError) as caught:
        record(kind="sell", symbol="INTC", quantity=11, price=60, occurred_on="2026-10-02")
    assert caught.value.code == "sell_exceeds_holdings"
    assert count() == 1  # nothing written
    # a card for it is never minted either
    with pytest.raises(PortfolioError):
        portfolio.describe_write(OWNER_HASH, "record_trade", {"kind": "sell", "symbol": "INTC", "quantity": 11, "price": 60})
    # selling shares held only later in the history is refused too (the history is replayed in date order)
    with pytest.raises(PortfolioError):
        record(kind="sell", symbol="INTC", quantity=5, price=60, occurred_on="2026-09-01")
    assert count() == 1


def test_negative_funds_warns(owner):
    result = record(kind="deposit", amount=100)
    assert result["warnings"] == []
    result = record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    assert result["ok"] and result["warnings"] == ["available_funds_negative"]
    assert "可用资金为负" in result["warning_text"][0]
    assert count() == 2  # still recorded
    assert portfolio.build_summary(OWNER_HASH)["available_funds"] == "-400.00"
    card = portfolio.describe_write(OWNER_HASH, "record_trade", {"kind": "buy", "symbol": "INTC", "quantity": 1, "price": 10})
    assert "可用资金为负" in card["alternative"]


def test_delete_that_would_orphan_a_sell_is_refused(owner):
    bought = record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    sold = record(kind="sell", symbol="INTC", quantity=4, price=60, occurred_on="2026-10-02")
    with pytest.raises(PortfolioError) as caught:
        portfolio.delete_transaction(OWNER_HASH, bought["id"])
    assert caught.value.code == "would_break_history" and count() == 2
    assert portfolio.delete_transaction(OWNER_HASH, sold["id"])["status"] == "deleted" and count() == 1


def test_set_available_funds_writes_the_difference(owner):
    record(kind="deposit", amount=1000)
    assert portfolio.set_available_funds(OWNER_HASH, "1500.50", today=date(2026, 10, 5))["available_funds"] == "1500.50"
    with SessionLocal() as db:
        adjust = db.query(PortfolioTransaction).filter_by(kind="cash_adjust").one()
    assert adjust.amount == D("500.50")
    assert portfolio.set_available_funds(OWNER_HASH, "1500.50", today=date(2026, 10, 5))["status"] == "unchanged"
    assert count() == 2


def test_plan_upsert_changes_only_given_fields(owner):
    portfolio.set_plan(OWNER_HASH, "intc", {"plan_text": "跌到 70 补", "add_price": 70, "stop_price": 60})
    portfolio.set_plan(OWNER_HASH, "INTC", {"target_price": "100", "stop_price": None})
    plan = portfolio.load_plans(SessionLocal(), OWNER_HASH)["INTC"]
    assert (plan["plan_text"], plan["add_price"], plan["stop_price"], plan["target_price"]) == ("跌到 70 补", "70.0000", None, "100.0000")
    with pytest.raises(PortfolioError):
        portfolio.set_plan(OWNER_HASH, "INTC", {"add_price": -1})


def test_summary_reads_latest_price_and_its_date(owner):
    record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-09-01")
    price("INTC", date(2026, 9, 30), 55.0)
    price("INTC", date(2026, 10, 1), 60.0)
    summary = portfolio.build_summary(OWNER_HASH)
    view = one(summary)
    assert (view["price"], view["price_date"], view["today_pnl"]) == ("60.0000", "2026-10-01", "50.00")
    assert summary["price_date"] == "2026-10-01" and summary["transactions"][0]["kind"] == "buy"


def test_sentinel_view_and_snapshot_wiring(owner, tmp_path):
    from app import sentinel_bridge
    record(kind="deposit", amount=1000)
    record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    price("INTC", date(2026, 10, 1), 60.0)
    portfolio.set_plan(OWNER_HASH, "INTC", {"plan_text": "拿住", "stop_price": 45})
    view = portfolio.sentinel_view(OWNER_HASH)
    assert set(view) >= {"positions", "plans", "total_assets"}
    assert view["total_assets"] == 1100.0
    assert view["positions"][0]["symbol"] == "INTC" and view["positions"][0]["price"] == 60.0
    assert view["plans"] == [{"symbol": "INTC", "plan_text": "拿住", "add_price": None, "stop_price": 45.0, "target_price": None}]
    sentinel_bridge.write_sentinel_snapshot(OWNER_HASH)
    written = json.loads((tmp_path / "sentinel-config.json").read_text())
    assert written["positions"][0]["symbol"] == "INTC" and written["total_assets"] == 1100.0 and written["plans"][0]["stop_price"] == 45.0


# --- API ----------------------------------------------------------------------------------------------------

def test_api_is_owner_only_and_snapshots_after_writes(owner, client, tmp_path):
    base = "/agent-chat/portfolio"
    assert client.get(base).status_code == 403
    assert client.get(base, headers={"X-Chat-Session": "stranger"}).status_code == 403
    assert client.post(base + "/transactions", json={"kind": "deposit", "amount": 5}).status_code in {401, 403}
    headers = {"X-Chat-Session": OWNER}
    assert client.post(base + "/transactions", headers=headers, json={"kind": "deposit", "amount": 10000}).status_code == 200
    bought = client.post(base + "/transactions", headers=headers,
                         json={"kind": "buy", "symbol": "INTC", "quantity": 100, "price": 80, "fee": 1, "occurred_on": "2026-10-01"})
    assert bought.status_code == 200 and bought.json()["warnings"] == []
    snapshot = json.loads((tmp_path / "sentinel-config.json").read_text())
    assert snapshot["positions"][0]["symbol"] == "INTC"
    refused = client.post(base + "/transactions", headers=headers,
                          json={"kind": "sell", "symbol": "INTC", "quantity": 101, "price": 80})
    assert refused.status_code == 422 and refused.json()["detail"]["error_code"] == "sell_exceeds_holdings"
    summary = client.get(base, headers=headers).json()
    assert summary["available_funds"] == "1999.00" and one(summary)["shares"] == "100"
    assert client.put(base + "/plans/INTC", headers=headers, json={"plan_text": "跌到 70 补", "add_price": 70}).status_code == 200
    assert json.loads((tmp_path / "sentinel-config.json").read_text())["plans"][0]["add_price"] == 70.0
    assert client.put(base + "/cash", headers=headers, json={"available_funds": "2500"}).json()["available_funds"] == "2500.00"
    entry = bought.json()["id"]
    assert client.delete(base + "/transactions/" + entry, headers=headers).status_code == 200
    assert client.delete(base + "/transactions/" + entry, headers=headers).status_code == 404


# --- agent: tools, cards, citations --------------------------------------------------------------------------

def _call(name, arguments, call_id=None):
    return {"tool_calls": [{"id": call_id or name, "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


async def _quiet(_event):
    pass


def _context(bot, **kwargs):
    from app.agent_workflow.state import AgentRuntimeContext
    kwargs.setdefault("resolver", lambda payload: {"relationship": "new", "canonical_question": payload["question"]})
    kwargs.setdefault("intent_recognizer", lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    return AgentRuntimeContext("custom", "test", "dummy", identity_credential=OWNER, owner_hash=OWNER_HASH,
                               conversation_id=bot["conversation_id"], bot_id=bot["id"], bot_name=bot["name"], **kwargs)


def _turn(question, context, **kwargs):
    from app import agent_chat_store as store
    from app.agent_workflow import direct

    async def run():
        try:
            return await direct.run_direct_turn(question, context, emit=_quiet, **kwargs)
        finally:
            await store.engine.dispose()
    return asyncio.run(run())


def _press(card, context, choice="confirm:"):
    value = next(c["value"] for c in card["choices"] if c["value"].startswith(choice))
    return _turn(value, context, state={"pending_request": card, "requested_pending_id": card["id"]})


def _proposer(name, arguments):
    steps = iter([_call(name, arguments), {"content": "请确认。"}])
    return lambda *_: next(steps)


def _route(*actions):
    return lambda _p: {"category": "D", "days_back": None, "requested_actions": list(actions)}


def test_catalogue_is_owner_only_with_cards_for_writes():
    policies = definitions()
    assert policies["query_portfolio"].level == "read" and not policies["query_portfolio"].guest
    for name in ("record_trade", "set_available_funds", "set_position_plan"):
        assert policies[name].level == "reversible" and policies[name].confirmation and name in OWNER_ONLY
    assert "query_portfolio" in OWNER_ONLY


def test_guest_cannot_read(owner, client):
    from app.agent_workflow import tools
    from app.agent_workflow.state import AgentRuntimeContext
    guest_tools = {s["function"]["name"] for s in schemas(owner=False, granted={"record_trade", "set_available_funds", "set_position_plan"})}
    assert not guest_tools & {"query_portfolio", "record_trade", "set_available_funds", "set_position_plan"}
    owner_tools = {s["function"]["name"] for s in schemas(owner=True)}
    assert "query_portfolio" in owner_tools
    record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    context = AgentRuntimeContext("custom", "test", "dummy", identity_credential="a-guest", owner_hash=owner_hash("a-guest"))
    refused = asyncio.run(tools.invoke("query_portfolio", {}, context))
    assert refused["ok"] is False and refused["error_code"] == "owner_login_required" and not refused["data"]
    assert client.get("/agent-chat/portfolio").status_code == 403
    assert client.get("/agent-chat/portfolio", headers={"X-Chat-Session": "a-guest"}).status_code == 403


def test_trade_by_conversation_makes_a_card_then_records_once(owner):
    finbot = bots.create_bot(OWNER_HASH, {"name": "FinBot"})
    args = {"kind": "buy", "symbol": "INTC", "quantity": 100, "price": 80, "occurred_on": "2026-10-01"}
    context = _context(finbot, decider=_proposer("record_trade", args), intent_recognizer=_route("record_trade"))
    waiting = _turn("我买了 100 股 INTC，成本 80", context)
    card = waiting["pending_request"]
    assert card["display"]["title"] == "记录买入 · INTC" and count() == 0  # nothing before the press
    assert "8000.00" in card["display"]["alternative"]
    done = _press(card, _context(finbot, decider=lambda *_: {"content": "已记录。"}))
    assert count() == 1, done
    with SessionLocal() as db:
        row = db.query(PortfolioTransaction).one()
    assert (row.symbol, row.kind, row.quantity, row.price, row.amount) == ("INTC", "buy", D("100"), D("80"), D("8000"))


def test_confirm_card_replay_no_double_entry(owner):
    finbot = bots.create_bot(OWNER_HASH, {"name": "FinBot"})
    args = {"kind": "buy", "symbol": "INTC", "quantity": 100, "price": 80, "occurred_on": "2026-10-01"}
    context = _context(finbot, decider=_proposer("record_trade", args), intent_recognizer=_route("record_trade"))
    card = _turn("我买了 100 股 INTC，成本 80", context)["pending_request"]
    after = _context(finbot, decider=lambda *_: {"content": "已记录。"})
    _press(card, after)
    try:
        _press(card, after)  # the same card pressed again: refused or answered from the saved result, never run again
    except Exception:
        pass
    assert count() == 1
    # the same at the consent layer: a second execute returns the saved result and runs nothing
    from app.agent_workflow import tools
    operation = {"name": "record_trade", "arguments": {"kind": "buy", "symbol": "AAPL", "quantity": 1, "price": 10, "occurred_on": "2026-10-02"}}
    proposed = consent.propose(OWNER, finbot["conversation_id"], [operation], {"title": "t"})
    token = proposed["choices"][0]["value"].split(":", 1)[1]
    ctx = _context(finbot)

    def handler(op, key):
        return asyncio.run(tools.execute_reversible(op, key, ctx))
    first = consent.execute(OWNER, finbot["conversation_id"], token, [operation], handler)
    second = consent.execute(OWNER, finbot["conversation_id"], token, [operation], handler)
    assert first == second and first["ok"] and count() == 2


def test_a_sell_over_holdings_by_conversation_makes_no_card(owner):
    record(kind="buy", symbol="INTC", quantity=10, price=50, occurred_on="2026-10-01")
    finbot = bots.create_bot(OWNER_HASH, {"name": "FinBot"})
    args = {"kind": "sell", "symbol": "INTC", "quantity": 50, "price": 60}
    context = _context(finbot, decider=_proposer("record_trade", args), intent_recognizer=_route("record_trade"))
    result = _turn("我卖了 50 股 INTC，价格 60", context)
    assert not result.get("pending_request") and count() == 1


def test_query_portfolio_rows_carry_portfolio_citations_with_every_figure(owner):
    from app.agent_workflow.evidence import number_rows, unsupported_number_values
    record(kind="deposit", amount=10000, occurred_on="2026-09-30")
    record(kind="buy", symbol="INTC", quantity=100, price=80, fee=1, occurred_on="2026-10-01")
    price("INTC", date(2026, 10, 1), 90.0)
    price("INTC", date(2026, 10, 2), 92.0)
    from app.agent_tools import query_portfolio
    from app.knowledge.runtime import research_context
    citations = []

    async def read():
        with research_context(OWNER_HASH, citations=[]):
            return await query_portfolio.ainvoke({"symbol": "INTC"})
    outcome = asyncio.run(read())
    assert outcome["ok"] and {r["source_type"] for r in outcome["data"]} == {"portfolio"}
    rows = number_rows("query_portfolio", [dict(r) for r in outcome["data"]], citations, {})
    assert [c["source_type"] for c in citations] == ["portfolio", "portfolio"]
    position = next(c for c in citations if c["symbol"] == "INTC")
    for figure in ("平均成本 80.0100", "摊薄成本 80.0100", "最新价 92.0000（数据日期 2026-10-02）", "浮动盈亏 1199.00", "可用资金"):
        assert figure in position["quote"] + citations[0]["quote"]
    assert rows[1]["citation"] == "[2]"
    answer = "INTC 持有 100 股，平均成本 80.01，最新价 92，浮动盈利 1199 [2]。可用资金 1999 [1]。"
    assert unsupported_number_values(answer, citations) == []
    assert unsupported_number_values("INTC 浮动盈利 5000 [2]。", citations) == [5000.0]


def test_a_question_about_the_portfolio_is_answered_with_numbers_that_pass_verification(owner):
    """「我今天赚了多少」: query_portfolio is read, its rows are numbered [n], and the answer's figures are held to them."""
    record(kind="deposit", amount=10000, occurred_on="2026-09-30")
    record(kind="buy", symbol="INTC", quantity=100, price=80, fee=1, occurred_on="2026-09-30")
    price("INTC", date(2026, 10, 1), 90.0)
    price("INTC", date(2026, 10, 2), 92.0)
    finbot = bots.create_bot(OWNER_HASH, {"name": "FinBot"})
    good = "今天 INTC 持仓盈亏 200 [2]，可用资金 1999 [1]。"
    bad = "今天 INTC 持仓盈亏 777 [2]。"

    def run(answer):
        steps = iter([_call("query_portfolio", {}), {"content": answer}, {"content": answer}, {"content": answer}])
        context = _context(finbot, decider=lambda *_: next(steps),
                           intent_recognizer=lambda _p: {"category": "A", "mode": "none", "days_back": None, "requested_actions": []})
        return _turn("我今天赚了多少", context)
    kept = run(good)
    assert kept["status"] == "succeeded" and kept["answer"] == good
    assert {c["source_type"] for c in kept["citations"]} == {"portfolio"}
    dropped = run(bad)  # 777 is in no portfolio row
    assert dropped["status"] == "failed" and "777" not in dropped["answer"]
    assert dropped["audit"]["stop_reason"] == "unsupported_numeric_claim"


def test_zz_leaves_a_price_revision_behind_for_a_shared_database(owner):
    # Stand-in for other modules: they leave market_price_revisions rows pointing at prices of the same symbols.
    price("INTC", date(2026, 10, 2), 61)
    with SessionLocal() as db:
        row = db.query(MarketPrice).filter_by(symbol="INTC").one()
        db.add(MarketPriceRevision(market_price_id=row.id, symbol="INTC", trading_date=row.trading_date,
                                   open=61, high=61, low=61, close=61, volume=1, source="test", revision_number=1,
                                   content_hash="0" * 64, available_at=datetime.now(UTC), observed_at=datetime.now(UTC),
                                   is_initial_backfill=True))
        db.commit()


def test_zz_fixture_setup_survives_foreign_revisions(owner):
    with SessionLocal() as db:
        assert db.query(MarketPrice).filter_by(symbol="INTC").count() == 0
