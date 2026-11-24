"""1f-2 Task 2: every alert the sentinel raises is also told to the API as `alert_posted` (so the agent can judge it).
Telling the API changes nothing the owner receives, and a down API only means the event waits in the retry queue."""
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentinel import signals
from sentinel.escalation import Escalator
from sentinel.main import Sentinel
from sentinel.store import Store

BJ = timezone(timedelta(hours=8))
DAY = datetime(2026, 11, 3, 10, 0, tzinfo=BJ).timestamp()
NIGHT = datetime(2026, 11, 3, 3, 0, tzinfo=BJ).timestamp()
SNAP = {"telegram": {"bot_token": "t", "chat_id": 1}, "pushover": {"user_key": "u", "app_token": "a"}}
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def telegram_alert(self, config, text, alert_id):
        self.calls.append(("telegram_alert", config, text, alert_id))
        return 1000 + len(self.calls)

    def telegram_text(self, config, text):
        self.calls.append(("telegram_text", config, text))
        return True

    def pushover_emergency(self, config, text):
        self.calls.append(("pushover_emergency", config, text))
        return f"receipt{len(self.calls)}"

    def receipt_status(self, config, receipt):
        return {"acknowledged": False}

    def cancel_receipt(self, config, receipt):
        self.calls.append(("cancel_receipt", config, receipt))


def make(tmp_path, at=DAY, *, post=True):
    s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
    notifier = FakeNotifier()
    clock = [at]
    s.escalator = Escalator(s.store, notifier, clock=lambda: clock[0])
    if not post:
        s._announce = lambda *a, **k: None
    return s, notifier, clock


def price_alert(symbol="AAPL", **extra):
    base = {"symbol": symbol, "kind": "daily", "direction": "down", "held": True, "text": f"【盘中异动】{symbol} 跌 4.4%",
            "escalate": True, "weight_pct": 12.5, "price_move": True, "trigger": "T0", "steps": 2,
            "event_date": "2026-11-03", "price": 323.5, "prev_close": 338.32, "earnings_unacked": False,
            "after_send": lambda deferred, alert_id: None, "rollback": lambda: None}
    return base | extra


@pytest.fixture
def posted(monkeypatch):
    sent = []
    monkeypatch.setattr(signals, "post_event", lambda base, t, p: sent.append((t, p)))
    return sent


def test_a_price_alert_is_posted_with_what_the_sentinel_knows(tmp_path, posted):
    s, _, _ = make(tmp_path)
    s._raise(SNAP, price_alert())
    s.resend_events()
    assert len(posted) == 1 and posted[0][0] == "alert_posted"
    p = posted[0][1]
    assert p == {"alert_id": 1, "symbol": "AAPL", "kind": "daily", "text": "【盘中异动】AAPL 跌 4.4%", "created_at": DAY,
                 "deferred": False, "escalate": True, "held": True, "weight_pct": 12.5, "price": 323.5,
                 "prev_close": 338.32, "move_pct": pytest.approx((323.5 / 338.32 - 1) * 100), "trigger": "T0",
                 "event_date": "2026-11-03"}
    assert "sigma_level" not in p and "members" not in p      # the sentinel does not have them: omitted, never invented


def test_a_plan_crossing_is_posted_without_the_price_move_fields(tmp_path, posted):
    s, _, _ = make(tmp_path)
    s._raise(SNAP, {"symbol": "AAPL", "kind": "plan_stop", "direction": "down", "held": True, "text": "AAPL 跌破止损 300",
                    "escalate": True, "weight_pct": None, "price_move": False, "trigger": "", "event_date": None,
                    "price": 299.0, "earnings_unacked": False, "after_send": lambda d, a: None})
    s.resend_events()
    p = posted[0][1]
    assert p["kind"] == "plan_stop" and p["price"] == 299.0 and p["held"] is True
    for missing in ("weight_pct", "prev_close", "move_pct", "trigger", "event_date", "members"):
        assert missing not in p


def test_a_merged_alert_is_posted_once_with_its_members(tmp_path, posted):
    s, _, _ = make(tmp_path)
    s._raise_merged(SNAP, [price_alert("A"), price_alert("B", held=False, escalate=False, weight_pct=None),
                           price_alert("C", weight_pct=3.0)])
    s.resend_events()
    assert len(posted) == 1
    p = posted[0][1]
    assert p["kind"] == "merged" and p["members"] == ["A", "B", "C"] and p["held"] is True and p["escalate"] is True
    assert p["weight_pct"] == 12.5 and p["trigger"] == "T0"
    assert "price" not in p and "move_pct" not in p and "event_date" not in p


def test_a_held_night_alert_is_posted_as_deferred(tmp_path, posted):
    s, notifier, _ = make(tmp_path, NIGHT)
    s._raise(SNAP, price_alert(weight_pct=4.0))               # a small holding: waits for the morning digest
    assert notifier.calls == []
    s.resend_events()
    p = posted[0][1]
    assert p["deferred"] is True and p["alert_id"] == 1 and p["created_at"] == NIGHT


def test_an_update_of_a_pending_night_line_posts_again_with_the_same_alert_id(tmp_path, posted):
    s, _, _ = make(tmp_path, NIGHT)
    s.store.open_event("AAPL", "2026-11-03", first_ts=NIGHT, first_bucket="pre", price=323.5, r=-0.044, step=0.0113)
    pending = price_alert(weight_pct=4.0, after_send=lambda deferred, alert_id: s.store.update_event(
        "AAPL", "2026-11-03", pending_alert_id=alert_id))
    s._raise(SNAP, pending)
    s._raise(SNAP, pending | {"text": "【盘中异动】AAPL 又跌"})
    s.resend_events()
    assert [p["alert_id"] for _, p in posted] == [1, 1]       # the API judges an alert id once (a later stage may re-judge updates)
    assert posted[1][1]["text"] == "【盘中异动】AAPL 又跌"


def test_api_down_queues_the_event_and_the_drain_resends_it_once(tmp_path, monkeypatch):
    s, _, _ = make(tmp_path)

    def down(base, t, p):
        raise OSError("api down")
    monkeypatch.setattr(signals, "post_event", down)
    s._raise(SNAP, price_alert())
    s.resend_events()                                          # still down: kept, not lost
    queued = s.store.pending()
    assert [e["type"] for e in queued] == ["alert_posted"] and queued[0]["payload"]["alert_id"] == 1
    sent = []
    monkeypatch.setattr(signals, "post_event", lambda base, t, p: sent.append((t, p)))
    s.resend_events()
    s.resend_events()
    assert [t for t, _ in sent] == ["alert_posted"] and sent[0][1]["alert_id"] == 1 and s.store.pending() == []


def test_a_failing_queue_never_breaks_the_alert(tmp_path, monkeypatch):
    s, notifier, _ = make(tmp_path)
    monkeypatch.setattr(s.store, "enqueue", lambda *a: (_ for _ in ()).throw(RuntimeError("disk full")))
    s._raise(SNAP, price_alert())                             # must not raise
    assert [c[0] for c in notifier.calls][:1] == ["telegram_alert"]


def test_with_the_api_unreachable_three_alerts_go_out_with_no_added_delay(tmp_path, monkeypatch):
    """The alert path never makes an HTTP call: a post_event that would hang for 15 s is not even touched."""
    s, notifier, _ = make(tmp_path)
    clock, calls = [0.0], []

    def hanging(base, t, p):
        calls.append(t)
        clock[0] += 15.0                                       # what an unreachable API costs per attempt
        raise OSError("unreachable")
    monkeypatch.setattr(signals, "post_event", hanging)
    for symbol in ("A", "B", "C"):
        s._raise(SNAP, price_alert(symbol))
    assert clock[0] == 0.0 and calls == []
    assert [c[0] for c in notifier.calls if c[0] == "telegram_alert"] == ["telegram_alert"] * 3
    assert len(s.store.pending()) == 3
    sent = []
    monkeypatch.setattr(signals, "post_event", lambda base, t, p: sent.append(p["symbol"]))
    s.resend_events()
    s.resend_events()
    assert sent == ["A", "B", "C"] and s.store.pending() == []


def test_the_events_job_runs_at_least_every_30_seconds():
    from sentinel.main import FAST_JOBS, INTERVAL
    assert min(INTERVAL, FAST_JOBS.get("events", INTERVAL)) <= 30.0


def _drive(s, clock):
    s._raise(SNAP, price_alert("AAPL"))
    s._raise_merged(SNAP, [price_alert("A"), price_alert("B", escalate=False), price_alert("C")])
    clock[0] = NIGHT
    s._raise(SNAP, price_alert("NVDA", weight_pct=4.0))
    s._raise(SNAP, price_alert("NVDA", weight_pct=4.0, text="update"))
    s._raise(SNAP, price_alert("MSFT", kind="plan_stop", price_move=False, event_date=None))
    s.escalator.tick(SNAP)


def test_the_sentinels_own_sends_are_identical_with_and_without_the_posting(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_post, n1, c1 = make(tmp_path / "a")
    without, n2, c2 = make(tmp_path / "b", post=False)
    _drive(with_post, c1)
    _drive(without, c2)
    assert len(with_post.store.pending()) == 5 and without.store.pending() == []
    assert n1.calls == n2.calls and len(n1.calls) > 3
    assert [(a["text"], a["deferred"], a["escalate"]) for a in with_post.store.alerts_where("1=1")] == \
           [(a["text"], a["deferred"], a["escalate"]) for a in without.store.alerts_where("1=1")]


# --- the drain: one bad alert_posted never holds up earnings_detected ---------------------------------------------

class Refused(Exception):
    def __init__(self, code):
        self.code = code


def _earnings(s):
    s.store.add_earnings({"accession": "0001", "symbol": "AAPL", "cik": "1", "held": 1, "filed": "2026-11-03",
                          "accepted_at": 1.0, "primary_doc": "x.htm", "url": "u", "detected_at": 1.0, "seeded": 0})
    s.store.enqueue("earnings_detected", {"accession": "0001", "symbol": "AAPL"})


def test_earnings_queued_behind_a_422_and_a_timeout_is_delivered_in_the_same_drain(tmp_path, monkeypatch):
    s, _, _ = make(tmp_path)
    s.store.enqueue("alert_posted", {"alert_id": 1, "symbol": "A"})       # the API answers 422
    s.store.enqueue("alert_posted", {"alert_id": 2, "symbol": "B"})       # no answer
    _earnings(s)
    sent = []

    def api(base, t, p):
        sent.append((t, p.get("alert_id") or p.get("accession")))
        if t == "alert_posted":
            raise Refused(422) if p["alert_id"] == 1 else TimeoutError("no answer")
    monkeypatch.setattr(signals, "post_event", api)
    s.resend_events()
    assert sent[0] == ("earnings_detected", "0001")                       # earnings go first
    assert s.store.earnings_rows("accession = ?", ("0001",))[0]["delivered_at"] is not None
    left = s.store.pending()
    assert [(e["type"], e["payload"]["alert_id"]) for e in left] == [("alert_posted", 2)]   # 422 dropped, timeout kept


def test_a_5xx_keeps_the_row_and_the_drain_moves_on(tmp_path, monkeypatch):
    s, _, _ = make(tmp_path)
    for i in (1, 2):
        s.store.enqueue("alert_posted", {"alert_id": i, "symbol": "A"})
    sent = []

    def api(base, t, p):
        sent.append(p["alert_id"])
        if p["alert_id"] == 1:
            raise Refused(503)
    monkeypatch.setattr(signals, "post_event", api)
    s.resend_events()
    assert sent == [1, 2] and [e["payload"]["alert_id"] for e in s.store.pending()] == [1]


def test_a_stale_alert_posted_is_dropped_and_a_fresh_one_is_sent(tmp_path, monkeypatch):
    s, _, _ = make(tmp_path)
    old = s.store.enqueue("alert_posted", {"alert_id": 1, "symbol": "A"})
    s.store.enqueue("alert_posted", {"alert_id": 2, "symbol": "B"})
    with s.store._conn() as conn:
        conn.execute("UPDATE event_queue SET created_at = created_at - 90000 WHERE id = ?", (old,))
    sent = []
    monkeypatch.setattr(signals, "post_event", lambda base, t, p: sent.append(p["alert_id"]))
    s.resend_events()
    assert sent == [2] and s.store.pending() == []


def test_the_payload_escalate_is_the_stored_one_including_the_night_ring(tmp_path):
    s, _, _ = make(tmp_path, NIGHT)
    s._raise(SNAP, price_alert(kind="earnings_followup", escalate=False, bias="down", confidence="high"))  # rings at night
    assert s.store.pending()[0]["payload"]["escalate"] is True
