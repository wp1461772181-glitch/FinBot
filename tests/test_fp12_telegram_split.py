"""FP12: Telegram chunk boundaries and explicit inbound truncation."""
import asyncio
import json
import re

import httpx
import pytest

from app.agent_telegram import split_for_telegram
from scripts import run_telegram_bridge as bridge


def _examples():
    paragraphs = "\n\n".join(["甲" * 1999 + "。", "乙" * 1999 + "。", "丙" * 1999 + "。"])
    table = "\n".join("| " + str(i).zfill(3) + " | " + "表" * 50 + " |" for i in range(120))
    number = "甲" * 3785 + "1,234,567.89%" + "乙" * (9000 - 3785 - 13)
    return paragraphs, table, number, "汉" * 9000


def test_short_text():
    assert split_for_telegram("短文本") == ["短文本"]


def test_paragraph_boundaries():
    text = _examples()[0]
    chunks = split_for_telegram(text)
    assert chunks == text.split("\n\n")
    assert all(len(chunk) <= 3800 and chunk.endswith("。") for chunk in chunks)


def test_table_rows_remain_whole():
    chunks = split_for_telegram(_examples()[1])
    assert len(chunks) > 1
    assert all(len(chunk) <= 3800 and all(line.startswith("|") and line.endswith("|")
               for line in chunk.splitlines()) for chunk in chunks)


def test_number_is_not_split():
    chunks = split_for_telegram(_examples()[2])
    assert sum("1,234,567.89%" in chunk for chunk in chunks) == 1
    assert all(len(chunk) <= 3800 for chunk in chunks)


def test_unbroken_chinese_terminates():
    chunks = split_for_telegram(_examples()[3])
    assert len(chunks) > 1 and all(0 < len(chunk) <= 3800 for chunk in chunks)


def test_fences_are_closed_and_reopened():
    chunks = split_for_telegram("```python\n" + "代码" * 2500 + "\n```")
    assert len(chunks) == 2
    assert chunks[0].endswith("```") and chunks[1].startswith("```")
    assert all(sum(line.startswith("```") for line in chunk.splitlines()) % 2 == 0 for chunk in chunks)
    assert all(len(chunk) <= 3800 for chunk in chunks)


def test_no_non_whitespace_lost():
    for text in _examples():
        chunks = split_for_telegram(text)
        assert all(chunks)
        assert re.sub(r"\s", "", "".join(chunks)) == re.sub(r"\s", "", text)


TOKEN = "123456789:AAH" + "x" * 32


class Telegram:
    def __init__(self):
        self.replies = []

    def record_reply(self, *args):
        self.replies.append(args)


class Client:
    def __init__(self, answer="好"):
        self.posts = []
        self.requests = []
        self.answer = answer

    async def post(self, url, json):
        self.posts.append(dict(json))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.posts)}})

    def stream(self, method, url, **kwargs):
        self.requests.append(kwargs["json"])
        client = self

        class Response:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def aiter_bytes(self):
                data = json.dumps({"text": client.answer}, ensure_ascii=False)
                yield f"event: delta\ndata: {data}\n\n".encode()

        return Response()


def _turn(client, telegram, text, **press):
    return asyncio.run(bridge._bot_turn(client, "cred", "owner", 4242, {}, telegram,
                                        "bot", "助理", text, **press))


def test_answer_sends_chunks_and_only_last_has_keyboard(monkeypatch):
    monkeypatch.setenv("FINBOT_FP12_TG_SPLIT", "on")
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)

    async def ask(*args, **kwargs):
        return "答" * 8000, [{"id": "card", "choices": [{"value": "confirm:yes", "label": "同意"}]}], "cid"

    monkeypatch.setattr(bridge, "_ask_with_retry", ask)
    client, telegram = Client(), Telegram()
    _turn(client, telegram, "问")
    assert len(client.posts) > 1
    assert all("reply_markup" not in post for post in client.posts[:-1])
    assert "reply_markup" in client.posts[-1]
    assert len(telegram.replies) == len(client.posts)


def test_overlong_notice_precedes_truncated_request(monkeypatch):
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    client, telegram = Client(), Telegram()
    _turn(client, telegram, "问" * 4050)
    assert client.posts[0]["text"] == bridge.OVERLONG_NOTICE.format(total=4050, limit=4000, dropped=50)
    assert "parse_mode" not in client.posts[0]
    assert len(client.requests) == 1 and client.requests[0]["message"] == "问" * 4000
    assert len(client.posts) == 2


def test_no_notice_at_limit_or_for_card_press(monkeypatch):
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    for text, press in [("问" * 4000, {}), ("问" * 4050, {"pending_request_id": "card"})]:
        client = Client()
        _turn(client, Telegram(), text, **press)
        assert len(client.posts) == 1
        assert client.posts[0]["text"] == "【助理】\n好"
        assert len(client.requests) == 1


def test_switch_off_restores_hard_slices(monkeypatch):
    monkeypatch.setenv("FINBOT_FP12_TG_SPLIT", "off")
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner, tg: TOKEN)
    answer = "甲" * 3000 + "\n\n" + "乙" * 4998
    client, telegram = Client(answer), Telegram()
    _turn(client, telegram, "问")
    full = "【助理】\n" + answer
    assert [post["text"] for post in client.posts] == [full[0:3800], full[3800:7600], full[7600:]]
