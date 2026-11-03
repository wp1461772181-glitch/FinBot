"""The sentinel push policy (.local/design-alert-policy.md): one event per symbol per New York date, one remembered
anchor price, re-alerts only when the price travels.  Time passing alone never pushes."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from sentinel import signals
from sentinel.signals import decide_push, realert_limits, step_for

ET = ZoneInfo("America/New_York")
PREV = 338.32
STEP = 0.0113
R1 = 323.50 / PREV - 1


def et(hour, minute, day=3):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET)


def event(**fields):
    base = {"first_bucket": "pre", "anchor_price": 323.50, "anchor_r": R1, "last_push_ts": et(5, 0).timestamp(),
            "step": STEP, "open_checked": False, "pushes": 1}
    return base | fields


def decide(ev, price, now, *, held=False, entry=True, **kw):
    return decide_push(ev, price, PREV, now, held=held, entry=entry, **kw)


# --- the four real AAPL pushes of 2026-11-03 -----------------------------------------------------------------

def test_replay_aapl_2026_11_03():
    first = decide(None, 323.50, et(5, 0))
    assert first.action == "push" and first.trigger == "T0"
    ev = event()
    for price, when in ((325.28, et(5, 31)), (325.29, et(6, 2)), (325.00, et(6, 33))):
        out = decide(ev, price, when)
        assert out.action == "none" and out.trigger == "", (price, out)
        out_held = decide(ev, price, when, held=True)
        assert out_held.action == "none"
    low, high = realert_limits(323.50, R1, STEP, held=False)
    assert (round(low, 2), round(high, 2)) == (316.19, 330.81)
    low, high = realert_limits(323.50, R1, STEP, held=True)
    assert (round(low, 2), round(high, 2)) == (319.84, 330.81)


def test_time_alone_never_pushes():
    ev, pushes = event(), 0
    now = et(5, 0)
    while now < et(20, 0):
        out = decide(ev, 323.50, now, entry=True)
        if out.action == "push":
            pushes += 1
        if out.open_checked:
            ev = event(open_checked=True)
        now += timedelta(minutes=1)
    assert pushes == 0


# --- re-alert triggers -----------------------------------------------------------------------------------------

def test_worsening_path_queue_is_one_update():
    ev = event()
    assert decide(ev, 316.20, et(7, 0)).action == "none"
    out = decide(ev, 316.15, et(7, 1))
    assert (out.action, out.trigger) == ("push", "T1")
    ev = event(anchor_price=316.15, anchor_r=316.15 / PREV - 1, last_push_ts=et(7, 1).timestamp())
    assert decide(ev, 312.00, et(7, 30)).action == "none"
    low, high = realert_limits(316.15, 316.15 / PREV - 1, STEP, held=False)
    assert (round(low, 2), round(high, 2)) == (309.01, 323.29)


def test_worsening_path_held_is_three_updates():
    ev, pushes = event(), 0
    now = et(7, 0)
    for price in (319.80, 316.15, 312.55, 312.00):
        out = decide(ev, price, now, held=True)
        if out.action == "push":
            pushes += 1
            assert out.trigger == "T1"
            ev = event(anchor_price=price, anchor_r=price / PREV - 1, last_push_ts=now.timestamp())
        now += timedelta(minutes=11)
    assert pushes == 3 and ev["anchor_price"] == 312.55


def test_recovery_path_is_one_update_without_ring_semantics():
    ev = event()
    assert decide(ev, 330.80, et(8, 0)).action == "none"
    out = decide(ev, 330.85, et(8, 1))
    assert (out.action, out.trigger) == ("push", "T2") and out.dist > 0
    low, high = realert_limits(330.85, 330.85 / PREV - 1, STEP, held=False)
    assert (round(low, 2), round(high, 2)) == (323.37, 338.33)
    # a holding needs the same two steps to be told about a recovery
    assert decide(ev, 330.80, et(8, 0), held=True).action == "none"


def test_chop_inside_two_steps_is_silent():
    ev = event()
    for i, price in enumerate((322.0, 325.5, 321.5, 326.0, 323.0, 327.0, 320.5)):
        assert decide(ev, price, et(7, 0) + timedelta(minutes=11 * i)).action == "none"


def test_tier_crossing_alone_is_silent():
    prev = 100.0
    ev = event(anchor_price=97.05, anchor_r=-0.0295, step=0.01)        # told at 2.95 sigma
    out = decide_push(ev, 96.99, prev, et(7, 0), held=True, entry=True)   # now 3.01 sigma
    assert out.action == "none"


def test_kind_change_is_not_a_new_event():
    ev = event(first_bucket="open30")
    # a gap at 09:59 and a daily signal at 10:00 are the same event: an entry signal never pushes by itself
    assert decide(ev, 323.40, et(10, 0), held=True, entry=True).action == "none"


def test_new_date_opens_new_event_and_continuation_is_labelled():
    assert decide(None, 323.50, et(5, 0, day=4)).action == "push"
    assert decide(None, 323.50, et(5, 0), entry=False).action == "none"
    prior = {"anchor_price": 323.50, "anchor_r": R1}
    same_side = decide(None, 323.00, et(4, 5, day=4), prev_event=prior)
    assert same_side.action == "push" and same_side.continuation is True
    far = decide(None, 310.00, et(4, 5, day=4), prev_event=prior)
    assert far.continuation is False
    opposite = decide_push(None, 340.0, PREV, et(4, 5, day=4), held=False, entry=True, prev_event=prior,
                           step=STEP)
    assert opposite.continuation is False


def test_open_check_once():
    ev = event()
    assert decide(ev, 320.00, et(9, 34)).action == "none"                      # before 09:35
    out = decide(ev, 319.00, et(9, 35))                                        # 1.39 steps: queue T1 needs 2, T3 needs 1
    assert (out.action, out.trigger) == ("push", "T3") and out.open_checked
    quiet = decide(ev, 322.00, et(9, 36))
    assert quiet.action == "none" and quiet.open_checked is True               # evaluated, under a step: silent, done
    done = event(open_checked=True)
    assert decide(done, 319.00, et(9, 40)).action == "none"                    # never twice
    assert decide(event(first_bucket="mid"), 319.00, et(9, 40)).action == "none"  # only if it opened premarket
    better = decide(ev, 327.5, et(9, 35))                                      # +1.2 steps, the better direction
    assert better.trigger == "T3"


def test_step_clamps():
    assert step_for(None) == 0.02
    assert step_for(0.004) == 0.01
    assert step_for(0.049) == 0.03
    assert step_for(0.0113) == 0.0113


def test_step_is_frozen_with_the_event():
    ev = event(step=0.0113)
    assert decide(ev, 319.80, et(7, 0), held=True, step=0.03).action == "push"   # a rebuilt baseline cannot move it


def test_min_gap_holds_then_reports_full_distance():
    ev = event(last_push_ts=et(7, 0).timestamp())
    early = decide(ev, 312.00, et(7, 5), held=True)
    assert (early.action, early.trigger, early.reason) == ("hold", "T1", "min_gap")
    later = decide(ev, 312.00, et(7, 10), held=True)
    assert later.action == "push" and later.dist == pytest.approx(312.00 / 323.50 - 1)


# --- the whole chain on built data ------------------------------------------------------------------------------

def _bars(end, price, n=15):
    start = end - timedelta(minutes=n - 1)
    return [{"ts": start + timedelta(minutes=i), "close": price, "volume": 100} for i in range(n)]


BASE = {"daily_sigma": 0.0113, "bucket_sigma": {}, "avg_vol5": {}}


def _sentinel(tmp_path):
    from sentinel.main import Sentinel
    from sentinel.store import Store
    return Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))


def _look(s, price, when, *, held=False, snap=None):
    return s.alerts_from("AAPL", held, when, snap or {}, _bars(when, price), PREV, BASE, [])


def test_chain_replay_only_the_first_message_goes_out(tmp_path):
    s = _sentinel(tmp_path)
    first = _look(s, 323.50, et(5, 0))
    assert len(first) == 1
    text = first[0]["text"]
    assert "盘前异动" in text and "较昨收跌 4.4%" in text and "超过 3σ" in text
    assert "再次提醒线：≤316.19 或 ≥330.81" in text and "开盘后 5 分钟再看一次" in text and "今日首条" in text
    assert first[0]["trigger"] == "T0" and first[0]["escalate"] is False          # a queue symbol never rings
    for price, when in ((325.28, et(5, 31)), (325.29, et(6, 2)), (325.00, et(6, 33))):
        assert _look(s, price, when) == []
    event_row = s.store.get_event("AAPL", "2026-11-03")
    assert event_row["anchor_price"] == 323.50 and event_row["pushes"] == 1 and event_row["suppressed"] >= 3


def test_chain_worsening_sends_an_update_measured_from_the_anchor(tmp_path):
    s = _sentinel(tmp_path)
    _look(s, 323.50, et(5, 0))
    out = _look(s, 316.15, et(5, 40))
    assert len(out) == 1 and out[0]["trigger"] == "T1"
    assert "较上次提醒（323.50" in out[0]["text"] and "又跌 2.3%" in out[0]["text"] and "今日第 2 条" in out[0]["text"]
    assert "再次提醒线：≤309.01 或 ≥323.29" in out[0]["text"]
    assert _look(s, 312.00, et(6, 20)) == []


def test_chain_recovery_sends_one_update_that_does_not_ring(tmp_path):
    s = _sentinel(tmp_path)
    _look(s, 323.50, et(5, 0), held=True, snap={"positions": [{"symbol": "AAPL", "shares": 10.0}], "total_assets": 50000.0})
    out = _look(s, 330.85, et(5, 40), held=True, snap={"positions": [{"symbol": "AAPL", "shares": 10.0}], "total_assets": 50000.0})
    assert len(out) == 1 and out[0]["trigger"] == "T2" and out[0]["escalate"] is False
    assert "回升 2.3%" in out[0]["text"] and "较昨收仍跌 2.2%" in out[0]["text"]


def test_chain_held_update_rings_and_reports_loss_since_last_push(tmp_path):
    snap = {"positions": [{"symbol": "AAPL", "shares": 100.0, "market_value": 32350.0}], "total_assets": 100000.0}
    s = _sentinel(tmp_path)
    first = _look(s, 323.50, et(5, 0), held=True, snap=snap)
    assert first[0]["kind"] == "gap" and first[0]["escalate"] is True
    out = _look(s, 319.80, et(5, 40), held=True, snap=snap)
    assert out[0]["escalate"] is True and "较上次提醒又亏 $370" in out[0]["text"] and "较昨收共亏" in out[0]["text"]


def test_chain_new_date_opens_a_new_event(tmp_path):
    s = _sentinel(tmp_path)
    _look(s, 323.50, et(5, 0))
    assert s.store.get_event("AAPL", "2026-11-04") is None
    nxt = s.alerts_from("AAPL", False, et(5, 0, day=4), {}, _bars(et(5, 0, day=4), 300.0), PREV, BASE, [])
    assert len(nxt) == 1 and nxt[0]["trigger"] == "T0"


def test_chain_plan_level_once_per_day_and_not_gap_limited(tmp_path):
    s = _sentinel(tmp_path)
    snap = {"positions": [{"symbol": "AAPL", "shares": 10.0}], "plans": [{"symbol": "AAPL", "stop_price": 300.0}],
            "total_assets": 50000.0}
    s.store.set_price("AAPL", 301.0)
    first = _look(s, 299.0, et(11, 0), held=True, snap=snap)
    assert [a["kind"] for a in first if a["kind"] == "plan_stop"] == ["plan_stop"]
    s.store.set_price("AAPL", 301.0)                                    # chops back above and down again, a minute later
    again = _look(s, 299.0, et(11, 1), held=True, snap=snap)
    assert not [a for a in again if a["kind"] == "plan_stop"]
    s.store.set_price("AAPL", 301.0)
    tomorrow = s.alerts_from("AAPL", True, et(11, 0, day=4), snap, _bars(et(11, 0, day=4), 299.0), 310.0, BASE, [])
    assert [a for a in tomorrow if a["kind"] == "plan_stop"]


def test_chain_plan_push_moves_the_anchor(tmp_path):
    s = _sentinel(tmp_path)
    snap = {"positions": [{"symbol": "AAPL", "shares": 10.0}], "plans": [{"symbol": "AAPL", "stop_price": 320.0}],
            "total_assets": 50000.0}
    _look(s, 323.50, et(11, 0), held=True, snap=snap)
    s.store.set_price("AAPL", 321.0)
    out = _look(s, 319.9, et(11, 30), held=True, snap=snap)
    assert [a["kind"] for a in out] == ["plan_stop"]                    # 319.9 is under a step from 323.50: no price push
    assert s.store.get_event("AAPL", "2026-11-03")["anchor_price"] == 319.9


def test_chain_split_is_sent_once(tmp_path):
    s = _sentinel(tmp_path)
    splits = [{"date": "2026-11-03", "ratio": "4:1"}]
    snap = {"positions": [{"symbol": "AAPL", "shares": 10.0}]}
    first = s.alerts_from("AAPL", True, et(11, 0), snap, _bars(et(11, 0), 80.0), PREV, BASE, splits)
    assert [a["kind"] for a in first] == ["split"]
    for minute in (31, 62, 93):
        assert s.alerts_from("AAPL", True, et(11, 0) + timedelta(minutes=minute), snap,
                             _bars(et(11, 0) + timedelta(minutes=minute), 80.0), PREV, BASE, splits) == []


def test_state_survives_a_restart_without_the_api(tmp_path):
    s = _sentinel(tmp_path)
    _look(s, 323.50, et(5, 0))
    again = _sentinel(tmp_path)                                         # a new process on the same sqlite file
    assert _look(again, 325.28, et(5, 31)) == []


def test_old_alerts_table_gets_the_new_columns(tmp_path):
    import sqlite3
    from sentinel.store import Store
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, kind TEXT NOT NULL,"
                 "text TEXT NOT NULL, escalate INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, acked_at REAL,"
                 "tg_chat_id INTEGER, tg_message_id INTEGER, last_sent_at REAL, resends INTEGER NOT NULL DEFAULT 0,"
                 "deferred INTEGER NOT NULL DEFAULT 0, digested_at REAL, receipt TEXT,"
                 "receipt_closed INTEGER NOT NULL DEFAULT 0, escalated_at REAL)")
    conn.commit()
    conn.close()
    store = Store(path)
    alert_id = store.add_alert("AAPL", "daily", "x", False, 1.0, event_date="2026-11-03")
    assert store.alert(alert_id)["event_date"] == "2026-11-03" and store.alert(alert_id)["superseded_by"] is None
    Store(path)                                                          # a second start is a no-op


# --- several symbols at once -------------------------------------------------------------------------------------

def _candidate(symbol, price=90.0, escalate=False, weight=None):
    return {"symbol": symbol, "kind": "daily", "direction": "down", "held": escalate, "text": f"【盘中异动】{symbol} 跌",
            "escalate": escalate, "weight_pct": weight, "price_move": True, "trigger": "T0", "event_date": "2026-11-03",
            "price": price, "after_send": lambda deferred, alert_id: None}


class Recorder:
    def __init__(self):
        self.raised = []

    def raise_alert(self, snap, alert):
        self.raised.append(alert)
        return len(self.raised)

    def deferred(self, alert_id):
        return False


def test_a_burst_of_three_symbols_goes_out_as_one_merged_message(tmp_path):
    s = _sentinel(tmp_path)
    s.escalator = Recorder()
    now = et(5, 0).astimezone(UTC)                                      # 18:00 Beijing: not night
    s.flush([_candidate("A"), _candidate("B"), _candidate("C", escalate=True)], {}, now)
    assert len(s.escalator.raised) == 1
    merged = s.escalator.raised[0]
    assert merged["kind"] == "merged" and merged["escalate"] is True and "多股异动" in merged["text"]
    assert {"A", "B", "C"} <= set(merged["symbols"])
    # inside the 10-minute interval the next burst sends nothing and moves no anchor
    s.flush([_candidate("A"), _candidate("B")], {}, now + timedelta(minutes=5))
    assert len(s.escalator.raised) == 1
    # a flush with one candidate after the interval ends merge mode and goes out as an ordinary push
    s.flush([_candidate("A")], {}, now + timedelta(minutes=11))
    assert len(s.escalator.raised) == 2 and s.escalator.raised[1]["symbol"] == "A"
    assert s.store.get_kv("merge_mode") is None or not s.store.get_kv("merge_mode")[0].get("active")


def test_two_symbols_are_not_a_burst(tmp_path):
    s = _sentinel(tmp_path)
    s.escalator = Recorder()
    s.flush([_candidate("A"), _candidate("B")], {}, et(5, 0).astimezone(UTC))
    assert [a["symbol"] for a in s.escalator.raised] == ["A", "B"]
