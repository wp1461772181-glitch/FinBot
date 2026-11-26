"""Stage 5b-2 part 1 (API): the system's default rules made visible and editable — the catalog, overrides and reset, the four new metrics (validation,
reading, dry run), the snapshot the sentinel reads (equal to ``fixtures/watch_presets_contract.json``), the cards of ``set_watch_preset`` and
``set_alert_settings``, the routes and the list.  Disposable Postgres; no network, no model."""
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app import agent_bots as bots
from app import sentinel_bridge, watch_presets, watch_rules, watch_rules_view
from app.agent_chat_models import AlertSetting, WatchPresetOverride, WatchRule
from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, legacy_definitions, schemas
from app.database import SessionLocal
from app.kernel import act
from app.kernel.operation_registry import OPERATION_REGISTRY
from app.models import MarketPrice
from app.watch_rules import WatchRuleError, describe, dry_run, dry_run_line, validate
from tests.test_watch_rules_act import HOLD, OTHER_HASH, OWNER, OWNER_HASH, make_run, owner, press, prepare, run  # noqa: F401  (owner: fixture)

TODAY = date(2026, 11, 26)
CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "watch_presets_contract.json").read_text())
HARD = "这条是硬保证，不能关。"
TIERS = {"quiet": {"remind": 2.5, "major": 5.0}, "standard": {"remind": 2.0, "major": 4.0}, "sensitive": {"remind": 1.5, "major": 3.0}}


@pytest.fixture(autouse=True)
def plain_env(monkeypatch):
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)
    monkeypatch.delenv("SENTINEL_SHORT_MOVES", raising=False)


def level(*pairs):
    return [{"threshold": t, "level": lv} for t, lv in pairs]


def daily(symbol, rows):
    """``rows``: dicts (close, and optionally high, low, volume), oldest first, on consecutive days ending TODAY."""
    with SessionLocal() as s:
        for index, bar in enumerate(rows):
            day = TODAY - timedelta(days=len(rows) - 1 - index)
            close = bar["close"]
            s.add(MarketPrice(symbol=symbol, trading_date=day, open=bar.get("open", close), high=bar.get("high", close), low=bar.get("low", close),
                              close=close, volume=bar.get("volume", 1000), source="t", fetched_at=datetime.now(UTC)))
        s.commit()


def preset(key):
    return next(p for p in watch_presets.resolved(OWNER_HASH) if p["preset_key"] == key)


# ---- the catalog and the contract --------------------------------------------------------------------------------------------

def test_the_catalog_is_the_plans_table():
    got = {k: (v["scope"], v["metric"], v["direction"], v["levels"], v["thresholds"]) for k, v in watch_presets.CATALOG.items()}
    assert got == {
        "concentration": ("holdings", "position_weight", "above", level((25, "remind")), True),
        "portfolio_drawdown": ("portfolio", "portfolio_day_change", "down", level((3, "remind"), (5, "urgent")), True),
        "down_streak": ("watched", "down_days", "down", level((5, "remind")), True),
        "new_high_52w": ("watched", "high_52w", "above", level((0, "remind")), False),
        "new_low_52w": ("watched", "low_52w", "below", level((0, "remind")), False),
        "volume_surge": ("holdings", "volume_ratio", "above", level((3, "remind")), True),
    }
    assert [k for k, v in watch_presets.FIXED.items() if v["hard"]] == ["stop_price", "filings"]


def test_the_snapshot_sections_equal_the_contract_fixture(owner, monkeypatch, tmp_path):
    monkeypatch.setattr(sentinel_bridge, "snapshot_path", lambda: tmp_path / "none.json")
    for name, value in (("_research_queue", []), ("_telegram", {}), ("_pushover", {}), ("_portfolio", {"positions": [], "plans": [], "total_assets": None})):
        monkeypatch.setattr(sentinel_bridge, name, lambda o, value=value: value)
    snap = sentinel_bridge.build_snapshot(OWNER_HASH)
    assert {"alert_settings": snap["alert_settings"], "presets": snap["presets"]} == CONTRACT
    assert "alert_sensitivity" not in snap and "short_moves" not in snap          # replaced by alert_settings
    for entry in snap["presets"]:
        assert entry["id"] == f"preset:{entry['preset_key']}" and entry["source"] == "preset" and entry["symbol"] == "*"
        assert entry["scope"] in ("holdings", "watched", "portfolio") and entry["text"] and entry["created_on"] is None


def test_the_snapshot_holds_only_enabled_presets_with_his_levels(owner):
    watch_presets.set_override(OWNER_HASH, "concentration", levels=level((40, "remind")))
    watch_presets.set_override(OWNER_HASH, "new_high_52w", enabled=False)
    got = {p["preset_key"]: p for p in watch_presets.snapshot_presets(OWNER_HASH)}
    assert "new_high_52w" not in got and len(got) == 5
    assert got["concentration"]["levels"] == level((40, "remind")) and "40%" in got["concentration"]["text"] and "25" not in got["concentration"]["text"]
    assert watch_presets.snapshot_presets("someone-else")[0]["levels"] == level((25, "remind"))      # his overrides are his


def test_a_snapshot_that_cannot_read_the_defaults_keeps_the_old_ones(owner, monkeypatch, tmp_path):
    path = tmp_path / "snap.json"
    monkeypatch.setattr(sentinel_bridge, "snapshot_path", lambda: path)
    path.write_text(json.dumps({"presets": CONTRACT["presets"][:2], "alert_settings": {"sensitivity": "quiet", "short_moves": True}}))
    monkeypatch.setattr(watch_presets, "snapshot_presets", lambda o: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(watch_presets, "get_settings", lambda o: (_ for _ in ()).throw(RuntimeError("db down")))
    assert sentinel_bridge._presets(OWNER_HASH) == CONTRACT["presets"][:2]
    assert sentinel_bridge._alert_settings(OWNER_HASH) == {"sensitivity": "quiet", "short_moves": True}
    path.unlink()
    assert sentinel_bridge._presets(OWNER_HASH) == [] and sentinel_bridge._alert_settings(OWNER_HASH) == {}


# ---- overrides and reset ------------------------------------------------------------------------------------------------------

def test_set_override_changes_only_what_is_given_and_reset_restores_the_default(owner):
    row = watch_presets.set_override(OWNER_HASH, "portfolio_drawdown", levels=level((4, "remind"), (8, "urgent")))
    assert row["levels"] == level((4, "remind"), (8, "urgent")) and row["enabled"] and row["changed"] and "达到 4%" in row["text"]
    off = watch_presets.set_override(OWNER_HASH, "portfolio_drawdown", enabled=False)
    assert not off["enabled"] and off["levels"] == level((4, "remind"), (8, "urgent"))          # the levels stay
    back = watch_presets.reset(OWNER_HASH, "portfolio_drawdown")
    assert back["enabled"] and back["levels"] == level((3, "remind"), (5, "urgent")) and not back["changed"]
    with SessionLocal() as db:
        assert db.query(WatchPresetOverride).count() == 0          # no row means the default


def test_setting_a_preset_back_to_its_defaults_drops_the_row(owner):
    watch_presets.set_override(OWNER_HASH, "concentration", enabled=False)
    watch_presets.set_override(OWNER_HASH, "concentration", enabled=True)
    with SessionLocal() as db:
        assert db.query(WatchPresetOverride).count() == 0
    watch_presets.set_override(OWNER_HASH, "concentration", levels=level((40, "remind")))
    assert watch_presets.set_override(OWNER_HASH, "concentration", levels=level((25, "remind")))["changed"] is False


def test_a_preset_change_is_validated_as_a_rule_is(owner):
    def refused(code, key="concentration", **kw):
        with pytest.raises(WatchRuleError) as caught:
            watch_presets.set_override(OWNER_HASH, key, **kw)
        assert caught.value.code == code and caught.value.reason
    refused("invalid_threshold", levels=level((0, "remind")))
    refused("invalid_threshold", levels=level((101, "remind")))
    refused("invalid_levels", levels=level((30, "remind"), (40, "remind")))
    refused("invalid_levels", levels=[{"threshold": 30}])
    refused("invalid_threshold", key="down_streak", levels=level((1, "remind")))
    refused("invalid_threshold", key="down_streak", levels=level((2.5, "remind")))
    refused("invalid_threshold", key="portfolio_drawdown", levels=level((100, "remind")))
    refused("not_editable", key="new_high_52w", levels=level((1, "urgent")))          # no number to change: only on or off
    refused("nothing_to_change")
    refused("unknown_preset", key="nope", enabled=False)
    with SessionLocal() as db:
        assert db.query(WatchPresetOverride).count() == 0
    assert watch_presets.set_override(OWNER_HASH, "down_streak", levels=level((3, "remind"), (6, "urgent")))["levels"] == level((3, "remind"), (6, "urgent"))


def test_the_stop_price_and_filings_can_never_be_turned_off(owner):
    for key in ("stop_price", "filings"):
        for call in (lambda k: watch_presets.set_override(OWNER_HASH, k, enabled=False), lambda k: watch_presets.set_override(OWNER_HASH, k, enabled=True),
                     lambda k: watch_presets.reset(OWNER_HASH, k), lambda k: watch_presets.merged(OWNER_HASH, k, False)):
            with pytest.raises(WatchRuleError) as caught:
                call(key)
            assert caught.value.code == "hard_guarantee" and caught.value.reason == HARD
    for key in ("day_tiers", "short_moves", "plan_prices"):          # listed, edited elsewhere: each says where
        with pytest.raises(WatchRuleError) as caught:
            watch_presets.set_override(OWNER_HASH, key, enabled=False)
        assert caught.value.code == "not_editable" and caught.value.reason != HARD
    with SessionLocal() as db:
        assert db.query(WatchPresetOverride).count() == 0
    assert not any(p["preset_key"] in ("stop_price", "filings") for p in watch_presets.resolved(OWNER_HASH))      # they are not presets the sentinel is told about


# ---- the settings -------------------------------------------------------------------------------------------------------------

def test_the_settings_default_to_standard_and_off_and_the_box_environment_is_the_default_until_he_chooses(owner, monkeypatch):
    assert watch_presets.get_settings(OWNER_HASH) == {"sensitivity": "standard", "short_moves": False}
    monkeypatch.setenv("SENTINEL_SENSITIVITY", "quiet")
    monkeypatch.setenv("SENTINEL_SHORT_MOVES", "on")
    assert watch_presets.get_settings(OWNER_HASH) == {"sensitivity": "quiet", "short_moves": True}
    done = watch_presets.set_settings(OWNER_HASH, sensitivity="sensitive")
    assert done == {"sensitivity": "sensitive", "short_moves": True, "thresholds": TIERS}
    assert watch_presets.set_settings(OWNER_HASH, short_moves=False)["short_moves"] is False and watch_presets.get_settings(OWNER_HASH)["sensitivity"] == "sensitive"
    with SessionLocal() as db:
        assert db.query(AlertSetting).count() == 1
    for bad in ({"sensitivity": "loud"}, {"short_moves": "yes"}, {}):
        with pytest.raises(WatchRuleError):
            watch_presets.set_settings(OWNER_HASH, **bad)


# ---- the new metrics: validation and reading ---------------------------------------------------------------------------------

def fields(**over):
    return {**{"symbol": "INTC", "metric": "down_days", "direction": "down", "levels": level((5, "remind"))}, **over}


def test_the_owner_can_use_the_three_per_symbol_metrics_but_not_the_portfolio_one(owner):
    assert validate(fields(), owner=OWNER_HASH, today=TODAY)["levels"] == level((5, "remind"))
    assert validate(fields(direction=None, levels=level((3, "remind"), (6, "urgent"))), owner=OWNER_HASH, today=TODAY)["direction"] == "down"
    high = validate(fields(metric="high_52w", direction=None, levels=level((1, "remind"))), owner=OWNER_HASH, today=TODAY)
    assert high["direction"] == "above" and high["levels"] == level((0, "remind"))          # the number is ignored: stored as 0
    low = validate(fields(metric="low_52w", direction="below", levels=[{"level": "urgent"}]), owner=OWNER_HASH, today=TODAY)
    assert low["levels"] == level((0, "urgent"))
    for bad, code in ((fields(levels=level((1, "remind"))), "invalid_threshold"), (fields(levels=level((2.5, "remind"))), "invalid_threshold"),
                      (fields(levels=level((31, "remind"))), "invalid_threshold"), (fields(direction="up"), "invalid_direction"),
                      (fields(metric="high_52w", direction="below"), "invalid_direction"), (fields(metric="low_52w", direction="above"), "invalid_direction"),
                      (fields(metric="high_52w", direction="above", levels=level((1, "remind"), (2, "urgent"))), "invalid_levels"),
                      (fields(metric="high_52w", direction="above", levels=[{"threshold": 1, "level": "loud"}]), "invalid_levels"),
                      (fields(metric="portfolio_day_change", symbol="*", direction="down", levels=level((3, "remind"))), "preset_only_metric"),
                      (fields(metric="portfolio_day_change", direction="down", levels=level((3, "remind"))), "preset_only_metric")):
        with pytest.raises(WatchRuleError) as caught:
            validate(bad, owner=OWNER_HASH, today=TODAY)
        assert caught.value.code == code and caught.value.reason
    with pytest.raises(WatchRuleError):          # a preset may use the portfolio metric and the symbol *; an owner rule may not use *
        validate(fields(symbol="*"), owner=OWNER_HASH, today=TODAY)
    assert validate(fields(metric="portfolio_day_change", symbol="*", direction="down", levels=level((3, "remind"))), preset=True)["symbol"] == "*"


def test_the_new_metrics_read_the_same_for_an_owner_rule_and_a_default():
    base = {"symbol": "INTC", "window_days": None, "repeat": "daily", "expires_on": None}
    assert describe({**base, "metric": "down_days", "direction": "down", "levels": level((4, "remind"), (6, "urgent"))}) == (
        "英特尔连续下跌（每个交易日收盘低于前一日，今天股价低于昨收也算一天）达到 4 个交易日：提醒；达到 6 个交易日：加急。"
        "条件成立时每档各提醒一次；提醒档连续下跌中断后再连跌到 4 个交易日、加急档连续下跌中断后再连跌到 6 个交易日，会再提醒该档；每天每档最多一次。")
    assert describe({**base, "metric": "high_52w", "direction": "above", "levels": level((0, "urgent"))}) == (
        "英特尔的股价创 52 周新高（不低于过去 252 个交易日里最高的收盘价）：加急。条件成立时提醒一次，股价回到前高以下后再创新高会再提醒；每天最多一次。")
    assert describe({**base, "metric": "low_52w", "direction": "below", "levels": level((0, "remind"))}).startswith("英特尔的股价创 52 周新低（不高于过去 252 个交易日里最低的收盘价）：提醒。")
    assert describe({**base, "symbol": "*", "metric": "portfolio_day_change", "direction": "down", "levels": level((3, "remind"))}, subject="你的组合") == (
        "你的组合今天的涨跌（所有持仓现有股数 × 相对昨收的价差，合计占昨收时总资产的比例）下跌达到 3%：提醒。每天最多一次。")
    for entry in CONTRACT["presets"]:
        subject = {"holdings": "每只持仓", "watched": "持仓和研究队列里的每只股票", "portfolio": "你的组合"}[entry["scope"]]
        assert describe(entry, subject=subject) == entry["text"]


# ---- the new metrics: dry runs -------------------------------------------------------------------------------------------------

def test_dry_run_down_days_counts_the_streak_on_closes(owner):
    daily("INTC", [{"close": 100}] * 40 + [{"close": c} for c in (99, 98, 97, 96, 95, 94)])          # six down days, the last six
    got = dry_run(OWNER_HASH, {"symbol": "INTC", "metric": "down_days", "direction": "down", "levels": level((5, "remind"), (6, "urgent")), "repeat": "daily"}, today=TODAY)
    assert got["hits"] == [{"date": "2026-11-25", "level": "remind"}, {"date": "2026-11-26", "level": "urgent"}] and got["note"] is None
    assert "按每天的收盘价估算" in dry_run_line(got)
    daily("NVDA", [{"close": 100 + (i % 2)} for i in range(50)])          # never two down days in a row
    quiet = dry_run(OWNER_HASH, {"symbol": "NVDA", "metric": "down_days", "direction": "down", "levels": level((2, "remind")), "repeat": "daily"}, today=TODAY)
    assert quiet["hits"] == [] and quiet["covered_days"] == 30


def test_dry_run_52_week_needs_a_year_of_bars_and_fires_on_the_day_it_becomes_true(owner):
    quiet = {"close": 100, "high": 99, "low": 101}          # bars that are neither at a high nor at a low
    rows = [dict(quiet) for _ in range(330)]
    rows[-11], rows[-4] = {**quiet, "high": 101}, {**quiet, "high": 102}          # new highs on day -10 and -3 (a quiet day between)
    rows[-8] = {**quiet, "low": 99}
    daily("INTC", rows)
    high = dry_run(OWNER_HASH, {"symbol": "INTC", "metric": "high_52w", "direction": "above", "levels": level((0, "remind")), "repeat": "daily"}, today=TODAY)
    assert high["hits"] == [{"date": "2026-11-16", "level": "remind"}, {"date": "2026-11-23", "level": "remind"}] and high["note"] is None
    low = dry_run(OWNER_HASH, {"symbol": "INTC", "metric": "low_52w", "direction": "below", "levels": level((0, "urgent")), "repeat": "daily"}, today=TODAY)
    assert low["hits"] == [{"date": "2026-11-19", "level": "urgent"}]
    daily("NVDA", [dict(quiet) for _ in range(120)])
    short = dry_run(OWNER_HASH, {"symbol": "NVDA", "metric": "high_52w", "direction": "above", "levels": level((0, "remind")), "repeat": "daily"}, today=TODAY)
    assert short["hits"] == [] and short["note"] == "历史行情不够一年，试跑不了" and dry_run_line(short) == "试跑：历史行情不够一年，试跑不了。"


def test_dry_run_portfolio_day_change_uses_todays_shares_and_total_assets(owner, monkeypatch):
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {"INTC": {"shares": 100.0, "avg_cost": 50.0, "total_assets": 20000.0},
                                                             "NVDA": {"shares": 10.0, "avg_cost": 100.0, "total_assets": 20000.0}})
    daily("INTC", [{"close": 100}] * 49 + [{"close": 90}])          # INTC falls 10 on the last day: 100 shares x -10 = -1000
    daily("NVDA", [{"close": 200}] * 50)
    rule = {"symbol": "*", "metric": "portfolio_day_change", "direction": "down", "levels": level((3, "remind"), (5, "urgent")), "repeat": "daily"}
    got = dry_run(OWNER_HASH, rule, today=TODAY)
    # -1000 over (20000 + 1000 = 21000, the total assets at the previous close) = -4.76%: the 3% level, not the 5%
    assert got["hits"] == [{"date": "2026-11-26", "level": "remind"}] and got["covered_days"] == 30 and got["metric"] == "portfolio_day_change"
    assert "按每天的收盘价估算" in dry_run_line(got)
    daily("AMD", [{"close": 50}] * 5)
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {"AMD": {"shares": 1.0, "avg_cost": 1.0, "total_assets": 100.0}})
    assert dry_run(OWNER_HASH, rule, today=TODAY)["note"] == watch_rules.NO_HISTORY
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {})
    assert dry_run(OWNER_HASH, rule, today=TODAY)["note"] == "你现在没有持仓，试跑不了"


def test_a_preset_dry_run_runs_each_symbol_and_names_it(owner, monkeypatch):
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {"INTC": {"shares": 100.0, "avg_cost": 50.0, "total_assets": 10000.0},
                                                             "NVDA": {"shares": 1.0, "avg_cost": 1.0, "total_assets": 10000.0}})
    daily("INTC", [{"close": 100, "volume": 1000}] * 38 + [{"close": 100, "volume": 5000}, {"close": 100, "volume": 1000}])
    daily("NVDA", [{"close": 100, "volume": 1000}] * 40)
    got = watch_presets.dry_run(OWNER_HASH, preset("volume_surge"), today=TODAY)
    assert got["hits"] == [{"date": "2026-11-25", "level": "remind", "symbol": "INTC"}] and got["symbols"] == 2
    assert watch_presets.dry_run_line(got).startswith("按这条规则，过去 30 天会提醒你 1 次：INTC 11-25。")
    none = watch_presets.dry_run(OWNER_HASH, preset("concentration"), today=TODAY)          # position weight on flat prices: 100% on neither day -> it was above 25 from the first day
    assert none["note"] is None and {h["symbol"] for h in none["hits"]} <= {"INTC", "NVDA"}
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {})
    assert watch_presets.dry_run_line(watch_presets.dry_run(OWNER_HASH, preset("concentration"), today=TODAY)) == "试跑：你现在没有持仓，试跑不了。"


# ---- the view (GET /agent-chat/watch) ----------------------------------------------------------------------------------------

def test_the_view_has_the_rules_the_defaults_and_the_settings(owner, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "none.db"))
    mine = watch_rules.create(OWNER_HASH, {"symbol": "INTC", "metric": "position_weight", "direction": "above", "levels": level((40, "remind"))}, "q", today=TODAY)
    view = watch_rules_view.watch_view(OWNER_HASH)
    assert set(view) == {"rules", "presets", "settings"}
    assert view["rules"] == [{"id": mine["id"], "symbol": "INTC", "metric": "position_weight", "direction": "above", "levels": level((40, "remind")),
                              "text": mine["text"], "status": "active", "last_fired": None,
                              "overrides_default": "系统默认的「单只占比过高」在 INTC 上让位给这条", "created_on": "2026-11-26", "expires_on": None}]
    by_key = {p["key"]: p for p in view["presets"]}
    assert list(by_key) == ["concentration", "portfolio_drawdown", "down_streak", "new_high_52w", "new_low_52w", "volume_surge",
                            "day_tiers", "short_moves", "plan_prices", "stop_price", "filings"]
    assert by_key["concentration"]["yields_on"] == ["INTC"] and by_key["volume_surge"]["yields_on"] == []
    assert set(by_key["concentration"]) == {"key", "title", "text", "enabled", "levels", "editable", "hard_guarantee", "applies_to", "yields_on", "changed", "threshold_editable", "unit"}
    for key in ("day_tiers", "short_moves", "plan_prices", "stop_price", "filings"):
        assert by_key[key]["levels"] is None and by_key[key]["editable"] is False
    assert [k for k, p in by_key.items() if p["hard_guarantee"]] == ["stop_price", "filings"] and all(by_key[k]["editable"] for k in list(by_key)[:6])
    assert view["settings"] == {"sensitivity": "standard", "short_moves": False, "thresholds": TIERS}
    assert [by_key[k]["unit"] for k in ("concentration", "portfolio_drawdown", "down_streak", "new_high_52w", "volume_surge", "stop_price", "day_tiers")] == ["%", "%", "天", None, "倍", None, None]
    assert [by_key[k]["applies_to"] for k in ("concentration", "down_streak", "portfolio_drawdown")] == ["所有持仓", "持仓和研究队列", "整个组合"]
    watch_presets.set_settings(OWNER_HASH, short_moves=True)
    assert {p["key"]: p for p in watch_rules_view.watch_view(OWNER_HASH)["presets"]}["short_moves"]["enabled"] is True


def test_an_expired_rule_does_not_make_a_default_yield(owner, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "none.db"))
    made = watch_rules.create(OWNER_HASH, {"symbol": "INTC", "metric": "volume_ratio", "levels": level((5, "remind"))}, "q", today=TODAY)
    with SessionLocal() as db:
        import uuid
        db.get(WatchRule, uuid.UUID(made["id"])).expires_on = date(2020, 1, 1)
        db.commit()
    view = watch_rules_view.watch_view(OWNER_HASH)
    assert view["rules"][0]["status"] == "expired" and view["rules"][0]["overrides_default"] is None
    assert {p["key"]: p for p in view["presets"]}["volume_surge"]["yields_on"] == []


def test_the_list_tool_and_the_memory_page_read_the_same_view(owner, monkeypatch, tmp_path):
    from app import memory_overview
    from app.database import Base, engine
    Base.metadata.create_all(engine)
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "none.db"))
    watch_presets.set_override(OWNER_HASH, "volume_surge", enabled=False)
    rows = watch_rules_view.rows(OWNER_HASH)
    surge = next(r for r in rows if r.get("key") == "volume_surge")
    assert surge["kind"] == "系统默认" and surge["enabled"] is False and surge["text"].endswith("（现在关着）") and not surge["hard_guarantee"]
    assert next(r for r in rows if r.get("key") == "stop_price")["hard_guarantee"] is True
    watch = memory_overview.collect(OWNER_HASH)["watch"]
    assert {p["id"]: p["enabled"] for p in watch["presets"]}["volume_surge"] is False and watch["settings"]["sensitivity"] == "standard"
    lines = memory_overview._watch_lines(watch)
    assert "### 系统默认规则" in lines and any(l.startswith("- 成交量异常放大：") and l.endswith("（已关）") for l in lines)
    assert "现在还不能按你单独调整" not in watch["default_rules_note"]


# ---- the cards ------------------------------------------------------------------------------------------------------------------

def test_the_card_of_a_threshold_change_shows_the_old_and_new_reading_and_a_dry_run(owner):
    out = prepare({"key": "concentration", "levels": level((40, "remind"))}, "set_watch_preset")
    assert isinstance(out, act.Prepared) and out.tier == 2 and watch_presets.snapshot_presets(OWNER_HASH)[0]["levels"] == level((25, "remind"))      # a card writes nothing
    assert out.display["title"] == "改系统默认规则 · 单只占比过高"
    assert out.display["targets"] == [{"title": "每只持仓占你总资产的比例高于 40%：提醒。条件成立时提醒一次，回到 40%以下后再升破会再提醒；每天最多一次。"}]
    assert out.display["alternative"] == (
        "原来：每只持仓占你总资产的比例高于 25%：提醒。条件成立时提醒一次，回到 25%以下后再升破会再提醒；每天最多一次。\n"
        "改后：每只持仓占你总资产的比例高于 40%：提醒。条件成立时提醒一次，回到 40%以下后再升破会再提醒；每天最多一次。\n"
        "试跑：没有足够的历史行情，试跑不了。\n"
        "夜里（北京时间 0–8 点）「提醒」会攒进早上的汇总，「加急」照常马上发。\n点确认后生效；哨兵每分钟检查，不用模型。")
    assert out.operation["fields"] == {"key": "concentration", "enabled": True, "levels": level((40, "remind"))}
    assert press(out)["ok"] and preset("concentration")["levels"] == level((40, "remind"))


def test_the_card_of_a_dry_run_that_has_history_says_when_it_would_have_fired(owner, monkeypatch):
    monkeypatch.setattr(watch_rules, "_holdings", lambda o: {"INTC": {"shares": 100.0, "avg_cost": 50.0, "total_assets": 10000.0}})
    daily("INTC", [{"close": 100, "volume": 1000}] * 38 + [{"close": 100, "volume": 9000}, {"close": 100, "volume": 1000}])
    out = prepare({"key": "volume_surge", "levels": level((2, "remind"), (6, "urgent"))}, "set_watch_preset")
    assert "按这条规则，过去 30 天会提醒你 2 次：INTC 11-25（加急）、INTC 11-25。" not in out.display["alternative"]      # ordered: remind first
    assert "过去 30 天会提醒你 2 次：INTC 11-25、INTC 11-25（加急）。" in out.display["alternative"]


def test_the_card_of_switching_off_and_of_resetting(owner):
    off = prepare({"key": "new_high_52w", "enabled": False}, "set_watch_preset")
    assert off.display["title"] == "改系统默认规则 · 52 周新高" and off.display["targets"] == [{"title": "52 周新高：关掉"}]
    assert "改后：关掉。这条默认规则不再提醒你" in off.display["alternative"] and "试跑" not in off.display["alternative"]
    assert press(off)["ok"] and not preset("new_high_52w")["enabled"]
    again = prepare({"key": "new_high_52w", "enabled": False}, "set_watch_preset")
    assert again["error_code"] == "nothing_to_change"
    back = prepare({"key": "new_high_52w", "reset": True}, "set_watch_preset")
    assert "原来：" in back.display["alternative"] and "（现在是关着的）" in back.display["alternative"] and "改后：持仓和研究队列里的每只股票的股价创 52 周新高" in back.display["alternative"]
    assert press(back)["ok"] and preset("new_high_52w")["enabled"]
    assert prepare({"key": "new_high_52w", "reset": True}, "set_watch_preset")["error_code"] == "nothing_to_change"
    assert prepare({"key": "concentration", "reset": True, "enabled": False}, "set_watch_preset")["error_code"] == "invalid_reset"


def test_the_card_refuses_the_hard_guarantees_and_the_fixed_ones_with_a_reason(owner):
    for key in ("stop_price", "filings"):
        for extra in ({"enabled": False}, {"enabled": True}, {"reset": True}):
            out = prepare({"key": key, **extra}, "set_watch_preset")
            assert out["ok"] is False and out["error_code"] == "hard_guarantee" and out["reason"] == HARD == out["hint"]
    assert prepare({"key": "day_tiers", "enabled": False}, "set_watch_preset")["error_code"] == "not_editable"
    assert prepare({"key": "nope", "enabled": False}, "set_watch_preset")["error_code"] == "unknown_preset"
    assert prepare({"key": "new_low_52w", "levels": level((3, "remind"))}, "set_watch_preset")["error_code"] == "not_editable"
    assert prepare({"key": "concentration"}, "set_watch_preset")["error_code"] == "nothing_to_change"
    assert prepare({"key": "concentration", "levels": level((0, "remind"))}, "set_watch_preset")["error_code"] == "invalid_arguments"          # the schema: above 0
    assert prepare({"key": "concentration", "levels": level((101, "remind"))}, "set_watch_preset")["error_code"] == "invalid_threshold"


def test_a_press_on_a_preset_card_whose_state_changed_since_is_refused(owner):
    out = prepare({"key": "concentration", "levels": level((40, "remind"))}, "set_watch_preset")
    watch_presets.set_override(OWNER_HASH, "concentration", levels=level((30, "remind")))
    done = press(out)
    assert not done["ok"] and done["data"][0]["error_code"] == "card_stale" and preset("concentration")["levels"] == level((30, "remind"))


def test_the_card_of_the_sensitivity_says_the_numbers_in_words(owner):
    out = prepare({"sensitivity": "quiet"}, "set_alert_settings")
    assert out.tier == 2 and out.display["title"] == "改提醒的灵敏度和开关" and out.display["targets"] == [{"title": "灵敏度：安静"}]
    assert out.display["alternative"] == (
        "灵敏度：标准 → 安静。涨跌按每只股票自己平时一天的波动幅度（σ）分档：原来标准（约 2σ 提醒、4σ 重大），改后安静（约 2.5σ 提醒、5σ 重大）；"
        "要更大的波动才会提醒，提醒会少一些。你自己定的规则、止损价和公告不受这个影响。\n点确认后生效；哨兵下一轮检查就按新的来。")
    assert watch_presets.get_settings(OWNER_HASH)["sensitivity"] == "standard"          # a card writes nothing
    assert press(out)["ok"] and watch_presets.get_settings(OWNER_HASH) == {"sensitivity": "quiet", "short_moves": False}
    more = prepare({"sensitivity": "sensitive", "short_moves": True}, "set_alert_settings")
    assert "改后灵敏（约 1.5σ 提醒、3σ 重大）；稍小的波动就会提醒，提醒会多一些。" in more.display["alternative"]
    assert "5 分钟急动提醒：关 → 开。开了以后" in more.display["alternative"] and more.display["targets"] == [{"title": "灵敏度：灵敏；5 分钟急动：开"}]
    assert prepare({"sensitivity": "quiet"}, "set_alert_settings")["error_code"] == "nothing_to_change"
    assert prepare({}, "set_alert_settings")["error_code"] == "nothing_to_change"
    assert prepare({"sensitivity": "loud"}, "set_alert_settings")["error_code"] == "invalid_arguments"


def test_the_operations_need_the_owner_and_a_card(owner):
    run_ = make_run()
    result = run(act.handle(run_, {"operation": "set_watch_preset", "arguments": {"key": "concentration", "enabled": False}}))
    assert result["data"][0]["status"] == "awaiting_confirmation" and len(run_.proposals) == 1 and preset("concentration")["enabled"]
    lookup = run(act.handle(make_run(), {"operation": "set_watch_preset"}))["data"][0]
    assert lookup["tier"] == 2 and [p["key"] for p in lookup["presets"]][:2] == ["concentration", "portfolio_drawdown"] and lookup["hard_guarantees"] == ["stop_price", "filings"]
    assert run(act.handle(make_run(), {"operation": "set_alert_settings"}))["data"][0]["settings"]["sensitivity"] == "standard"
    guest = make_run()
    guest.context.identity_credential = "x" * 64
    assert run(act.handle(guest, {"operation": "set_watch_preset", "arguments": {"key": "concentration", "enabled": False}}))["error_code"] == "owner_login_required"


# ---- the routes ------------------------------------------------------------------------------------------------------------------

def test_the_routes_are_owner_only_and_refuse_what_cannot_change(owner, client, monkeypatch):
    mine, guest = {"X-Chat-Session": OWNER}, {"X-Chat-Session": "g" * 64}
    for call in (lambda h: client.get("/agent-chat/watch", headers=h), lambda h: client.patch("/agent-chat/watch-presets/concentration", json={"enabled": False}, headers=h),
                 lambda h: client.post("/agent-chat/watch-presets/concentration/reset", headers=h), lambda h: client.put("/agent-chat/alert-settings", json={"sensitivity": "quiet"}, headers=h)):
        assert call(guest).status_code == 403
    view = client.get("/agent-chat/watch", headers=mine).json()
    assert set(view) == {"rules", "presets", "settings"} and len(view["presets"]) == 11 and view["settings"]["sensitivity"] == "standard"
    changed = client.patch("/agent-chat/watch-presets/concentration", json={"levels": [{"threshold": 40, "level": "remind"}]}, headers=mine)
    assert changed.status_code == 200 and changed.json()["key"] == "concentration" and changed.json()["levels"] == level((40, "remind")) and changed.json()["changed"] is True
    off = client.patch("/agent-chat/watch-presets/concentration", json={"enabled": False}, headers=mine).json()
    assert off["enabled"] is False and off["levels"] == level((40, "remind"))
    back = client.post("/agent-chat/watch-presets/concentration/reset", headers=mine)
    assert back.status_code == 200 and back.json()["enabled"] and back.json()["levels"] == level((25, "remind")) and back.json()["changed"] is False
    for key in ("stop_price", "filings"):
        for call in (lambda: client.patch(f"/agent-chat/watch-presets/{key}", json={"enabled": False}, headers=mine), lambda: client.post(f"/agent-chat/watch-presets/{key}/reset", headers=mine)):
            refused = call()
            assert refused.status_code == 400 and refused.json()["detail"] == {"error_code": "hard_guarantee", "reason": HARD}
    assert client.patch("/agent-chat/watch-presets/nope", json={"enabled": False}, headers=mine).status_code == 400
    assert client.patch("/agent-chat/watch-presets/day_tiers", json={"enabled": False}, headers=mine).status_code == 400
    assert client.patch("/agent-chat/watch-presets/concentration", json={}, headers=mine).status_code == 400
    assert client.patch("/agent-chat/watch-presets/new_high_52w", json={"levels": [{"threshold": 1, "level": "remind"}]}, headers=mine).status_code == 400
    bad = client.patch("/agent-chat/watch-presets/concentration", json={"levels": [{"threshold": 500, "level": "remind"}]}, headers=mine)
    assert bad.status_code == 422 and bad.json()["detail"]["error_code"] == "invalid_threshold" and bad.json()["detail"]["reason"]
    saved = client.put("/agent-chat/alert-settings", json={"sensitivity": "sensitive", "short_moves": True}, headers=mine)
    assert saved.status_code == 200 and saved.json()["sensitivity"] == "sensitive" and saved.json()["short_moves"] is True and "thresholds" in saved.json()
    assert client.put("/agent-chat/alert-settings", json={"sensitivity": "loud"}, headers=mine).status_code == 422
    assert client.put("/agent-chat/alert-settings", json={}, headers=mine).status_code == 400
    assert client.put("/agent-chat/alert-settings", json={"short_moves": "maybe"}, headers=mine).status_code == 422
    with SessionLocal() as db:
        assert db.query(WatchPresetOverride).count() == 0 and db.query(AlertSetting).count() == 1


def test_a_route_change_refreshes_the_sentinel_snapshot(owner, client, monkeypatch):
    seen = []
    monkeypatch.setattr(sentinel_bridge, "refresh_sentinel_snapshot", lambda: seen.append(1))
    mine = {"X-Chat-Session": OWNER}
    client.patch("/agent-chat/watch-presets/concentration", json={"enabled": False}, headers=mine)
    client.put("/agent-chat/alert-settings", json={"sensitivity": "quiet"}, headers=mine)
    client.post("/agent-chat/watch-presets/concentration/reset", headers=mine)
    assert len(seen) == 3


def test_the_get_shape_with_a_rule(owner, client, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "none.db"))
    mine = {"X-Chat-Session": OWNER}
    client.post("/agent-chat/watch-rules", json={"symbol": "INTC", "metric": "day_change", "levels": [{"threshold": 8, "level": "remind"}]}, headers=mine)
    rule = client.get("/agent-chat/watch", headers=mine).json()["rules"][0]
    assert set(rule) == {"id", "symbol", "metric", "direction", "levels", "text", "status", "last_fired", "overrides_default", "created_on", "expires_on"}
    assert rule["status"] == "active" and rule["overrides_default"] == "默认的涨跌分级对它不生效" and rule["last_fired"] is None


# ---- the registry, the catalogue ----------------------------------------------------------------------------------------------------

def test_the_registry_maps_the_new_routes_to_the_operations():
    assert OPERATION_REGISTRY[("PATCH", "/agent-chat/watch-presets/{key}")] == {"operation": "set_watch_preset"}
    assert OPERATION_REGISTRY[("POST", "/agent-chat/watch-presets/{key}/reset")] == {"operation": "set_watch_preset"}
    assert OPERATION_REGISTRY[("PUT", "/agent-chat/alert-settings")] == {"operation": "set_alert_settings"}


def test_the_new_operations_are_kernel_only_owner_only_tier_two_and_kept_by_a_scoped_bot():
    for name in ("set_watch_preset", "set_alert_settings"):
        assert name in KERNEL_ONLY and name in OWNER_ONLY and name not in legacy_definitions() and name in bots.ALWAYS_ON and act.tier_of(name) == 2
        assert not any(s["function"]["name"] == name for s in schemas(owner=True))
        assert name in act.ACT_SCHEMA["function"]["description"] and act.SUMMARIES[name]
    assert "不能关" in act.SUMMARIES["set_watch_preset"] and "止损价" in act.SUMMARIES["set_watch_preset"] and "硬保证" in act.SUMMARIES["set_watch_preset"]
    assert "down_days" in act.SUMMARIES["set_watch_rule"] and "high_52w" in act.SUMMARIES["set_watch_rule"] and "portfolio_day_change" not in act.SUMMARIES["set_watch_rule"]


def test_the_status_codes_are_active_expired_finished(owner, monkeypatch, tmp_path):
    import sqlite3
    import uuid
    from sentinel import rules as sr
    path = tmp_path / "sentinel.db"
    monkeypatch.setenv("SENTINEL_DB_PATH", str(path))
    once = watch_rules.create(OWNER_HASH, {"symbol": "AMD", "metric": "day_change", "levels": level((8, "remind")), "repeat": "once"}, "q", today=TODAY)
    old = watch_rules.create(OWNER_HASH, {"symbol": "MSFT", "metric": "day_change", "levels": level((8, "remind"))}, "q", today=TODAY)
    new = watch_rules.create(OWNER_HASH, {"symbol": "NVDA", "metric": "day_change", "levels": level((8, "remind"))}, "q", today=TODAY)
    with SessionLocal() as db:
        db.get(WatchRule, uuid.UUID(old["id"])).expires_on = date(2020, 1, 1)
        db.commit()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE rule_state(rule_id TEXT, ny_date TEXT, level TEXT, fired_at REAL)")
    conn.execute("INSERT INTO rule_state VALUES (?, '*', ?, 1763640000)", (once["id"], sr.level_key(once, sr.severity_order(once)[-1])))
    conn.commit()
    conn.close()
    status = {r["symbol"]: r["status"] for r in watch_rules_view.watch_view(OWNER_HASH)["rules"]}
    assert status == {"AMD": "finished", "MSFT": "expired", "NVDA": "active"} and new
