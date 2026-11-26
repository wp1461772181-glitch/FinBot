"""5b-1 Half B: sentinel/rules.py, the pure measuring of the owner's rules (no network, no store)."""
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sentinel import rules

CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "watch_rules_contract.json").read_text(encoding="utf-8"))["rules"]
BY_METRIC = {r["metric"] + ":" + r["direction"]: r for r in CONTRACT}


def rule(metric, direction, levels, **extra):
    base = {"id": "r1", "symbol": "INTC", "metric": metric, "direction": direction, "window_days": None,
            "level_price": None, "repeat": "daily", "expires_on": None, "created_on": "2026-11-26", "text": "t",
            "levels": [{"threshold": t, "level": n} for t, n in levels]}
    return base | extra


def test_every_contract_rule_is_accepted_and_one_per_metric():
    assert all(rules.valid(r) for r in CONTRACT)
    assert {r["metric"] for r in CONTRACT} == set(rules.METRICS)


@pytest.mark.parametrize("change", [
    {"metric": "short_interest"}, {"direction": "sideways"}, {"levels": []},
    {"levels": [{"threshold": -1, "level": "remind"}]}, {"levels": [{"threshold": 5, "level": "loud"}]},
    {"repeat": "weekly"}, {"id": ""}, {"symbol": ""},
    {"levels": [{"threshold": 1, "level": "remind"}] * 3},
])
def test_a_malformed_rule_is_not_valid(change):
    assert not rules.valid(BY_METRIC["day_change:either"] | change)


def test_volume_ratio_only_goes_above_and_n_day_needs_a_window():
    assert not rules.valid(BY_METRIC["volume_ratio:above"] | {"direction": "below"})
    assert not rules.valid(BY_METRIC["n_day_change:up"] | {"window_days": None})
    assert not rules.valid(BY_METRIC["n_day_change:up"] | {"window_days": 1})
    assert not rules.valid(BY_METRIC["n_day_change:up"] | {"window_days": 61})


# --- measure ----------------------------------------------------------------------------------------------------------

CTX = {"price": 36.0, "prev_close": 40.0, "open": 38.0, "avg_cost": 30.0, "closes": [30.0, 32.0, 34.0, 35.0, 40.0],
       "volume_today": 600.0, "avg_volume": 1000.0, "session_minutes": 195, "shares": 100.0, "market_value": 4000.0,
       "total_assets": 10000.0}


def test_each_metric_measures_what_the_table_says():
    assert rules.measure(rule("day_change", "either", [(10, "remind")]), CTX) == pytest.approx(-10.0)
    assert rules.measure(rule("open_change", "down", [(3, "remind")]), CTX) == pytest.approx((36 / 38 - 1) * 100, abs=1e-5)
    assert rules.measure(rule("cost_change", "up", [(10, "remind")]), CTX) == pytest.approx(20.0)
    assert rules.measure(rule("price", "above", [(30, "remind")]), CTX) == 36.0
    assert rules.measure(rule("position_pnl", "down", [(100, "remind")]), CTX) == pytest.approx(-400.0)
    # the position is worth 3600 now and total assets follow it: 3600 / (10000 - 4000 + 3600)
    assert rules.measure(rule("position_weight", "above", [(30, "remind")]), CTX) == pytest.approx(3600 / 9600 * 100, abs=1e-4)
    # half the session has gone (195 of 390 minutes), 600 traded against an average day of 1000: 600 / (1000 * 0.5)
    assert rules.measure(rule("volume_ratio", "above", [(2, "remind")]), CTX) == pytest.approx(1.2)


def test_n_day_change_counts_trading_days_back_from_yesterday():
    two = rule("n_day_change", "up", [(10, "remind")], window_days=2)
    # yesterday (1 day ago) closed 40; two trading days ago it closed 35
    assert rules.measure(two, CTX) == pytest.approx((36 / 35 - 1) * 100, abs=1e-5)
    five = rule("n_day_change", "up", [(10, "remind")], window_days=5)
    assert rules.measure(five, CTX) == pytest.approx((36 / 30 - 1) * 100, abs=1e-5)
    six = rule("n_day_change", "up", [(10, "remind")], window_days=6)
    assert rules.measure(six, CTX) is None                            # not enough history: no guessing


def test_the_volume_floor_and_ceiling_of_the_session_fraction():
    r = rule("volume_ratio", "above", [(2, "remind")])
    assert rules.measure(r, CTX | {"session_minutes": 30, "volume_today": 100.0}) == pytest.approx(100 / (1000 * 0.1))
    assert rules.measure(r, CTX | {"session_minutes": 390, "volume_today": 1000.0}) == pytest.approx(1.0)


@pytest.mark.parametrize("metric,direction,missing", [
    ("day_change", "either", "prev_close"), ("open_change", "down", "open"), ("cost_change", "up", "avg_cost"),
    ("n_day_change", "up", "closes"), ("volume_ratio", "above", "avg_volume"), ("volume_ratio", "above", "volume_today"),
    ("volume_ratio", "above", "session_minutes"), ("position_pnl", "down", "shares"), ("position_weight", "above", "total_assets"),
    ("position_pnl", "down", "prev_close"), ("price", "above", "price"),
])
def test_missing_data_measures_none_and_never_fires(metric, direction, missing):
    r = rule(metric, direction, [(0.0001, "urgent")], window_days=2)
    assert rules.measure(r, CTX | {missing: None}) is None
    assert rules.crossed(r, rules.measure(r, CTX | {missing: None})) is None


def test_volume_ratio_is_not_measured_before_ten():
    assert rules.measure(rule("volume_ratio", "above", [(2, "remind")]), CTX | {"session_minutes": 29}) is None


def test_zero_avg_cost_or_prev_close_is_missing_not_a_division_error():
    assert rules.measure(rule("cost_change", "up", [(1, "remind")]), CTX | {"avg_cost": 0}) is None
    assert rules.measure(rule("day_change", "up", [(1, "remind")]), CTX | {"prev_close": 0}) is None


# --- crossed ----------------------------------------------------------------------------------------------------------

def test_direction_semantics_for_percent_metrics():
    up, down, either = (rule("day_change", d, [(10, "remind"), (20, "urgent")]) for d in ("up", "down", "either"))
    assert rules.crossed(up, 10.0) == 0 and rules.crossed(up, 25.0) == 1 and rules.crossed(up, -25.0) is None
    assert rules.crossed(down, -10.0) == 0 and rules.crossed(down, -25.0) == 1 and rules.crossed(down, 25.0) is None
    assert rules.crossed(either, -10.0) == 0 and rules.crossed(either, 20.0) == 1 and rules.crossed(either, 9.99) is None


def test_the_highest_level_reached_wins_and_urgent_outranks_by_name():
    r = rule("day_change", "either", [(10, "remind"), (20, "urgent")])
    assert rules.crossed(r, -15.0) == 0 and rules.crossed(r, -20.0) == 1
    below = rule("price", "below", [(250, "remind"), (230, "urgent")])        # the urgent level is the lower price
    assert rules.crossed(below, 240.0) == 0 and rules.crossed(below, 229.0) == 1 and rules.crossed(below, 251.0) is None
    assert rules.severity_order(below) == [0, 1]
    flipped = rule("price", "below", [(230, "urgent"), (250, "remind")])
    assert rules.severity_order(flipped) == [1, 0] and rules.crossed(flipped, 229.0) == 0


def test_above_below_and_pnl_directions():
    assert rules.crossed(rule("price", "above", [(300, "remind")]), 300.0) == 0
    assert rules.crossed(rule("price", "above", [(300, "remind")]), 299.99) is None
    assert rules.crossed(rule("position_weight", "below", [(10, "remind")]), 9.0) == 0
    pnl = rule("position_pnl", "down", [(1000, "remind"), (3000, "urgent")])
    assert rules.crossed(pnl, -1500.0) == 0 and rules.crossed(pnl, -3000.0) == 1 and rules.crossed(pnl, 5000.0) is None
    assert rules.crossed(rule("position_pnl", "up", [(1000, "remind")]), 1000.0) == 0
    assert rules.crossed(rule("volume_ratio", "above", [(2, "remind")]), 2.0) == 0


def test_a_move_of_exactly_the_threshold_counts_despite_float_noise():
    r = rule("day_change", "up", [(10, "remind")])
    assert rules.crossed(r, rules.measure(r, {"price": 44.0, "prev_close": 40.0})) == 0


# --- keys, expiry, daily summary -----------------------------------------------------------------------------------

def test_expiry_is_the_last_day_checked():
    r = rule("price", "above", [(1, "remind")], expires_on="2026-11-30")
    assert not rules.expired(r, "2026-11-30") and rules.expired(r, "2026-12-01")
    assert not rules.expired(rule("price", "above", [(1, "remind")]), "2099-01-01")


def test_level_key_carries_the_threshold():
    r = rule("day_change", "up", [(10, "remind"), (20, "urgent")])
    assert [rules.level_key(r, i) for i in (0, 1)] == ["remind@10", "urgent@20"]


def test_daily_summary_drops_today_and_averages_twenty_days():
    bars = [{"ts": datetime(2026, 11, 1, 20, 0, tzinfo=UTC) + timedelta(days=i), "close": 10.0 + i, "volume": 1000.0 + i}
            for i in range(25)]
    out = rules.daily_summary(bars, date(2026, 11, 20))
    # bars dated Nov 1 .. Nov 19 are complete (19 days); today's and later are dropped
    assert len(out["closes"]) == 19 and out["closes"][-1] == 28.0
    assert out["avg_volume"] == pytest.approx(sum(1000.0 + i for i in range(19)) / 19)
    few = rules.daily_summary(bars[:5], date(2026, 11, 20))
    assert few["avg_volume"] is None and len(few["closes"]) == 5
