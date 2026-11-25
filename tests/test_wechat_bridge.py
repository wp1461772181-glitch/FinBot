"""WeChat bridge: only the owner is answered, the answer goes back with the message's context token, a write card
is pointed at the web page, a stale login pauses, and the login file is owner-only."""
import asyncio
import json
import os
import stat

import pytest

from app import agent_wechat as wx
from scripts import run_wechat_bridge as bridge

OWNER_ID = "o9owner@im.wechat"
STRANGER_ID = "o9stranger@im.wechat"


class FakeIlink:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    async def send_text(self, to_user, text, context_token=None):
        self.sent.append((to_user, text, context_token))
        return self.fail or {"ret": 0}


class FakeChannels:
    """Stands in for app.channels: records the calls, serves the queued rows."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def expire_stuck(self, owner):
        self.calls.append(("expire_stuck", owner))
        return 0

    def pending(self, owner, channel, limit=20, telegram_bot_row_id=None):
        self.calls.append(("pending", owner, channel))
        return list(self.rows)

    def mark_sent(self, message_id, external_id=None):
        self.calls.append(("mark_sent", message_id))

    def mark_failed(self, message_id, code="send_failed"):
        self.calls.append(("mark_failed", message_id, code))

    def mark_partial(self, message_id):
        self.calls.append(("mark_partial", message_id))

    def claim(self, message_id, now=None):
        self.calls.append(("claim", message_id))

    def acknowledge(self, owner, channel, now=None, seen_at=None):
        self.calls.append(("acknowledge", owner, channel))
        self.seen_at = seen_at
        return 0


@pytest.fixture(autouse=True)
def fake_channels(monkeypatch):
    fake = FakeChannels()
    monkeypatch.setattr(bridge, "channels", fake)
    return fake


def _state():
    return wx.new_state(bot_token="secret-token", baseurl="https://ilinkai.weixin.qq.com", bot_id="bot@im.bot",
                        owner_user_id=OWNER_ID)


def _message(text="英伟达财报怎么样", sender=OWNER_ID, token="ctx-1", kind=1, items=None):
    return {"message_type": kind, "from_user_id": sender, "context_token": token,
            "item_list": items if items is not None else [{"type": 1, "text_item": {"text": text}}]}


def _route(owner, text, reply_to=None):
    if text.startswith("@研究员"):
        return {"bot_id": "bot-2", "bot_name": "研究员", "text": text[4:].strip(), "via": "mention"}
    return {"bot_id": "bot-1", "bot_name": "助理", "text": text, "via": "default"}


def _make(ask, ilink=None):
    ilink = ilink or FakeIlink()
    state = _state()
    return bridge.Bridge(ilink, state, owner="owner-hash", route=_route, ask=ask), ilink, state


async def _drain(b):
    while b.tasks:
        await asyncio.gather(*list(b.tasks))


def run(coro):
    return asyncio.run(coro)


def test_owner_message_is_answered_with_the_message_context_token():
    calls = []

    async def ask(bot_id, text, on_event=None):
        calls.append((bot_id, text))
        return "营收 **同比增长**。", [], "cid-1"

    async def go():
        b, ilink, state = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink, state

    ilink, state = run(go())
    assert calls == [("bot-1", "英伟达财报怎么样")]
    assert ilink.sent == [(OWNER_ID, "营收 同比增长。", "ctx-1")]
    assert state["context_tokens"][OWNER_ID] == "ctx-1"


def test_stranger_and_bot_messages_are_ignored():
    async def ask(bot_id, text, on_event=None):
        raise AssertionError("must not run a turn")

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message(sender=STRANGER_ID))
        await b.handle(_message(kind=2))
        await _drain(b)
        return ilink

    assert run(go()).sent == []


def test_mention_routes_to_that_bot_and_names_it():
    async def ask(bot_id, text, on_event=None):
        assert (bot_id, text) == ("bot-2", "看下 AMD")
        return "好的。", [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message("@研究员 看下 AMD"))
        await _drain(b)
        return ilink

    assert run(go()).sent[0][1] == "【研究员】\n好的。"


def test_non_text_message_gets_one_notice_and_no_turn():
    async def ask(bot_id, text, on_event=None):
        raise AssertionError("must not run a turn")

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message(items=[{"type": 2, "image_item": {}}]))
        await _drain(b)
        return ilink

    assert [text for _, text, _ in run(go()).sent] == [bridge.NON_TEXT_TEXT]


def test_card_answer_points_to_the_page():
    async def ask(bot_id, text, on_event=None):
        return "要把这笔交易记下吗？", [{"request_id": "r1"}], "cid"

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message("记一笔买入"))
        await _drain(b)
        return ilink

    sent = run(go()).sent[0][1]
    assert sent.startswith("要把这笔交易记下吗？") and bridge.CARD_TEXT in sent


def test_backend_down_is_said_plainly():
    async def ask(bot_id, text, on_event=None):
        raise bridge.BackendUnavailable()

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink

    assert run(go()).sent[0][1] == bridge.BACKEND_DOWN_TEXT


def test_busy_conversation_waits_then_answers(monkeypatch):
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    attempts = []

    async def ask(bot_id, text, on_event=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise bridge.ConversationBusy()
        return "答完了。", [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink

    texts = [text for _, text, _ in run(go()).sent]
    assert texts == [bridge.BUSY_WAITING_TEXT, "答完了。"]


def test_slow_turn_sends_one_note_before_the_answer(monkeypatch):
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 0.02)

    async def ask(bot_id, text, on_event=None):
        await asyncio.sleep(0.1)
        return "好了。", [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink

    assert [text for _, text, _ in run(go()).sent] == [bridge.SLOW_TEXT, "好了。"]


def test_a_second_message_goes_to_the_api_while_the_first_runs_and_a_409_waits_in_line(monkeypatch):
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    running, peak, refused = [], [], []

    async def ask(bot_id, text, on_event=None):
        if text == "第二句" and not refused:
            refused.append(1)                       # an engine that cannot take it answers 409
            raise bridge.ConversationBusy()
        running.append(1)
        peak.append(len(running))
        await asyncio.sleep(0.03)
        running.pop()
        return text, [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message("第一句"))
        await b.handle(_message("第二句"))
        await _drain(b)
        return ilink

    sent = run(go()).sent
    assert max(peak) == 1 and [text for _, text, _ in sent] == ["第一句", "第二句"]


class _Second:
    """The first message blocks on a gate; the second is answered by ``second(on_event)``."""

    def __init__(self, second):
        self.gate = None
        self.calls = []
        self.second = second

    async def ask(self, bot_id, text, on_event=None):
        self.calls.append(text)
        if text == "第一句":
            await self.gate.wait()
            return "答一", [], "c"
        return await self.second(on_event)


def _two(second):
    async def go():
        fake = _Second(second)
        fake.gate = asyncio.Event()
        b, ilink, _ = _make(fake.ask)
        await b.handle(_message("第一句"))
        await asyncio.sleep(0.02)
        await b.handle(_message("第二句：" + "很长" * 30))
        await asyncio.sleep(0.02)
        during = [text for _, text, _ in ilink.sent]
        fake.gate.set()
        await _drain(b)
        return fake, during, [text for _, text, _ in ilink.sent]

    return run(go())


async def _emit(on_event, *events):
    for kind, data in events:
        await on_event(kind, data)


def test_second_message_is_posted_at_once_and_merged_gets_one_line():
    async def second(on_event):
        await _emit(on_event, ("received", {}), ("merged", {"into_turn": "t"}))
        return "", [], None

    fake, during, sent = _two(second)
    assert len(fake.calls) == 2 and during == [bridge.RECEIVED_TEXT, bridge.MERGED_TEXT]   # before the first finished
    assert sent == [bridge.RECEIVED_TEXT, bridge.MERGED_TEXT, "答一"]


def test_stopped_says_stopped_and_the_stopped_answer_keeps_its_text():
    async def second(on_event):
        await _emit(on_event, ("received", {}), ("stopped", {}))
        return "", [], None

    _, _, sent = _two(second)
    assert sent == [bridge.RECEIVED_TEXT, bridge.STOPPED_TEXT, "答一"]


def test_separate_answer_is_its_own_message_with_a_one_line_quote():
    async def second(on_event):
        await _emit(on_event, ("received", {}), ("separate", {}))
        return "答二", [], "c"

    _, _, sent = _two(second)
    assert sent[0] == bridge.RECEIVED_TEXT
    quote = next(t for t in sent if t.endswith("答二"))
    assert quote.startswith("回复：第二句：") and "\n\n答二" in quote and "…" in quote.split("\n")[0]


def test_queued_is_told_with_the_count_then_answered():
    async def second(on_event):
        await _emit(on_event, ("received", {}), ("separate", {}), ("queued", {"ahead": 2}))
        return "答二", [], "c"

    _, _, sent = _two(second)
    assert sent[:2] == [bridge.RECEIVED_TEXT, "排队中（前面 2 件）"] and any(t.endswith("答二") for t in sent)


def test_a_separate_answer_keeps_the_two_extra_messages_limit(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.01)

    async def second(on_event):
        await _emit(on_event, ("received", {}), ("separate", {}))
        for i in range(5):
            await _emit(on_event, ("checklist", {"items": [{"text": f"步{i}"}]}), ("narration", {"text": f"句{i}"}))
            await asyncio.sleep(0.02)
        return "答二", [], "c"

    _, _, sent = _two(second)
    extra = [t for t in sent if t not in (bridge.RECEIVED_TEXT, "答一") and not t.endswith("答二")]
    assert len(extra) <= 2


def test_long_answer_is_split_and_every_part_carries_the_token():
    async def ask(bot_id, text, on_event=None):
        return "\n\n".join(f"第{i}段：" + "字" * 600 for i in range(8)), [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink

    sent = run(go()).sent
    assert len(sent) > 1 and all(len(text) <= wx.MESSAGE_CHARS for _, text, _ in sent)
    assert {token for _, _, token in sent} == {"ctx-1"}


def test_rejected_send_is_logged_not_raised(capsys):
    async def ask(bot_id, text, on_event=None):
        return "答案", [], None

    async def go():
        b, ilink, _ = _make(ask, FakeIlink(fail={"ret": -1, "errmsg": "bad"}))
        await b.handle(_message())
        await _drain(b)

    run(go())
    assert "send_failed" in capsys.readouterr().out


def test_poll_status_tells_stale_from_rejected():
    assert wx.poll_status({"ret": 0}) == "ok"
    assert wx.poll_status({}) == "ok"
    assert wx.poll_status({"errcode": -14}) == "stale"
    assert wx.poll_status({"ret": -14}) == "stale"
    assert wx.poll_status({"ret": 1, "errmsg": "x"}) == "rejected"


def test_state_file_is_owner_only_and_round_trips(tmp_path):
    path = tmp_path / "data" / "wechat-bridge.json"
    wx.save_state(_state(), path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert wx.load_state(path)["owner_user_id"] == OWNER_ID
    assert wx.load_state(tmp_path / "missing.json") == {}


def test_import_probe_keeps_cursor_and_tokens(tmp_path, monkeypatch, capsys):
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps({"bot_token": "t", "baseurl": "https://x", "ilink_bot_id": "b@im.bot",
                                 "ilink_user_id": OWNER_ID, "get_updates_buf": "cursor-9",
                                 "users": {OWNER_ID: {"context_token": "ctx-9"}}}))
    monkeypatch.setenv("WECHAT_STATE_PATH", str(tmp_path / "out.json"))
    assert bridge.import_probe(str(probe)) == 0
    state = wx.load_state()
    assert (state["get_updates_buf"], state["context_tokens"], state["owner_user_id"]) == (
        "cursor-9", {OWNER_ID: "ctx-9"}, OWNER_ID)
    out = capsys.readouterr().out
    assert "b@im.bot" in out and "ctx-9" not in out and "cursor-9" not in out


def test_inbound_text_joins_text_items_only():
    message = {"item_list": [{"type": 1, "text_item": {"text": "甲"}}, {"type": 2, "image_item": {}},
                             {"type": 1, "text_item": {"text": "乙"}}]}
    assert wx.inbound_text(message) == "甲\n乙"


def test_plain_text_drops_markdown_marks():
    assert wx.plain_text("## 结论\n**营收**增长 `5%`") == "结论\n营收增长 5%"


def test_headers_carry_the_bot_token_only_on_posts():
    post = wx.ilink_headers("tok")
    assert post["Authorization"] == "Bearer tok" and post["AuthorizationType"] == "ilink_bot_token"
    assert "Authorization" not in wx.ilink_headers("tok", post=False)


# ---- kernel progress: the checklist once, one sentence at the 10 s mark ----

def _kernel_ask(script, answer="答案。"):
    """A fake stream: ``script`` is a list of (seconds to wait, kind, data) played through ``on_event``."""
    async def ask(bot_id, text, on_event=None):
        for wait, kind, data in script:
            await asyncio.sleep(wait)
            await on_event(kind, data)
        return answer, [], None
    return ask


def _sent(ask, ilink=None):
    async def go():
        b, il, _ = _make(ask, ilink)
        await b.handle(_message())
        await _drain(b)
        return [text for _, text, _ in il.sent]
    return run(go())


def _say(text):
    return ("narration", {"text": text})


def _plan(*texts):
    return ("checklist", {"items": [{"text": t, "status": "pending"} for t in texts]})


def test_fast_turn_sends_only_the_answer(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.3)
    script = [(0, *_say("先看财报")), (0.01, *_say("再看估值"))]
    assert _sent(_kernel_ask(script)) == ["答案。"]


def test_slow_turn_sends_the_newest_sentence_once_at_the_mark(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.1)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 5)
    script = [(0, *_say("第一句")), (0.02, *_say("第二句")), (0.3, *_say("第三句")), (0.05, *_say("第四句"))]
    assert _sent(_kernel_ask(script)) == ["第二句", "答案。"]


def test_the_mark_fires_without_a_new_event(monkeypatch):
    # one sentence, then a long silence: the sentence goes out at the mark, not at the next event
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 5)
    seen = []

    async def ask(bot_id, text, on_event=None):
        await on_event("narration", {"text": "只有这一句"})
        await asyncio.sleep(0.2)
        seen.extend(ilink.sent)
        return "答案。", [], None

    ilink = FakeIlink()
    assert _sent(ask, ilink) == ["只有这一句", "答案。"]
    assert [text for _, text, _ in seen] == ["只有这一句"]


def test_first_sentence_after_the_mark_is_sent_when_it_arrives(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 5)
    script = [(0.15, *_say("迟到的一句")), (0.01, *_say("再一句"))]
    assert _sent(_kernel_ask(script)) == ["迟到的一句", "答案。"]


def test_checklist_is_sent_once(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 5)
    script = [(0, *_plan("财报", "估值")), (0, *_plan("财报", "估值", "同行")), (0, *_plan("财报"))]
    assert _sent(_kernel_ask(script)) == ["我分几步来做：\n1. 财报\n2. 估值", "答案。"]


def test_checklist_and_sentence_make_two_extra_messages(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 0.02)
    script = [(0, *_plan("财报")), (0, *_say("在看")), (0.15, *_say("还在看"))]
    assert _sent(_kernel_ask(script)) == ["我分几步来做：\n1. 财报", "在看", "答案。"]


def test_progress_send_failure_does_not_stop_the_answer(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 5)

    class Flaky(FakeIlink):
        async def send_text(self, to_user, text, context_token=None):
            if text.startswith("我分几步"):
                raise RuntimeError("down")
            return await super().send_text(to_user, text, context_token)

    assert _sent(_kernel_ask([(0, *_plan("财报"))]), Flaky()) == ["答案。"]


def test_clock_starts_when_the_stream_starts_not_while_queued(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.15)
    monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 5)
    calls = []

    async def ask(bot_id, text, on_event=None):
        calls.append(1)
        if len(calls) < 6:
            await asyncio.sleep(0.04)
            raise bridge.ConversationBusy()
        await on_event("narration", {"text": "排队后的一句"})
        await asyncio.sleep(0.05)
        return "答案。", [], None

    assert _sent(ask) == [bridge.BUSY_WAITING_TEXT, "答案。"]


def test_parse_turn_ignores_kernel_events():
    plain = ('event: conversation\ndata: {"conversation_id": "c1"}\n\n'
             'event: delta\ndata: {"text": "你好"}\n\n')
    noisy = ('event: checklist\ndata: {"items": []}\n\n' + plain
             + 'event: narration\ndata: {"text": "在看"}\n\n')
    assert bridge.parse_turn(noisy) == bridge.parse_turn(plain)
    assert bridge.parse_turn(plain)[0] == "你好"


def test_ask_agent_hands_events_over_as_they_arrive_and_returns_the_same_turn():
    chunks = [b'event: narration\ndata: {"text": "\xe5\x85\x88', b'\xe7\x9c\x8b"}\n\nevent: delta\ndata: {"text": "ok"}\n\n']
    got = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_bytes(self):
            for chunk in chunks:
                yield chunk

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *exc):
            return False

    class Http:
        def stream(self, *args, **kwargs):
            return Stream()

    async def on_event(kind, data):
        got.append((kind, data))

    async def go():
        return await bridge.ask_agent(Http(), "cred", "bot-1", "hi", on_event)

    assert run(go())[0] == "ok"
    assert got == [("narration", {"text": "先看"}), ("delta", {"text": "ok"})]


def test_the_slow_note_takes_the_sentence_slot(monkeypatch):
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 0.05)
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.1)
    script = [(0.08, *_plan("财报")), (0, *_say("一句")), (0.1, *_say("又一句"))]
    assert _sent(_kernel_ask(script)) == [bridge.SLOW_TEXT, "我分几步来做：\n1. 财报", "答案。"]


def test_empty_checklist_items_are_dropped_before_numbering(monkeypatch):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 5)
    script = [(0, "checklist", {"items": [{"text": "财报"}, {"text": "  "}, {"text": "估值"}]})]
    assert _sent(_kernel_ask(script)) == ["我分几步来做：\n1. 财报\n2. 估值", "答案。"]


@pytest.mark.parametrize("fails", [False, True])
def test_the_mark_timer_does_not_outlive_the_turn(monkeypatch, fails):
    monkeypatch.setattr(bridge, "PROGRESS_AFTER_SECONDS", 0.05)
    monkeypatch.setattr(bridge, "SLOW_NOTICE_AFTER", 5)

    async def ask(bot_id, text, on_event=None):
        await on_event("narration", {"text": "没发出去的一句"})
        if fails:
            raise RuntimeError("boom")
        return "答案。", [], None

    async def go():
        b, il, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        done = len(il.sent)
        await asyncio.sleep(0.15)
        return done, len(il.sent)

    done, later = run(go())
    assert done == 1 and later == 1


# ---- the outbox: proactive messages queued for this channel ----

def _row(i="r1", text="提醒：INTC 急跌"):
    return {"id": i, "bot_id": "bot-1", "text": text}


def _outbox_bridge(fake_channels, rows, ilink=None, token="ctx-9"):
    fake_channels.rows = rows
    b, ilink, state = _make(None, ilink)
    if token:
        state["context_tokens"] = {OWNER_ID: token}
    return b, ilink, state


def test_a_pending_row_goes_to_the_owner_with_the_held_context_token(fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])
    run(b.deliver_outbox())
    assert ilink.sent == [(OWNER_ID, "提醒：INTC 急跌", "ctx-9")]
    assert ("expire_stuck", "owner-hash") in fake_channels.calls
    assert ("pending", "owner-hash", "wechat") in fake_channels.calls
    assert ("mark_sent", "r1") in fake_channels.calls
    # deliver first, sweep afterwards; the row's lease is refreshed just before it is sent
    calls = fake_channels.calls
    assert calls.index(("pending", "owner-hash", "wechat")) < calls.index(("claim", "r1")) < calls.index(("mark_sent", "r1")) \
        < calls.index(("expire_stuck", "owner-hash"))


def test_a_rejected_send_marks_a_failure(fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()], FakeIlink(fail={"ret": -2}))
    run(b.deliver_outbox())
    assert ("mark_failed", "r1", "send_failed") in fake_channels.calls
    assert not [c for c in fake_channels.calls if c[0] == "mark_sent"]


def test_a_long_text_is_sent_in_chunks_and_marked_sent_once(fake_channels):
    long_text = "数据。" * 1500
    b, ilink, _ = _outbox_bridge(fake_channels, [_row(text=long_text)])
    run(b.deliver_outbox())
    assert len(ilink.sent) > 1 and all(t[0] == OWNER_ID for t in ilink.sent)
    assert [c for c in fake_channels.calls if c[0] == "mark_sent"] == [("mark_sent", "r1")]


def test_a_push_without_a_context_token_is_still_attempted(fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()], token=None)
    run(b.deliver_outbox())
    assert ilink.sent == [(OWNER_ID, "提醒：INTC 急跌", None)]


def test_nothing_is_sent_while_the_login_is_stale(fake_channels):
    import time
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])
    b.paused_until = time.time() + 600
    run(b.deliver_outbox())
    assert ilink.sent == []
    assert not [c for c in fake_channels.calls if c[0] in ("pending", "mark_sent", "mark_failed")]
    assert ("expire_stuck", "owner-hash") in fake_channels.calls   # the rows are left to expire


def test_an_exception_in_one_send_does_not_stop_the_next_row(fake_channels):
    class Flaky(FakeIlink):
        async def send_text(self, to_user, text, context_token=None):
            if "坏" in text:
                raise RuntimeError("boom")
            return await super().send_text(to_user, text, context_token)

    b, ilink, _ = _outbox_bridge(fake_channels, [_row("r1", "坏消息"), _row("r2", "好消息")], Flaky())
    run(b.deliver_outbox())
    assert ("mark_failed", "r1", "send_failed") in fake_channels.calls
    assert ("mark_sent", "r2") in fake_channels.calls


def test_a_database_failure_in_the_pass_is_logged_not_raised(fake_channels):
    def boom(*a, **k):
        raise RuntimeError("db down")
    fake_channels.pending = boom
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])
    run(b.deliver_outbox())   # does not raise
    assert ilink.sent == []


def test_the_recipient_is_always_the_login_owner(fake_channels):
    row = _row()
    row.update({"to": STRANGER_ID, "user_id": STRANGER_ID, "from_user_id": STRANGER_ID})
    b, ilink, _ = _outbox_bridge(fake_channels, [row])
    run(b.deliver_outbox())
    assert [s[0] for s in ilink.sent] == [OWNER_ID]


def test_the_log_has_the_row_id_and_code_never_the_text(fake_channels, capsys):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row(text="秘密内容XYZ")], FakeIlink(fail={"ret": -2}))
    run(b.deliver_outbox())
    out = capsys.readouterr().out
    assert "outbox_failed" in out and "r1" in out
    assert "秘密内容XYZ" not in out and "ctx-9" not in out and OWNER_ID not in out


def test_an_owner_message_acknowledges_before_it_is_handled(fake_channels):
    async def ask(bot_id, text, on_event=None):
        return "好", [], "cid"

    async def go():
        b, ilink, state = _make(ask)
        await b.handle(_message())
        await _drain(b)

    run(go())
    assert fake_channels.calls[0] == ("acknowledge", "owner-hash", "wechat")


def test_a_message_from_someone_else_does_not_acknowledge(fake_channels):
    async def ask(bot_id, text, on_event=None):
        raise AssertionError("no turn")

    async def go():
        b, ilink, state = _make(ask)
        await b.handle(_message(sender=STRANGER_ID))

    run(go())
    assert not [c for c in fake_channels.calls if c[0] == "acknowledge"]


def test_a_failing_acknowledgement_does_not_stop_the_message(fake_channels):
    def boom(*a, **k):
        raise RuntimeError("db down")
    fake_channels.acknowledge = boom
    calls = []

    async def ask(bot_id, text, on_event=None):
        calls.append(text)
        return "好", [], "cid"

    async def go():
        b, ilink, state = _make(ask)
        await b.handle(_message())
        await _drain(b)

    run(go())
    assert calls == ["英伟达财报怎么样"]


def test_a_stale_login_is_recorded_in_the_state_file_and_cleared_by_the_next_poll(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_STATE_PATH", str(tmp_path / "wx.json"))
    state = _state()
    bridge._mark_stale(state)
    saved = wx.load_state()
    assert isinstance(saved["stale_since"], float) and saved["owner_user_id"] == OWNER_ID
    bridge._clear_stale(state)
    wx.save_state(state)
    assert "stale_since" not in wx.load_state()


# ---- review fixes: partial sends, loop survival, sweep isolation, wiring, pass cap ----

class SecondChunkRejected(FakeIlink):
    async def send_text(self, to_user, text, context_token=None):
        self.sent.append((to_user, text, context_token))
        return {"ret": 0} if len(self.sent) == 1 else {"ret": -2}


def test_a_later_chunk_failing_leaves_the_row_sent_and_stops_sending(fake_channels, capsys):
    ilink = SecondChunkRejected()
    b, ilink, _ = _outbox_bridge(fake_channels, [_row(text="数据。" * 1500)], ilink)
    run(b.deliver_outbox())
    assert len(ilink.sent) == 2   # chunk 1 out, chunk 2 rejected, the rest not tried
    marks = [c for c in fake_channels.calls if c[0] in ("mark_sent", "mark_failed", "mark_partial")]
    assert marks == [("mark_partial", "r1")]
    out = capsys.readouterr().out
    assert "outbox_partial" in out and '"chunks_sent": 1' in out and "数据" not in out
    fake_channels.rows = []   # the closed row is no longer served: nothing goes out on the next pass
    run(b.deliver_outbox())
    assert len(ilink.sent) == 2


def test_a_failing_first_chunk_still_fails_the_row(fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row(text="数据。" * 1500)], FakeIlink(fail={"ret": -2}))
    run(b.deliver_outbox())
    assert len(ilink.sent) == 1
    assert ("mark_failed", "r1", "send_failed") in fake_channels.calls
    assert not [c for c in fake_channels.calls if c[0] == "mark_sent"]


def test_a_failing_sweep_does_not_skip_delivery(fake_channels):
    def boom(owner):
        raise RuntimeError("db down")
    fake_channels.expire_stuck = boom
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])
    run(b.deliver_outbox())
    assert ("mark_sent", "r1") in fake_channels.calls


def test_the_outbox_loop_survives_a_failing_pass_and_failing_log(monkeypatch, fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [])
    runs = []

    async def deliver():
        runs.append(1)
        if len(runs) < 3:
            raise RuntimeError("boom")
        raise asyncio.CancelledError
    b.deliver_outbox = deliver
    monkeypatch.setattr(bridge, "OUTBOX_INTERVAL", 0)
    monkeypatch.setattr(bridge, "_log", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log broke")))

    async def go():
        with pytest.raises(asyncio.CancelledError):
            await bridge._outbox_loop(b)
    run(go())
    assert len(runs) == 3


def test_going_stale_pauses_what_the_delivery_pass_reads(monkeypatch, fake_channels):
    monkeypatch.setattr(bridge, "_mark_stale", lambda state: None)
    monkeypatch.setattr(bridge, "_notify_stale", lambda owner: None)
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])

    async def go():
        await bridge._enter_stale(b, "owner-hash")
        await b.deliver_outbox()
    run(go())
    assert b.paused_until > 0 and ilink.sent == []


def test_the_outbox_task_is_started_and_delivers(monkeypatch, fake_channels):
    b, ilink, _ = _outbox_bridge(fake_channels, [_row()])

    async def go():
        task = bridge._start_outbox(b)
        await asyncio.sleep(0.05)
        task.cancel()
        return task
    run(go())
    assert ilink.sent and ("mark_sent", "r1") in fake_channels.calls


def test_one_pass_stops_taking_rows_after_the_cap(monkeypatch, fake_channels):
    ticks = iter([0, 0, 61, 61, 61])   # start, row 1 checked, row 2 over the cap
    monkeypatch.setattr(bridge, "_monotonic", lambda: next(ticks))
    b, ilink, _ = _outbox_bridge(fake_channels, [_row("r1"), _row("r2"), _row("r3")])
    run(b.deliver_outbox())
    assert [c for c in fake_channels.calls if c[0] == "mark_sent"] == [("mark_sent", "r1")]


def test_the_owner_message_acknowledges_up_to_its_own_time(fake_channels):
    b, ilink, _ = _make(lambda *a, **k: None)
    b.ask = None
    msg = _message(items=[])
    msg["create_time_ms"] = 1_780_000_000_000
    run(b.handle(msg))
    assert fake_channels.seen_at.timestamp() == 1_780_000_000
    run(b.handle(_message(items=[])))                                   # no time on the message: when it was received
    assert abs(fake_channels.seen_at.timestamp() - __import__("time").time()) < 30
