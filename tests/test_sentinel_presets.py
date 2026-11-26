"""5b-2 Part 2: the system's preset rules in the sentinel (new metrics, expansion per scope, yielding, messages, settings).
No network: bars and daily closes are built by hand."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sentinel import escalation, replay, rules, signals
from sentinel.filings import FilingWatcher
from sentinel.main import Sentinel
from sentinel.store import Store

ET = ZoneInfo("America/New_York")
CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "watch_presets_contract.json").read_text(encoding="utf-8"))
PRESETS = {p["preset_key"]: p for p in CONTRACT["presets"]}
BASE_STATS = {"daily_sigma": 0.075, "bucket_sigma": {"pre": 0.002, "mid": 0.003},
              "avg_vol5": {"open30": 3000.0, "mid": 1000.0, "close30": 2000.0}}
INTC = {"symbol": "INTC", "shares": 100.0, "avg_cost": 50.0, "market_value": 4000.0}      # 40.00 a share
NVDA = {"symbol": "NVDA", "shares": 10.0, "avg_cost": 90.0, "market_value": 1000.0}       # 100.00 a share
SNAP = {"positions": [INTC, NVDA], "total_assets": 10000.0}
RULE_TAIL = "规则：单只占比过高（系统默认；可以在「它眼中的你」页面关掉或改门槛）"


def et(hour, minute, day=3):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET)


def bars(end, price, n=15, volume=100):
    start = end - timedelta(minutes=n - 1)
    return [{"ts": start + timedelta(minutes=i), "close": price, "volume": volume, "open": price} for i in range(n)]


def preset(key, **extra):
    return json.loads(json.dumps(PRESETS[key])) | extra


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", "tiers")
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)
    monkeypatch.delenv("SENTINEL_SHORT_MOVES", raising=False)

    count = []

    def build():                                                       # every call is a sentinel with its own, empty state
        count.append(1)
        s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / f"s{len(count)}.db"))
        s._market = None
        return s
    return build


def look(s, symbol, price, when, *, held=True, snap=None, presets=(), rules_list=(), prev=None, daily=None,
         window=None, rules_only=False, base=BASE_STATS, splits=None):
    snapshot = dict(SNAP if snap is None else snap)
    snapshot["presets"], snapshot["rules"] = list(presets), list(rules_list)
    prev = {"INTC": 40.0, "NVDA": 100.0}.get(symbol, 100.0) if prev is None else prev
    series = window if window is not None else bars(when, price)
    return s.alerts_from(symbol, held, when, snapshot, series, prev, base, splits or [], daily=daily, rules_only=rules_only)


def presets_of(out):
    return [a for a in out if a["kind"] == "preset"]


# --- the contract fixture ---------------------------------------------------------------------------------------------

def test_the_contract_fixture_holds_the_six_defaults_and_the_settings():
    assert CONTRACT["alert_settings"] == {"sensitivity": "standard", "short_moves": False}
    assert list(PRESETS) == ["concentration", "portfolio_drawdown", "down_streak", "new_high_52w", "new_low_52w", "volume_surge"]
    assert all(rules.preset_valid(p) for p in CONTRACT["presets"])
    assert all(p["id"] == f"preset:{p['preset_key']}" and p["source"] == "preset" for p in CONTRACT["presets"])
    assert {p["scope"] for p in CONTRACT["presets"]} == {"holdings", "watched", "portfolio"}


def test_a_malformed_preset_is_not_valid():
    assert not rules.preset_valid(preset("concentration", scope="everywhere"))
    assert not rules.preset_valid(preset("concentration", preset_key=""))
    assert not rules.preset_valid(preset("concentration", source="owner"))
    assert not rules.preset_valid(preset("portfolio_drawdown", scope="holdings"))        # a portfolio metric needs scope portfolio
    assert not rules.preset_valid(preset("concentration", scope="portfolio"))
    assert not rules.preset_valid(preset("down_streak", levels=[{"threshold": 1, "level": "remind"}]))   # days are integers >= 2
    assert not rules.preset_valid(preset("down_streak", levels=[{"threshold": 2.5, "level": "remind"}]))
    assert rules.preset_valid(preset("down_streak", levels=[{"threshold": 2, "level": "remind"}]))


def test_owner_rules_cannot_use_the_star_symbol_or_the_portfolio_metric():
    mine = {"id": "r", "symbol": "INTC", "metric": "down_days", "direction": "down", "repeat": "daily",
            "levels": [{"threshold": 3, "level": "remind"}], "window_days": None}
    assert rules.valid(mine)
    assert not rules.valid(mine | {"symbol": "*"})
    assert not rules.valid(mine | {"metric": "portfolio_day_change", "direction": "down", "symbol": "*"})
    assert rules.valid({**mine, "metric": "high_52w", "direction": "above", "levels": [{"threshold": 0, "level": "remind"}]})
    assert not rules.valid({**mine, "metric": "high_52w", "direction": "below", "levels": [{"threshold": 0, "level": "remind"}]})


# --- the new metrics (pure) -------------------------------------------------------------------------------------------

def test_down_days_counts_completed_down_days_and_today():
    rule = {"metric": "down_days", "direction": "down"}
    closes = [10.0, 11.0, 10.5, 10.0, 9.5, 9.0, 8.5]                 # 5 completed closes below the one before
    ctx = {"price": 8.4, "prev_close": 8.5, "closes": closes}
    assert rules.measure(rule, ctx) == 6                              # +1: today is down too
    assert rules.measure(rule, ctx | {"price": 8.6}) == 5             # today is up: only the completed run
    assert rules.measure(rule, ctx | {"closes": [10.0, 11.0, 12.0, 8.5]}) == 1 + 1   # one completed down day, plus today
    assert rules.measure(rule, ctx | {"closes": [10.0, 11.0]}) == 0 + 1


def test_down_days_needs_its_inputs():
    rule = {"metric": "down_days", "direction": "down"}
    ctx = {"price": 8.4, "prev_close": 8.5, "closes": [10.0, 9.0]}
    assert rules.measure(rule, ctx | {"closes": None}) is None
    assert rules.measure(rule, ctx | {"closes": []}) is None
    assert rules.measure(rule, ctx | {"prev_close": None}) is None
    assert rules.measure(rule, ctx | {"price": None}) is None


def test_down_days_levels_use_the_count_not_a_percentage():
    rule = preset("down_streak") | {"symbol": "AMD"}
    assert rules.reached(rule, 4) == [] and rules.reached(rule, 5) == [0] and rules.reached(rule, 9) == [0]
    assert rules.reached(rule, None) == []


def year(n=250, up=True):
    return [float(i + 1) if up else float(n - i) for i in range(n)]


def test_high_and_low_52w_compare_with_the_extreme_close():
    high, low = {"metric": "high_52w", "direction": "above", "levels": [{"threshold": 0, "level": "remind"}]}, \
        {"metric": "low_52w", "direction": "below", "levels": [{"threshold": 0, "level": "remind"}]}
    ctx = {"price": 251.0, "closes": year()}                         # highest close 250
    assert rules.measure(high, ctx) == 1.0 and rules.reached(high, 1.0) == [0]
    assert rules.reached(high, rules.measure(high, ctx | {"price": 250.0})) == [0]       # equal counts
    assert rules.reached(high, rules.measure(high, ctx | {"price": 249.9})) == []
    down = {"price": 0.9, "closes": year(up=False)}                  # lowest close 1
    assert rules.reached(low, rules.measure(low, down)) == [0]
    assert rules.reached(low, rules.measure(low, down | {"price": 1.0})) == [0]
    assert rules.reached(low, rules.measure(low, down | {"price": 1.1})) == []


def test_52w_uses_the_last_252_closes_only_and_needs_a_year_of_them():
    high = {"metric": "high_52w", "direction": "above", "levels": [{"threshold": 0, "level": "remind"}]}
    old_peak = [1000.0] + [100.0] * 260                               # the 1000 is 261 closes ago: outside the window
    assert rules.reached(high, rules.measure(high, {"price": 101.0, "closes": old_peak})) == [0]
    assert rules.measure(high, {"price": 101.0, "closes": year(100)}) is None            # not a year of history: never guess
    assert rules.measure(high, {"price": 101.0, "closes": None}) is None
    assert rules.measure(high, {"price": None, "closes": year()}) is None


def test_portfolio_day_change_is_the_move_of_all_holdings_over_yesterdays_assets():
    rule = preset("portfolio_drawdown")
    ctx = {"total_assets": 10000.0, "holdings": [
        {"symbol": "INTC", "shares": 100.0, "price": 36.0, "prev_close": 40.0, "market_value": 4000.0},
        {"symbol": "NVDA", "shares": 10.0, "price": 94.0, "prev_close": 100.0, "market_value": 1000.0}]}
    # moves -400 and -60; assets now 5000 + 3600 + 940 = 9540; yesterday's 10000
    assert rules.measure(rule, ctx) == pytest.approx(-4.6)
    assert rules.reached(rule, -4.6) == [0] and rules.reached(rule, -5.0) == [0, 1] and rules.reached(rule, -2.9) == []
    assert rules.reached(rule, +6.0) == []                            # direction down only
    # without market values the total is taken as it stands now: -460 / (10000 + 460)
    bare = {"total_assets": 10000.0, "holdings": [{k: v for k, v in h.items() if k != "market_value"} for h in ctx["holdings"]]}
    assert rules.measure(rule, bare) == pytest.approx(-460 / 10460 * 100, abs=1e-4)


def test_portfolio_day_change_is_none_when_any_input_is_missing():
    rule = preset("portfolio_drawdown")
    good = [{"symbol": "INTC", "shares": 100.0, "price": 36.0, "prev_close": 40.0, "market_value": 4000.0}]
    assert rules.measure(rule, {"total_assets": 10000.0, "holdings": good}) is not None
    assert rules.measure(rule, {"total_assets": 10000.0, "holdings": good + [{"symbol": "X", "shares": 1.0, "price": None, "prev_close": 5.0}]}) is None
    assert rules.measure(rule, {"total_assets": 10000.0, "holdings": good + [{"symbol": "X", "shares": 1.0, "price": 4.0, "prev_close": None}]}) is None
    assert rules.measure(rule, {"total_assets": None, "holdings": good}) is None
    assert rules.measure(rule, {"total_assets": 10000.0, "holdings": []}) is None


# --- concentration: one preset, expanded per holding -------------------------------------------------------------------

def test_concentration_is_expanded_per_holding(make):
    s, conc = make(), preset("concentration")
    out = presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[conc]))
    assert len(out) == 1
    a = out[0]
    assert a["text"] == f"【系统默认·提醒】INTC 占你总资产 40.0%，超过 25%。\n{RULE_TAIL}"
    assert a["kind"] == "preset" and a["preset_key"] == "concentration" and a["rule_id"] == "preset:concentration"
    assert a["escalate"] is False and a["price_move"] is False and a["tier"] == 1 and a["held"] is True
    assert a["symbol"] == "INTC" and a["weight_pct"] == pytest.approx(40.0) and "owner_rule" not in a
    assert presets_of(look(s, "NVDA", 100.0, et(10, 0), presets=[conc])) == []        # 10%: not heavy


def test_each_holding_has_its_own_edge_state(make):
    s, conc = make(), preset("concentration")
    assert len(presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[conc]))) == 1
    # NVDA grows past 25% while INTC's alert is still "said": NVDA says its own
    assert len(presets_of(look(s, "NVDA", 400.0, et(10, 1), presets=[conc]))) == 1    # 4000 / 13000 = 30.8%
    assert presets_of(look(s, "INTC", 40.0, et(10, 2), presets=[conc])) == []         # same stretch: said once
    assert presets_of(look(s, "NVDA", 400.0, et(10, 2), presets=[conc])) == []


def test_concentration_says_it_again_only_after_the_weight_fell_back_and_the_day_changed(make):
    s, conc = make(), preset("concentration")
    assert len(presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[conc]))) == 1
    assert presets_of(look(s, "INTC", 10.0, et(10, 5), presets=[conc])) == []         # 1000 / 7000: below, re-armed
    assert presets_of(look(s, "INTC", 40.0, et(10, 10), presets=[conc])) == []        # but already said today
    assert len(presets_of(look(s, "INTC", 40.0, et(10, 0, day=4), presets=[conc]))) == 1


def test_an_edited_threshold_starts_afresh(make):
    s = make()
    assert len(presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[preset("concentration")]))) == 1
    edited = preset("concentration", levels=[{"threshold": 30, "level": "remind"}])
    out = presets_of(look(s, "INTC", 40.0, et(10, 1), presets=[edited]))
    assert len(out) == 1 and "超过 30%" in out[0]["text"]


def test_a_disabled_or_expired_preset_does_nothing(make):
    s = make()
    assert presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[preset("concentration", enabled=False)])) == []
    assert presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[preset("concentration", expires_on="2026-11-02")])) == []
    assert presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[preset("concentration", metric="nonsense")])) == []


def test_a_holdings_preset_does_not_apply_to_a_symbol_that_is_not_held(make):
    s = make()
    out = look(s, "AMD", 100.0, et(10, 0), held=False, snap={"positions": [INTC], "total_assets": 10000.0},
               presets=[preset("concentration", levels=[{"threshold": 0.001, "level": "remind"}])])
    assert presets_of(out) == []


# --- watched scope: held + research queue, not a symbol only an owner rule names ---------------------------------------

STREAK = {"closes": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0], "avg_volume": None}               # 5 completed down days


def test_down_streak_applies_to_the_queue_and_to_holdings_but_not_to_rule_only_symbols(make):
    s, streak = make(), preset("down_streak")
    queued = presets_of(look(s, "AMD", 4.9, et(10, 0), held=False, prev=5.0, presets=[streak], daily=STREAK))
    assert len(queued) == 1
    a = queued[0]
    assert a["text"].splitlines()[0] == "【系统默认·提醒】AMD 已连续 6 个交易日下跌（含今天盘中），现价 4.90。"
    assert a["text"].splitlines()[1].startswith("规则：连续下跌（系统默认；")
    assert a["held"] is False and a["preset_key"] == "down_streak" and a["direction"] == "down"
    held = presets_of(look(make(), "INTC", 4.9, et(10, 0), prev=5.0, presets=[streak], daily=STREAK))
    assert len(held) == 1
    only = presets_of(look(make(), "TSLA", 4.9, et(10, 0), held=False, prev=5.0, presets=[streak], daily=STREAK, rules_only=True))
    assert only == []


def test_down_streak_says_the_completed_run_when_today_is_not_down_and_is_silent_without_history(make):
    s, streak = make(), preset("down_streak")
    out = presets_of(look(s, "AMD", 5.2, et(10, 0), held=False, prev=5.0, presets=[streak], daily=STREAK))
    assert out[0]["text"].splitlines()[0] == "【系统默认·提醒】AMD 已连续 5 个交易日收跌，现价 5.20。"
    assert presets_of(look(make(), "AMD", 4.9, et(10, 0), held=False, prev=5.0, presets=[streak], daily=None)) == []
    short = {"closes": [10.0, 9.0], "avg_volume": None}
    assert presets_of(look(make(), "AMD", 4.9, et(10, 0), held=False, prev=5.0, presets=[streak], daily=short)) == []


def test_down_streak_is_an_edge_and_rearms_when_the_run_breaks(make):
    s, streak = make(), preset("down_streak")
    args = dict(held=False, prev=5.0, presets=[streak])
    assert len(presets_of(look(s, "AMD", 4.9, et(10, 0), daily=STREAK, **args))) == 1
    assert presets_of(look(s, "AMD", 4.8, et(10, 1), daily=STREAK, **args)) == []
    broken = {"closes": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 5.5], "avg_volume": None}      # the run ended yesterday
    assert presets_of(look(s, "AMD", 5.6, et(10, 0, day=4), daily=broken, held=False, prev=5.5, presets=[streak])) == []
    again = {"closes": [5.5, 5.0, 4.5, 4.0, 3.5, 3.0], "avg_volume": None}
    assert len(presets_of(look(s, "AMD", 2.9, et(10, 0, day=5), daily=again, held=False, prev=3.0, presets=[streak]))) == 1


def test_a_streak_is_said_once_even_when_today_flickers_back_over_yesterdays_close(make):
    s, streak = make(), preset("down_streak")
    first = {"closes": [9.0, 8.0, 7.0, 6.0, 5.0], "avg_volume": None}                  # 4 completed down days
    args = dict(held=False, presets=[streak])
    assert len(presets_of(look(s, "AMD", 4.9, et(10, 0), daily=first, prev=5.0, **args))) == 1   # today makes the 5th
    assert presets_of(look(s, "AMD", 5.1, et(10, 5), daily=first, prev=5.0, **args)) == []      # flickers up: 4 again
    nxt = {"closes": [9.0, 8.0, 7.0, 6.0, 5.0, 4.9], "avg_volume": None}                # it closed down: 5 completed
    assert presets_of(look(s, "AMD", 4.95, et(10, 0, day=4), daily=nxt, prev=4.9, **args)) == []    # the same streak: not again


def test_a_new_52w_high_and_low_say_the_close_they_beat(make):
    s = make()
    up, down = {"closes": year(), "avg_volume": None}, {"closes": year(up=False), "avg_volume": None}
    out = presets_of(look(s, "AMD", 251.0, et(10, 0), held=False, prev=250.0, presets=[preset("new_high_52w")], daily=up))
    assert out[0]["text"].splitlines()[0] == "【系统默认·提醒】AMD 创 52 周新高：现价 251.00，高过过去一年的最高收盘 250.00。"
    assert out[0]["direction"] == "up" and out[0]["preset_key"] == "new_high_52w"
    assert presets_of(look(s, "AMD", 252.0, et(10, 1), held=False, prev=250.0, presets=[preset("new_high_52w")], daily=up)) == []   # still the same stretch
    out = presets_of(look(make(), "AMD", 0.9, et(10, 0), held=False, prev=1.0, presets=[preset("new_low_52w")], daily=down))
    assert out[0]["text"].splitlines()[0] == "【系统默认·提醒】AMD 创 52 周新低：现价 0.90，低于过去一年的最低收盘 1.00。"
    assert out[0]["direction"] == "down"
    assert presets_of(look(make(), "AMD", 100.0, et(10, 0), held=False, prev=1.0, presets=[preset("new_high_52w"), preset("new_low_52w")], daily=down)) == []


def test_52w_without_a_year_of_closes_is_silent(make):
    short = {"closes": year(100), "avg_volume": None}
    out = look(make(), "AMD", 500.0, et(10, 0), held=False, prev=100.0, presets=[preset("new_high_52w")], daily=short)
    assert presets_of(out) == []


# --- volume_surge ------------------------------------------------------------------------------------------------------

def volume_window(minutes, per_minute):
    return [{"ts": et(9, 30) + timedelta(minutes=i), "close": 40.0, "volume": per_minute(i), "open": 40.0} for i in range(minutes + 1)]


def test_volume_surge_on_a_holding(make):
    daily = {"closes": [40.0] * 30, "avg_volume": 39000.0}
    heavy = lambda i: 1800.0 if i < 30 else 600.0                                       # noqa: E731   3x the profile
    out = presets_of(look(make(), "INTC", 40.0, et(10, 30), presets=[preset("volume_surge")], daily=daily,
                          window=volume_window(59, heavy)))
    assert len(out) == 1
    assert out[0]["text"].splitlines()[0] == "【系统默认·提醒】INTC 今日成交量已是同一时段正常水平的 3.0 倍，现价 40.00。"
    ordinary = lambda i: 1200.0 if i < 30 else 400.0                                    # noqa: E731   2x: under 3
    assert presets_of(look(make(), "INTC", 40.0, et(10, 30), presets=[preset("volume_surge")], daily=daily,
                           window=volume_window(59, ordinary))) == []
    queued = look(make(), "AMD", 40.0, et(10, 30), held=False, presets=[preset("volume_surge")], daily=daily,
                  window=volume_window(59, heavy))
    assert presets_of(queued) == []                                                     # scope holdings


# --- yielding to the owner's own rule of the same kind -----------------------------------------------------------------

def owner_rule(metric, direction, levels, symbol="INTC", **extra):
    return {"id": f"r-{symbol}-{metric}", "symbol": symbol, "metric": metric, "direction": direction, "window_days": None,
            "repeat": "daily", "expires_on": None, "created_on": "2026-11-02", "text": "你定的。",
            "levels": [{"threshold": t, "level": n} for t, n in levels]} | extra


def test_a_preset_yields_on_the_symbol_where_the_owner_has_the_same_metric(make):
    s, conc = make(), preset("concentration")
    mine = owner_rule("position_weight", "above", [(60, "remind")])
    out = look(s, "INTC", 40.0, et(10, 0), presets=[conc], rules_list=[mine])
    assert presets_of(out) == [] and [a for a in out if a["kind"] == "rule"] == []        # 40% < 60%: his rule is silent, the default stays out
    nvda = look(s, "NVDA", 400.0, et(10, 0), presets=[conc], rules_list=[mine])
    assert len(presets_of(nvda)) == 1                                                     # another symbol: the preset still works


def test_a_preset_yields_to_a_rule_of_the_same_metric_whatever_its_direction_or_level(make):
    s, conc = make(), preset("concentration")
    mine = owner_rule("position_weight", "below", [(5, "urgent")])
    assert presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[conc], rules_list=[mine])) == []


def test_a_preset_does_not_yield_to_a_different_metric_nor_to_a_disabled_or_expired_rule(make):
    conc = preset("concentration")
    other = owner_rule("price", "above", [(1000, "remind")])
    assert len(presets_of(look(make(), "INTC", 40.0, et(10, 0), presets=[conc], rules_list=[other]))) == 1
    off = owner_rule("position_weight", "above", [(60, "remind")]) | {"enabled": False}
    assert len(presets_of(look(make(), "INTC", 40.0, et(10, 0), presets=[conc], rules_list=[off]))) == 1
    old = owner_rule("position_weight", "above", [(60, "remind")], expires_on="2026-11-02")
    assert len(presets_of(look(make(), "INTC", 40.0, et(10, 0), presets=[conc], rules_list=[old]))) == 1


# --- hard guarantees: a preset never blocks a stop crossing or a filing alert ---------------------------------------------

def test_the_stop_price_still_fires_with_presets_on_and_with_a_yielding_owner_rule(make):
    snap = SNAP | {"plans": [{"symbol": "INTC", "stop_price": 34.0}]}
    conc = preset("concentration", levels=[{"threshold": 1, "level": "urgent"}])
    mine = owner_rule("position_weight", "above", [(1, "remind")])
    for rules_list in ([], [mine]):
        s = make()
        out = look(s, "INTC", 35.0, et(10, 0), snap=snap, presets=[conc], rules_list=rules_list)      # arms the level
        out += look(s, "INTC", 33.0, et(10, 1), snap=snap, presets=[conc], rules_list=rules_list)
        stop = [a for a in out if a["kind"] == "plan_stop"]
        assert len(stop) == 1 and stop[0]["escalate"] is True


def test_a_failing_preset_costs_neither_the_stop_nor_the_default_alerts(make, monkeypatch):
    snap = SNAP | {"plans": [{"symbol": "INTC", "stop_price": 34.0}]}
    s = make()
    real = rules.measure

    def broken(rule, ctx):
        if rule.get("source") == "preset":
            raise ZeroDivisionError
        return real(rule, ctx)
    monkeypatch.setattr(rules, "measure", broken)
    out = look(s, "INTC", 35.0, et(10, 0), snap=snap, presets=[preset("concentration")])
    out += look(s, "INTC", 33.0, et(10, 1), snap=snap, presets=[preset("concentration")])
    assert presets_of(out) == [] and [a["kind"] for a in out if a["kind"] == "plan_stop"] == ["plan_stop"]


def test_a_filing_alert_goes_whatever_the_presets_say(tmp_path):
    events = []
    snap = {"positions": [{"symbol": "INTC", "shares": 10}], "research_queue": [], "telegram": {"chat_id": 1},
            "presets": CONTRACT["presets"] + [{"junk": True}], "alert_settings": CONTRACT["alert_settings"]}
    tickers = {"0": {"cik_str": 50863, "ticker": "INTC", "title": "INTEL CORP"}}
    keys = ["form", "items", "accessionNumber", "filingDate", "acceptanceDateTime", "primaryDocument"]
    row = ("8-K", "2.02,9.01", "0000050863-26-000188", "2026-10-29", "2026-10-29T20:31:07.000Z", "x.htm")

    def fetch(url):
        return tickers if url.endswith("company_tickers.json") else {"filings": {"recent": {k: [row[i]] for i, k in enumerate(keys)}}}
    watcher = FilingWatcher(Store(tmp_path / "f.db"), lambda: snap, fetch_json=fetch, post_event=lambda kind, payload: events.append((kind, payload)),
                            raise_alert=lambda sn, alert: 1, sleep=lambda s: None)
    watcher.poll(datetime(2026, 10, 30, 1, 0, tzinfo=UTC).timestamp())
    assert [(k, p["symbol"]) for k, p in events] == [("earnings_detected", "INTC")]


# --- the portfolio preset: one evaluation per poll after every symbol ---------------------------------------------------

def poll(s, prices, when, *, snap=None, presets=(), skip=(), stale=()):
    """One poll: every held symbol is looked at, then the portfolio preset is evaluated once."""
    snapshot = dict(SNAP if snap is None else snap) | {"presets": list(presets), "rules": []}
    s.new_poll()
    out = []
    for symbol, price in prices.items():
        if symbol in skip:
            continue
        window = bars(when - timedelta(minutes=30), price) if symbol in stale else bars(when, price)
        prev = {"INTC": 40.0, "NVDA": 100.0}[symbol]
        out += s.alerts_from(symbol, True, when, snapshot, window, prev, BASE_STATS, [], daily=None)
    out += s.portfolio_alerts(when, snapshot)
    return presets_of(out)


def test_the_portfolio_preset_says_remind_then_urgent_once_a_level_a_day(make):
    s, drop = make(), preset("portfolio_drawdown")
    assert poll(s, {"INTC": 38.0, "NVDA": 95.0}, et(10, 0), presets=[drop]) == []                  # -2.5%
    out = poll(s, {"INTC": 36.0, "NVDA": 94.0}, et(10, 1), presets=[drop])                          # -4.6%
    assert len(out) == 1
    a = out[0]
    assert a["text"].splitlines()[0] == "【系统默认·提醒】你的组合今天跌 4.6%（-460 美元）。"
    assert a["text"].splitlines()[1] == "拖累最大：INTC -400 美元、NVDA -60 美元。"
    assert a["text"].splitlines()[2].startswith("规则：组合单日大跌（系统默认；")
    assert a["symbol"] == "*" and a["kind"] == "preset" and a["preset_key"] == "portfolio_drawdown"
    assert a["escalate"] is False and a["tier"] == 1 and a["price_move"] is False and a["held"] is True
    assert poll(s, {"INTC": 36.0, "NVDA": 94.0}, et(10, 2), presets=[drop]) == []                   # said today
    urgent = poll(s, {"INTC": 34.0, "NVDA": 90.0}, et(10, 3), presets=[drop])                       # -7.0%
    assert len(urgent) == 1 and urgent[0]["escalate"] is True and urgent[0]["tier"] == 2
    assert urgent[0]["text"].startswith("【系统默认·加急】你的组合今天跌 7.0%（-700 美元）。")
    assert poll(s, {"INTC": 30.0, "NVDA": 80.0}, et(10, 4), presets=[drop]) == []
    assert len(poll(s, {"INTC": 34.0, "NVDA": 90.0}, et(10, 0, day=4), presets=[drop])) == 1        # the next day: afresh (prev closes are 40 and 100 again)


def test_a_jump_straight_to_urgent_says_urgent_only(make):
    out = poll(make(), {"INTC": 34.0, "NVDA": 90.0}, et(10, 0), presets=[preset("portfolio_drawdown")])
    assert [a["escalate"] for a in out] == [True]


def test_the_portfolio_preset_waits_for_a_fresh_price_of_every_holding(make):
    drop = preset("portfolio_drawdown")
    prices = {"INTC": 34.0, "NVDA": 90.0}
    assert poll(make(), prices, et(10, 0), presets=[drop], skip=("NVDA",)) == []                    # NVDA failed this poll
    assert poll(make(), prices, et(10, 0), presets=[drop], stale=("NVDA",)) == []                   # NVDA's last bar is old
    assert len(poll(make(), prices, et(10, 0), presets=[drop])) == 1


def test_a_recent_split_makes_the_portfolio_measure_nothing(make):
    s = make()
    when = et(10, 0)
    s.new_poll()
    snap = dict(SNAP) | {"presets": [preset("portfolio_drawdown")], "rules": []}
    s.alerts_from("INTC", True, when, snap, bars(when, 34.0), 40.0, BASE_STATS, [{"date": "2026-11-03", "ratio": "2:1"}])
    s.alerts_from("NVDA", True, when, snap, bars(when, 90.0), 100.0, BASE_STATS, [])
    assert s.portfolio_alerts(when, snap) == []


def test_no_portfolio_preset_no_portfolio_alert(make):
    s = make()
    s.new_poll()
    assert s.portfolio_alerts(et(10, 0), SNAP) == []


def test_the_portfolio_preset_is_not_held_by_the_merge_interval_or_merged(make):
    s = make()
    sent = []

    class Collector:
        def __init__(self, store):
            self.store = store

        def raise_alert(self, snap, alert):
            sent.append(alert)
            return self.store.add_alert(alert["symbol"], alert.get("kind", ""), alert["text"], bool(alert.get("escalate")), 1.0)

        def deferred(self, alert_id):
            return False
    s.escalator, s._announce = Collector(s.store), lambda *a, **k: None
    s.store.set_kv("merge_mode", {"active": True, "last_flush": et(10, 0).timestamp()})
    out = poll(s, {"INTC": 34.0, "NVDA": 90.0}, et(10, 1), presets=[preset("portfolio_drawdown")])
    s.flush(out, SNAP, et(10, 1))
    assert [a["kind"] for a in sent] == ["preset"]


# --- night, payload, state ---------------------------------------------------------------------------------------------

def test_only_an_urgent_preset_rings_at_night():
    assert escalation.rings_at_night({"kind": "preset", "escalate": True, "held": True}) is True
    assert escalation.rings_at_night({"kind": "preset", "escalate": False, "held": True, "weight_pct": 50}) is False


def test_the_alert_payload_carries_the_preset_key(make):
    s = make()
    cand = presets_of(look(s, "INTC", 40.0, et(10, 0), presets=[preset("concentration")]))[0]
    alert_id = s.store.add_alert("INTC", "preset", cand["text"], False, 1.0)
    payload = s.alert_payload(alert_id, cand)
    assert payload["preset_key"] == "concentration" and payload["kind"] == "preset" and payload["rule_id"] == "preset:concentration"
    assert "owner_rule" not in payload


def test_the_morning_digest_line_of_a_preset_is_its_headline(make):
    cand = presets_of(look(make(), "INTC", 40.0, et(10, 0), presets=[preset("concentration")]))[0]
    assert cand["digest_text"] == "【系统默认·提醒】INTC 占你总资产 40.0%，超过 25%。"


# --- daily history: a year only for what needs it, fetched once ---------------------------------------------------------

def fake_chart_factory(calls):
    def fake_chart(symbol, interval, range_, **kw):
        calls.append((symbol, interval, range_))
        if interval == "1d" and range_ in ("3mo", "1y"):
            n = 60 if range_ == "3mo" else 250
            return {"bars": [{"ts": datetime(2026, 11, 2, 20, tzinfo=UTC) - timedelta(days=n - i), "close": 30.0 + i, "volume": 1000.0}
                             for i in range(n)], "prev_close": 40.0, "splits": []}
        return {"bars": bars(et(10, 0), 36.0), "prev_close": 40.0, "splits": []}
    return fake_chart


def test_the_daily_history_is_a_year_when_a_preset_needs_it_and_three_months_otherwise(make, monkeypatch):
    s, calls = make(), []
    monkeypatch.setattr(signals, "fetch_chart", fake_chart_factory(calls))
    monkeypatch.setattr(signals, "compute_baseline", lambda *a, **k: BASE_STATS)
    now = et(10, 0)
    snap = SNAP | {"presets": [preset("new_high_52w")], "rules": []}
    s.evaluate_symbol("INTC", True, now, snap)
    s.evaluate_symbol("INTC", True, now + timedelta(minutes=1), snap)
    assert calls.count(("INTC", "1d", "1y")) == 1 and ("INTC", "1d", "3mo") not in calls
    cached = s.store.get_kv("rules_daily:INTC")[0]
    assert len(cached["closes"]) == 250 and cached["asof"] == "2026-11-03"
    calls.clear()
    s2 = make()
    s2.evaluate_symbol("INTC", True, now, SNAP | {"presets": [preset("volume_surge")], "rules": []})
    assert ("INTC", "1d", "3mo") in calls and ("INTC", "1d", "1y") not in calls
    calls.clear()
    s2.evaluate_symbol("NVDA", True, now, SNAP | {"presets": [preset("concentration")], "rules": []})
    assert [c for c in calls if c[1] == "1d" and c[2] in ("3mo", "1y")] == []                          # concentration needs no history


def test_a_three_month_cache_is_refetched_when_a_year_is_needed(make, monkeypatch):
    s, calls = make(), []
    monkeypatch.setattr(signals, "fetch_chart", fake_chart_factory(calls))
    now = et(10, 0)
    assert len(s.rules_daily("INTC", now)["closes"]) == 60
    assert len(s.rules_daily("INTC", now, year=True)["closes"]) == 250
    assert len(s.rules_daily("INTC", now)["closes"]) == 250                                           # the longer one serves both


# --- settings: alert_settings, then the old keys, then env ---------------------------------------------------------------

def test_sensitivity_precedence(make, monkeypatch):
    s = make()
    both = {"alert_settings": {"sensitivity": "quiet"}, "alert_sensitivity": "sensitive"}
    monkeypatch.setenv("SENTINEL_SENSITIVITY", "standard")
    assert s._sensitivity(both) == "quiet"
    assert s._sensitivity({"alert_sensitivity": "sensitive"}) == "sensitive"
    assert s._sensitivity({}) == "standard"
    monkeypatch.setenv("SENTINEL_SENSITIVITY", "quiet")
    assert s._sensitivity({"alert_settings": {"short_moves": True}}) == "quiet"                       # no sensitivity there: env
    monkeypatch.delenv("SENTINEL_SENSITIVITY")
    assert s._sensitivity({}) == "standard"
    s.sensitivity = "sensitive"                                                                       # the replay harness override
    assert s._sensitivity(both) == "sensitive"


def test_short_moves_precedence(make, monkeypatch):
    s = make()
    monkeypatch.setenv("SENTINEL_SHORT_MOVES", "on")
    assert s._short_moves_on({"alert_settings": {"short_moves": False}, "short_moves": True}) is False
    assert s._short_moves_on({"alert_settings": {"short_moves": True}}) is True
    assert s._short_moves_on({"short_moves": False}) is False                                         # the old key beats env
    assert s._short_moves_on({}) is True                                                              # env
    monkeypatch.delenv("SENTINEL_SHORT_MOVES")
    assert s._short_moves_on({}) is False and s._short_moves_on({"short_moves": True}) is True
    s.short_moves = False
    assert s._short_moves_on({"alert_settings": {"short_moves": True}}) is False


def test_alert_settings_change_the_tier_lines(make):
    quiet = SNAP | {"alert_settings": {"sensitivity": "quiet", "short_moves": False}}
    sensitive = SNAP | {"alert_settings": {"sensitivity": "sensitive", "short_moves": False}}
    assert look(make(), "INTC", 33.6, et(10, 0), snap=quiet) == []                                    # 2.13 sigma < 2.5
    assert len(look(make(), "INTC", 35.0, et(10, 0), snap=sensitive)) == 1                            # 1.67 sigma >= 1.5


# --- check_signals runs the portfolio preset after every symbol ----------------------------------------------------------

def test_check_signals_evaluates_the_portfolio_after_the_symbols(make, tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    snap = SNAP | {"research_queue": [], "presets": [preset("portfolio_drawdown")]}
    cfg.write_text(json.dumps(snap), encoding="utf-8")
    s = make()
    s.config = signals.SnapshotConfig(cfg)
    order = []
    monkeypatch.setattr(signals, "in_trading_session", lambda n: True)
    monkeypatch.setattr(s, "fetch_market", lambda n: None)

    def fake_eval(symbol, held, when, snapshot, rules_only=False):
        order.append(symbol)
        price = {"INTC": 34.0, "NVDA": 90.0}[symbol]
        return s.alerts_from(symbol, held, when, snapshot, bars(when, price), {"INTC": 40.0, "NVDA": 100.0}[symbol],
                             BASE_STATS, [], daily=None)
    monkeypatch.setattr(s, "evaluate_symbol", fake_eval)
    sent = []
    monkeypatch.setattr(s, "flush", lambda collected, snapshot, when: sent.extend(collected))
    s.check_signals()
    assert order == ["INTC", "NVDA"]
    assert [a["kind"] for a in sent if a["kind"] == "preset"] == ["preset"] and sent[-1]["symbol"] == "*"


# --- replay honours presets and alert_settings ----------------------------------------------------------------------------

def utc(day, hour, minute):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET).astimezone(UTC)


def session(day, price):
    out, ts = [], utc(day, 4, 0)
    while ts < utc(day, 20, 0):
        out.append({"ts": ts, "close": price, "volume": 1000, "open": None})
        ts += timedelta(minutes=5)
    return out


def replay_data(price):
    daily = lambda close: [{"ts": utc(2, 14, 30), "close": close, "volume": 1}]                       # noqa: E731
    return {"bars5": {"INTC": session(3, price), "NVDA": session(3, price * 2.5), "SPY": session(3, 100.0)},
            "daily": {"INTC": daily(40.0), "NVDA": daily(100.0), "SPY": daily(100.0)}, "errors": {}}


def test_replay_runs_the_presets_and_the_portfolio_and_counts_them(tmp_path):
    snap = SNAP | {"research_queue": [], "presets": [preset("concentration"), preset("portfolio_drawdown")]}
    result = replay.run_replay(replay_data(34.0), snap, datetime(2026, 11, 3).date(), datetime(2026, 11, 3).date(), workdir=tmp_path)
    kinds = [(a["kind"], a.get("preset_key")) for a in result["alerts"] if a["kind"] == "preset"]
    assert ("preset", "concentration") in kinds and ("preset", "portfolio_drawdown") in kinds
    counts = replay.counts(result)
    assert counts["per_preset"]["portfolio_drawdown"] == 1 and counts["per_preset"]["concentration"] >= 1
    out = tmp_path / "out"
    out.mkdir()
    replay.write_alerts_csv(result, out / "a.csv")
    replay.write_summary(result, out / "s.md", title="t", args_line="x", notes=[])
    assert "portfolio_drawdown" in (out / "a.csv").read_text(encoding="utf-8")
    assert "| portfolio_drawdown | 1 |" in (out / "s.md").read_text(encoding="utf-8")


def test_replay_reads_the_snapshots_alert_settings(tmp_path):
    base = SNAP | {"research_queue": []}
    day = datetime(2026, 11, 3).date()
    loud = replay.run_replay(replay_data(38.2), base | {"alert_settings": {"sensitivity": "sensitive", "short_moves": False}}, day, day, workdir=tmp_path / "a")
    calm = replay.run_replay(replay_data(38.2), base | {"alert_settings": {"sensitivity": "quiet", "short_moves": False}}, day, day, workdir=tmp_path / "b")
    assert [a["symbol"] for a in loud["alerts"] if a["symbol"] == "INTC"] == ["INTC"]
    assert [a for a in calm["alerts"] if a["symbol"] == "INTC"] == []
    forced = replay.run_replay(replay_data(38.2), base | {"alert_settings": {"sensitivity": "quiet"}}, day, day, sensitivity="standard", workdir=tmp_path / "c")
    assert [a["symbol"] for a in forced["alerts"] if a["symbol"] == "INTC"] != []                      # an explicit argument still wins
