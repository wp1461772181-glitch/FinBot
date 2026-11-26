"""Stage 5b-1 half A: the kernel's ``set_watch_rule`` / ``delete_watch_rule`` (a card, a press), the ``list_watch_rules`` read, the owner routes,
the memory overview and the operation registry.  Disposable Postgres; no network, no model."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import agent_bots as bots
from app import sentinel_bridge, watch_rules, watch_rules_view
from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage, AgentTask, PortfolioPlan, WatchRule
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, legacy_definitions, schemas
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.kernel import act, loop, progress
from app.kernel.operation_registry import OPERATION_REGISTRY
from app.models import MarketPrice

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
OTHER_HASH = owner_hash("somebody-else")
ASK = "英特尔涨跌 10% 提醒我，20% 加急"
ARGS = {"symbol": "INTC", "metric": "day_change", "direction": "either",
        "levels": [{"threshold": 10, "level": "remind"}, {"threshold": 20, "level": "urgent"}], "quote": ASK}
HOLD = {"INTC": {"shares": 100.0, "avg_cost": 50.0, "total_assets": 10000.0}}


def run(coro):
    return asyncio.run(coro)


def make_run(question=ASK):
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id="c", bot_id=None, bot_name="", tool_scope=None,
                              default_company=None, watchlist=(), executor=None)
    return SimpleNamespace(context=context, user_text="", question=question, turn_id="t", web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], writes=[], audit={}, read_results=0, inbox=None)


def wipe():
    with SessionLocal() as db:
        for model in (WatchRule, MarketPrice, AgentConsent, AgentMessage):
            db.query(model).delete()
        db.commit()


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[WatchRule.__table__, MarketPrice.__table__, AgentConsent.__table__, AgentBot.__table__,
                                             AgentConversation.__table__, AgentMessage.__table__, PortfolioPlan.__table__, AgentTask.__table__])
    wipe()
    import app.agent_chat_identity as identity
    import app.agent_chat_stream as stream
    from app.agent_workflow import direct, tools
    for module in (consent, direct, tools, identity, act, stream):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: HOLD)
    monkeypatch.setattr(sentinel_bridge, "refresh_sentinel_snapshot", lambda: None)
    yield
    wipe()


def prepare(arguments, name="set_watch_rule", question=ASK):
    return run(act.prepare(make_run(question), name, arguments))


def press(prepared):
    conv = "aaaaaaaa-1111-2222-3333-444444444444"
    card = consent.propose(OWNER, conv, [prepared.operation], prepared.display)
    token = card["choices"][0]["value"].split(":", 1)[1]
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id=conv, bot_id=None, executor=None)
    return consent.execute(OWNER, conv, token, [prepared.operation], act.execute_handler(context))


def bars(symbol="INTC", days=45, spikes=None):
    today = watch_rules.today_ny()
    with SessionLocal() as db:
        for ago in range(days - 1, -1, -1):
            price = 100.0
            high = (spikes or {}).get(ago, price)
            db.add(MarketPrice(symbol=symbol, trading_date=today - timedelta(days=ago), open=price, high=high, low=price, close=price, volume=1000,
                               source="t", fetched_at=datetime.now(UTC)))
        db.commit()


def stored():
    with SessionLocal() as db:
        return [(r.symbol, r.metric, r.enabled) for r in db.query(WatchRule).filter_by(owner_hash=OWNER_HASH).order_by(WatchRule.created_at)]


# ---- the card ------------------------------------------------------------------------------------------------------------------

def test_the_card_is_the_reading_plus_the_dry_run_and_nothing_the_model_wrote(owner):
    bars(spikes={25: 111, 10: 121, 3: 112})
    out = prepare({**ARGS, "levels": ARGS["levels"]})
    assert isinstance(out, act.Prepared) and out.tier == 2 and stored() == []          # nothing is written by proposing
    display = out.display
    assert display["title"] == "设一条盯防规则 · 英特尔（INTC）"
    assert display["targets"] == [{"symbol": "INTC", "title": "英特尔相对昨收涨或跌达到 10%：提醒；达到 20%：加急。每天每档一次。", "quote": ASK}]
    today = watch_rules.today_ny()
    first, second, third = (today - timedelta(days=n) for n in (25, 10, 3))
    assert display["alternative"] == (f"按这条规则，过去 30 天会提醒你 4 次：{first:%m-%d}、{second:%m-%d}（提醒+加急）、{third:%m-%d}。\n"
                                      "点确认后生效；哨兵每分钟检查，不用模型。")
    assert out.operation["fields"]["levels"] == ARGS["levels"] and out.operation["arguments"]["quote"] == ASK


def test_the_dry_run_line_says_when_there_is_no_history(owner):
    out = prepare(ARGS)
    assert out.display["alternative"] == "试跑：没有足够的历史行情，试跑不了。\n点确认后生效；哨兵每分钟检查，不用模型。"


def test_a_dry_run_that_breaks_does_not_stop_the_card(owner, monkeypatch):
    monkeypatch.setattr(watch_rules, "dry_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    out = prepare(ARGS)
    assert isinstance(out, act.Prepared) and "没跑成" in out.display["alternative"]


def test_a_quote_that_is_not_his_is_refused_and_a_typed_yes_confirms_nothing(owner):
    out = prepare({**ARGS, "quote": "网页上说英特尔会涨很多"})
    assert out["error_code"] == "watch_quote_not_owners" and "原样摘出" in out["hint"]
    assert prepare({**ARGS, "quote": "英特"})["error_code"] == "watch_quote_not_owners"      # too short to anchor anything
    assert stored() == []


def test_a_refused_rule_comes_back_with_its_reason_and_no_card(owner):
    out = prepare({**ARGS, "symbol": "NVDA", "metric": "cost_change"}, question="英伟达比成本跌 10% 提醒我")
    assert out["error_code"] == "watch_quote_not_owners"          # the model's quote (about INTC) is not in this message
    out = prepare({**ARGS, "symbol": "NVDA", "metric": "cost_change", "quote": "比成本跌 10% 提醒我"}, question="英伟达比成本跌 10% 提醒我")
    assert out["error_code"] == "not_a_holding" and "NVDA" in out["reason"] and out["hint"] == out["reason"]
    assert prepare({**ARGS, "metric": "price", "direction": None})["error_code"] == "direction_required"
    with_missing = prepare({"quote": ASK, "symbol": "INTC"})
    assert with_missing["error_code"] == "invalid_arguments"          # a new rule needs metric and levels


def test_the_press_writes_exactly_what_the_card_showed(owner):
    out = prepare(ARGS)
    done = press(out)
    assert done["ok"] and stored() == [("INTC", "day_change", True)]
    rules = watch_rules.list_rules(OWNER_HASH)
    assert rules[0]["text"] == out.display["targets"][0]["title"] and rules[0]["created_on"] == watch_rules.today_ny().isoformat()
    with SessionLocal() as db:
        assert db.query(WatchRule).one().quote == ASK


def test_a_rule_is_never_created_without_the_card(owner):
    run_ = make_run()
    result = run(act.handle(run_, {"operation": "set_watch_rule", "arguments": ARGS}))
    assert result["data"][0]["status"] == "awaiting_confirmation" and len(run_.proposals) == 1 and stored() == []
    assert run_.writes == [{"operation": "set_watch_rule", "tier": 2, "outcome": "proposed"}]
    lookup = run(act.handle(make_run(), {"operation": "set_watch_rule"}))
    assert lookup["data"][0]["tier"] == 2 and lookup["data"][0]["rules"] == [] and "rule_id" in json.dumps(lookup["data"][0]["arguments"])


def test_update_shows_the_old_reading_and_changes_only_what_was_said(owner):
    press(prepare(ARGS))
    rule = watch_rules.list_rules(OWNER_HASH)[0]
    words = "英特尔的规则改成只看上涨，8% 提醒"
    out = prepare({"rule_id": rule["id"], "direction": "up", "levels": [{"threshold": 8, "level": "remind"}], "quote": "只看上涨，8% 提醒"}, question=words)
    assert out.display["title"] == "改一条盯防规则 · 英特尔（INTC）"
    assert out.display["alternative"].startswith(f"原来的规则：{rule['text']}\n") and out.display["targets"][0]["title"] == "英特尔相对昨收上涨达到 8%：提醒。每天最多一次。"
    assert out.operation["fields"]["metric"] == "day_change" and out.operation["fields"]["symbol"] == "INTC"
    assert press(out)["ok"]
    after = watch_rules.list_rules(OWNER_HASH)
    assert len(after) == 1 and after[0]["id"] == rule["id"] and after[0]["direction"] == "up"


def test_a_press_on_a_card_whose_rule_changed_since_is_refused(owner):
    press(prepare(ARGS))
    rule = watch_rules.list_rules(OWNER_HASH)[0]
    out = prepare({"rule_id": rule["id"], "repeat": "once", "quote": "英特尔只提醒一次"}, question="英特尔只提醒一次")
    watch_rules.update(OWNER_HASH, rule["id"], {"repeat": "daily", "levels": [{"threshold": 7, "level": "remind"}]})
    done = press(out)
    assert not done["ok"] and done["data"][0]["error_code"] == "card_stale"
    assert watch_rules.list_rules(OWNER_HASH)[0]["repeat"] == "daily"          # the stale card wrote nothing


def test_delete_is_a_card_too_and_is_soft(owner):
    press(prepare(ARGS))
    rule = watch_rules.list_rules(OWNER_HASH)[0]
    out = prepare({"rule_id": rule["id"]}, "delete_watch_rule", question="不用盯英特尔了")
    assert out.tier == 2 and out.display["title"] == "删掉一条盯防规则 · 英特尔（INTC）" and out.display["targets"][0]["title"] == rule["text"]
    assert len(watch_rules.list_rules(OWNER_HASH)) == 1
    assert press(out)["ok"]
    assert watch_rules.list_rules(OWNER_HASH) == [] and stored() == [("INTC", "day_change", False)]
    assert prepare({"rule_id": rule["id"]}, "delete_watch_rule")["error_code"] == "rule_not_found"
    assert prepare({"rule_id": "not-a-rule"}, "delete_watch_rule")["error_code"] == "rule_not_found"


def test_another_owners_rule_is_not_found(owner):
    rule = watch_rules.create(OTHER_HASH, ARGS | {"quote": None}, "q")
    assert prepare({"rule_id": rule["id"]}, "delete_watch_rule")["error_code"] == "rule_not_found"
    assert prepare({"rule_id": rule["id"], "repeat": "once", "quote": ASK})["error_code"] == "rule_not_found"


# ---- the catalogue, the kernel and the old engine --------------------------------------------------------------------------------------

def test_the_operations_are_kernel_only_owner_only_and_the_old_engine_does_not_see_them():
    for name in ("set_watch_rule", "delete_watch_rule", "list_watch_rules"):
        assert name in KERNEL_ONLY and name in OWNER_ONLY and name not in legacy_definitions()
        assert not any(s["function"]["name"] == name for s in schemas(owner=True))
        assert not any(s["function"]["name"] == name for s in schemas(owner=False, kernel=True))
    assert definitions()["list_watch_rules"].level == "read" and "list_watch_rules" in loop.READ_TOOLS
    assert progress.TOOL_PHRASES["list_watch_rules"] and any(s["function"]["name"] == "list_watch_rules" for s in schemas(owner=True, kernel=True))
    assert act.tier_of("set_watch_rule") == act.tier_of("delete_watch_rule") == 2 and "set_watch_rule" in act.ACT_SCHEMA["function"]["description"]


def test_the_directory_tells_the_model_what_is_and_is_not_a_rule():
    text = act.SUMMARIES["set_watch_rule"]
    for metric in watch_rules.METRICS:
        assert metric in text
    assert "remember" in text and "新闻" in text           # a condition that needs content is an instruction, not a rule
    for missing in ("期权", "卖空比例", "分析师评级"):
        assert missing in text


def test_the_registry_maps_the_routes_to_the_operations():
    assert OPERATION_REGISTRY[("POST", "/agent-chat/watch-rules")] == {"operation": "set_watch_rule"}
    assert OPERATION_REGISTRY[("PATCH", "/agent-chat/watch-rules/{rule_id}")] == {"operation": "set_watch_rule"}
    assert OPERATION_REGISTRY[("DELETE", "/agent-chat/watch-rules/{rule_id}")] == {"operation": "delete_watch_rule"}


def test_a_scoped_bot_keeps_the_watch_operations():
    assert {"set_watch_rule", "delete_watch_rule", "list_watch_rules"} <= bots.ALWAYS_ON


# ---- list_watch_rules --------------------------------------------------------------------------------------------------------------

def test_list_watch_rules_has_his_rules_and_the_marked_defaults(owner, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "none.db"))
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)
    mine = watch_rules.create(OWNER_HASH, ARGS | {"quote": None}, ASK)
    watch_rules.create(OWNER_HASH, {"symbol": "NVDA", "metric": "price", "direction": "below", "levels": [{"threshold": 90, "level": "remind"}]}, "q")
    rows = watch_rules_view.rows(OWNER_HASH)
    own = [r for r in rows if r["kind"] == "你自己定的规则"]
    defaults = [r for r in rows if r["kind"] == "系统默认"]
    assert [r["id"] for r in own][0] == mine["id"] and own[0]["text"] == mine["text"] and own[0]["created_on"] == mine["created_on"]
    assert own[0]["last_fired"] is None
    assert own[0]["note"] == "默认的涨跌分级对它不生效" and "note" not in own[1]
    assert len(defaults) == 4 and "标准" in defaults[0]["text"] and "INTC 默认的涨跌分级对它不生效" in defaults[0]["text"]
    assert "止损价永远会盯" in defaults[1]["text"] and defaults[2]["text"] == "5 分钟急动提醒：关。"


def test_list_watch_rules_reads_the_last_firing_from_the_sentinel_store(owner, monkeypatch, tmp_path):
    import sqlite3
    path = tmp_path / "sentinel.db"
    rule = watch_rules.create(OWNER_HASH, ARGS | {"quote": None}, ASK)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE rule_state(rule_id TEXT, ny_date TEXT, level TEXT, fired_at REAL)")
    conn.execute("INSERT INTO rule_state VALUES (?, '2026-11-20', 'remind', 1763640000)", (rule["id"],))
    conn.commit()
    conn.close()
    monkeypatch.setenv("SENTINEL_DB_PATH", str(path))
    assert watch_rules_view.rows(OWNER_HASH)[0]["last_fired"] == "2025-11-20 12:00"


def test_the_read_tool_dispatch_returns_the_rows(owner):
    from app.agent_workflow import tools
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id="c", tool_scope=None, executor=None)
    watch_rules.create(OWNER_HASH, ARGS | {"quote": None}, ASK)
    out = run(tools.invoke("list_watch_rules", {}, context))
    assert out["ok"] and out["data"][0]["kind"] == "你自己定的规则"
    guest = SimpleNamespace(identity_credential="x" * 64, owner_hash=OTHER_HASH, conversation_id="c", tool_scope=None, executor=None)
    assert run(tools.invoke("list_watch_rules", {}, guest))["error_code"] == "owner_login_required"


# ---- the routes and the memory page ----------------------------------------------------------------------------------------------------

def test_the_routes_are_owner_only_and_validate(owner, client):
    mine, guest = {"X-Chat-Session": OWNER}, {"X-Chat-Session": "g" * 64}
    body = {"symbol": "INTC", "metric": "day_change", "direction": "either", "levels": [{"threshold": 10, "level": "remind"}], "quote": ASK}
    assert client.post("/agent-chat/watch-rules", json=body, headers=guest).status_code == 403
    assert client.get("/agent-chat/watch-rules", headers=guest).status_code == 403
    made = client.post("/agent-chat/watch-rules", json=body, headers=mine)
    assert made.status_code == 200 and made.json()["text"] == "英特尔相对昨收涨或跌达到 10%：提醒。每天最多一次。"
    bad = client.post("/agent-chat/watch-rules", json={**body, "metric": "rsi"}, headers=mine)
    assert bad.status_code == 422 and bad.json()["detail"]["error_code"] == "unknown_metric"
    rule_id = made.json()["id"]
    listed = client.get("/agent-chat/watch-rules", headers=mine).json()
    assert [r["id"] for r in listed["rules"]] == [rule_id] and all(d["kind"] == "系统默认" for d in listed["defaults"])
    changed = client.patch(f"/agent-chat/watch-rules/{rule_id}", json={"repeat": "once"}, headers=mine)
    assert changed.status_code == 200 and changed.json()["repeat"] == "once"
    assert client.patch(f"/agent-chat/watch-rules/{rule_id}", json={"repeat": "hourly"}, headers=mine).status_code == 422
    assert client.delete(f"/agent-chat/watch-rules/{rule_id}", headers=guest).status_code == 403
    assert client.delete(f"/agent-chat/watch-rules/{rule_id}", headers=mine).status_code == 200
    assert client.delete(f"/agent-chat/watch-rules/{rule_id}", headers=mine).status_code == 404
    assert client.get("/agent-chat/watch-rules", headers=mine).json()["rules"] == []


def test_the_memory_overview_lists_his_rules_with_their_text(owner):
    from app import memory_overview
    rule = watch_rules.create(OWNER_HASH, ARGS | {"quote": None}, ASK)
    watch = memory_overview.collect(OWNER_HASH)["watch"]
    assert watch["rules"] == [{"id": rule["id"], "symbol": "INTC", "text": rule["text"], "created_on": rule["created_on"], "expires_on": None}]
    assert memory_overview.collect(OWNER_HASH)["counts"]["watch"] == 1
    lines = memory_overview._watch_lines(watch)
    assert "### 你自己定的规则" in lines and any(rule["text"] in line for line in lines)
