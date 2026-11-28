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


# --- step 2: who he is as a person (plan B, C) ------------------------------------------------------------------------------------------

from datetime import UTC, timedelta  # noqa: E402

from app import memory_review  # noqa: E402
from app.agent_chat_models import AgentProfileItem  # noqa: E402
from app.database import SessionLocal  # noqa: E402

OWNER = "h" * 64


@pytest.fixture
def clean_owner(disposable_database):
    from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage
    from app.database import Base, engine
    from app.memory_events import MemoryEvent
    Base.metadata.create_all(engine, tables=[AgentProfileItem.__table__, AgentBot.__table__, AgentConversation.__table__,
                                             AgentMessage.__table__, MemoryEvent.__table__])

    def wipe():
        with SessionLocal() as db:
            db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER).delete()
            db.commit()
    wipe()
    yield OWNER
    wipe()


def test_a_recent_item_is_used_at_once_dated_and_the_same_one_only_moves_its_date(clean_owner):
    now = datetime(2026, 11, 28, 12, tzinfo=UTC)
    added = profile.add_noticed(clean_owner, kind="recent", text="在找还没被广泛关注的潜力股", quote="主要是针对于那种暂时未获得太多关注的潜力股公司", now=now)
    assert added["status"] == "added" and added["item"]["status"] == "active" and added["item"]["kind"] == "recent"
    again = profile.add_noticed(clean_owner, kind="recent", text="在找还没被广泛关注的潜力股", quote="潜力股", now=now + timedelta(days=5))
    assert again["status"] == "duplicate"
    block, _ = profile.render_block(clean_owner)
    assert "[近况·12-03·推断] 在找还没被广泛关注的潜力股" in block


def test_a_recent_item_not_seen_for_thirty_days_leaves_the_block_and_the_review_archives_it(clean_owner):
    old = datetime.now(UTC) - timedelta(days=31)
    profile.add_noticed(clean_owner, kind="recent", text="担心加息会让股价再跌", quote="加息的话我感觉还会再跌啊", now=old)
    assert profile.render_block(clean_owner)[0] is None
    assert profile.archive_stale_recent(clean_owner, datetime.now(UTC)) == 1
    assert [i["status"] for i in profile.list_items(clean_owner)] == ["archived"]


def test_at_most_eight_recent_items_the_oldest_goes_first(clean_owner):
    start = datetime.now(UTC) - timedelta(days=9)
    for day in range(9):
        profile.add_noticed(clean_owner, kind="recent", text=f"第 {day} 件最近在想的事", quote=f"第 {day} 件事", now=start + timedelta(days=day))
    items = profile.list_items(clean_owner)
    active = [i["text"] for i in items if i["status"] == "active"]
    assert len(active) == 8 and "第 0 件最近在想的事" not in active


def test_a_style_guess_waits_for_him_like_any_guess(clean_owner):
    added = profile.add_noticed(clean_owner, kind="style", text="他是刚入门的新手，喜欢口语、少用术语", quote="我刚开始炒股，什么是市盈率啊")
    assert added["item"]["status"] == "proposed" and added["item"]["kind"] == "style"


def test_a_standing_instruction_carries_his_words(clean_owner):
    profile.add_item(clean_owner, kind="instruction", text="找新闻默认最近 7 天", quote="找新闻没说时间就默认最近7天", message="以后找新闻没说时间就默认最近7天",
                     origin="explicit")
    block, _ = profile.render_block(clean_owner)
    assert "[长期指令] 找新闻默认最近 7 天（他的原话：「找新闻没说时间就默认最近7天」）" in block


def test_the_monthly_review_also_looks_for_how_to_talk_with_him():
    assert "相处方式（type=style）" in memory_review.PROMPT
    examples = [{"message_id": "m1", "quote": "什么是市盈率"}, {"message_id": "m2", "quote": "听着好复杂"}]
    by_id = {"m1": {"id": "m1", "content": "我刚开始炒股，什么是市盈率啊", "at": None, "date": ""},
             "m2": {"id": "m2", "content": "听着好复杂", "at": None, "date": ""}}
    checked = memory_review._checked({"text": "他刚入门，喜欢大白话", "type": "style", "examples": examples}, by_id)
    assert checked is not None and checked["kind"] == "style"


def test_the_model_may_note_style_and_recent_and_is_told_how_each_works():
    from app.kernel import act
    assert {"style", "recent"} <= set(act.NOTICED_KINDS) and "不用特意告诉他" in act.RECENT_NOTE
    text = prompt.system_text()
    assert "相处方式（kind=style" in text and "近况（kind=recent" in text
