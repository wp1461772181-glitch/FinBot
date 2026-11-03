"""Intraday move signals (Task 11): rules are relative to each stock's own history."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sentinel import signals

ET = ZoneInfo("America/New_York")


def test_gap_and_daily_level_with_intc_numbers():
    assert signals.gap_signal(68.36, 92.07, 0.0490) is True
    assert signals.daily_move_level(-0.2575, 0.0490) == 2


def test_daily_move_level_aapl():
    sigma = 0.0164
    assert signals.daily_move_level(-0.02, sigma) == 0
    assert signals.daily_move_level(-0.034, sigma) == 1
    assert signals.daily_move_level(-0.05, sigma) == 2
    assert signals.daily_move_level(-0.07, None) == 0 and signals.daily_move_level(-0.08, None) == 1


def test_short_move_signal():
    assert signals.short_move_signal(-0.05, 0.01) is True
    assert signals.short_move_signal(-0.009, 0.001) is False   # 4 sigma is met, the 1% floor is not
    assert signals.short_move_signal(-0.05, None) is True
    assert signals.short_move_signal(-0.03, None) is False


def test_bucket_of_in_summer_and_winter_time():
    # 09:35 New York is 13:35 UTC in July (EDT) and 14:35 UTC in January (EST)
    assert signals.bucket_of(datetime(2026, 7, 15, 13, 35, tzinfo=UTC)) == "open30"
    assert signals.bucket_of(datetime(2026, 1, 15, 14, 35, tzinfo=UTC)) == "open30"
    assert signals.bucket_of(datetime(2026, 7, 15, 12, 0, tzinfo=ET)) == "mid"
    assert signals.bucket_of(datetime(2026, 1, 15, 12, 0, tzinfo=ET)) == "mid"
    assert signals.bucket_of(datetime(2026, 1, 15, 8, 0, tzinfo=ET)) == "pre"
    assert signals.bucket_of(datetime(2026, 1, 15, 15, 45, tzinfo=ET)) == "close30"
    assert signals.bucket_of(datetime(2026, 1, 15, 17, 0, tzinfo=ET)) == "post"


def test_is_stale():
    now = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)
    assert signals.is_stale(now - timedelta(minutes=11), now) is True
    assert signals.is_stale(now - timedelta(minutes=9), now) is False
    assert signals.is_stale(None, now) is True


BASELINE = {"daily_sigma": 0.02, "bucket_sigma": {"open30": 0.01, "mid": 0.01, "pre": 0.01, "close30": 0.01, "post": 0.01},
            "avg_vol5": {"open30": 1000.0, "mid": 1000.0, "pre": 1000.0, "close30": 1000.0, "post": 1000.0}}


def _bars(end, closes, volume=100):
    """One bar per minute ending at ``end``; ``closes`` oldest first."""
    start = end - timedelta(minutes=len(closes) - 1)
    return [{"ts": start + timedelta(minutes=i), "close": c, "volume": volume} for i, c in enumerate(closes)]


NOW = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)  # 11:00 New York, mid session


def test_five_minute_drop_signals_for_a_holding():
    closes = [100.0] * 10 + [99.0, 98.0, 97.0, 96.0, 95.0]  # -5% in 5 minutes
    found = signals.detect("INTC", _bars(NOW, closes), NOW, BASELINE, prev_close=100.0, held=True)
    kinds = {s.kind for s in found}
    assert "short" in kinds
    short = next(s for s in found if s.kind == "short")
    assert short.direction == "down" and round(short.r, 3) == -0.05 and short.price == 95.0 and short.ref_price == 100.0


def test_stale_or_empty_bars_no_signal():
    assert signals.detect("INTC", [], NOW, BASELINE, prev_close=100.0, held=True) == []
    old = NOW - timedelta(minutes=30)
    bars = _bars(old, [100.0] * 10 + [90.0] * 5)             # a halt: the last bar is half an hour old
    assert signals.detect("INTC", bars, NOW, BASELINE, prev_close=100.0, held=True) == []
    assert signals.detect("INTC", [{"ts": NOW, "close": None, "volume": None}], NOW, BASELINE, prev_close=100.0, held=True) == []
    saturday = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    assert signals.in_trading_session(saturday) is False
    assert signals.in_trading_session(NOW) is True
    assert signals.in_trading_session(datetime(2026, 7, 15, 8, 30, tzinfo=UTC)) is True   # 04:30 ET pre-market
    assert signals.in_trading_session(datetime(2026, 7, 16, 0, 30, tzinfo=UTC)) is False  # 20:30 ET


def test_split_no_false_alarm():
    closes = [100.0] * 10 + [10.0] * 5                         # 1-for-10 shows as -90 percent
    splits = [{"date": NOW.date().isoformat(), "ratio": "10:1"}]
    found = signals.detect("AAPL", _bars(NOW, closes), NOW, BASELINE, prev_close=100.0, held=True, splits=splits)
    assert [s.kind for s in found] == ["split"]
    old_split = [{"date": (NOW - timedelta(days=5)).date().isoformat(), "ratio": "10:1"}]
    again = signals.detect("AAPL", _bars(NOW, [100.0] * 10 + [95.0] * 5), NOW, BASELINE, prev_close=100.0, held=True, splits=old_split)
    assert "split" not in {s.kind for s in again}


def test_queue_symbols_only_report_level_two():
    closes = [100.0] * 15
    drop = _bars(NOW, [100.0] * 10 + [99.0, 98.0, 97.0, 96.0, 95.0])
    assert signals.detect("INTC", drop, NOW, BASELINE, prev_close=100.0, held=False) == []   # -5% = 2.5 sigma: level 1 only
    deep = _bars(NOW, closes[:10] + [97.0, 95.0, 93.0, 92.0, 90.0])                         # -10% = 5 sigma: level 2
    found = signals.detect("INTC", deep, NOW, BASELINE, prev_close=100.0, held=False)
    assert [s.kind for s in found] == ["daily"] and found[0].level == 2


def test_volume_surge_is_only_a_note():
    quiet = _bars(NOW, [100.0] * 15, volume=100)
    assert signals.detect("INTC", quiet, NOW, BASELINE, prev_close=100.0, held=True) == []   # heavy volume alone: nothing
    closes = [100.0] * 10 + [99.0, 98.0, 97.0, 96.0, 95.0]
    loud = signals.detect("INTC", _bars(NOW, closes, volume=2000), NOW, BASELINE, prev_close=100.0, held=True)
    assert any(s.volume_surge for s in loud)


def test_plan_prices_crossed():
    plan = {"symbol": "INTC", "add_price": 60.0, "stop_price": 55.0, "target_price": 80.0}
    assert [s.kind for s in signals.plan_crossings("INTC", 61.0, 59.5, plan)] == ["plan_add"]
    assert [s.kind for s in signals.plan_crossings("INTC", 56.0, 54.0, plan)] == ["plan_stop"]
    assert [s.kind for s in signals.plan_crossings("INTC", 79.0, 81.0, plan)] == ["plan_target"]
    assert signals.plan_crossings("INTC", 70.0, 71.0, plan) == []
    assert signals.plan_crossings("INTC", None, 54.0, plan) == []


def test_cooldown_and_deepening():
    cooldown = signals.Cooldown()
    t0 = 1_000_000.0
    assert cooldown.allow("INTC", "short:down", 4.5, t0) is True
    assert cooldown.allow("INTC", "short:down", 4.6, t0 + 600) is False       # inside 30 minutes
    assert cooldown.allow("INTC", "short:down", 5.4, t0 + 600) is False       # not yet one sigma further
    assert cooldown.allow("INTC", "short:down", 5.6, t0 + 600) is True        # one sigma deeper than the last alert
    assert cooldown.allow("INTC", "short:down", 5.7, t0 + 600 + 1801) is True  # window over
    assert cooldown.allow("AAPL", "short:down", 4.5, t0 + 10) is True         # another stock
    assert cooldown.allow("INTC", "short:up", 4.5, t0 + 20) is True           # another kind


def test_baseline_from_five_minute_bars():
    bars, ts = [], datetime(2026, 6, 1, 13, 30, tzinfo=UTC)
    price = 100.0
    for day in range(25):
        start = ts + timedelta(days=day)
        if start.weekday() >= 5:
            continue
        for i in range(78):                                  # 09:30-16:00 ET in 5-minute bars
            price *= 1.001 if i % 2 else 0.999
            bars.append({"ts": start + timedelta(minutes=5 * i), "close": price, "volume": 500})
    base = signals.compute_baseline(bars, datetime(2026, 6, 30, 22, 0, tzinfo=UTC))
    assert base["bucket_sigma"]["mid"] is not None and 0.0005 < base["bucket_sigma"]["mid"] < 0.002
    assert base["avg_vol5"]["mid"] == 500
    assert base["daily_sigma"] is None or base["daily_sigma"] >= 0


# --- the whole chain on built data: bars -> signal -> cooldown -> alert text --------------------------------

def _sentinel(tmp_path):
    from sentinel.main import Sentinel
    from sentinel.store import Store
    return Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))


SNAP = {"positions": [{"symbol": "INTC", "shares": 100.0, "avg_cost": 23.12, "price": 65.76, "market_value": 6576.0, "weight_pct": 46.1}],
        "plans": [{"symbol": "INTC", "add_price": 60.0, "stop_price": 55.0, "target_price": 80.0}],
        "total_assets": 14264.0, "research_queue": ["AAPL"]}
INTC_BASE = {"daily_sigma": 0.049, "bucket_sigma": {b: 0.008 for b in ("pre", "open30", "mid", "close30", "post")},
             "avg_vol5": {b: 50000.0 for b in ("pre", "open30", "mid", "close30", "post")}}


def test_offline_five_minute_drop_produces_a_sized_alert(tmp_path):
    s = _sentinel(tmp_path)
    closes = [65.76] * 10 + [65.1, 64.4, 63.7, 63.0, 62.47]   # -5.0% in five minutes
    bars = _bars(NOW, closes, volume=80000)
    alerts = s.alerts_from("INTC", True, NOW, SNAP, bars, 65.76, INTC_BASE, [])
    short = next(a for a in alerts if a["kind"] == "short")
    assert short["escalate"] is True and short["direction"] == "down"
    assert "INTC" in short["text"] and "5 分钟内跌 5.0%" in short["text"]
    assert "亏 $329" in short["text"] and "占总资产 2.31%" in short["text"]   # 100 shares x 3.29 of 14264
    assert "放量" in short["text"]
    assert short["weight_pct"] is not None and 40 < short["weight_pct"] < 50
    # a minute later the same fall does not alert again
    again = s.alerts_from("INTC", True, NOW + timedelta(minutes=1), SNAP, _bars(NOW + timedelta(minutes=1), closes + [62.4]),
                          65.76, INTC_BASE, [])
    assert not [a for a in again if a["kind"] == "short"]


def test_offline_plan_price_crossing_and_queue_symbol(tmp_path):
    s = _sentinel(tmp_path)
    s.store.set_price("INTC", 60.5)
    alerts = s.alerts_from("INTC", True, NOW, SNAP, _bars(NOW, [59.9] * 15), 65.76, INTC_BASE, [])
    assert any(a["kind"] == "plan_add" and "补仓价 60.0" in a["text"] for a in alerts)
    quiet = s.alerts_from("AAPL", False, NOW, SNAP, _bars(NOW, [100.0] * 10 + [99, 98, 97, 96, 95.0]), 100.0,
                          {"daily_sigma": 0.0164, "bucket_sigma": {}}, [])
    assert [a["escalate"] for a in quiet] == [False]           # queue: level 2 only, never escalates


# --- prev_close from daily bars (Yahoo's chartPreviousClose is a day stale in premarket) --------------------

def _daily(*pairs):
    """Daily bars stamped at the 09:30 ET open, like Yahoo's 1d series."""
    return [{"ts": datetime(y, m, d, 9, 30, tzinfo=ET).astimezone(UTC), "close": c, "volume": 1}
            for (y, m, d), c in pairs]


FRI, MON, TUE = (2026, 10, 30), (2026, 11, 2), (2026, 11, 3)


def _et_now(day, hour, minute):
    return datetime(*day, hour, minute, tzinfo=ET).astimezone(UTC)


def test_prev_close_from_daily_uses_last_completed_day():
    bars = _daily((FRI, 344.63), (MON, 338.32), (TUE, 336.0))   # Tue bar is forming
    for hour, minute in ((4, 5), (12, 0), (19, 0)):
        assert signals.prev_close_from_daily(bars, _et_now(TUE, hour, minute)) == 338.32
    # premarket: Yahoo may not have Tuesday's bar yet
    assert signals.prev_close_from_daily(bars[:2], _et_now(TUE, 4, 5)) == 338.32
    # next morning the Tuesday bar is complete
    bars[2]["close"] = 330.0
    assert signals.prev_close_from_daily(bars, _et_now((2026, 11, 4), 4, 5)) == 330.0


def test_prev_close_from_daily_none_without_completed_day():
    now = _et_now(TUE, 4, 5)
    assert signals.prev_close_from_daily([], now) is None
    assert signals.prev_close_from_daily(_daily((TUE, 336.0)), now) is None
    assert signals.prev_close_from_daily(_daily((MON, None), (TUE, 336.0)), now) is None


def test_derived_prev_close_beats_yahoo_meta_value(tmp_path, monkeypatch):
    s = _sentinel(tmp_path)
    now = _et_now(TUE, 4, 17)
    charts = {
        "5m": {"bars": [], "prev_close": None, "splits": []},
        "1d": {"bars": _daily((FRI, 344.63), (MON, 338.32)), "prev_close": 344.63, "splits": []},
        "1m": {"bars": _bars(now, [328.5] * 15), "prev_close": 344.63, "splits": []},
    }
    seen = {}
    real_detect = signals.detect

    def spy(symbol, bars, now_, baseline, prev_close, **kw):
        seen["prev_close"] = prev_close
        return real_detect(symbol, bars, now_, baseline, prev_close, **kw)

    monkeypatch.setattr(signals, "fetch_chart", lambda symbol, interval, range_, **kw: charts[interval])
    monkeypatch.setattr(signals, "detect", spy)
    s.evaluate_symbol("AAPL", False, now, {})
    assert seen["prev_close"] == 338.32
    # the hourly splits refresh recomputes it; no daily history -> fall back to the meta value
    charts["1d"]["bars"] = []
    later = now + timedelta(hours=2)
    s.evaluate_symbol("AAPL", False, later, {})
    assert seen["prev_close"] == 344.63
