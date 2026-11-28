"""「活人感」 (docs/finbot-humanlike-plan-2026-11-28): who it is and how it reads what he says, the 「此刻」 line (Beijing time and the channel),
the bridges saying where a message came from, the profile block's header, and the fixed failure lines in its own voice."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import agent_profile as profile
from app.agent_chat_stream import GENERIC_FAILURE, StreamRequest
from app.kernel import prompt
from tests.test_kernel_loop import env, run, script, step  # noqa: F401  (env is a fixture)

AT = datetime(2026, 11, 29, 0, 41, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_the_system_text_says_who_it_is_and_to_read_a_remark_as_a_remark():
    text = prompt.system_text()
    assert text.startswith("你是 FinBot，他的私人助手，最懂的是金融。")
    for phrase in ("一句感想、一点担心，还是随口聊聊", "是感想就像朋友那样接话", "上文看得出指什么就直接接着说，真看不出来再问",
                   "他是新手就少用术语、多打比方", "不扫兴，也不奉承", "数字照旧只说查到的", "不必每次在结尾问要不要接着做"):
        assert phrase in text, phrase
    assert "结论先说，不绕" not in text          # the one line it used to be


@pytest.mark.parametrize("via,where,shown", [("wechat", "微信", "纯文字"), ("telegram", "Telegram", "纯文字"), ("web", "网页", "Markdown"),
                                             (None, "网页", "Markdown"), ("carrier pigeon", "网页", "Markdown")])
def test_the_scene_line_says_the_time_and_what_the_channel_shows(via, where, shown):
    line = prompt.scene_line(via, AT)
    assert line.startswith("系统说明（此刻）：北京时间 2026-11-29（周日）00:41。") and f"他是在{where}上发来的" in line and shown in line


def test_the_scene_line_converts_to_beijing_time():
    utc = datetime(2026, 11, 28, 16, 41, tzinfo=ZoneInfo("UTC"))
    assert "2026-11-29（周日）00:41" in prompt.scene_line("web", utc)


def test_a_turn_gets_the_scene_right_before_the_question(env, monkeypatch):
    monkeypatch.setenv("FINBOT_KERNEL_SCENE", "on")
    fake = script(env, [step(text="好")])
    history = [{"role": "system", "content": "e"}, {"role": "user", "content": "前"}, {"role": "assistant", "content": "答"},
               {"role": "user", "content": "这些企业看着就挺狠呐"}]
    from tests.test_kernel_loop import make_context
    run("这些企业看着就挺狠呐", context=make_context(via="wechat"), messages=history)
    sent = fake.calls[0]["messages"]
    assert sent[-1] == {"role": "user", "content": "这些企业看着就挺狠呐"}
    scenes = [m for m in sent if m["role"] == "system" and m["content"].startswith("系统说明（此刻）")]
    answered = max(i for i, m in enumerate(sent) if m["role"] == "assistant")
    assert len(scenes) == 1 and "微信" in scenes[0]["content"] and sent.index(scenes[0]) > answered


def test_with_the_switch_off_there_is_no_scene(env):
    fake = script(env, [step(text="好")])
    run("你好")
    assert not any(str(m.get("content", "")).startswith("系统说明（此刻）") for m in fake.calls[0]["messages"])


def test_the_stream_request_takes_where_the_message_came_from():
    base = {"message": "你好", "bot_id": "b1"}
    assert StreamRequest(**base).via is None
    assert StreamRequest(**base, via="wechat").via == "wechat" and StreamRequest(**base, via="telegram").via == "telegram"
    with pytest.raises(ValueError):
        StreamRequest(**base, via="email")


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield b'event: done\ndata: {"conversation_id": "c1"}\n\n'


class _Stream:
    def __init__(self, sent):
        self.sent = sent

    def stream(self, method, url, json=None, **kwargs):
        self.sent.append(json)
        sent = self

        class Context:
            async def __aenter__(self):
                return _Response()

            async def __aexit__(self, *a):
                return False
        return Context()


def test_the_telegram_bridge_says_its_messages_come_from_telegram():
    from scripts import run_telegram_bridge as bridge
    sent = []
    asyncio.run(bridge._ask_agent(_Stream(sent), "cred", "b1", "你好"))
    assert sent and sent[0]["via"] == "telegram" and sent[0]["message"] == "你好"


def test_the_wechat_bridge_says_its_messages_come_from_wechat():
    from scripts import run_wechat_bridge as bridge
    sent = []
    asyncio.run(bridge.ask_agent(_Stream(sent), "cred", "b1", "你好"))
    assert sent and sent[0]["via"] == "wechat" and sent[0]["message"] == "你好"


def test_the_profile_block_says_these_are_things_it_remembers_not_rules():
    assert profile.BLOCK_LABEL.startswith("你记得的关于他的事") and "不授权任何写操作" in profile.BLOCK_LABEL
    assert "不是见到某个词就触发的规则" in profile.BLOCK_NOTE and "不能据此调用写操作" in profile.BLOCK_NOTE
    assert "只用来理解用户想要的格式" not in profile.BLOCK_NOTE


def test_the_catch_all_failure_line_is_in_its_own_voice():
    assert GENERIC_FAILURE.startswith("抱歉，这次我没能答完") and "这一轮没有完成" not in GENERIC_FAILURE


def test_the_cleanup_names_only_the_two_old_instructions():
    from scripts.humanlike_memory_cleanup import planned
    items = [{"id": "1", "status": "active", "kind": "instruction", "text": "用户要求：说到“那些企业”等泛称时，应先对应到具体公司，再据此搜索。［注：记忆判断未确认，请自行核对］"},
             {"id": "2", "status": "active", "kind": "instruction", "text": "回答前先上网搜索［注：记忆判断未确认，请自行核对］"},
             {"id": "3", "status": "active", "kind": "instruction", "text": "找新闻/资讯未指明时间时，默认最近7天，越新越好"},
             {"id": "4", "status": "archived", "kind": "instruction", "text": "回答前先上网搜索"},
             {"id": "5", "status": "active", "kind": "preference", "text": "回答前先上网搜索"}]
    assert [(a, i["id"], n) for a, i, n in planned(items)] == [("archive", "1", None), ("rewrite", "2", "涉及最新消息和行情时先联网查")]
