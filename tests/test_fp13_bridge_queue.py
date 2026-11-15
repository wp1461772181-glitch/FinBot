"""FP13-b (bridge): a Telegram turn that finds its conversation busy (the web page is answering) waits in line
instead of giving up after BUSY_RETRIES.  With FINBOT_FP13_TG_BUSY_QUEUE off the old retry count applies.
The request body never asks the server to detach the turn: the bridge keeps "disconnect cancels"."""
import asyncio
from types import SimpleNamespace

import httpx

from scripts import run_telegram_bridge as bridge

TOKEN = "123456789:AAH" + "x" * 32
OWNER_ID = 4242
FLAG = "FINBOT_FP13_TG_BUSY_QUEUE"
ANSWER_STREAM = (
    'event: conversation\ndata: {"conversation_id": "c-1"}\n\n'
    'event: delta\ndata: {"text": "答案"}\n\n'
).encode("utf-8")


class _Wire:
    """Records the Telegram calls of a turn: typing, sends, edits (the same shape as test_telegram_bridge_flow)."""

    def __init__(self, monkeypatch):
        self.actions, self.sends, self.edits = [], [], []

        async def send_text(client, token, chat_id, text, inline_keyboard=None, *, markdown=True):
            self.sends.append((chat_id, text))
            return 500 + len(self.sends)

        async def send_action(client, token, chat_id, action="typing"):
            self.actions.append((chat_id, action))

        async def edit_text(client, token, chat_id, message_id, text):
            self.edits.append((message_id, text))

        monkeypatch.setattr(bridge, "_send_text", send_text)
        monkeypatch.setattr(bridge, "_send_action", send_action)
        monkeypatch.setattr(bridge, "_edit_text", edit_text)
        monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)

    def texts(self):
        return [text for _, text in self.sends]


def _turn(text="问"):
    tg = SimpleNamespace(record_reply=lambda *args: None)
    return bridge._bot_turn(None, "cred", "owner", OWNER_ID, {}, tg, "b-default", "助理", text, feedback=True)


class _Response:
    def __init__(self, status, body=b""):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    async def aiter_bytes(self):
        yield self._body


class _Context:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *exc):
        return False


class _BusyThenOkClient:
    """The first stream answers 409 conversation_busy, the next one an answer.  Keeps every request body."""

    def __init__(self):
        self.bodies = []

    def stream(self, method, url, json=None, headers=None, timeout=None):
        self.bodies.append(dict(json))
        if len(self.bodies) == 1:
            return _Context(_Response(409))
        return _Context(_Response(200, ANSWER_STREAM))


def test_busy_turn_waits_in_line_and_the_answer_still_comes(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    wire = _Wire(monkeypatch)
    calls = []

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        calls.append(1)
        if len(calls) <= 8:
            raise bridge.ConversationBusy()
        return "答案", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(asyncio.wait_for(_turn(), 5))
    assert len(calls) == 9
    assert wire.texts().count(bridge.BUSY_WAITING_TEXT) == 1
    assert bridge.BUSY_GIVEUP_TEXT not in wire.texts()
    assert wire.texts()[-1] == "【助理】\n答案"


def test_a_turn_still_busy_past_the_wait_gives_up_with_the_old_text(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    monkeypatch.setattr(bridge, "BUSY_WAIT_SECONDS", 0.05)
    wire = _Wire(monkeypatch)
    calls = []

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        calls.append(1)
        raise bridge.ConversationBusy()

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(asyncio.wait_for(_turn(), 5))
    assert wire.texts().count(bridge.BUSY_WAITING_TEXT) == 1
    assert wire.texts()[-1] == bridge.BUSY_GIVEUP_TEXT


def test_with_the_queue_off_a_busy_turn_gets_the_old_retries_and_no_waiting_text(monkeypatch):
    monkeypatch.setenv(FLAG, "off")
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    wire = _Wire(monkeypatch)
    calls = []

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        calls.append(1)
        raise bridge.ConversationBusy()

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(asyncio.wait_for(_turn(), 5))
    assert len(calls) == bridge.BUSY_RETRIES + 1
    assert bridge.BUSY_WAITING_TEXT not in wire.texts()
    assert wire.texts()[-1] == bridge.BUSY_GIVEUP_TEXT


def test_the_wait_callback_stays_out_of_the_ask_and_the_request_never_asks_to_detach(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    real_ask = bridge._ask_agent
    seen_kwargs = []

    async def spy(client, credential, bot_id, text, **kw):
        seen_kwargs.append(set(kw))
        return await real_ask(client, credential, bot_id, text, **kw)

    monkeypatch.setattr(bridge, "_ask_agent", spy)
    waits = []

    async def on_busy():
        waits.append(1)

    client = _BusyThenOkClient()
    answer, _, cid = asyncio.run(asyncio.wait_for(
        bridge._ask_with_retry(client, "cred", "b-default", "问", on_busy=on_busy), 5))
    assert waits == [1]
    assert len(seen_kwargs) == 2 and all("on_busy" not in kw for kw in seen_kwargs)
    assert len(client.bodies) == 2 and all("detach" not in body for body in client.bodies)
    assert answer == "答案" and cid == "c-1"
