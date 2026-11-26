"""5a T3: the tiers policy through Sentinel.alerts_from / flush on built bars (no network)."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sentinel import signals
from sentinel.main import Sentinel
from sentinel.store import Store

ET = ZoneInfo("America/New_York")
PREV = 40.0
INTC = {"daily_sigma": 0.075, "bucket_sigma": {"pre": 0.002, "mid": 0.003}, "avg_vol5": {"pre": 100.0, "mid": 1000.0}}
NVDA = {"daily_sigma": 0.04, "bucket_sigma": {}, "avg_vol5": {}}
BIG = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 100000.0}


def et(hour, minute, day=3):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET)


def bars(end, price, n=15, volume=100):
    start = end - timedelta(minutes=n - 1)
    return [{"ts": start + timedelta(minutes=i), "close": price, "volume": volume} for i in range(n)]


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", "tiers")
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)
    monkeypatch.delenv("SENTINEL_SHORT_MOVES", raising=False)

    def build():
        s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
        s._market = None
        return s
    return build


def look(s, symbol, price, when, *, held=True, snap=None, prev=PREV, base=INTC, window=None):
    series = window if window is not None else bars(when, price)
    return s.alerts_from(symbol, held, when, BIG if snap is None else snap, series, prev, base, [])


def test_a_one_percent_five_minute_drop_before_the_open_says_nothing(make):
    s = make()
    flat = bars(et(5, 0), 40.0, n=10)
    drop = flat + [{"ts": et(5, 0) + timedelta(minutes=1), "close": 39.6, "volume": 100}]
    assert look(s, "INTC", 39.6, et(5, 1), window=drop) == []
    assert look(s, "INTC", 39.6, et(5, 2)) == []
    # and a tier-0 move over 1 sigma is a digest line, not a push
    assert look(s, "INTC", 37.0, et(5, 30)) == []                       # -7.5% = 1 sigma exactly
    rows = s.store.alerts_where("kind = 'record'")
    assert len(rows) == 1 and rows[0]["deferred"] == 1 and "没有单独提醒" in rows[0]["digest_text"]


def test_sixteen_percent_day_is_one_worth_knowing_then_one_major(make):
    s = make()
    out = look(s, "INTC", 33.6, et(10, 0))                              # -16%: 2.1 sigma
    assert len(out) == 1 and out[0]["tier"] == 1 and out[0]["escalate"] is False and out[0]["price_move"]
    text = out[0]["text"]
    assert "值得知道" in text and "约 2.1 倍它的日常波动" in text and "超过 2 倍日常波动" in text
    assert "持仓 100 股" in text and "占总资产" in text and "原因" not in text
    for price, minute in ((33.0, 15), (32.0, 30), (33.6, 45)):           # no step re-alerts
        assert look(s, "INTC", price, et(10, minute)) == []
    major = look(s, "INTC", 27.0, et(11, 0))                             # -32.5%: 4.3 sigma
    assert len(major) == 1 and major[0]["tier"] == 2 and major[0]["escalate"] is True
    assert "重大：超过 4 倍日常波动" in major[0]["text"] and "升级" in major[0]["text"]
    assert look(s, "INTC", 26.0, et(11, 30)) == []


def test_major_is_not_held_back_by_min_gap(make):
    s = make()
    assert look(s, "INTC", 33.6, et(10, 0))
    out = look(s, "INTC", 27.0, et(10, 1))
    assert [a["tier"] for a in out] == [2]


def test_minor_pushes_wait_for_min_gap_and_are_not_lost(make):
    s = make()
    assert look(s, "INTC", 33.6, et(10, 0))
    assert look(s, "INTC", 46.4, et(10, 3)) == []                        # +16%: the other side, held 10 minutes
    out = look(s, "INTC", 46.4, et(10, 10))
    assert len(out) == 1 and out[0]["direction"] == "up"


def test_nvda_up_36_percent_is_major_once(make):
    s = make()
    snap = {"positions": [], "total_assets": 100000.0}
    out = look(s, "NVDA", 136.0, et(4, 5), held=False, snap=snap, prev=100.0, base=NVDA)
    assert len(out) == 1 and out[0]["tier"] == 2 and out[0]["escalate"] is False         # a queue symbol never rings
    assert "约 9.0 倍它的日常波动" in out[0]["text"] and "持仓" not in out[0]["text"]
    for minute in (35, 65, 95):
        assert look(s, "NVDA", 140.0, et(4, 5) + timedelta(minutes=minute), held=False, snap=snap, prev=100.0, base=NVDA) == []


def test_reversal_is_said_once(make):
    s = make()
    assert look(s, "INTC", 33.6, et(10, 0))
    assert look(s, "INTC", 35.0, et(10, 30)) == []                       # -12.5%: gave back 22%
    out = look(s, "INTC", 36.9, et(11, 0))                               # -7.75%: more than half of -16% back
    assert len(out) == 1 and "回吐" in out[0]["text"] and out[0]["why"] == "reversal"
    assert look(s, "INTC", 39.0, et(11, 30)) == []


def test_a_new_date_starts_clean_and_premarket_belongs_to_it(make):
    s = make()
    assert look(s, "INTC", 33.6, et(10, 0))
    assert look(s, "INTC", 33.0, et(4, 5, day=4))                       # same direction, next date, first print: pushes again


def test_restart_does_not_repeat_a_push(make, monkeypatch):
    from types import SimpleNamespace
    import sentinel.store as store_module
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=lambda: et(12, 0).timestamp()))
    s = make()
    assert look(s, "INTC", 33.6, et(10, 0))
    again = make()
    assert look(again, "INTC", 33.0, et(10, 30)) == []


def test_sensitivity_from_snapshot_and_env(make, monkeypatch):
    s = make()
    quiet = dict(BIG, alert_sensitivity="quiet")
    assert look(s, "INTC", 33.6, et(10, 0), snap=quiet) == []            # 2.13 sigma < 2.5
    sensitive = dict(BIG, alert_sensitivity="sensitive")
    assert len(look(make(), "INTC", 35.0, et(10, 0), snap=sensitive)) == 1   # -12.5% = 1.67 sigma >= 1.5
    monkeypatch.setenv("SENTINEL_SENSITIVITY", "quiet")
    assert look(make(), "INTC", 35.0, et(10, 0, day=4), snap=sensitive) == []   # env overrides the snapshot


def test_holding_impact_over_two_percent_is_major_but_only_for_a_move_worth_knowing(make):
    s = make()
    small = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 13135.0}
    assert look(s, "INTC", 36.0, et(10, 0), snap=small) == []            # -10%: 1.3 sigma, 3% of assets, still its ordinary day
    out = look(s, "INTC", 33.6, et(10, 30), snap=small)                  # -16%: 2.1 sigma and 4.9% of assets
    assert len(out) == 1 and out[0]["tier"] == 2 and out[0]["escalate"] is True
    assert "重大：这一下占总资产 4.9%，超过 2%" in out[0]["text"]


def test_market_move_is_in_the_message_when_known(make):
    s = make()
    s._market = {"r": -0.004, "sigma": 0.01}
    out = look(s, "INTC", 33.6, et(10, 0))
    assert "同期标普 -0.4%" in out[0]["text"] and out[0]["market_r"] == -0.004


# --- price levels ------------------------------------------------------------------------------------------------

PLAN = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 100000.0,
        "plans": [{"symbol": "INTC", "add_price": 55.0, "stop_price": 30.0, "target_price": 80.0}]}


def levels(out):
    return [a for a in out if a["kind"].startswith("plan_")]


def test_add_price_five_crossings_in_a_week_is_at_most_once_a_day(make):
    s = make()
    base = {"daily_sigma": 0.04, "bucket_sigma": {}, "avg_vol5": {}}
    run = lambda price, when, day: look(s, "INTC", price, when, snap=PLAN, prev=56.0, base=base)   # noqa: E731
    assert not levels(run(56.0, et(10, 0), 3))                           # first sight above: armed
    first = levels(run(54.9, et(10, 30), 3))
    assert len(first) == 1 and first[0]["escalate"] is False and "穿过补仓价 55" in first[0]["text"]
    assert first[0]["text"].count("第") == 0
    for minute, price in ((40, 55.5), (50, 54.0), (55, 55.8)):           # chop inside the lock
        assert not levels(run(price, et(10, minute), 3))
    assert not levels(run(56.2, et(11, 0), 3))                           # 2% above 55 is 56.1: re-armed here
    second = levels(run(54.5, et(11, 30), 3))
    assert len(second) == 1 and "第 2 次穿过补仓价 55" in second[0]["text"]
    assert not levels(run(54.0, et(12, 0), 3))
    run(56.5, et(10, 0, 4), 4)
    third = levels(run(54.0, et(10, 30, 4), 4))
    assert len(third) == 1 and "第" not in third[0]["text"].split("规则：")[1]     # a new date: the count is back to one


def test_stop_crossing_is_major_and_escalates_even_on_a_quiet_day(make):
    s = make()
    base = {"daily_sigma": 0.075, "bucket_sigma": {}, "avg_vol5": {}}
    look(s, "INTC", 31.0, et(10, 0), snap=PLAN, prev=31.2, base=base)
    out = levels(look(s, "INTC", 29.9, et(10, 5), snap=PLAN, prev=31.2, base=base))
    assert len(out) == 1 and out[0]["escalate"] is True and out[0]["tier"] == 2
    assert "重大：穿过止损价 30" in out[0]["text"]


def test_level_state_survives_a_restart(make, monkeypatch):
    from types import SimpleNamespace
    import sentinel.store as store_module
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=lambda: et(12, 0).timestamp()))
    s = make()
    base = {"daily_sigma": 0.04, "bucket_sigma": {}, "avg_vol5": {}}
    look(s, "INTC", 56.0, et(10, 0), snap=PLAN, prev=56.0, base=base)
    assert levels(look(s, "INTC", 54.9, et(10, 30), snap=PLAN, prev=56.0, base=base))
    again = make()
    assert not levels(look(again, "INTC", 54.8, et(10, 31), snap=PLAN, prev=56.0, base=base))


# --- short moves -------------------------------------------------------------------------------------------------

def test_short_moves_are_off_by_default_and_need_half_a_sigma_when_on(make, monkeypatch):
    base = {"daily_sigma": 0.02, "bucket_sigma": {"mid": 0.001}, "avg_vol5": {"mid": 1000.0}}
    series = bars(et(10, 59), 100.0, n=14) + [{"ts": et(11, 0), "close": 98.8, "volume": 100}]
    s = make()
    assert look(s, "INTC", 98.8, et(11, 0), prev=99.0, base=base, window=series) == []
    monkeypatch.setenv("SENTINEL_SHORT_MOVES", "on")
    out = look(make(), "INTC", 98.8, et(11, 0), prev=99.0, base=base, window=series)
    assert len(out) == 1 and out[0]["kind"] == "short" and out[0]["tier"] == 1 and "短线" in out[0]["text"]
    small = bars(et(10, 59), 100.0, n=14) + [{"ts": et(11, 0), "close": 99.7, "volume": 100}]
    assert look(make(), "INTC", 99.7, et(11, 0), prev=99.0, base=base, window=small) == []     # 0.3% < 0.5 * 2%


# --- flush: grouping, merging, urgency ---------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.raised = []

    def raise_alert(self, snap, alert):
        self.raised.append(alert)
        return len(self.raised)

    def deferred(self, alert_id):
        return False


def cand(symbol, *, tier=1, held=False, direction="down", r=-0.05, why="first", escalate=False):
    return {"symbol": symbol, "kind": "daily", "direction": direction, "held": held, "text": f"【值得知道·盘中】{symbol} 较昨收跌",
            "escalate": escalate, "weight_pct": None, "price_move": True, "trigger": "", "event_date": None, "price": 90.0,
            "tier": tier, "why": why, "sigma_mult": 2.5, "r": r, "impact_pct": -2.5 if held else None,
            "market_r": -0.02, "market_sigma": 0.01, "after_send": lambda d, a: None, "rollback": lambda: None}


def test_three_symbols_with_the_market_down_two_percent_are_one_grouped_message(make):
    s = make()
    s.escalator = Recorder()
    now = et(10, 0).astimezone(UTC)
    s.flush([cand("AMD"), cand("INTC", tier=2, held=True, escalate=True), cand("AAPL")], {}, now)
    assert len(s.escalator.raised) == 1
    msg = s.escalator.raised[0]
    assert msg["kind"] == "merged" and msg["escalate"] is True and msg["symbols"][0] == "INTC"
    assert "大盘同向：标普 -2.0%" in msg["text"] and "你关注的 3 只" in msg["text"]
    assert msg["text"].index("INTC") < msg["text"].index("AMD")
    assert msg["tier"] == 2


def test_the_market_flat_means_no_grouping_and_two_symbols_go_one_by_one(make):
    s = make()
    s.escalator = Recorder()
    flat = [dict(cand(n), market_r=0.001) for n in ("A", "B", "C")]
    s.flush(flat[:2], {}, et(10, 0).astimezone(UTC))
    assert [a["symbol"] for a in s.escalator.raised] == ["A", "B"]


def test_a_major_push_goes_through_the_merge_interval(make):
    s = make()
    s.escalator = Recorder()
    now = et(10, 0).astimezone(UTC)
    s.store.set_kv("merge_mode", {"active": True, "last_flush": now.timestamp() - 60})
    held_back = cand("AMD")
    rolled = []
    held_back["rollback"] = lambda: rolled.append(1)
    s.flush([held_back, cand("INTC", tier=2, held=True, escalate=True, direction="up", r=0.2)], {}, now)
    assert [a["symbol"] for a in s.escalator.raised] == ["INTC"] and rolled == [1]


def test_alert_payload_gains_tier_and_sigma_mult(make):
    s = make()
    out = look(s, "INTC", 33.6, et(10, 0))
    alert_id = s.escalator.raise_alert({}, out[0]) if False else s.store.add_alert("INTC", "daily", out[0]["text"], False, 1.0)
    payload = s.alert_payload(alert_id, out[0])
    assert payload["tier"] == 1 and payload["sigma_mult"] == pytest.approx(2.13, abs=0.01) and "trigger" not in payload


def test_anchor_policy_still_available_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", "anchor")
    s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
    out = s.alerts_from("INTC", True, et(10, 0), BIG, bars(et(10, 0), 33.6), PREV, INTC, [])
    assert out and out[0]["trigger"] == "T0" and "tier" not in out[0]
