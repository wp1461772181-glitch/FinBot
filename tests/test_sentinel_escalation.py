"""Task 12: unacknowledged alerts escalate (Pushover emergency by day, rules by night, Telegram resend without
Pushover); an acknowledgement stops everything; alerts never touch a bot's daily_notify_cap."""
from datetime import UTC, datetime, timedelta, timezone

from sentinel.escalation import Escalator
from sentinel.store import Store

BJ = timezone(timedelta(hours=8))
DAY = datetime(2026, 11, 3, 10, 0, tzinfo=BJ).timestamp()
SNAP_BOTH = {"telegram": {"bot_token": "t", "chat_id": 1}, "pushover": {"user_key": "u", "app_token": "a"}}
SNAP_TG_ONLY = {"telegram": {"bot_token": "t", "chat_id": 1}, "pushover": {}}


class FakeNotifier:
    def __init__(self):
        self.telegram, self.texts, self.pushover, self.cancelled = [], [], [], []
        self.acknowledged = set()

    def telegram_alert(self, config, text, alert_id):
        self.telegram.append((alert_id, text))
        return 1000 + len(self.telegram)

    def telegram_text(self, config, text):
        self.texts.append(text)
        return True

    def pushover_emergency(self, config, text):
        self.pushover.append(text)
        return f"receipt{len(self.pushover)}"

    def receipt_status(self, config, receipt):
        return {"acknowledged": receipt in self.acknowledged}

    def cancel_receipt(self, config, receipt):
        self.cancelled.append(receipt)


def make(tmp_path, at):
    clock = [at]
    notifier = FakeNotifier()
    return Escalator(Store(tmp_path / "s.db"), notifier, clock=lambda: clock[0]), notifier, clock


def drop(symbol="INTC", weight=4.0, **extra):
    base = {"symbol": symbol, "kind": "short", "direction": "down", "held": True, "text": f"{symbol} 急跌",
            "escalate": True, "weight_pct": weight, "earnings_unacked": False}
    return base | extra


def test_day_escalates_after_one_minute(tmp_path):
    esc, n, clock = make(tmp_path, DAY)
    alert_id = esc.raise_alert(SNAP_BOTH, drop())
    assert [a for a, _ in n.telegram] == [alert_id] and n.pushover == []     # Telegram first, with the button
    clock[0] += 59
    esc.tick(SNAP_BOTH)
    assert n.pushover == []
    clock[0] += 2
    esc.tick(SNAP_BOTH)
    assert len(n.pushover) == 1
    esc.tick(SNAP_BOTH)
    assert len(n.pushover) == 1                                              # one emergency per alert; Pushover repeats it


def test_ack_stops_escalation(tmp_path):
    esc, n, clock = make(tmp_path, DAY)
    alert_id = esc.raise_alert(SNAP_BOTH, drop())
    clock[0] += 30
    esc.store.ack_alert(alert_id)                                            # what the bridge does on the button press
    clock[0] += 60
    esc.tick(SNAP_BOTH)
    assert n.pushover == []
    # acknowledged on the phone after the emergency went out: polling the receipt syncs it and nothing else rings
    other = esc.raise_alert(SNAP_BOTH, drop("AAPL"))
    clock[0] += 61
    esc.tick(SNAP_BOTH)
    assert len(n.pushover) == 1
    n.acknowledged.add("receipt1")
    esc.tick(SNAP_BOTH)
    assert esc.store.alert(other)["acked_at"] is not None
    # a Telegram acknowledgement cancels a ringing emergency
    third = esc.raise_alert(SNAP_BOTH, drop("NVDA"))
    clock[0] += 61
    esc.tick(SNAP_BOTH)
    esc.store.ack_alert(third)
    esc.tick(SNAP_BOTH)
    assert n.cancelled == ["receipt2"]


def test_reply_to_the_alert_message_acks(tmp_path):
    esc, n, _ = make(tmp_path, DAY)
    alert_id = esc.raise_alert(SNAP_BOTH, drop())
    message_id = esc.store.alert(alert_id)["tg_message_id"]
    assert esc.store.ack_by_message(1, message_id) == alert_id
    assert esc.store.ack_by_message(1, 424242) is None


def test_non_escalating_alerts_are_sent_once(tmp_path):
    esc, n, clock = make(tmp_path, DAY)
    esc.raise_alert(SNAP_BOTH, drop(direction="up", escalate=False))
    clock[0] += 600
    esc.tick(SNAP_BOTH)
    assert len(n.telegram) == 1 and n.pushover == []


def test_earnings_unacked_escalates_at_once(tmp_path):
    esc, n, _ = make(tmp_path, DAY)
    esc.raise_alert(SNAP_BOTH, drop(earnings_unacked=True))
    assert len(n.pushover) == 1


def test_night_rules(tmp_path):
    night = datetime(2026, 11, 3, 3, 0, tzinfo=BJ).timestamp()
    esc, n, clock = make(tmp_path, night)
    esc.raise_alert(SNAP_BOTH, drop("AAPL", weight=4.0))                      # a fall, but a small position: waits for 8:00
    esc.raise_alert(SNAP_BOTH, drop("NVDA", direction="up", escalate=False))
    assert n.telegram == [] and n.pushover == []
    clock[0] += 3600
    esc.tick(SNAP_BOTH)
    assert n.telegram == [] and n.pushover == []
    esc.raise_alert(SNAP_BOTH, drop("INTC", weight=12.0))                     # held, >=10% of the book: rings now
    assert len(n.pushover) == 1
    esc.raise_alert(SNAP_BOTH, {"symbol": "MSFT", "kind": "earnings_followup", "held": True, "text": "MSFT 财报追加",
                                "escalate": False, "bias": "down", "confidence": "high"})
    assert len(n.pushover) == 2
    esc.raise_alert(SNAP_BOTH, {"symbol": "ORCL", "kind": "earnings_followup", "held": True, "text": "ORCL 财报追加",
                                "escalate": False, "bias": "down", "confidence": "medium"})
    assert len(n.pushover) == 2
    # 7:59 is still night, 8:00 releases one digest of what was held back
    clock[0] = datetime(2026, 11, 3, 7, 59, tzinfo=BJ).timestamp()
    esc.tick(SNAP_BOTH)
    assert n.texts == []
    clock[0] = datetime(2026, 11, 3, 8, 0, tzinfo=BJ).timestamp()
    esc.tick(SNAP_BOTH)
    assert len(n.texts) == 1 and all(s in n.texts[0] for s in ("AAPL", "NVDA", "ORCL"))
    esc.tick(SNAP_BOTH)
    assert len(n.texts) == 1
    # 0:00 is already night
    midnight = datetime(2026, 11, 4, 0, 0, tzinfo=BJ).timestamp()
    esc2, n2, _ = make(tmp_path / "b", midnight)
    esc2.raise_alert(SNAP_BOTH, drop("AAPL", weight=1.0))
    assert n2.telegram == []


def test_no_pushover_falls_back_to_telegram(tmp_path):
    esc, n, clock = make(tmp_path, DAY)
    esc.raise_alert(SNAP_TG_ONLY, drop())
    for minute in range(1, 21):
        clock[0] = DAY + minute * 60
        esc.tick(SNAP_TG_ONLY)
    assert n.pushover == []
    assert len(n.telegram) == 4                                               # the alert plus three resends, 5 minutes apart
    assert all("急跌" in text for _, text in n.telegram)


def test_alerts_ignore_daily_cap(tmp_path):
    # Alerts go straight from the sentinel to Telegram; they never pass the bot's notify queue, so a cap of 5
    # cannot swallow the sixth.
    esc, n, _ = make(tmp_path, DAY)
    for i in range(8):
        esc.raise_alert(SNAP_BOTH, drop(f"S{i}"))
    assert len(n.telegram) == 8


def test_bridge_button_and_reply_write_the_ack(tmp_path, monkeypatch):
    """The bridge side: 「收到」and a reply to the alert message both land in sentinel.db."""
    import asyncio

    from scripts import run_telegram_bridge as bridge

    store = Store(tmp_path / "s.db")
    first = store.add_alert("INTC", "short", "INTC 急跌", True, DAY)
    second = store.add_alert("AAPL", "short", "AAPL 急跌", True, DAY)
    store.update_alert(second, tg_message_id=777, tg_chat_id=42)
    monkeypatch.setattr(bridge, "_sentinel_store", lambda: store)
    answers, cleared = [], []

    async def answer(client, token, cb_id, text=None):
        answers.append(text)

    async def clear(client, token, chat_id, message_id):
        cleared.append(message_id)

    monkeypatch.setattr(bridge, "_answer_callback", answer)
    monkeypatch.setattr(bridge, "_clear_keyboard", clear)
    callback = {"id": "cb1", "data": f"ack:{first}", "from": {"id": 42},
                "message": {"chat": {"id": 42, "type": "private"}, "message_id": 5}}
    asyncio.run(bridge._handle_callback(None, callback, {}, "owner", "cred", 42, 42, tg=object(), channel={"token": "t"}))
    assert store.alert(first)["acked_at"] is not None and cleared == [5] and answers == ["已确认"]
    assert asyncio.run(bridge._ack_by_reply(42, 777)) is True and store.alert(second)["acked_at"] is not None
    assert asyncio.run(bridge._ack_by_reply(42, 1)) is False
