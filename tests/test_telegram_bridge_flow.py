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


def test_unverified_lines_no_longer_carry_the_unverified_suffix_in_telegram():
    """WP0 step 8: the stream sends no unverified lines any more, so Telegram adds no 「（未核实）」 suffix; the
    sentences are delivered as written."""
    events = [
        ("delta", {"text": "AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。"}),
        ("unverified_lines", {"items": [{"line": "AMD 成交量为 999 万股 [1]。", "reason": "unsupported_numeric_claim", "numbers": ["999 万"]}]}),
    ]
    answer, _, _ = bridge.format_turn(events)
    lines = answer.split("\n")
    assert lines[0] == "AMD 收盘价为 100 美元。"
    assert lines[1] == "AMD 成交量为 999 万股。"
    assert "[1]" not in answer and "（未核实）" not in answer


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


def test_same_bot_second_message_is_posted_at_once_and_a_409_queues_it(monkeypatch):
    wire = _Wire(monkeypatch)
    log = []

    async def scenario():
        gate = asyncio.Event()
        refused = []

        async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
            log.append(("start", text))
            if text == "第一条":
                await gate.wait()
            elif not refused:
                refused.append(1)               # an engine that cannot take a second message answers 409
                raise bridge.ConversationBusy()
            log.append(("end", text))
            return f"答:{text}", [], "c-1"

        monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
        monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
        runner = bridge.TurnRunner()
        monkeypatch.setattr(bridge, "_RUNNER", runner)
        telegram = _Telegram()
        for text in ("第一条", "第二条"):
            msg = {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": text}
            await bridge._handle_message(None, "cred", "owner", msg, OWNER_ID, OWNER_ID, {}, telegram)
            await asyncio.sleep(0.02)
        assert bridge.QUEUED_TEXT in [t for _, t in wire.sends]     # told at once
        assert log == [("start", "第一条"), ("start", "第二条")]     # posted at once, refused, now waiting its turn
        gate.set()
        await runner.wait_idle()
        assert log == [("start", "第一条"), ("start", "第二条"), ("end", "第一条"), ("start", "第二条"), ("end", "第二条")]

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


# --- 5c-3b: 「有用／没用」 on alerts and duty messages ----------------------------------------------------------
from app import alert_feedback  # noqa: E402

GROUP = "6f1c2a4e-1b2c-4d5e-8f90-0a1b2c3d4e5f"
ROW = "0d9e8f7a-6b5c-4d3e-9f2a-1b0c9d8e7f6a"
ACK_ROW = [{"text": "收到", "callback_data": "ack:7"}]
ALERT_FEEDBACK_ROW = [{"text": "有用", "callback_data": "fu:s:7"}, {"text": "没用", "callback_data": "fn:s:7"}]


def _outbox_row(group):
    return [{"text": "有用", "callback_data": f"fu:o:{group}"}, {"text": "没用", "callback_data": f"fn:o:{group}"}]


class _FeedbackStore:
    """``alert_feedback`` with the real parser and a recorded store; ``fail`` makes the write raise."""
    SOURCES = alert_feedback.SOURCES
    parse_callback = staticmethod(alert_feedback.parse_callback)

    def __init__(self, fail=False):
        self.records, self.fail = [], fail

    def describe(self, owner, target, target_id):
        return {"symbol": "INTC", "kind": "short", "text": "INTC 急跌"}

    def record(self, owner, target, target_id, verdict, channel, **about):
        if self.fail:
            raise RuntimeError("db down")
        self.records.append((owner, target, target_id, verdict, channel, about))
        return {"verdict": verdict}


def _press_wire(monkeypatch, store=None):
    """Telegram recorded: the callback answers (toasts) and the keyboard edits (posts)."""
    calls = {"toasts": [], "posts": []}

    class Client:
        async def post(self, url, json=None):
            calls["posts"].append((url.rsplit("/", 1)[-1], json))

    async def answer(client, token, cb_id, text=None):
        calls["toasts"].append(text)

    async def nothing(*a, **k):
        pass

    monkeypatch.setattr(bridge, "_answer_callback", answer)
    monkeypatch.setattr(bridge, "_acknowledge", nothing)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    monkeypatch.setattr(bridge, "alert_feedback", store or _FeedbackStore())
    return Client(), calls


def _keyboard_press(data, keyboard):
    return {"id": "cb-1", "data": data, "from": {"id": OWNER_ID},
            "message": {"message_id": 55, "chat": {"id": OWNER_ID, "type": "private"}, "reply_markup": {"inline_keyboard": keyboard}}}


def _press(client, callback):
    asyncio.run(bridge._handle_callback(client, callback, {}, "owner", "cred", OWNER_ID, OWNER_ID, _Telegram()))


def _edit(rows):
    return ("editMessageReplyMarkup", {"chat_id": OWNER_ID, "message_id": 55, "reply_markup": {"inline_keyboard": rows}})


def test_duty_and_brief_messages_go_out_with_the_feedback_row_and_a_notify_without(monkeypatch):
    sent = []

    async def send_text(client, token, chat_id, text, inline_keyboard=None, *, markdown=True):
        sent.append((text, inline_keyboard, markdown))
        return 900 + len(sent)

    monkeypatch.setattr(bridge, "_send_text", send_text)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    telegram = _Telegram()
    telegram.pending_messages = lambda owner, *a: [
        {"id": "a1", "text": "值班", "source": "duty", "group_id": GROUP},
        {"id": ROW, "text": "简报", "source": "brief", "group_id": None},           # no group: its own id
        {"id": "a3", "text": "提醒", "source": "notify", "group_id": GROUP}]
    marked = []
    telegram.mark_sent = lambda *a: marked.append(a)
    telegram.mark_failed = lambda *a: None
    asyncio.run(bridge._send_queued(None, "owner", OWNER_ID, telegram, None))
    assert sent == [("值班", [_outbox_row(GROUP)], False), ("简报", [_outbox_row(ROW)], False), ("提醒", None, False)]
    assert [a[0] for a in marked] == ["a1", ROW, "a3"]


def _acks(monkeypatch, fail=False):
    acked = []

    def ack_alert(self, alert_id):
        if fail:
            raise OSError("locked")
        acked.append(alert_id)
    monkeypatch.setattr(bridge, "_sentinel_store", lambda: type("S", (), {"ack_alert": ack_alert})())
    return acked


@pytest.mark.parametrize("data,keyboard,recorded,toast,left", [
    # on a sentinel alert a press also counts as 收到: the ack row goes, the chosen button is ticked
    ("fu:s:7", [ACK_ROW, ALERT_FEEDBACK_ROW], ("sentinel", "7", "useful"), "记下了：有用，已确认", [bridge._feedback_row("sentinel", "7", "useful")]),
    ("fn:s:7", [ACK_ROW, ALERT_FEEDBACK_ROW], ("sentinel", "7", "not_useful"), "记下了：没用，已确认", [bridge._feedback_row("sentinel", "7", "not_useful")]),
    ("fu:s:7", [ALERT_FEEDBACK_ROW], ("sentinel", "7", "useful"), "记下了：有用，已确认", [bridge._feedback_row("sentinel", "7", "useful")]),
    (f"fu:o:{GROUP}", [_outbox_row(GROUP)], ("outbox", GROUP, "useful"), "记下了：有用", [bridge._feedback_row("outbox", GROUP, "useful")]),
    (f"fn:o:{GROUP}", [_outbox_row(GROUP)], ("outbox", GROUP, "not_useful"), "记下了：没用", [bridge._feedback_row("outbox", GROUP, "not_useful")]),
])
def test_a_feedback_press_records_and_ticks_the_chosen_button(monkeypatch, data, keyboard, recorded, toast, left):
    store = _FeedbackStore()
    client, calls = _press_wire(monkeypatch, store)
    acked = _acks(monkeypatch)
    _press(client, _keyboard_press(data, keyboard))
    assert store.records == [("owner", *recorded, "telegram", {"symbol": "INTC", "kind": "short", "text": "INTC 急跌"})]
    assert calls["toasts"] == [toast] and calls["posts"] == [_edit(left)]
    assert acked == ([7] if recorded[0] == "sentinel" else [])


def test_pressing_the_other_button_changes_the_verdict(monkeypatch):
    store = _FeedbackStore()
    client, calls = _press_wire(monkeypatch, store)
    _acks(monkeypatch)
    _press(client, _keyboard_press(f"fn:o:{GROUP}", [bridge._feedback_row("outbox", GROUP, "useful")]))
    assert store.records[-1][3] == "not_useful" and calls["posts"] == [_edit([bridge._feedback_row("outbox", GROUP, "not_useful")])]
    assert bridge._feedback_row("outbox", GROUP, "useful")[0]["text"] == "✓ 有用"


def test_a_press_without_the_keyboard_records_and_edits_nothing(monkeypatch):
    store = _FeedbackStore()
    client, calls = _press_wire(monkeypatch, store)
    _acks(monkeypatch)
    callback = _keyboard_press("fu:s:7", [])
    del callback["message"]["reply_markup"]
    _press(client, callback)
    assert len(store.records) == 1 and calls["posts"] == []


def test_a_failed_ack_on_a_feedback_press_keeps_the_ack_row(monkeypatch):
    store = _FeedbackStore()
    client, calls = _press_wire(monkeypatch, store)
    _acks(monkeypatch, fail=True)
    _press(client, _keyboard_press("fu:s:7", [ACK_ROW, ALERT_FEEDBACK_ROW]))
    assert calls["toasts"] == ["记下了：有用"] and calls["posts"] == [_edit([ACK_ROW, bridge._feedback_row("sentinel", "7", "useful")])]


@pytest.mark.parametrize("keyboard,left", [([ACK_ROW, ALERT_FEEDBACK_ROW], [ALERT_FEEDBACK_ROW]), ([ACK_ROW], [])])
def test_ack_takes_off_only_the_ack_row(monkeypatch, keyboard, left):
    client, calls = _press_wire(monkeypatch)
    acked = []
    monkeypatch.setattr(bridge, "_sentinel_store", lambda: type("S", (), {"ack_alert": lambda self, alert_id: acked.append(alert_id)})())
    _press(client, _keyboard_press("ack:7", keyboard))
    assert acked == [7] and calls["toasts"] == ["已确认"] and calls["posts"] == [_edit(left)]


@pytest.mark.parametrize("data", ["fu:s:abc", "fn:s:", "fu:o:not-a-uuid", "fu:x:7", "fu:s:7:8", "fu:o:" + "a" * 100, "fx:s:1"])
def test_a_button_it_cannot_read_records_nothing(monkeypatch, data):
    store = _FeedbackStore()
    client, calls = _press_wire(monkeypatch, store)
    _press(client, _keyboard_press(data, [ACK_ROW, ALERT_FEEDBACK_ROW]))
    assert store.records == [] and calls["toasts"] == ["看不懂这个按钮"] and calls["posts"] == []


def test_a_failed_write_leaves_the_keyboard_and_asks_for_another_press(monkeypatch):
    client, calls = _press_wire(monkeypatch, _FeedbackStore(fail=True))
    _press(client, _keyboard_press("fu:s:7", [ACK_ROW, ALERT_FEEDBACK_ROW]))
    assert calls["toasts"] == ["没有记上，请再点一次。"] and calls["posts"] == []
