"""Stage 5b-1 half A: the owner's watch rules — validation, the plain-language reading, the 30-day dry run, storage and the snapshot the
sentinel reads.  Disposable Postgres; no network, no model."""
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app import sentinel_bridge, watch_rules
from app.agent_chat_models import WatchRule
from app.database import Base, SessionLocal, engine
from app.models import MarketPrice
from app.watch_rules import WatchRuleError, describe, dry_run, dry_run_line, validate

OWNER = "owner-hash"
TODAY = date(2026, 11, 26)
CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "watch_rules_contract.json").read_text())
HOLD = {"INTC": {"shares": 100.0, "avg_cost": 50.0, "total_assets": 10000.0}}


@pytest.fixture
def db(monkeypatch):
    Base.metadata.create_all(engine, tables=[WatchRule.__table__, MarketPrice.__table__])
    with SessionLocal() as s:
        s.query(WatchRule).delete()
        s.query(MarketPrice).delete()
        s.commit()
    monkeypatch.setattr(watch_rules, "_holdings", lambda owner: HOLD)
    monkeypatch.setattr(sentinel_bridge, "refresh_sentinel_snapshot", lambda: None)
    yield
    with SessionLocal() as s:
        s.query(WatchRule).delete()
        s.query(MarketPrice).delete()
        s.commit()


def level(*pairs):
    return [{"threshold": t, "level": lv} for t, lv in pairs]


def fields(**over):
    base = {"symbol": "INTC", "metric": "day_change", "direction": "either", "levels": level((10, "remind"), (20, "urgent"))}
    return {**base, **over}


def refused(code, **over):
    with pytest.raises(WatchRuleError) as caught:
        validate(fields(**over), owner=OWNER, today=TODAY)
    assert caught.value.code == code and caught.value.reason
    return caught.value


# ---- validation ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("metric,direction,lv,extra", [
    ("day_change", "either", level((10, "remind"), (20, "urgent")), {}),
    ("day_change", "up", level((5, "remind")), {}),
    ("open_change", "down", level((3, "urgent")), {}),
    ("cost_change", "either", level((10, "remind")), {}),
    ("n_day_change", "up", level((15, "remind")), {"window_days": 5}),
    ("price", "above", level((100, "remind"), (110, "urgent")), {}),
    ("price", "below", level((90, "urgent"), (100, "remind")), {}),
    ("volume_ratio", "above", level((3, "remind")), {}),
    ("position_pnl", "down", level((500, "remind"), (1000, "urgent")), {}),
    ("position_weight", "below", level((10, "urgent")), {}),
])
def test_each_metric_has_a_valid_shape(db, metric, direction, lv, extra):
    clean = validate(fields(metric=metric, direction=direction, levels=lv, **extra), owner=OWNER, today=TODAY)
    assert clean["metric"] == metric and clean["direction"] == direction and clean["levels"] == lv
    assert "level_price" not in clean and clean["repeat"] == "daily" and clean["expires_on"] is None


def test_defaults_and_normalization(db):
    clean = validate({"symbol": "intc", "metric": "volume_ratio", "levels": [{"threshold": 3.0, "level": "remind"}]}, owner=OWNER, today=TODAY)
    assert clean["symbol"] == "INTC" and clean["direction"] == "above" and clean["levels"] == level((3, "remind"))
    assert validate(fields(direction=None), owner=OWNER, today=TODAY)["direction"] == "either"
    # levels come back ascending whatever order they were given in
    assert validate(fields(levels=level((20, "urgent"), (10, "remind"))), owner=OWNER, today=TODAY)["levels"] == level((10, "remind"), (20, "urgent"))


def test_refusals_say_why(db):
    refused("invalid_symbol", symbol="英特尔")
    refused("unknown_metric", metric="rsi")
    refused("direction_required", metric="price", direction=None, levels=level((100, "remind")))
    refused("invalid_direction", metric="price", direction="up", levels=level((100, "remind")))
    refused("invalid_direction", metric="volume_ratio", direction="below", levels=level((3, "remind")))
    refused("invalid_window", metric="n_day_change")
    refused("invalid_window", metric="n_day_change", window_days=1)
    refused("invalid_window", metric="n_day_change", window_days=61)
    refused("invalid_window", window_days=5)
    refused("invalid_levels", levels=[])
    refused("invalid_levels", levels=level((10, "remind"), (20, "remind")))
    refused("invalid_levels", levels=level((10, "urgent"), (20, "urgent")))
    refused("invalid_levels", levels=level((10, "urgent"), (20, "remind")))          # the urgent one is the further one
    refused("invalid_levels", metric="price", direction="below", levels=level((90, "remind"), (100, "urgent")))
    refused("invalid_levels", levels=level((10, "remind"), (10, "urgent")))
    refused("invalid_levels", levels=level((1, "remind"), (2, "urgent"), (3, "urgent")))
    refused("invalid_levels", levels=[{"threshold": 10, "level": "loud"}])
    refused("invalid_threshold", levels=level((0, "remind")))
    refused("invalid_threshold", levels=level((-5, "remind")))
    refused("invalid_threshold", direction="down", levels=level((100, "remind")))
    refused("invalid_threshold", metric="position_weight", direction="above", levels=level((101, "remind")))
    refused("invalid_repeat", repeat="hourly")
    refused("invalid_expiry", expires_on="next week")
    refused("invalid_expiry", expires_on="2026-11-01")
    assert validate(fields(repeat="once", expires_on="2026-12-01"), owner=OWNER, today=TODAY)["expires_on"] == "2026-12-01"


@pytest.mark.parametrize("metric,direction", [("cost_change", "either"), ("position_pnl", "up"), ("position_weight", "above")])
def test_a_rule_that_needs_a_holding_is_refused_for_a_symbol_he_does_not_hold(db, metric, direction):
    error = refused("not_a_holding", symbol="NVDA", metric=metric, direction=direction)
    assert "NVDA" in error.reason
    assert validate(fields(metric=metric, direction=direction), owner=OWNER, today=TODAY)["symbol"] == "INTC"
    # a rule that needs no holding does not care
    assert validate(fields(symbol="NVDA"), owner=OWNER, today=TODAY)["symbol"] == "NVDA"


# ---- the reading ---------------------------------------------------------------------------------------------------------------

def test_describe_is_the_fixture_text_for_every_metric():
    assert {r["metric"] for r in CONTRACT} == set(watch_rules.METRICS)
    for rule in CONTRACT:
        assert describe(rule) == rule["text"], rule["metric"]


def test_the_plan_example_reads_as_the_plan_says():
    rule = next(r for r in CONTRACT if r["metric"] == "day_change")
    assert describe(rule) == "英特尔相对昨收涨或跌达到 10%：提醒；达到 20%：加急。每天每档一次。"


def test_describe_directions_repeat_and_expiry():
    base = {**CONTRACT[0], "levels": level((8, "urgent"))}
    assert describe({**base, "direction": "up"}) == "英特尔相对昨收上涨达到 8%：加急。每天最多一次。"
    assert describe({**base, "direction": "down", "repeat": "once"}) == "英特尔相对昨收下跌达到 8%：加急。只触发一次，之后这条规则自动停用。"
    assert describe({**base, "expires_on": "2026-12-01"}).endswith("每天最多一次。有效到 2026-12-01。")
    price = next(r for r in CONTRACT if r["metric"] == "price")
    assert describe({**price, "direction": "above", "levels": level((110, "remind"), (120, "urgent"))}) == (
        "超微的股价高于 110 美元：提醒；高于 120 美元：加急。每档各自：条件成立时提醒一次，回到该档之内后再次越过，才会再提醒；每天每档最多一次。")
    one = describe({**price, "direction": "below", "levels": level((50, "remind"))})
    assert one == "超微的股价低于 50 美元：提醒。条件成立时提醒一次，回到 50 美元之内后再次越过，才会再提醒；每天最多一次。"
    assert describe({**base, "symbol": "ZZZZ"}).startswith("ZZZZ相对昨收")      # no Chinese name: the ticker


# ---- the dry run ---------------------------------------------------------------------------------------------------------------

def put(symbol, rows):
    """rows: (date, open, high, low, close, volume)"""
    with SessionLocal() as s:
        for day, o, h, lo, c, v in rows:
            s.add(MarketPrice(symbol=symbol, trading_date=day, open=o, high=h, low=lo, close=c, volume=v, source="test",
                              fetched_at=datetime.now(UTC)))
        s.commit()


def flat(symbol, days=60, price=100.0, volume=1_000_000, spikes=None):
    """``days`` consecutive daily bars ending TODAY, flat at ``price``; ``spikes`` maps days-ago to the fields to change."""
    rows = []
    for ago in range(days - 1, -1, -1):
        bar = {"open": price, "high": price, "low": price, "close": price, "volume": volume, **(spikes or {}).get(ago, {})}
        rows.append((TODAY - timedelta(days=ago), bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]))
    put(symbol, rows)


def rule(**over):
    return {**{k: v for k, v in CONTRACT[0].items() if k not in {"id", "text", "created_on"}}, **over}


def test_dry_run_day_change_counts_each_level_reached_per_day(db):
    flat("INTC", spikes={25: {"high": 111}, 10: {"high": 121}, 3: {"low": 85}, 2: {"close": 100}})
    got = dry_run(OWNER, rule(), today=TODAY)
    assert got["note"] is None and got["covered_days"] == 30
    assert got["hits"] == [{"date": "2026-11-01", "level": "remind"}, {"date": "2026-11-16", "level": "remind"},
                           {"date": "2026-11-16", "level": "urgent"}, {"date": "2026-11-23", "level": "remind"}]
    assert dry_run_line(got) == "按这条规则，过去 30 天会提醒你 4 次：11-01、11-16（提醒+加急）、11-23。"


def test_dry_run_direction_is_respected(db):
    flat("INTC", spikes={5: {"high": 112}, 3: {"low": 88}})
    up = dry_run(OWNER, rule(direction="up"), today=TODAY)["hits"]
    down = dry_run(OWNER, rule(direction="down"), today=TODAY)["hits"]
    assert [h["date"] for h in up] == ["2026-11-21"] and [h["date"] for h in down] == ["2026-11-23"]


def test_dry_run_a_quiet_stock_would_not_have_rung(db):
    flat("INTC")
    got = dry_run(OWNER, rule(), today=TODAY)
    assert got["hits"] == [] and got["covered_days"] == 30
    assert dry_run_line(got) == "按这条规则，过去 30 天不会提醒你（看了 30 个交易日）。"


def test_dry_run_once_counts_each_level_once(db):
    flat("INTC", spikes={20: {"high": 112}, 10: {"high": 125}, 5: {"high": 130}})
    daily = dry_run(OWNER, rule(), today=TODAY)["hits"]
    once = dry_run(OWNER, rule(repeat="once"), today=TODAY)["hits"]
    assert len(daily) == 5
    assert once == [{"date": "2026-11-06", "level": "remind"}, {"date": "2026-11-16", "level": "urgent"}]      # then it switched itself off


def test_dry_run_open_change_uses_the_days_open(db):
    flat("INTC", spikes={4: {"open": 100, "high": 106}, 3: {"open": 100, "low": 94}})
    up = dry_run(OWNER, rule(metric="open_change", direction="up", levels=level((5, "remind"))), today=TODAY)["hits"]
    assert [h["date"] for h in up] == ["2026-11-22"]


def test_dry_run_price_levels(db):
    flat("INTC", price=105, spikes={6: {"low": 98}, 2: {"low": 88}})
    got = dry_run(OWNER, rule(metric="price", direction="below", levels=level((90, "urgent"), (100, "remind"))), today=TODAY)
    assert got["hits"] == [{"date": "2026-11-20", "level": "remind"}, {"date": "2026-11-24", "level": "remind"}, {"date": "2026-11-24", "level": "urgent"}]
    above = dry_run(OWNER, rule(metric="price", direction="above", levels=level((104, "remind"))), today=TODAY)
    # flat at 105: above 104 every day, but a state metric fires once, on the day the condition becomes true (the window's first day)
    assert above["covered_days"] == 30 and above["hits"] == [{"date": "2026-10-28", "level": "remind"}]


def test_dry_run_n_day_change_compares_closes(db):
    closes = {ago: {"open": 100 + (30 - ago), "high": 100 + (30 - ago), "low": 100 + (30 - ago), "close": 100 + (30 - ago)} for ago in range(0, 31)}
    flat("INTC", spikes=closes)
    got = dry_run(OWNER, rule(metric="n_day_change", direction="up", window_days=2, levels=level((1.9, "remind"))), today=TODAY)
    # a steady climb of 1 a day: a 2-day move is 2% at 100 and falls below 1.9% from 108 up
    # edge-triggered: the condition holds on 6 days in a row and fires on the first only
    assert got["covered_days"] == 30 and [h["date"] for h in got["hits"]] == ["2026-10-29"]


def test_dry_run_volume_ratio_against_the_twenty_day_average(db):
    flat("INTC", spikes={7: {"volume": 4_500_000}, 1: {"volume": 2_000_000}})
    got = dry_run(OWNER, rule(metric="volume_ratio", direction="above", levels=level((3, "remind"), (5, "urgent"))), today=TODAY)
    assert got["hits"] == [{"date": "2026-11-19", "level": "remind"}]


def test_dry_run_holding_rules_use_todays_holding(db):
    flat("INTC", spikes={4: {"high": 130, "low": 100}, 2: {"low": 80}})
    cost = dry_run(OWNER, rule(metric="cost_change", direction="up", levels=level((150, "remind"))), today=TODAY)["hits"]      # avg cost 50: 100 is +100%, 130 is +160%
    assert [h["date"] for h in cost] == ["2026-11-22"]
    pnl = dry_run(OWNER, rule(metric="position_pnl", direction="down", levels=level((1500, "remind"), (2000, "urgent"))), today=TODAY)["hits"]
    assert pnl == [{"date": "2026-11-24", "level": "remind"}, {"date": "2026-11-24", "level": "urgent"}]      # 100 shares x 20 = 2000
    weight = dry_run(OWNER, rule(metric="position_weight", direction="above", levels=level((120, "remind"))), today=TODAY)["hits"]
    assert [h["date"] for h in weight] == ["2026-11-22"]      # 100 x 130 / 10000 = 130%, flat days 100% (total assets taken as today's)


def test_dry_run_says_so_when_there_is_no_history(db):
    flat("INTC", days=6)
    got = dry_run(OWNER, rule(), today=TODAY)
    assert got["hits"] == [] and got["note"] == "没有足够的历史行情，试跑不了"
    assert dry_run_line(got) == "试跑：没有足够的历史行情，试跑不了。"
    assert dry_run(OWNER, rule(symbol="NOPE"), today=TODAY)["note"] == "没有足够的历史行情，试跑不了"
    flat("AMD", days=15)      # enough for a day move, not for 20-day volume
    assert dry_run(OWNER, rule(symbol="AMD", metric="volume_ratio", direction="above", levels=level((3, "remind"))), today=TODAY)["note"]


def test_dry_run_holding_rule_on_a_symbol_not_held(db):
    flat("NVDA")
    assert "没有持有" in dry_run(OWNER, rule(symbol="NVDA", metric="cost_change"), today=TODAY)["note"]


# ---- storage and the snapshot ---------------------------------------------------------------------------------------------------

def test_create_update_delete(db):
    made = watch_rules.create(OWNER, fields(), "英特尔涨跌 10% 提醒我，20% 加急", today=TODAY)
    assert made["text"] == CONTRACT[0]["text"] and made["created_on"] == "2026-11-26" and made["expires_on"] is None
    assert [r["id"] for r in watch_rules.list_rules(OWNER)] == [made["id"]] and watch_rules.list_rules("someone-else") == []
    changed = watch_rules.update(OWNER, made["id"], {"levels": level((5, "remind"), (15, "urgent")), "direction": "up"})
    assert changed["levels"] == level((5, "remind"), (15, "urgent")) and changed["direction"] == "up" and changed["metric"] == "day_change"
    assert changed["text"] == "英特尔相对昨收上涨达到 5%：提醒；达到 15%：加急。每天每档一次。"
    # a different metric starts the direction over, and the whole rule is checked
    moved = watch_rules.update(OWNER, made["id"], {"metric": "price", "direction": "above", "levels": level((50, "remind"))})
    assert moved["metric"] == "price" and moved["text"].startswith("英特尔的股价高于 50 美元")
    with pytest.raises(WatchRuleError) as bad:
        watch_rules.update(OWNER, made["id"], {"metric": "n_day_change"})
    assert bad.value.code == "invalid_window"
    gone = watch_rules.delete(OWNER, made["id"])
    assert gone["id"] == made["id"] and watch_rules.list_rules(OWNER) == []
    with SessionLocal() as s:
        row = s.get(WatchRule, uuid.UUID(made["id"]))
        assert row.enabled is False and row.deleted_at is not None and row.quote.startswith("英特尔涨跌")      # soft
    for call in (lambda: watch_rules.delete(OWNER, made["id"]), lambda: watch_rules.update(OWNER, made["id"], {"repeat": "once"}),
                 lambda: watch_rules.update("someone-else", made["id"], {"repeat": "once"}), lambda: watch_rules.delete(OWNER, "not-a-uuid")):
        with pytest.raises(WatchRuleError) as missing:
            call()
        assert missing.value.code == "rule_not_found"


def test_every_write_refreshes_the_sentinel_snapshot(db, monkeypatch):
    calls = []
    monkeypatch.setattr(sentinel_bridge, "refresh_sentinel_snapshot", lambda: calls.append(1))
    made = watch_rules.create(OWNER, fields(), "q", today=TODAY)
    watch_rules.update(OWNER, made["id"], {"repeat": "once"})
    watch_rules.delete(OWNER, made["id"])
    assert len(calls) == 3


def test_the_number_of_rules_is_capped(db, monkeypatch):
    monkeypatch.setattr(watch_rules, "MAX_RULES", 2)
    watch_rules.create(OWNER, fields(), "q", today=TODAY)
    watch_rules.create(OWNER, fields(symbol="NVDA"), "q", today=TODAY)
    with pytest.raises(WatchRuleError) as full:
        watch_rules.create(OWNER, fields(symbol="AMD"), "q", today=TODAY)
    assert full.value.code == "too_many_rules"


def stored(rule):
    return WatchRule(id=uuid.UUID(rule["id"]), owner_hash=OWNER, symbol=rule["symbol"], metric=rule["metric"], direction=rule["direction"],
                     levels=rule["levels"], window_days=rule["window_days"], repeat=rule["repeat"],
                     expires_on=date.fromisoformat(rule["expires_on"]) if rule["expires_on"] else None,
                     created_on=date.fromisoformat(rule["created_on"]), enabled=True, source="owner", quote="q",
                     created_at=datetime(2026, 11, 26, tzinfo=UTC) + timedelta(minutes=int(rule["id"][-1])))


def test_the_snapshot_rules_equal_the_contract_fixture(db, monkeypatch):
    """The same file Half B (the sentinel) tests against: one rule per metric, exactly the plan's shape."""
    with SessionLocal() as s:
        s.add_all([stored(r) for r in CONTRACT])
        s.commit()
    monkeypatch.setattr(sentinel_bridge, "_research_queue", lambda owner: [])
    monkeypatch.setattr(sentinel_bridge, "_telegram", lambda owner: {})
    monkeypatch.setattr(sentinel_bridge, "_pushover", lambda owner: {})
    monkeypatch.setattr(sentinel_bridge, "_portfolio", lambda owner: {"positions": [], "plans": [], "total_assets": None})
    snapshot = sentinel_bridge.build_snapshot(OWNER)
    assert snapshot["rules"] == CONTRACT
    assert all(set(r) == {"id", "symbol", "metric", "direction", "levels", "window_days", "repeat", "expires_on", "created_on", "text"}
               for r in snapshot["rules"])


def test_the_snapshot_holds_enabled_unexpired_rules_only(db):
    live = watch_rules.create(OWNER, fields(), "q", today=TODAY)
    old = watch_rules.create(OWNER, fields(symbol="NVDA", expires_on="2026-12-01"), "q", today=TODAY)
    off = watch_rules.create(OWNER, fields(symbol="AMD"), "q", today=TODAY)
    watch_rules.delete(OWNER, off["id"])
    assert [r["id"] for r in watch_rules.snapshot_rules(OWNER, today=date(2026, 12, 1))] == [live["id"], old["id"]]
    assert [r["id"] for r in watch_rules.snapshot_rules(OWNER, today=date(2026, 12, 2))] == [live["id"]]
    assert watch_rules.snapshot_rules("someone-else") == []


def test_a_broken_rules_section_does_not_stop_the_snapshot(db, monkeypatch):
    monkeypatch.setattr(watch_rules, "snapshot_rules", lambda owner: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(sentinel_bridge, "_research_queue", lambda owner: [])
    monkeypatch.setattr(sentinel_bridge, "_telegram", lambda owner: {})
    monkeypatch.setattr(sentinel_bridge, "_pushover", lambda owner: {})
    monkeypatch.setattr(sentinel_bridge, "_portfolio", lambda owner: {"positions": [], "plans": [], "total_assets": None})
    assert sentinel_bridge.build_snapshot(OWNER)["rules"] == []


def test_a_state_metric_rearms_after_the_condition_was_false(db):
    flat("INTC", price=105, spikes={10: {"low": 95}, 9: {"low": 94}, 8: {"low": 96}, 6: {"low": 99}})
    got = dry_run(OWNER, rule(metric="price", direction="below", levels=level((100, "remind"))), today=TODAY)
    # below 100 on days 10, 9, 8 (one hit), back above on day 7, below again on day 6 (a second hit)
    assert [h["date"] for h in got["hits"]] == ["2026-11-16", "2026-11-20"]


def test_the_first_window_day_counts_as_becoming_true(db):
    flat("INTC", price=90)
    got = dry_run(OWNER, rule(metric="price", direction="below", levels=level((100, "remind"), )), today=TODAY)
    assert got["hits"] == [{"date": "2026-10-28", "level": "remind"}]
