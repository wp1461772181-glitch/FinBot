"""Telegram bridge: answers reach the owner, a bridge with no chat bound yet can bind one, and a message
Telegram cannot parse as Markdown still goes out."""
import asyncio

import httpx

from scripts import run_telegram_bridge as bridge

TOKEN = "123456789:AAH" + "x" * 32
OWNER_ID = 4242


def _command(chat_id, chat_type, sender_id, text):
    command = text.split()[0]
    return {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": sender_id}, "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}]}


def _record_sends(monkeypatch):
    sent = []

    async def send_text(client, bot_token, chat_id, text, inline_keyboard=None, *, markdown=True):
        sent.append((bot_token, chat_id, text))
        return 1000 + len(sent)

    monkeypatch.setattr(bridge, "_send_text", send_text)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    return sent


class _Telegram:
    def __init__(self):
        self.binds = []

        self.replies = []

    def confirm_bind(self, owner, code, chat_id, user_id):
        self.binds.append((code, chat_id, user_id))
        return {"bound": True}

    def route(self, owner, text, reply_to):
        if reply_to == 1001:
            return {"bot_id": "b-news", "bot_name": "抓新闻", "text": text, "via": "reply"}
        return {"bot_id": "b-default", "bot_name": "助理", "text": text, "via": "default"}

    def record_reply(self, owner, bot_id, text, message_id):
        self.replies.append((bot_id, message_id))


def test_the_owner_gets_an_answer_back_from_the_bot_the_message_was_for(monkeypatch):
    sent = _record_sends(monkeypatch)
    asked = []

    async def ask_agent(client, credential, bot_id, text):
        asked.append((bot_id, text))
        return "微软 FY2025 营收 2,817.24 亿美元 [1]", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    telegram = _Telegram()
    message = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": "去年微软营收多少"}
    asyncio.run(bridge._handle_message(None, "cred", "owner", message, OWNER_ID, OWNER_ID, {}, telegram))
    assert asked == [("b-default", "去年微软营收多少")]
    assert sent == [(TOKEN, OWNER_ID, "【助理】\n微软 FY2025 营收 2,817.24 亿美元 [1]")]
    assert telegram.replies == [("b-default", 1001)]
    # Replying to that message goes on with the bot that sent it (here the fake routes 1001 to the news bot).
    reply = {**message, "text": "细说", "reply_to_message": {"message_id": 1001}}
    asyncio.run(bridge._handle_message(None, "cred", "owner", reply, OWNER_ID, OWNER_ID, {}, telegram))
    assert asked[-1] == ("b-news", "细说") and sent[-1][2].startswith("【抓新闻】")


def test_an_unbound_bridge_binds_from_a_private_chat(monkeypatch):
    sent = _record_sends(monkeypatch)
    telegram = _Telegram()
    message = _command(OWNER_ID, "private", OWNER_ID, "/bind abcdef01")
    asyncio.run(bridge._handle_message(None, "cred", "owner", message, None, None, {}, telegram))
    assert telegram.binds == [("abcdef01", OWNER_ID, OWNER_ID)]
    assert sent[-1][2].startswith("绑定成功")


def test_an_unbound_bridge_ignores_everything_else(monkeypatch):
    sent = _record_sends(monkeypatch)
    telegram = _Telegram()
    question = {"chat": {"id": 7, "type": "private"}, "from": {"id": 7}, "text": "去年微软营收多少"}
    in_a_group = _command(-100, "group", 7, "/bind abcdef01")
    for message in (question, in_a_group):
        asyncio.run(bridge._handle_message(None, "cred", "owner", message, None, None, {}, telegram))
    assert telegram.binds == []
    assert [text for _, _, text in sent] == ["请在和 bot 的私聊里绑定。"]


def _client(statuses):
    class Client:
        def __init__(self):
            self.bodies = []

        async def post(self, url, json):
            self.bodies.append(dict(json))
            status = statuses[len(self.bodies) - 1]
            return httpx.Response(status, json={"ok": status == 200,
                                                "description": "Bad Request: can't parse entities"})

    return Client()


def test_markdown_telegram_cannot_parse_goes_out_as_plain_text():
    client = _client([400, 200])
    asyncio.run(bridge._send_text(client, TOKEN, OWNER_ID, "*营收* 同比 -14.93%，来源 \\[1\\]，FY2025_Q3"))
    first, second = client.bodies
    assert first["parse_mode"] == "Markdown" and "parse_mode" not in second
    assert second["text"] == "*营收* 同比 -14.93%，来源 [1]，FY2025_Q3"


def test_a_message_telegram_accepts_goes_out_once():
    client = _client([200])
    asyncio.run(bridge._send_text(client, TOKEN, OWNER_ID, "营收 2,817.24 亿美元"))
    assert len(client.bodies) == 1


def test_unverified_lines_carry_the_unverified_suffix_in_telegram():
    """The stream's unverified_lines are flagged in the chat text; sentences that checked out are untouched."""
    events = [
        ("delta", {"text": "AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。\n\n（另有 1 处表述未能与来源核对，已保留并标注“证据不足”。）"}),
        ("unverified_lines", {"items": [{"line": "AMD 成交量为 999 万股 [1]。", "reason": "unsupported_numeric_claim", "numbers": ["999 万"]}]}),
    ]
    answer, _, _ = bridge.format_turn(events)
    lines = answer.split("\n")
    assert lines[0] == "AMD 收盘价为 100 美元。"
    assert lines[1] == "AMD 成交量为 999 万股。（未核实）"
    assert "[1]" not in answer and answer.count("（未核实）") == 1


def test_a_table_row_and_a_bullet_get_the_suffix_too():
    from app.agent_telegram import chat_text
    flagged = [{"line": "| 成交量 | 999 万股 [1] |", "reason": "unsupported_numeric_claim", "numbers": []},
               {"line": "- 开盘价 998 美元 [1]", "reason": "unsupported_numeric_claim", "numbers": []}]
    text = "| 成交量 | 999 万股 [1] |\n- 开盘价 998 美元 [1]\n- 收盘价 100 美元 [1]"
    out = chat_text(text, flagged).split("\n")
    assert out[0].endswith("（未核实）") and out[1].endswith("（未核实）") and not out[2].endswith("（未核实）")


# --- Task 10: feedback while a turn runs --------------------------------------------------------------
import pytest  # noqa: E402


class _Wire:
    """Records the Telegram calls of a turn: typing, sends, edits."""

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


def _turn(bot_id="b-default", text="问"):
    return bridge._bot_turn(None, "cred", "owner", OWNER_ID, {}, _Telegram(), bot_id, "助理", text, feedback=True)


def test_typing_and_ack_before_answer(monkeypatch):
    wire = _Wire(monkeypatch)
    order = []

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        order.append(("asked", list(wire.actions), list(wire.sends)))
        return "答案", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(_turn())
    _, actions_at_ask, sends_at_ask = order[0]
    assert actions_at_ask == [(OWNER_ID, "typing")]          # typing is up before the model is asked
    assert sends_at_ask == [(OWNER_ID, bridge.ACK_TEXT)]      # and so is the placeholder
    assert wire.sends[-1][1] == "【助理】\n答案"                # the answer is a separate message
    assert wire.edits[-1][1] == bridge.DONE_TEXT


def test_typing_is_renewed_while_the_turn_runs(monkeypatch):
    wire = _Wire(monkeypatch)
    monkeypatch.setattr(bridge, "TYPING_INTERVAL", 0.02)

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        await asyncio.sleep(0.15)
        return "答案", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(_turn())
    assert len(wire.actions) >= 4
    count = len(wire.actions)
    asyncio.run(asyncio.sleep(0.1))
    assert len(wire.actions) == count                          # stopped with the turn


def test_progress_edits_are_throttled(monkeypatch):
    wire = _Wire(monkeypatch)
    monkeypatch.setattr(bridge, "PROGRESS_MIN_INTERVAL", 0.1)

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        for i in range(30):                                    # 30 step events in ~0.3 s
            await on_event("tool_start", {"name": f"tool_{i}"})
            await asyncio.sleep(0.01)
        return "答案", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(_turn())
    progress_edits = [e for e in wire.edits if e[1] != bridge.DONE_TEXT]
    assert 1 <= len(progress_edits) <= 4
    assert all("正在调用" in text for _, text in progress_edits)


def test_long_turn_does_not_block_other_bot_callback_or_outbox(monkeypatch):
    wire = _Wire(monkeypatch)
    release = asyncio.Event
    asked = []

    async def scenario():
        gate = asyncio.Event()

        async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
            asked.append(bot_id)
            if bot_id == "b-news":
                await gate.wait()
            return f"答:{bot_id}", [], "c-1"

        monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
        runner = bridge.TurnRunner()
        monkeypatch.setattr(bridge, "_RUNNER", runner)
        telegram = _Telegram()
        telegram.pending_messages = lambda owner, *a: [{"id": 1, "text": "提醒：INTC 急跌"}]
        telegram.mark_sent = lambda *a: None
        telegram.mark_failed = lambda *a: None
        # b-news starts a long turn (a reply to message 1001 routes to it)
        long_msg = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": "慢问题",
                    "reply_to_message": {"message_id": 1001}}
        await bridge._handle_message(None, "cred", "owner", long_msg, OWNER_ID, OWNER_ID, {}, telegram)
        await asyncio.sleep(0.05)
        assert "b-news" in asked and runner.busy("b-news")
        # meanwhile: another bot answers, a stray button press is handled, the outbox is delivered
        other = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": "快问题"}
        await bridge._handle_message(None, "cred", "owner", other, OWNER_ID, OWNER_ID, {}, telegram)
        answered = []

        async def answer_cb(client, token, cb_id, text=None):
            answered.append(cb_id)

        monkeypatch.setattr(bridge, "_answer_callback", answer_cb)
        cb = {"id": "cb1", "data": "zz:none", "from": {"id": OWNER_ID},
              "message": {"message_id": 9, "chat": {"id": OWNER_ID, "type": "private"}}}
        await bridge._handle_callback(None, cb, {}, "owner", "cred", OWNER_ID, OWNER_ID, telegram)
        await bridge._deliver_outbox(None, "owner", OWNER_ID, telegram)
        await asyncio.sleep(0.05)
        texts = [t for _, t in wire.sends]
        assert any(t.startswith("【助理】\n答:b-default") for t in texts)   # the other bot finished
        assert "提醒：INTC 急跌" in texts and answered == ["cb1"]            # outbox and callback went through
        assert not any(t.startswith("【助理】\n答:b-news") for t in texts)   # the long turn is still running
        gate.set()
        await runner.wait_idle()

    asyncio.run(scenario())


def test_same_bot_second_message_queued(monkeypatch):
    wire = _Wire(monkeypatch)
    log = []

    async def scenario():
        gate = asyncio.Event()

        async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
            log.append(("start", text))
            if text == "第一条":
                await gate.wait()
            log.append(("end", text))
            return f"答:{text}", [], "c-1"

        monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
        runner = bridge.TurnRunner()
        monkeypatch.setattr(bridge, "_RUNNER", runner)
        telegram = _Telegram()
        for text in ("第一条", "第二条"):
            msg = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": text}
            await bridge._handle_message(None, "cred", "owner", msg, OWNER_ID, OWNER_ID, {}, telegram)
            await asyncio.sleep(0.02)
        assert bridge.QUEUED_TEXT in [t for _, t in wire.sends]     # told at once
        assert log == [("start", "第一条")]                          # but not started yet
        gate.set()
        await runner.wait_idle()
        assert log == [("start", "第一条"), ("end", "第一条"), ("start", "第二条"), ("end", "第二条")]

    asyncio.run(scenario())


def test_conversation_busy_409_is_retried(monkeypatch):
    wire = _Wire(monkeypatch)
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    calls = []

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise bridge.ConversationBusy()
        return "答案", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(_turn())
    assert len(calls) == 3 and wire.sends[-1][1] == "【助理】\n答案"


def test_api_down_replies_quickly(monkeypatch):
    wire = _Wire(monkeypatch)

    class _DownClient:
        def stream(self, *a, **kw):
            raise httpx.ConnectError("refused")

    async def go():
        await bridge._bot_turn(_DownClient(), "cred", "owner", OWNER_ID, {}, _Telegram(), "b-default", "助理", "问",
                               feedback=True)

    started = __import__("time").monotonic()
    asyncio.run(go())
    assert __import__("time").monotonic() - started < 5
    assert wire.sends[-1][1] == bridge.BACKEND_DOWN_TEXT


def test_the_compress_command_compacts_the_bots_line_and_is_not_sent_to_the_model(monkeypatch):
    """「/压缩 重点」 (Task 15): the focus reaches the compact endpoint, the reply says what was done, and no model
    turn runs.  Telegram does not make 「/压缩」 a bot_command entity, but 「/compact」 is one and must not be eaten."""
    sent = _record_sends(monkeypatch)
    asked, posted = [], []

    async def ask_agent(client, credential, bot_id, text):
        asked.append(text)
        return "x", [], "c"

    class Client:
        async def post(self, url, json=None, headers=None, timeout=None):
            posted.append((url, json))
            return httpx.Response(200, json={"compacted": 7, "message": "已压缩 7 轮"})

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    telegram = _Telegram()
    plain = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": "/压缩 重点保留 Intel 的分析"}
    asyncio.run(bridge._handle_message(Client(), "cred", "owner", plain, OWNER_ID, OWNER_ID, {}, telegram))
    assert asked == [] and posted[-1][0].endswith("/agent-chat/bots/b-default/compact")
    assert posted[-1][1] == {"focus": "重点保留 Intel 的分析"}
    assert sent[-1][2] == "【助理】\n已压缩 7 轮"
    entity = _command(OWNER_ID, "private", OWNER_ID, "/compact")
    asyncio.run(bridge._handle_message(Client(), "cred", "owner", entity, OWNER_ID, OWNER_ID, {}, telegram))
    assert asked == [] and posted[-1][1] == {"focus": ""} and len(posted) == 2
    other = _command(OWNER_ID, "private", OWNER_ID, "/help")
    asyncio.run(bridge._handle_message(Client(), "cred", "owner", other, OWNER_ID, OWNER_ID, {}, telegram))
    assert len(posted) == 2                                                      # other commands are still ignored
