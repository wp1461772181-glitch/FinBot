"""5a review fixes: record rows and the digest, level seeding, escalation direction, reversal vs supersede, impact rule,
grouping market, default policy."""
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sentinel import signals, tiers
from sentinel.escalation import Escalator
from sentinel.main import Sentinel
from sentinel.store import Store

ET = ZoneInfo("America/New_York")
BJ = timezone(timedelta(hours=8))
SNAP = {"telegram": {"bot_token": "t", "chat_id": 1}, "pushover": {"user_key": "u", "app_token": "a"}}
INTC = {"daily_sigma": 0.075, "bucket_sigma": {}, "avg_vol5": {}}


def et(hour, minute, day=3):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET)


def bars(end, price, n=15):
    start = end - timedelta(minutes=n - 1)
    return [{"ts": start + timedelta(minutes=i), "close": price, "volume": 100} for i in range(n)]


class Notifier:
    def __init__(self):
        self.telegram, self.texts, self.cancelled, self.pushover = [], [], [], []

    def telegram_alert(self, config, text, alert_id):
        self.telegram.append(text)
        return 100 + len(self.telegram)

    def telegram_text(self, config, text):
        self.texts.append(text)
        return True

    def pushover_emergency(self, config, text):
        self.pushover.append(text)
        return f"r{len(self.pushover)}"

    def receipt_status(self, config, receipt):
        return {}

    def cancel_receipt(self, config, receipt):
        self.cancelled.append(receipt)


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", "tiers")
    monkeypatch.delenv("SENTINEL_SENSITIVITY", raising=False)

    def build(at=et(10, 0)):
        s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
        clock = [at.timestamp()]
        notifier = Notifier()
        s.escalator = Escalator(s.store, notifier, clock=lambda: clock[0])
        return s, notifier, clock
    return build


# --- 1: record rows only in the morning digest -------------------------------------------------------------------

def test_a_record_row_waits_for_the_0800_beijing_digest(make):
    s, n, clock = make(et(5, 30))                                    # 18:30 Beijing
    s.store.add_alert("INTC", "record", "INTC 较昨收涨 8.0%", False, clock[0], deferred=True, digest_text="INTC 较昨收涨 8.0%，没有单独提醒。")
    s.escalator.tick(SNAP)
    assert n.texts == []
    clock[0] = datetime(2026, 11, 4, 7, 59, tzinfo=BJ).timestamp()
    s.escalator.tick(SNAP)
    assert n.texts == []                                              # still night
    clock[0] = datetime(2026, 11, 4, 8, 0, tzinfo=BJ).timestamp()
    s.escalator.tick(SNAP)
    assert len(n.texts) == 1 and "昨天没有单独提醒的波动" in n.texts[0] and "昨夜" not in n.texts[0]
    s.escalator.tick(SNAP)
    assert len(n.texts) == 1


def test_a_night_alert_and_a_record_share_one_morning_message(make):
    s, n, clock = make(et(5, 30))
    s.store.add_alert("AAPL", "record", "x", False, clock[0], deferred=True, digest_text="AAPL 记录行")
    s.store.add_alert("INTC", "daily", "【值得知道】INTC", False, clock[0], deferred=True)
    clock[0] = datetime(2026, 11, 4, 8, 5, tzinfo=BJ).timestamp()
    s.escalator.tick(SNAP)
    assert len(n.texts) == 1 and "昨夜到现在没有直接打扰你的提醒" in n.texts[0] and "AAPL 记录行" in n.texts[0]


def test_a_night_alert_alone_still_goes_at_the_first_daytime_tick(make):
    s, n, clock = make(datetime(2026, 11, 3, 23, 0, tzinfo=BJ))
    s.store.add_alert("INTC", "daily", "【值得知道】INTC", False, clock[0], deferred=True)
    clock[0] = datetime(2026, 11, 4, 8, 0, tzinfo=BJ).timestamp()
    s.escalator.tick(SNAP)
    assert len(n.texts) == 1


# --- 2: level lock seeding ------------------------------------------------------------------------------------------

def test_a_stop_already_gapped_through_on_the_first_look_fires():
    fire, count, state = tiers.level_state(None, "plan_stop", 38.0, 36.0, 0.04, "2026-11-03", ref=40.0)
    assert fire and count == 1 and state["armed"] == 0
    fire, _, state = tiers.level_state(None, "plan_stop", 38.0, 36.0, 0.04, "2026-11-03", ref=37.0)   # it was already below
    assert not fire and state["armed"] == 0


def test_first_look_through_a_stop_gives_a_major_alert_via_the_sentinel(make):
    s, _, _ = make()
    snap = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 1_000_000.0,
            "plans": [{"symbol": "INTC", "stop_price": 38.0}]}
    out = s.alerts_from("INTC", True, et(9, 0), snap, bars(et(9, 0), 36.0), 40.0, INTC, [])
    stop = [a for a in out if a["kind"] == "plan_stop"]
    assert len(stop) == 1 and stop[0]["tier"] == 2 and stop[0]["escalate"] is True


def test_seed_uses_the_last_stored_price_before_it_is_overwritten(make):
    s, _, _ = make()
    snap = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 1_000_000.0,
            "plans": [{"symbol": "INTC", "stop_price": 38.0}]}
    s.store.set_price("INTC", 37.0)                                   # the owner last saw it below the stop already
    out = s.alerts_from("INTC", True, et(9, 0), snap, bars(et(9, 0), 36.0), 40.0, INTC, [])
    assert not [a for a in out if a["kind"] == "plan_stop"]


# --- 4: escalation direction ------------------------------------------------------------------------------------------

def test_a_major_up_move_is_pushed_but_does_not_ring_while_a_major_down_move_does(make):
    s, _, _ = make()
    snap = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 1_000_000.0}
    up = s.alerts_from("INTC", True, et(10, 0), snap, bars(et(10, 0), 54.0), 40.0, INTC, [])
    assert len(up) == 1 and up[0]["tier"] == 2 and up[0]["escalate"] is False
    down = s.alerts_from("INTC", True, et(10, 0, 4), snap, bars(et(10, 0, 4), 26.0), 40.0, INTC, [])
    assert len(down) == 1 and down[0]["tier"] == 2 and down[0]["escalate"] is True


# --- 5: a reversal does not supersede a ringing alert ----------------------------------------------------------------

def test_a_reversal_does_not_stop_the_ringing_of_the_major_alert(make):
    s, n, clock = make(et(10, 0))
    snap = {**SNAP, "positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 1_000_000.0}
    first = s.alerts_from("INTC", True, et(10, 0), snap, bars(et(10, 0), 30.0), 40.0, INTC, [])      # -25%
    s.flush(first, snap, et(10, 0).astimezone(UTC))
    first_id = s.store.alerts_where("symbol = 'INTC'")[0]["id"]
    s.store.update_alert(first_id, receipt="r9")
    clock[0] += 900
    rev = s.alerts_from("INTC", True, et(10, 15), snap, bars(et(10, 15), 36.0), 40.0, INTC, [])       # -10%: gave back > half
    assert [a["why"] for a in rev] == ["reversal"] and rev[0]["kind"] == "reversal"
    s.flush(rev, snap, et(10, 15).astimezone(UTC))
    row = s.store.alert(first_id)
    assert row["superseded_by"] is None and n.cancelled == []


# --- 6: impact rule ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("price, held, expect", [
    (95.4, True, (0, "")),                 # 0.9 sigma, impact 2.3%: impact alone is not pushed (11-26 replay)
    (89.0, True, (2, "impact")),           # 2.2 sigma and impact over 2%
    (89.0, False, (1, "sigma")),
    (99.0, True, (0, "")),                 # tiny
])
def test_impact_rule(price, held, expect):
    m = tiers.measure(price, 100.0, 0.05, shares=50, total_assets=10000 if price != 99.0 else 1_000_000)
    assert tiers.tier_rule(m, "standard", held) == expect
    assert tiers.tier_rule(tiers.measure(80.0, 100.0, 0.05, shares=1, total_assets=1e9), "standard", True) == (2, "sigma_major")


def test_an_ordinary_day_of_a_big_holding_is_not_pushed_on_impact_alone(make):
    s, _, _ = make()
    snap = {"positions": [{"symbol": "INTC", "shares": 100.0}], "total_assets": 13135.0}
    out = s.alerts_from("INTC", True, et(10, 0), snap, bars(et(10, 0), 38.0), 40.0, INTC, [])      # -5%: 0.67 sigma, 1.5% ... 
    assert out == []                                                  # 1.5% of assets: under the 2% line
    out = s.alerts_from("INTC", True, et(10, 5), snap, bars(et(10, 5), 37.0), 40.0, INTC, [])       # -7.5%: 1 sigma, 2.3% of assets
    assert out == []                                                  # 1 sigma, 2.3% of assets: its ordinary day, digest only


# --- 8: grouping market -----------------------------------------------------------------------------------------------

def test_grouping_takes_the_market_from_the_first_member_that_has_it(make):
    s, _, _ = make()
    rec = []
    s.escalator = type("R", (), {"raise_alert": lambda self, snap, a: rec.append(a) or len(rec), "deferred": lambda self, i: False})()

    def c(symbol, market):
        return {"symbol": symbol, "kind": "daily", "direction": "down", "held": False, "text": symbol, "escalate": False,
                "weight_pct": None, "price_move": True, "trigger": "", "event_date": None, "tier": 1, "why": "first",
                "sigma_mult": 2.0, "r": -0.05, "impact_pct": None, "market_r": market, "market_sigma": 0.01,
                "after_send": lambda d, a: None, "rollback": lambda: None}
    s.flush([c("A", None), c("B", -0.02), c("C", -0.02)], {}, et(10, 0).astimezone(UTC))
    assert len(rec) == 1 and rec[0]["kind"] == "merged"


# --- 10: default policy -----------------------------------------------------------------------------------------------

def test_the_default_policy_is_tiers(tmp_path, monkeypatch):
    monkeypatch.delenv("SENTINEL_ALERT_POLICY", raising=False)
    s = Sentinel(config=signals.SnapshotConfig(tmp_path / "none.json"), store=Store(tmp_path / "s.db"))
    assert s._policy() == "tiers"
    monkeypatch.setenv("SENTINEL_ALERT_POLICY", "anchor")
    assert s._policy() == "anchor"
