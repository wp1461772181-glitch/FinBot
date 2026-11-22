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

    async def ask(bot_id, text):
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
    async def ask(bot_id, text):
        raise AssertionError("must not run a turn")

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message(sender=STRANGER_ID))
        await b.handle(_message(kind=2))
        await _drain(b)
        return ilink

    assert run(go()).sent == []


def test_mention_routes_to_that_bot_and_names_it():
    async def ask(bot_id, text):
        assert (bot_id, text) == ("bot-2", "看下 AMD")
        return "好的。", [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message("@研究员 看下 AMD"))
        await _drain(b)
        return ilink

    assert run(go()).sent[0][1] == "【研究员】\n好的。"


def test_non_text_message_gets_one_notice_and_no_turn():
    async def ask(bot_id, text):
        raise AssertionError("must not run a turn")

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message(items=[{"type": 2, "image_item": {}}]))
        await _drain(b)
        return ilink

    assert [text for _, text, _ in run(go()).sent] == [bridge.NON_TEXT_TEXT]


def test_card_answer_points_to_the_page():
    async def ask(bot_id, text):
        return "要把这笔交易记下吗？", [{"request_id": "r1"}], "cid"

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message("记一笔买入"))
        await _drain(b)
        return ilink

    sent = run(go()).sent[0][1]
    assert sent.startswith("要把这笔交易记下吗？") and bridge.CARD_TEXT in sent


def test_backend_down_is_said_plainly():
    async def ask(bot_id, text):
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

    async def ask(bot_id, text):
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

    async def ask(bot_id, text):
        await asyncio.sleep(0.1)
        return "好了。", [], None

    async def go():
        b, ilink, _ = _make(ask)
        await b.handle(_message())
        await _drain(b)
        return ilink

    assert [text for _, text, _ in run(go()).sent] == [bridge.SLOW_TEXT, "好了。"]


def test_turns_of_one_bot_run_one_at_a_time():
    running, peak = [], []

    async def ask(bot_id, text):
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


def test_long_answer_is_split_and_every_part_carries_the_token():
    async def ask(bot_id, text):
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
    async def ask(bot_id, text):
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
