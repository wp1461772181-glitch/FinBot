"""The Telegram bridge's outbox cycle sends first and sweeps stuck rows afterwards, and an owner message or button press
acknowledges the channel.  Sending itself is unchanged."""
import asyncio
import types

import pytest

from scripts import run_telegram_bridge as bridge

OWNER_ID = 4242


class FakeChannels:
    def __init__(self):
        self.calls = []

    def expire_stuck(self, owner):
        self.calls.append(("expire_stuck", owner))
        return 0

    def acknowledge(self, owner, channel, now=None, seen_at=None):
        self.calls.append(("acknowledge", owner, channel))
        self.seen_at = seen_at
        return 0


@pytest.fixture
def fake(monkeypatch):
    f = FakeChannels()
    monkeypatch.setattr(bridge, "channels", f)
    return f


class Tg:
    def __init__(self, rows=()):
        self.rows, self.sent, self.failed = list(rows), [], []

    def pending_messages(self, owner, limit=20, bot_row_id=None):
        return list(self.rows)

    def mark_sent(self, message_id, external_id=None):
        self.sent.append((message_id, external_id))

    def mark_failed(self, message_id):
        self.failed.append(message_id)

    def route(self, owner, text, reply_to):
        return {"bot_id": "b", "bot_name": "助理", "text": text, "via": "default"}

    def record_reply(self, *a):
        pass


def _wire(monkeypatch, result=555):
    sends = []

    async def send_text(client, token, chat_id, text, inline_keyboard=None, *, markdown=True):
        sends.append((chat_id, text, markdown))
        return result
    monkeypatch.setattr(bridge, "_send_text", send_text)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, module: "tok")
    return sends


def test_the_outbox_cycle_sweeps_after_sending(monkeypatch, fake):
    sends = _wire(monkeypatch)
    tg = Tg([{"id": "m1", "text": "提醒"}])
    asyncio.run(bridge._deliver_outbox(None, "owner", OWNER_ID, tg))
    assert fake.calls == [("expire_stuck", "owner")]
    assert sends == [(OWNER_ID, "提醒", False)] and tg.sent == [("m1", 555)] and tg.failed == []


def test_the_sweep_runs_after_the_send_and_even_when_the_send_raises(monkeypatch, fake):
    order = []
    fake.expire_stuck = lambda owner: order.append("sweep")
    tg = Tg([{"id": "m1", "text": "提醒"}])
    tg.mark_sent = lambda *a: order.append("sent")
    _wire(monkeypatch)
    asyncio.run(bridge._deliver_outbox(None, "owner", OWNER_ID, tg))
    assert order == ["sent", "sweep"]

    async def boom(*a, **k):
        raise RuntimeError("send blew up")
    monkeypatch.setattr(bridge, "_send_text", boom)
    order.clear()
    with pytest.raises(RuntimeError):
        asyncio.run(bridge._deliver_outbox(None, "owner", OWNER_ID, tg))
    assert order == ["sweep"]


def test_a_failed_send_is_marked_as_before(monkeypatch, fake):
    _wire(monkeypatch, result=None)
    tg = Tg([{"id": "m1", "text": "提醒"}])
    asyncio.run(bridge._deliver_outbox(None, "owner", OWNER_ID, tg))
    assert tg.failed == ["m1"] and tg.sent == []


def test_a_failing_expiry_sweep_does_not_stop_the_sends(monkeypatch, fake):
    sends = _wire(monkeypatch)

    def boom(owner):
        raise RuntimeError("db down")
    fake.expire_stuck = boom
    tg = Tg([{"id": "m1", "text": "提醒"}])
    asyncio.run(bridge._deliver_outbox(None, "owner", OWNER_ID, tg))
    assert tg.sent == [("m1", 555)]


def test_an_owner_message_acknowledges_telegram(monkeypatch, fake):
    _wire(monkeypatch)

    async def ask_agent(*a, **k):
        return "答", [], None
    monkeypatch.setattr(bridge, "_ask_agent", ask_agent, raising=False)
    msg = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": "/start"}
    asyncio.run(bridge._handle_message(None, "cred", "owner", {**msg, "text": "你好", "date": 1_780_000_000}, OWNER_ID, OWNER_ID, {}, Tg()))
    assert ("acknowledge", "owner", "telegram") in fake.calls
    assert fake.seen_at.timestamp() == 1_780_000_000      # the message's own time, not the time it was read


def test_a_message_from_someone_else_does_not_acknowledge(monkeypatch, fake):
    _wire(monkeypatch)
    msg = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": 999}, "text": "你好"}
    asyncio.run(bridge._handle_message(None, "cred", "owner", msg, OWNER_ID, OWNER_ID, {}, Tg()))
    assert not [c for c in fake.calls if c[0] == "acknowledge"]


def test_a_button_press_from_the_owner_acknowledges(monkeypatch, fake):
    async def answer_cb(client, token, cb_id, text=None):
        pass
    monkeypatch.setattr(bridge, "_answer_callback", answer_cb)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, module: "tok")
    cb = {"id": "cb1", "data": "zz:none", "from": {"id": OWNER_ID},
          "message": {"message_id": 9, "chat": {"id": OWNER_ID, "type": "private"}}}
    asyncio.run(bridge._handle_callback(None, cb, {}, "owner", "cred", OWNER_ID, OWNER_ID, Tg()))
    assert ("acknowledge", "owner", "telegram") in fake.calls
    assert abs(fake.seen_at.timestamp() - __import__("time").time()) < 30      # a button press counts from now


def test_a_button_press_from_someone_else_does_not(monkeypatch, fake):
    cb = {"id": "cb1", "data": "zz:none", "from": {"id": 999},
          "message": {"message_id": 9, "chat": {"id": OWNER_ID, "type": "private"}}}
    asyncio.run(bridge._handle_callback(None, cb, {}, "owner", "cred", OWNER_ID, OWNER_ID, Tg()))
    assert not [c for c in fake.calls if c[0] == "acknowledge"]
