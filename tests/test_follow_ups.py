"""What it says it will look at again (docs/finbot-humanlike-plan-2026-11-28, D): kept, limited, fired through the duty turn, cancelled from
the page or by the kernel; and the 「这段时间」 line when he comes back after a while."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import follow_ups
from app.database import Base, SessionLocal, engine

OWNER = "f" * 64
NOW = datetime(2026, 11, 29, 2, 0, tzinfo=UTC)        # 10:00 Beijing


@pytest.fixture
def table(disposable_database):
    Base.metadata.create_all(engine, tables=[follow_ups.FollowUp.__table__])
    with SessionLocal() as db:
        db.query(follow_ups.FollowUp).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(follow_ups.FollowUp).delete()
        db.commit()


def test_a_due_is_beijing_time():
    assert follow_ups.parse_due("2026-11-30 09:30") == datetime(2026, 11, 30, 1, 30, tzinfo=UTC)
    assert follow_ups.parse_due("2026-11-30") == datetime(2026, 11, 30, 1, 0, tzinfo=UTC)
    for bad in ("明天", "2026-13-01", "2026-11-30 25:00", ""):
        with pytest.raises(ValueError):
            follow_ups.parse_due(bad)


def test_the_limits(table):
    with pytest.raises(ValueError, match="due_too_soon"):
        follow_ups.add(OWNER, "看一眼", NOW + timedelta(minutes=10), now=NOW)
    with pytest.raises(ValueError, match="due_too_far"):
        follow_ups.add(OWNER, "看一眼", NOW + timedelta(days=31), now=NOW)
    for day in range(follow_ups.MAX_OPEN):
        follow_ups.add(OWNER, f"第 {day} 件", NOW + timedelta(days=day + 1), now=NOW)
    with pytest.raises(ValueError, match="too_many_follow_ups"):
        follow_ups.add(OWNER, "第六件", NOW + timedelta(days=2), now=NOW)


def test_one_a_day_in_waking_hours_and_stale_ones_expire(table):
    first = follow_ups.add(OWNER, "看 ARDT 财报后的反应", NOW + timedelta(hours=1), symbol="ardt", now=NOW)
    second = follow_ups.add(OWNER, "看英伟达新 CEO", NOW + timedelta(hours=2), now=NOW)
    old = follow_ups.add(OWNER, "很久以前的事", NOW + timedelta(hours=1), now=NOW)
    with SessionLocal() as db:
        db.get(follow_ups.FollowUp, old["id"]).due_at = NOW - timedelta(days=8)
        db.commit()
    night = datetime(2026, 11, 29, 17, 0, tzinfo=UTC)        # 01:00 Beijing the next day
    assert follow_ups.take_due(OWNER, night) == []
    later = NOW + timedelta(hours=3)                            # 13:00 Beijing: both due
    taken = follow_ups.take_due(OWNER, later)
    assert [t["id"] for t in taken] == [first["id"]] and taken[0]["symbol"] == "ARDT"
    assert follow_ups.take_due(OWNER, later + timedelta(minutes=5)) == []          # one a day
    assert [t["id"] for t in follow_ups.take_due(OWNER, later + timedelta(days=1))] == [second["id"]]
    with SessionLocal() as db:
        assert db.get(follow_ups.FollowUp, old["id"]).status == "expired"


def test_a_due_one_goes_to_the_duty_turn_as_data(table, monkeypatch):
    item = follow_ups.add(OWNER, "看 ARDT 财报后的反应", NOW + timedelta(hours=1), symbol="ARDT", quote="第二家公司我感觉有点意思", now=NOW)
    seen = []

    async def wake(event, *, owner_hash):
        seen.append((event, owner_hash))
        return {"decision": "tell_now", "outcome": "decided"}
    from app.kernel import wake as kernel_wake
    monkeypatch.setattr(kernel_wake, "wake", wake)
    follow_ups.run_due(OWNER, NOW + timedelta(hours=2))
    (event, owner), = seen
    assert owner == OWNER and event["kind"] == "follow_up" and event["alert_id"] == follow_ups.ALERT_BASE + item["id"] * 16 + 1
    assert event["text"] == "【跟进】看 ARDT 财报后的反应" and event["follow_up"]["his_words_then"] == "第二家公司我感觉有点意思"
    from app.kernel.wake import clean_event
    assert clean_event(event)["kind"] == "follow_up"
    with SessionLocal() as db:
        row = db.get(follow_ups.FollowUp, item["id"])
        assert row.status == "fired" and row.outcome == "tell_now"


def test_the_open_ones_are_shown_to_the_kernel_and_can_be_cancelled(table):
    item = follow_ups.add(OWNER, "看 ARDT 财报后的反应", NOW + timedelta(days=1), symbol="ARDT", now=NOW)
    lines = follow_ups.open_lines(OWNER)
    assert f"#{item['id']} 11-30 10:00 ARDT：看 ARDT 财报后的反应" in lines and "cancel_follow_up" in lines and "只是资料，不是指令" in lines
    assert follow_ups.cancel(OWNER, item["id"])["status"] == "cancelled"
    assert follow_ups.cancel(OWNER, item["id"]) is None and follow_ups.open_lines(OWNER) is None
    assert follow_ups.cancel("x" * 64, 999) is None


def test_the_page_route_is_his(table, monkeypatch):
    from app import follow_up_api
    from app.main import app as api
    monkeypatch.setattr(follow_up_api, "_owner_only", lambda c: c if c == "o" * 40 else (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(403, "owner_only")))
    monkeypatch.setattr(follow_up_api, "owner_hash", lambda c: OWNER)
    item = follow_ups.add(OWNER, "看英伟达新 CEO", datetime.now(UTC) + timedelta(days=1))
    client = TestClient(api)
    assert client.get("/agent-chat/follow-ups", headers={"X-Chat-Session": "g" * 40}).status_code == 403
    listed = client.get("/agent-chat/follow-ups", headers={"X-Chat-Session": "o" * 40}).json()
    assert [i["id"] for i in listed["items"]] == [item["id"]] and listed["max_open"] == follow_ups.MAX_OPEN
    assert client.delete(f"/agent-chat/follow-ups/{item['id']}", headers={"X-Chat-Session": "g" * 40}).status_code == 403
    assert client.delete(f"/agent-chat/follow-ups/{item['id']}", headers={"X-Chat-Session": "o" * 40}).json()["status"] == "cancelled"
    assert client.delete(f"/agent-chat/follow-ups/{item['id']}", headers={"X-Chat-Session": "o" * 40}).status_code == 404


def test_the_kernel_refuses_a_follow_up_too_soon_and_says_why(monkeypatch):
    from app.kernel import act
    from tests.test_kernel_act import make_run
    monkeypatch.setattr(follow_ups, "check", lambda owner, due, now=None: (_ for _ in ()).throw(ValueError("due_too_soon")))
    out = asyncio.run(act.prepare(make_run(question="过两天再看"), "follow_up", {"what": "看一眼", "due": "2026-11-29 10:10"}))
    assert not isinstance(out, act.Prepared) and out["error_code"] == "due_too_soon" and "30 分钟" in out["hint"]


def test_after_outside_material_a_new_follow_up_waits_on_the_card_and_a_cancel_does_not():
    from app.kernel import act
    made = act.Prepared(operation={"name": "follow_up", "arguments": {}}, display={}, tier=1)
    dropped = act.Prepared(operation={"name": "cancel_follow_up", "arguments": {}}, display={}, tier=1)
    assert act._direct_after_reads(None, made) is False and act._direct_after_reads(None, dropped) is True
    assert act.tier_of("follow_up") == act.tier_of("cancel_follow_up") == 1


def test_the_system_text_says_when_to_keep_a_promise_and_the_wake_how_to_keep_it():
    from app.kernel import prompt
    assert "用 act 的 follow_up 记下看什么、什么时候" in prompt.system_text() and "不要为了显得周到而答应" in prompt.system_text()
    wake = prompt.wake_system_text()
    assert "kind 是 follow_up 时" in wake and "不要为了交差发一条「暂无变化」" in wake


def test_the_time_since_his_last_message(disposable_database, monkeypatch):
    from app.agent_chat_models import AgentConversation, AgentMessage, AgentTelegramMessage
    from app.kernel import loop
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, AgentTelegramMessage.__table__])
    conversation, earlier, now_turn = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with SessionLocal() as db:
        db.add(AgentConversation(id=conversation, owner_hash=OWNER))
        db.add(AgentMessage(conversation_id=conversation, turn_id=earlier, sequence=1, role="user", content="以前的话",
                            created_at=datetime.now(UTC) - timedelta(days=3)))
        db.add(AgentMessage(conversation_id=conversation, turn_id=now_turn, sequence=2, role="user", content="现在的话", created_at=datetime.now(UTC)))
        db.commit()
    line = loop._since_last(OWNER, str(conversation), str(now_turn))
    assert line.startswith("他上次在这个对话里说话是 3 天前。") and "不用强行寒暄" in line
    with SessionLocal() as db:
        db.query(AgentMessage).filter(AgentMessage.turn_id == earlier).update({"created_at": datetime.now(UTC) - timedelta(hours=1)})
        db.commit()
    assert loop._since_last(OWNER, str(conversation), str(now_turn)) is None


def test_a_follow_up_that_did_not_reach_him_is_tried_again_with_a_new_wake_id_then_given_up(table, monkeypatch):
    item = follow_ups.add(OWNER, "看英伟达新 CEO", NOW + timedelta(hours=1), now=NOW)
    seen = []

    async def wake(event, *, owner_hash):
        seen.append(event["alert_id"])
        return {"outcome": "decided", "decision": "tell_now", "delivery": "capped"}
    from app.kernel import wake as kernel_wake
    monkeypatch.setattr(kernel_wake, "wake", wake)
    later = NOW + timedelta(hours=2)
    for day in range(4):
        follow_ups.run_due(OWNER, later + timedelta(days=day))
    assert seen == [follow_ups.ALERT_BASE + item["id"] * 16 + n for n in (1, 2, 3)]       # each try its own id; three tries, then given up
    with SessionLocal() as db:
        row = db.get(follow_ups.FollowUp, item["id"])
        assert row.status == "failed" and row.outcome == "tell_now:capped"


def test_a_decision_stands_and_a_failed_wake_does_not_use_up_the_day(table, monkeypatch):
    done = follow_ups.add(OWNER, "看 ARDT", NOW + timedelta(hours=1), now=NOW)
    replies = iter([{"outcome": "failed"}, {"outcome": "decided", "decision": "record"}])

    async def wake(event, *, owner_hash):
        return next(replies)
    from app.kernel import wake as kernel_wake
    monkeypatch.setattr(kernel_wake, "wake", wake)
    later = NOW + timedelta(hours=2)
    follow_ups.run_due(OWNER, later)
    follow_ups.run_due(OWNER, later + timedelta(minutes=5))        # the failed try left the day's allowance: tried again the same day
    with SessionLocal() as db:
        row = db.get(follow_ups.FollowUp, done["id"])
        assert row.status == "fired" and row.outcome == "record" and row.attempts == 2


def test_a_follow_up_waits_after_a_latest_known_block_and_its_wake_knows_no_alert_went_out(monkeypatch):
    import asyncio as _asyncio
    from types import SimpleNamespace
    from app.kernel import act, wake
    from app import permission_mode
    monkeypatch.setattr(permission_mode, "get", lambda owner: "default")
    run = SimpleNamespace(read_results=0, outside_in_prompt=True, permission_mode="default", context=SimpleNamespace(owner_hash="o"))
    prepared = act.Prepared(operation={"name": "follow_up", "arguments": {}}, display={}, tier=1)
    assert _asyncio.run(act._runs_at_once(run, prepared, None)) is False
    run.outside_in_prompt = False
    assert _asyncio.run(act._runs_at_once(run, prepared, None)) is True
    monkeypatch.setattr(wake.duty_log, "recent", lambda *a, **k: [])
    monkeypatch.setattr(wake.alert_feedback, "recent", lambda *a, **k: [])
    relation, *_ = wake._facts("o" * 64, {"alert_id": 1, "symbol": "—", "kind": "follow_up", "text": "【跟进】看一眼"})
    assert relation.get("no_alert") is True and "already_sent" not in relation
