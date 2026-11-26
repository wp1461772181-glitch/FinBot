"""5b-1 Half B: the owner's rules through Sentinel.alerts_from / flush / check_signals on built bars (no network)."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sentinel import escalation, replay, rules, signals
from sentinel.main import Sentinel
from sentinel.store import Store

ET = ZoneInfo("America/New_York")
PREV = 40.0
INTC = {"daily_sigma": 0.075, "bucket_sigma": {"pre": 0.002, "mid": 0.003}, "avg_vol5": {"pre": 100.0, "mid": 1000.0}}
CONTRACT = json.loads((Path(__file__).parent / "fixtures" / "watch_rules_contract.json").read_text(encoding="utf-8"))
POSITION = {"symbol": "INTC", "shares": 100.0, "avg_cost": 50.0, "market_value": 4000.0}
BASE = {"positions": [POSITION], "total_assets": 100000.0}


def et(hour, minute, day=3):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET)


def bars(end, price, n=15, volume=100, opened=None):
    start = end - timedelta(minutes=n - 1)
    return [{"ts": start + timedelta(minutes=i), "close": price, "volume": volume,
             "open": opened if (opened is not None and i == 0) else price} for i in range(n)]


def make_rule(metric="day_change", direction="either", levels=((10, "remind"), (20, "urgent")), **extra):
    rule = {"id": "r-" + metric, "symbol": "INTC", "metric": metric, "direction": direction, "window_days": None,
            "repeat": "daily", "expires_on": None, "created_on": "2026-11-02",
            "text": "英特尔相对昨收涨或跌达到 10%：提醒；达到 20%：加急。每天每档一次。",
            "levels": [{"threshold": t, "level": n} for t, n in levels]}
    return rule | extra


@pytest.fixture(params=["tiers", "anchor"])
def make(request, tmp_path, monkeypatch):
    """A sentinel factory; every test runs under both default policies (rules do not depend on the policy)."""
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", request.param)
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)
    monkeypatch.delenv("SENTINEL_SHORT_MOVES", raising=False)

    def build():
        s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
        s._market = None
        return s
    return build


def look(s, price, when, *, symbol="INTC", held=True, snap=None, rules_list=(), window=None, prev=PREV, daily=None,
         rules_only=False, splits=None):
    snapshot = dict(BASE if snap is None else snap)
    snapshot["rules"] = list(rules_list)
    series = window if window is not None else bars(when, price)
    return s.alerts_from(symbol, held, when, snapshot, series, prev, INTC, splits or [], daily=daily, rules_only=rules_only)


def only_rules(out):
    return [a for a in out if a["kind"] == "rule"]


# --- day_change: levels, once per day, remind -> urgent ----------------------------------------------------------------

def test_a_remind_message_names_the_move_and_quotes_the_rule(make):
    s, rule = make(), make_rule()
    out = only_rules(look(s, 35.84, et(10, 0), rules_list=[rule]))
    assert len(out) == 1
    a = out[0]
    assert a["text"].splitlines()[0] == "【你的规则·提醒】INTC 较昨收跌 10.4%，现价 35.84。"
    assert a["text"].splitlines()[1] == "按你 11-02 定的规则：" + rule["text"]
    assert a["escalate"] is False and a["price_move"] is False and a["tier"] == 1 and a["rule_id"] == rule["id"]
    assert a["held"] is True and a["symbol"] == "INTC" and a["direction"] == "down"


def test_each_level_is_said_once_per_day_and_urgent_rises_from_remind(make):
    s, rule = make(), make_rule()
    assert len(only_rules(look(s, 35.84, et(10, 0), rules_list=[rule]))) == 1
    assert only_rules(look(s, 35.0, et(10, 1), rules_list=[rule])) == []                     # same level, same day
    urgent = only_rules(look(s, 31.0, et(10, 2), rules_list=[rule]))                         # -22.5%
    assert len(urgent) == 1 and urgent[0]["escalate"] is True and urgent[0]["tier"] == 2
    assert urgent[0]["text"].startswith("【你的规则·加急】INTC 较昨收跌 22.5%，现价 31.00。")
    assert only_rules(look(s, 30.0, et(10, 3), rules_list=[rule])) == []
    assert only_rules(look(s, 35.0, et(10, 4), rules_list=[rule])) == []                     # back in the remind zone: said
    # the next New York date starts afresh (prev close is the same 40 in this build)
    assert len(only_rules(look(s, 35.0, et(10, 0, day=4), rules_list=[rule]))) == 1


def test_a_jump_straight_to_urgent_says_urgent_only_and_settles_remind(make):
    s, rule = make(), make_rule()
    out = only_rules(look(s, 30.0, et(10, 0), rules_list=[rule]))
    assert [a["escalate"] for a in out] == [True]
    assert only_rules(look(s, 35.0, et(10, 5), rules_list=[rule])) == []


def test_urgent_escalates_in_either_direction_and_on_a_symbol_not_held(make):
    s, rule = make(), make_rule()
    up = only_rules(look(s, 50.0, et(10, 0), rules_list=[rule]))                             # +25%
    assert up[0]["escalate"] is True and up[0]["direction"] == "up" and "较昨收涨 25.0%" in up[0]["text"]
    s2, rule2 = make(), make_rule(symbol="NVDA")
    out = only_rules(look(s2, 150.0, et(10, 0), symbol="NVDA", held=False, snap={"positions": []}, prev=100.0,
                          rules_list=[rule2]))
    assert out[0]["escalate"] is True and out[0]["held"] is False


def test_direction_and_threshold_gate_the_rule(make):
    s, rule = make(), make_rule(direction="up", levels=((10, "remind"),))
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[rule])) == []                     # a fall: not this rule
    assert len(only_rules(look(s, 44.0, et(10, 1), rules_list=[rule]))) == 1                 # exactly +10%


def test_once_fires_once_ever_and_then_the_rule_is_finished(make):
    s, rule = make(), make_rule(repeat="once", levels=((10, "remind"),))
    assert len(only_rules(look(s, 35.0, et(10, 0), rules_list=[rule]))) == 1
    assert only_rules(look(s, 30.0, et(10, 5), rules_list=[rule])) == []
    assert only_rules(look(s, 30.0, et(10, 0, day=4), rules_list=[rule])) == []              # never again
    s2 = make()                                                                               # same store file: a restart
    assert only_rules(look(s2, 30.0, et(10, 1, day=4), rules_list=[rule])) == []


def test_a_once_rule_with_two_levels_finishes_after_its_highest(make):
    s, rule = make(), make_rule(repeat="once")
    assert len(only_rules(look(s, 35.0, et(10, 0), rules_list=[rule]))) == 1                 # remind
    assert len(only_rules(look(s, 30.0, et(10, 1, day=4), rules_list=[rule]))) == 1          # urgent, the next day
    assert only_rules(look(s, 30.0, et(10, 2, day=5), rules_list=[rule])) == []


def test_an_expired_rule_is_not_checked(make):
    s = make()
    rule = make_rule(expires_on="2026-11-02")
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[rule])) == []
    assert len(only_rules(look(s, 30.0, et(10, 0), rules_list=[make_rule(expires_on="2026-11-03")]))) == 1


def test_a_disabled_or_malformed_rule_is_ignored(make):
    s = make()
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[make_rule() | {"enabled": False}])) == []
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[make_rule() | {"metric": "nonsense"}])) == []


def test_an_edited_rule_starts_afresh(make):
    s = make()
    assert len(only_rules(look(s, 35.0, et(10, 0), rules_list=[make_rule()]))) == 1
    edited = make_rule(levels=((5, "remind"), (20, "urgent")))                               # same id, new threshold
    assert len(only_rules(look(s, 35.0, et(10, 1), rules_list=[edited]))) == 1


def test_a_stale_price_or_a_split_never_fires(make):
    s, rule = make(), make_rule()
    old = bars(et(9, 0), 30.0)
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[rule], window=old)) == []
    split = [{"date": "2026-11-03", "ratio": "2:1"}]
    assert only_rules(look(s, 30.0, et(10, 0), rules_list=[rule], splits=split)) == []


# --- the hard guarantees ---------------------------------------------------------------------------------------------

def test_a_day_change_rule_replaces_the_default_tier_pushes_of_its_symbol_only(make):
    s = make()
    if s._policy() != "tiers":
        pytest.skip("the class override is a tiers-policy matter")
    rule = make_rule(levels=((30, "remind"),))                                                # never reached by -16%
    mine = look(s, 33.6, et(10, 0), rules_list=[rule])                                        # -16%: 2.1 sigma, tier 1 by default
    assert mine == []
    rows = s.store.alerts_where("kind = 'record'")
    assert len(rows) == 1 and rows[0]["deferred"] == 1 and rows[0]["symbol"] == "INTC"       # the digest line stays
    other = look(s, 33.6, et(10, 0), symbol="NVDA", rules_list=[rule], snap={"positions": [{"symbol": "NVDA", "shares": 10.0}], "total_assets": 1e5})
    assert [a["tier"] for a in other] == [1]                                                 # NVDA keeps its defaults


def test_without_a_day_change_rule_the_defaults_still_push(make):
    s = make()
    if s._policy() != "tiers":
        pytest.skip("tiers only")
    rule = make_rule("price", "above", ((1000, "remind"),))                                   # another metric: no override
    out = look(s, 33.6, et(10, 0), rules_list=[rule])
    assert [a["tier"] for a in out if a["kind"] != "rule"] == [1]


def test_the_stop_price_still_fires_with_a_day_change_rule(make):
    s = make()
    if s._policy() != "tiers":
        pytest.skip("tiers only")
    snap = BASE | {"plans": [{"symbol": "INTC", "stop_price": 34.0}]}
    rule = make_rule(levels=((30, "remind"),))
    out = look(s, 35.0, et(10, 0), rules_list=[rule], snap=snap)                              # arms the level from the prev close
    out += look(s, 33.0, et(10, 1), rules_list=[rule], snap=snap)
    stop = [a for a in out if a["kind"] == "plan_stop"]
    assert len(stop) == 1 and stop[0]["escalate"] is True


def test_a_finished_once_day_change_rule_gives_the_defaults_back_on_the_next_day(make):
    s = make()
    if s._policy() != "tiers":
        pytest.skip("tiers only")
    rule = make_rule(repeat="once", levels=((10, "remind"),))
    assert len(only_rules(look(s, 33.6, et(10, 0), rules_list=[rule]))) == 1
    assert [a for a in look(s, 33.6, et(10, 30), rules_list=[rule]) if a["kind"] != "rule"] == []   # same day: still replaced
    nxt = look(s, 33.6, et(10, 0, day=4), rules_list=[rule])
    assert [a["tier"] for a in nxt if a["kind"] != "rule"] == [1]


def test_a_rule_error_does_not_cost_the_default_alerts(make, monkeypatch):
    s = make()
    monkeypatch.setattr(rules, "measure", lambda *a, **k: 1 / 0)
    out = look(s, 33.6, et(10, 0), rules_list=[make_rule()])
    assert only_rules(out) == []
    if s._policy() == "tiers":
        assert len(out) == 0 or all(a["kind"] != "rule" for a in out)


def test_rules_only_symbols_get_no_default_alerts(make):
    s = make()
    snap = {"positions": [], "total_assets": 1e5}
    rule = make_rule(symbol="NVDA", metric="price", direction="above", levels=((120, "remind"),))
    out = look(s, 136.0, et(10, 0), symbol="NVDA", held=False, snap=snap, prev=100.0, rules_list=[rule], rules_only=True)
    assert [a["kind"] for a in out] == ["rule"]                                               # +36% would be a default push otherwise
    plain = look(make(), 136.0, et(10, 0), symbol="NVDA", held=False, snap=snap, prev=100.0, rules_list=[], rules_only=False)
    assert plain and plain[0]["kind"] != "rule"


# --- every metric ----------------------------------------------------------------------------------------------------

def test_open_change_uses_the_regular_session_open(make):
    s = make()
    rule = make_rule("open_change", "down", ((3, "remind"),))
    window = [{"ts": et(9, 29), "close": 41.0, "volume": 5, "open": 41.0},
              {"ts": et(9, 30), "close": 40.0, "volume": 5, "open": 40.0}] + bars(et(10, 0), 38.5, n=5)
    out = only_rules(look(s, 38.5, et(10, 0), rules_list=[rule], window=window))
    assert len(out) == 1 and out[0]["text"].startswith("【你的规则·提醒】INTC 较今日开盘价 40.00 跌 3.8%，现价 38.50。")
    # before the open there is no regular-session open: nothing to measure
    assert only_rules(look(make(), 38.5, et(8, 0), rules_list=[rule], window=bars(et(8, 0), 38.5))) == []


def test_cost_change_needs_a_holding_and_its_cost(make):
    s = make()
    rule = make_rule("cost_change", "down", ((15, "urgent"),), repeat="once")
    out = only_rules(look(s, 40.0, et(10, 0), rules_list=[rule]))                             # cost 50: -20%
    assert out[0]["text"].startswith("【你的规则·加急】INTC 较你的持仓成本 50.00 跌 20.0%，现价 40.00。")
    none = only_rules(look(make(), 40.0, et(10, 0), rules_list=[rule], snap={"positions": [], "total_assets": 1e5}))
    assert none == []


def test_n_day_change_reads_the_daily_closes(make):
    s = make()
    rule = make_rule("n_day_change", "up", ((10, "remind"),), window_days=5)
    daily = {"closes": [30.0, 32.0, 34.0, 35.0, 40.0], "avg_volume": None}
    out = only_rules(look(s, 36.0, et(10, 0), rules_list=[rule], daily=daily))                # +20% on 5 days ago (30)
    assert out[0]["text"].startswith("【你的规则·提醒】INTC 较 5 个交易日前的收盘 30.00 涨 20.0%，现价 36.00。")
    assert only_rules(look(make(), 36.0, et(10, 0), rules_list=[rule], daily=None)) == []     # no history: silent
    assert only_rules(look(make(), 36.0, et(10, 0), rules_list=[rule], daily={"closes": [30.0], "avg_volume": None})) == []


def test_price_above_and_below(make):
    s = make()
    above = make_rule("price", "above", ((38, "remind"),), repeat="once", id="a")
    below = make_rule("price", "below", ((36, "remind"), (30, "urgent")), id="b")
    out = only_rules(look(s, 39.0, et(10, 0), rules_list=[above, below]))
    assert [a["rule_id"] for a in out] == ["a"] and "涨到 39.00，到了你设的 38 美元" in out[0]["text"]
    out = only_rules(look(s, 29.0, et(10, 1), rules_list=[above, below]))
    assert [(a["rule_id"], a["escalate"]) for a in out] == [("b", True)] and "跌到 29.00，到了你设的 30 美元" in out[0]["text"]


def test_volume_ratio_measures_against_the_time_of_day(make):
    s = make()
    rule = make_rule("volume_ratio", "above", ((2, "remind"), (4, "urgent")))
    daily = {"closes": [40.0] * 20, "avg_volume": 39000.0}
    window = [{"ts": et(9, 30) + timedelta(minutes=i), "close": 40.0, "volume": 1000.0, "open": 40.0} for i in range(61)]
    # 10:30 = 60 minutes in (fraction 60/390); 61 bars * 1000 = 61000 against 39000 * 60/390 = 6000 -> 10.2x
    out = only_rules(look(s, 40.0, et(10, 30), rules_list=[rule], window=window, daily=daily))
    assert len(out) == 1 and out[0]["escalate"] is True
    assert out[0]["text"].startswith("【你的规则·加急】INTC 今日成交量已是同一时段正常水平的 10.2 倍，现价 40.00。")
    # before 10:00 it is not measured, whatever the volume
    early = [{"ts": et(9, 30) + timedelta(minutes=i), "close": 40.0, "volume": 1e6, "open": 40.0} for i in range(10)]
    assert only_rules(look(make(), 40.0, et(9, 39), rules_list=[rule], window=early, daily=daily)) == []
    assert only_rules(look(make(), 40.0, et(10, 30), rules_list=[rule], window=window, daily=None)) == []


def test_position_pnl_and_weight(make):
    s = make()
    pnl = make_rule("position_pnl", "down", ((300, "remind"),), id="p")
    weight = make_rule("position_weight", "below", ((3.6, "remind"),), id="w")
    out = {a["rule_id"]: a for a in only_rules(look(s, 35.0, et(10, 0), rules_list=[pnl, weight]))}
    assert out["p"]["text"].startswith("【你的规则·提醒】INTC 持仓今天较昨收亏 $500，现价 35.00。")
    # 100 * 35 = 3500 of (100000 - 4000 + 3500) = 99500 -> 3.5%
    assert out["w"]["text"].startswith("【你的规则·提醒】INTC 持仓占总资产 3.5%，现价 35.00。")
    assert only_rules(look(make(), 35.0, et(10, 0), rules_list=[pnl], snap={"positions": [], "total_assets": 1e5})) == []


def test_no_total_assets_means_the_weight_rule_is_silent(make):
    s = make()
    rule = make_rule("position_weight", "above", ((0.0001, "remind"),))
    assert only_rules(look(s, 35.0, et(10, 0), rules_list=[rule], snap={"positions": [POSITION]})) == []


def test_every_contract_rule_is_accepted_end_to_end(make):
    s = make()
    snap = {"positions": [{"symbol": sym, "shares": 10.0, "avg_cost": 30.0, "market_value": 300.0}
                          for sym in ("INTC", "NVDA", "TSLA", "AAPL", "AMD")], "total_assets": 5000.0}
    daily = {"closes": [30.0] * 30, "avg_volume": 1000.0}
    for symbol in ("INTC", "NVDA", "TSLA", "AAPL", "AMD"):
        window = [{"ts": et(9, 30) + timedelta(minutes=i), "close": 31.0, "volume": 100.0, "open": 30.0} for i in range(66)]
        look(s, 31.0, et(10, 35), symbol=symbol, snap=snap, prev=30.0, rules_list=CONTRACT, window=window, daily=daily)
    assert all(rules.valid(r) for r in CONTRACT)


# --- delivery: rule pushes stand alone ---------------------------------------------------------------------------------

class Collector:
    def __init__(self, store):
        self.store, self.sent = store, []

    def raise_alert(self, snap, alert):
        self.sent.append(alert)
        return self.store.add_alert(alert["symbol"], alert.get("kind", ""), alert["text"], bool(alert.get("escalate")), 1.0)

    def deferred(self, alert_id):
        return False


def rule_candidate(symbol, urgent=False):
    return {"symbol": symbol, "kind": "rule", "direction": "down", "held": True, "text": f"【你的规则·提醒】{symbol}",
            "escalate": urgent, "weight_pct": None, "price_move": False, "trigger": "", "event_date": None, "price": 10.0,
            "prev_close": 11.0, "earnings_unacked": False, "after_send": lambda d, i: None, "rollback": lambda: None,
            "tier": 2 if urgent else 1, "rule_id": "r-" + symbol}


def move_candidate(symbol):
    return {"symbol": symbol, "kind": "daily", "direction": "down", "held": True, "text": f"【值得知道·盘中】{symbol}",
            "escalate": False, "weight_pct": None, "price_move": True, "trigger": "", "event_date": None, "price": 10.0,
            "prev_close": 11.0, "earnings_unacked": False, "after_send": lambda d, i: None, "rollback": lambda: None,
            "tier": 1, "r": -0.1, "sigma_mult": 2.0}


def test_rule_pushes_are_raised_one_by_one_beside_a_merged_burst_and_inside_the_merge_interval(make):
    s = make()
    s.escalator = Collector(s.store)
    s._announce = lambda *a, **k: None
    now = et(10, 0)
    s.flush([rule_candidate("INTC"), move_candidate("A"), move_candidate("B"), move_candidate("C")], {}, now)
    kinds = [a["kind"] for a in s.escalator.sent]
    assert kinds.count("rule") == 1 and kinds.count("merged") == 1 and kinds[0] == "rule"
    # inside the merge interval minor moves are held back, a rule push is not
    s.escalator.sent.clear()
    s.flush([rule_candidate("INTC"), rule_candidate("NVDA", urgent=True), move_candidate("A")], {}, now + timedelta(minutes=1))
    assert [a["symbol"] for a in s.escalator.sent] == ["INTC", "NVDA"]


def test_the_alert_payload_carries_the_rule_id(make):
    s = make()
    s.escalator = Collector(s.store)
    cand = rule_candidate("INTC")
    alert_id = s.escalator.raise_alert({}, cand)
    payload = s.alert_payload(alert_id, cand)
    assert payload["rule_id"] == "r-INTC" and payload["kind"] == "rule" and payload["tier"] == 1


def test_a_rule_push_is_not_held_by_min_gap_after_a_default_push(make):
    s = make()
    out = look(s, 33.6, et(10, 0), rules_list=[make_rule(levels=((10, "remind"),))])
    assert len(only_rules(out)) == 1                                                          # alongside whatever the default said


# --- night -------------------------------------------------------------------------------------------------------------

def test_only_an_urgent_rule_rings_at_night():
    assert escalation.rings_at_night({"kind": "rule", "escalate": True, "held": False}) is True
    assert escalation.rings_at_night({"kind": "rule", "escalate": False, "held": True, "weight_pct": 50}) is False


# --- check_signals polls the symbols rules name ----------------------------------------------------------------------

def test_check_signals_polls_a_rule_symbol_that_is_neither_held_nor_queued(make, tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    snap = {"positions": [{"symbol": "INTC", "shares": 10.0}], "research_queue": ["AMD"], "total_assets": 1e5,
            "rules": [make_rule(symbol="NVDA", metric="price", direction="above", levels=((120, "remind"),), id="n"),
                      make_rule(symbol="AMD", metric="price", direction="above", levels=((120, "remind"),), id="q"),
                      make_rule(symbol="TSLA", metric="price", direction="above", levels=((1, "remind"),), id="x",
                                expires_on="2020-01-01")]}
    cfg.write_text(json.dumps(snap), encoding="utf-8")
    s = make()
    s.config = signals.SnapshotConfig(cfg)
    polled = []
    monkeypatch.setattr(signals, "in_trading_session", lambda now: True)
    monkeypatch.setattr(s, "fetch_market", lambda now: None)
    monkeypatch.setattr(s, "evaluate_symbol", lambda symbol, held, now, snap, rules_only=False: polled.append((symbol, held, rules_only)) or [])
    s.check_signals()
    assert polled == [("INTC", True, False), ("AMD", False, False), ("NVDA", False, True)]


def test_evaluate_symbol_fetches_daily_history_once_a_day_only_for_rules_that_need_it(make, monkeypatch):
    s = make()
    calls = []

    def fake_chart(symbol, interval, range_, **kw):
        calls.append((symbol, interval, range_))
        if interval == "1d" and range_ == "3mo":
            return {"bars": [{"ts": datetime(2026, 10, 1, 20, tzinfo=UTC) + timedelta(days=i), "close": 30.0 + i,
                              "volume": 1000.0} for i in range(30)], "prev_close": 40.0, "splits": []}
        return {"bars": bars(et(10, 0), 36.0), "prev_close": 40.0, "splits": []}
    monkeypatch.setattr(signals, "fetch_chart", fake_chart)
    monkeypatch.setattr(signals, "compute_baseline", lambda *a, **k: INTC)
    n_rule = make_rule("n_day_change", "up", ((10, "remind"),), window_days=3)
    snap = BASE | {"rules": [n_rule]}
    now = et(10, 0)
    s.evaluate_symbol("INTC", True, now, snap)
    s.evaluate_symbol("INTC", True, now + timedelta(minutes=1), snap)
    assert calls.count(("INTC", "1d", "3mo")) == 1
    cached = s.store.get_kv("rules_daily:INTC")[0]
    assert cached["asof"] == "2026-11-03" and cached["avg_volume"] == 1000.0 and len(cached["closes"]) == 30
    calls.clear()
    s.evaluate_symbol("INTC", True, now, BASE | {"rules": [make_rule()]})                    # day_change needs no history
    assert ("INTC", "1d", "3mo") not in calls


def test_a_failed_daily_fetch_is_not_retried_every_minute(make, monkeypatch):
    s = make()
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise OSError("no route")
    monkeypatch.setattr(signals, "fetch_chart", boom)
    assert s.rules_daily("INTC", et(10, 0)) is None
    assert s.rules_daily("INTC", et(10, 1)) is None
    assert len(calls) == 1


# --- replay honours the snapshot's rules -------------------------------------------------------------------------------

def test_replay_runs_the_owner_rules(tmp_path):
    def utc(day, hour, minute):
        return datetime(2026, 11, day, hour, minute, tzinfo=ET).astimezone(UTC)

    def session(price_at):
        out, ts = [], utc(3, 4, 0)
        while ts < utc(3, 20, 0):
            local = ts.astimezone(ET)
            out.append({"ts": ts, "close": price_at(local.hour, local.minute), "volume": 1000, "open": None})
            ts += timedelta(minutes=5)
        return out
    drop = lambda h, m: 40.0 if (h, m) < (10, 0) else 35.0                                    # noqa: E731
    flat = lambda h, m: 100.0                                                                 # noqa: E731
    daily = lambda c: [{"ts": utc(2, 14, 30), "close": c, "volume": 1}]                       # noqa: E731
    data = {"bars5": {"INTC": session(drop), "NVDA": session(flat), "SPY": session(flat)},
            "daily": {"INTC": daily(40.0), "NVDA": daily(100.0), "SPY": daily(100.0)}, "errors": {}}
    snap = {"positions": [], "research_queue": ["NVDA"], "total_assets": 1e5,
            "rules": [make_rule(symbol="INTC", levels=((10, "remind"),))]}
    result = replay.run_replay(data, snap, datetime(2026, 11, 3).date(), datetime(2026, 11, 3).date(), workdir=tmp_path)
    kinds = [(a["symbol"], a["kind"]) for a in result["alerts"]]
    assert ("INTC", "rule") in kinds and kinds.count(("INTC", "rule")) == 1
    assert all(sym != "INTC" or kind == "rule" for sym, kind in kinds)                        # INTC is only named by the rule


def test_at_night_a_reminder_waits_for_the_digest_and_an_urgent_rule_is_sent(tmp_path):
    class Channels:
        def __init__(self):
            self.sent, self.rang = [], []

        def telegram_alert(self, config, text, alert_id):
            self.sent.append(text)
            return 7

        def pushover_emergency(self, config, text):
            self.rang.append(text)
            return "receipt"

    channels, store = Channels(), Store(tmp_path / "n.db")
    night = datetime(2026, 11, 3, 3, 0, tzinfo=escalation.BEIJING).timestamp()
    esc = escalation.Escalator(store, channels, clock=lambda: night)
    snap = {"pushover": {"user_key": "u", "app_token": "t"}, "telegram": {"chat_id": 1}}
    esc.raise_alert(snap, rule_candidate("INTC"))
    assert channels.sent == [] and store.alerts_where("deferred = 1")[0]["kind"] == "rule"
    esc.raise_alert(snap, rule_candidate("NVDA", urgent=True))
    assert len(channels.sent) == 1 and len(channels.rang) == 1


# --- state-like metrics fire on the edge -------------------------------------------------------------------------------

def below_50(**extra):
    return make_rule("price", "below", ((50, "remind"),), **extra)


def test_price_below_that_stays_below_for_three_days_says_one_push(make):
    s, rule = make(), below_50()
    assert len(only_rules(look(s, 48.0, et(10, 0, day=3), rules_list=[rule]))) == 1     # first look, condition holds
    assert only_rules(look(s, 47.0, et(10, 30, day=3), rules_list=[rule])) == []
    assert only_rules(look(s, 46.0, et(10, 0, day=4), rules_list=[rule])) == []         # a new day, same stretch
    assert only_rules(look(s, 45.0, et(10, 0, day=5), rules_list=[rule])) == []


def test_it_says_again_once_the_condition_was_seen_false(make):
    s, rule = make(), below_50()
    assert len(only_rules(look(s, 48.0, et(10, 0, day=3), rules_list=[rule]))) == 1
    assert only_rules(look(s, 47.0, et(10, 0, day=4), rules_list=[rule])) == []
    assert only_rules(look(s, 52.0, et(10, 0, day=5), rules_list=[rule])) == []         # above: re-armed, nothing to say
    assert len(only_rules(look(s, 49.0, et(11, 0, day=5), rules_list=[rule]))) == 1     # below again, same day as the re-arm


def test_still_at_most_once_per_day_after_a_re_arm(make):
    s, rule = make(), below_50()
    assert len(only_rules(look(s, 48.0, et(10, 0), rules_list=[rule]))) == 1
    assert only_rules(look(s, 52.0, et(10, 5), rules_list=[rule])) == []
    assert only_rules(look(s, 48.0, et(10, 10), rules_list=[rule])) == []               # re-armed, but said today already
    assert len(only_rules(look(s, 48.0, et(10, 0, day=4), rules_list=[rule]))) == 1     # next day it may say again


def test_a_restart_in_the_middle_of_the_condition_does_not_repeat(make):
    s, rule = make(), below_50()
    assert len(only_rules(look(s, 48.0, et(10, 0, day=3), rules_list=[rule]))) == 1
    restarted = make()                                                                  # same store file
    assert only_rules(look(restarted, 47.0, et(10, 0, day=4), rules_list=[rule])) == []


def test_a_missing_measurement_neither_re_arms_nor_fires(make):
    s = make()
    rule = make_rule("n_day_change", "up", ((10, "remind"),), window_days=3)
    daily = {"closes": [30.0, 31.0, 32.0], "avg_volume": None}
    assert len(only_rules(look(s, 36.0, et(10, 0, day=3), rules_list=[rule], daily=daily))) == 1
    assert only_rules(look(s, 36.0, et(10, 0, day=4), rules_list=[rule], daily=None)) == []     # no history today
    assert only_rules(look(s, 36.0, et(10, 5, day=4), rules_list=[rule], daily=daily)) == []    # still the same stretch


def test_a_stronger_level_is_armed_on_its_own(make):
    s = make()
    rule = make_rule("price", "below", ((50, "remind"), (40, "urgent")))
    assert [a["escalate"] for a in only_rules(look(s, 48.0, et(10, 0), rules_list=[rule]))] == [False]
    assert [a["escalate"] for a in only_rules(look(s, 39.0, et(10, 5), rules_list=[rule]))] == [True]


def test_a_change_metric_keeps_plain_once_per_day(make):
    s, rule = make(), make_rule("position_pnl", "down", ((300, "remind"),))
    assert len(only_rules(look(s, 35.0, et(10, 0, day=3), rules_list=[rule]))) == 1
    assert only_rules(look(s, 35.0, et(10, 30, day=3), rules_list=[rule])) == []
    assert len(only_rules(look(s, 35.0, et(10, 0, day=4), rules_list=[rule]))) == 1     # no edge needed: a new day
