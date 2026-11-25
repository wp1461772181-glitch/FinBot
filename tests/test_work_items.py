"""3b Task 3: one list of the owner's work (list_work), and the end message of a job started from a card.

Review Focus 3 (a card's job fails: one message, one notice, never twice), 4 (the list: statuses, times, nothing of another owner, a guest
gets nothing), 5 (two workers or a restart in the watcher pass: no duplicate end message).
"""
import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from runpy import run_path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app import work
from app.agent_chat_models import (AgentBot, AgentChannelPref, AgentConversation, AgentMessage, AgentTask, AgentTelegramMessage)
from app.agent_workflow.models import AgentConsent
from app.database import SessionLocal, engine
from app.models import ArchiveSubject

OWNER = "owner-hash-work-items"
OTHER = "other-owner-hash"


@pytest.fixture(autouse=True)
def tables(monkeypatch):
    import app.agent_tasks  # noqa: F401  (registers its tables)
    from app.database import Base
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name.startswith("agent_") or t.name in ("archive_subjects",)])
    run_path("scripts/migrate_agent_actions.py")["apply"]()
    with SessionLocal() as db:
        for model in (work.AgentWork, AgentTask, AgentConsent, AgentTelegramMessage, ArchiveSubject):
            db.query(model).delete()
        db.execute(text("DELETE FROM agent_action_requests"))
        db.commit()
    import app.channels as channels
    monkeypatch.setattr(channels, "available", lambda db, owner, channel, bot: channel == "telegram")
    monkeypatch.delenv("FINBOT_WORK_DAILY_CAP", raising=False)
    yield


def _conversation(owner=OWNER, quiet=True):
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=owner)
        db.add(conversation)
        db.flush()
        stamp = datetime.now(UTC) - (timedelta(minutes=30) if quiet else timedelta(seconds=5))
        db.add(AgentMessage(conversation_id=conversation.id, turn_id=uuid.uuid4(), sequence=1, role="user", content="预测一下 AAPL", status="complete",
                            created_at=stamp))
        db.add(AgentMessage(conversation_id=conversation.id, turn_id=uuid.uuid4(), sequence=2, role="assistant", content="好的，请确认", status="complete",
                            created_at=stamp))
        db.commit()
        return str(conversation.id)


def _card_job(conversation, *, owner=OWNER, action="forecast", status="running", job_status=None, created=None, updated=None, title="预测 AAPL"):
    """A consent (the card) and the action request it started, with the job's status as the job table would give it."""
    created = created or datetime.now(UTC) - timedelta(minutes=5)
    with SessionLocal() as db:
        consent = AgentConsent(owner_hash=owner, conversation_id=conversation, capability_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                               payload_digest="d", operations=[{"name": "request_action", "arguments": {"action": action, "symbol": "AAPL"}}],
                               display={"title": title}, expires_at=created + timedelta(minutes=10), status="executed")
        db.add(consent)
        db.flush()
        request_id = uuid.uuid4()
        db.execute(text("""INSERT INTO agent_action_requests (id,owner_hash,request_key,action,payload_digest,status,job_kind,job_id,result,created_at,updated_at)
                           VALUES (:id,:o,:k,:a,'d',:s,:jk,:j,'{}'::jsonb,:c,:u)"""),
                   {"id": request_id, "o": owner, "k": f"{consent.id}.0", "a": action, "s": status,
                    "jk": "forecast" if action == "forecast" else "analysis", "j": uuid.uuid4(), "c": created, "u": updated or created})
        db.commit()
    return str(request_id), job_status


@pytest.fixture
def job_status(monkeypatch):
    """Live job statuses by request, as the job tables would report them (the watcher and the list read them through actions._status)."""
    live = {}
    from app.agent_workflow import actions
    real = actions._status

    def fake(db, row):
        state = live.get(str(row["id"]))
        if state is None:
            return real(db, row)
        mapped = {"queued": "running", "running": "running", "succeeded": "succeeded", "failed": "failed"}[state]
        return {"ok": mapped != "failed", "status": mapped, "job_status": state, "action": row["action"], "job_id": str(row["job_id"]),
                "error_code": state if mapped == "failed" else None, "result": {}}
    monkeypatch.setattr(actions, "_status", fake)
    return live


def _messages(conversation):
    with SessionLocal() as db:
        return db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == uuid.UUID(conversation))
                          .order_by(AgentMessage.sequence)).all()


def _notices():
    with SessionLocal() as db:
        return db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.source == "work")).all()


# ---- Review Focus 3: a card's job ends; one message, one notice, never twice ----

def test_a_failed_forecast_posts_one_message_in_its_conversation_and_one_notice(job_status):
    conversation = _conversation()
    request, _ = _card_job(conversation, created=datetime.now(UTC) - timedelta(minutes=3), title="预测 AAPL")
    job_status[request] = "failed"

    assert work.report_job_ends() == 1
    assert work.report_job_ends() == 0   # the watcher's next minute: nothing again

    rows = _messages(conversation)
    assert [r.role for r in rows][-2:] == ["user", "assistant"] and rows[-1].status == "complete"
    assert rows[-2].content.startswith(work.WORK_END_HEAD) and "预测 AAPL" in rows[-1].content
    assert "失败了" in rows[-1].content and "你让我做的「预测 AAPL」" in rows[-1].content
    [notice] = _notices()                        # ran 3 minutes (over 60 s), nobody reading
    assert "预测 AAPL" in notice.text and "失败" in notice.text


def test_a_job_that_succeeds_says_where_to_see_it_and_a_short_job_or_a_reader_gets_no_notice(job_status):
    quiet = _conversation()
    short, _ = _card_job(quiet, created=datetime.now(UTC) - timedelta(seconds=30), title="预测 MSFT")
    reading = _conversation(quiet=False)       # the owner's last message there was seconds ago
    slow, _ = _card_job(reading, created=datetime.now(UTC) - timedelta(minutes=5), title="预测 NVDA")
    job_status[short] = job_status[slow] = "succeeded"

    assert work.report_job_ends() == 2
    assert "已完成" in _messages(quiet)[-1].content and "预测" in _messages(quiet)[-1].content
    assert _notices() == []


def test_a_job_still_running_or_not_from_a_card_is_left_alone(job_status):
    conversation = _conversation()
    running, _ = _card_job(conversation)
    job_status[running] = "running"
    with SessionLocal() as db:   # an action request with no card (a direct call)
        db.execute(text("""INSERT INTO agent_action_requests (id,owner_hash,request_key,action,payload_digest,status,job_kind,job_id,result)
                           VALUES (:i,:o,'direct-1','forecast','d','failed','forecast',:j,'{}'::jsonb)"""),
                   {"i": uuid.uuid4(), "o": OWNER, "j": uuid.uuid4()})
        db.commit()
    assert work.report_job_ends() == 0 and len(_messages(conversation)) == 2


def test_a_conversation_with_an_unfinished_turn_waits_for_the_next_pass(job_status):
    conversation = _conversation()
    with SessionLocal() as db:   # the owner's question is being answered: the last row is not a final answer
        db.add(AgentMessage(conversation_id=uuid.UUID(conversation), turn_id=uuid.uuid4(), sequence=3, role="user", content="再说一下", status="complete"))
        db.commit()
    request, _ = _card_job(conversation)
    job_status[request] = "succeeded"
    assert work.report_job_ends() == 0
    with SessionLocal() as db:
        db.query(AgentMessage).filter(AgentMessage.sequence == 3, AgentMessage.conversation_id == uuid.UUID(conversation)).delete()
        db.commit()
    assert work.report_job_ends() == 1


# ---- Review Focus 5: two workers, or a restart during the pass ----

def test_two_watchers_at_once_post_one_message(job_status):
    conversation = _conversation()
    request, _ = _card_job(conversation, created=datetime.now(UTC) - timedelta(minutes=3))
    job_status[request] = "failed"
    counts = []
    gate = threading.Barrier(2)

    def run():
        gate.wait()
        counts.append(work.report_job_ends())
    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert sorted(counts) == [0, 1]
    assert len([r for r in _messages(conversation) if r.role == "assistant"]) == 2   # the card's own answer and one end message
    assert len(_notices()) == 1


def test_a_pass_that_fails_after_the_claim_rolls_it_back_and_the_next_pass_posts_once(job_status, monkeypatch):
    conversation = _conversation()
    request, _ = _card_job(conversation)
    job_status[request] = "succeeded"
    real = work._post_end
    monkeypatch.setattr(work, "_post_end", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert work.report_job_ends() == 0
    monkeypatch.setattr(work, "_post_end", real)
    assert work.report_job_ends() == 1 and work.report_job_ends() == 0
    assert len(_messages(conversation)) == 4


# ---- Review Focus 4: the owner's list ----

def test_the_list_shows_the_running_turn_the_queued_routine_the_running_analysis_and_yesterdays_failed_forecast(job_status):
    now = datetime.now(UTC)
    conversation = _conversation()
    work.start_turn(OWNER, conversation, str(uuid.uuid4()), "你手上有什么事")
    analysis, _ = _card_job(conversation, action="analyze", title="分析 AAPL 10-Q", created=now - timedelta(minutes=2))
    job_status[analysis] = "running"
    forecast, _ = _card_job(conversation, title="预测 TSLA", created=now - timedelta(hours=20), updated=now - timedelta(hours=19))
    job_status[forecast] = "failed"
    with SessionLocal() as db:
        db.add(AgentTask(owner_hash=OWNER, name="每日简报", kind="brief", schedule_kind="daily", schedule_time="08:00", timezone="Asia/Shanghai",
                         scope="research_queue", symbols=[], channel="inbox", config={}, enabled=True, next_run_at=now + timedelta(hours=3)))
        # another owner's work: none of it may show
        db.add(AgentTask(owner_hash=OTHER, name="别人的例行", kind="brief", schedule_kind="daily", schedule_time="09:00", timezone="Asia/Shanghai",
                         scope="research_queue", symbols=[], channel="inbox", config={}, enabled=True, next_run_at=now + timedelta(hours=3)))
        db.commit()
    work.start_turn(OTHER, _conversation(OTHER), str(uuid.uuid4()), "别人的问题")
    other_conversation = _conversation(OTHER)
    other_request, _ = _card_job(other_conversation, owner=OTHER, title="别人的预测")
    job_status[other_request] = "running"

    items = work.list_for(OWNER)

    by_kind = {(i["kind"], i["title"]): i for i in items}
    chat = next(i for i in items if i["kind"] == "chat")
    routine = next(i for i in items if i["kind"] == "routine")
    running_job = next(i for i in items if "分析 AAPL 10-Q" in i["title"])
    failed_job = next(i for i in items if "预测 TSLA" in i["title"])
    assert (chat["status"], chat["status_label"]) == ("running", "进行中") and "你手上有什么事" in chat["title"] and chat["started_at"]
    assert (routine["status"], routine["status_label"]) == ("queued", "排队中") and "每日简报" in routine["title"] and routine["next_run_at"]
    assert (running_job["status"], running_job["status_label"], running_job["ended_at"]) == ("running", "进行中", None)
    assert (failed_job["status"], failed_job["status_label"]) == ("failed", "失败") and failed_job["failure"] and failed_job["ended_at"]
    assert not any("别人" in i["title"] for i in items) and len(items) == 4 and by_kind
    assert work.list_for("someone-else-entirely") == []     # a guest's own hash has nothing


def test_yesterdays_ended_work_and_old_turns_drop_off_and_the_list_is_bounded(job_status):
    now = datetime.now(UTC)
    conversation = _conversation()
    old_request, _ = _card_job(conversation, title="很久以前", created=now - timedelta(days=3), updated=now - timedelta(days=3))
    job_status[old_request] = "failed"
    for i in range(35):
        work.start_turn(OWNER, conversation, str(uuid.uuid4()), f"问题{i}")
    items = work.list_for(OWNER)
    assert len(items) == 30 and not any("很久以前" in i["title"] for i in items)
    assert [i["started_at"] for i in items] == sorted((i["started_at"] for i in items), reverse=True)


def test_archive_builds_show_for_the_owner_only(job_status, monkeypatch):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(ArchiveSubject(symbol="PLTR", held=False, queued=False, asked_at=now, first_seen_at=now, last_active_at=now, build_status="building",
                              build_started_at=now - timedelta(minutes=4), filings_added=0))
        db.add(ArchiveSubject(symbol="SNOW", held=False, queued=False, asked_at=now, first_seen_at=now, last_active_at=now, build_status="queued", filings_added=0))
        db.add(ArchiveSubject(symbol="HELD", held=True, queued=False, asked_at=None, first_seen_at=now, last_active_at=now, build_status="building",
                              build_started_at=now, filings_added=0))     # nobody asked: the system's own, not the owner's request
        db.commit()
    import app.sentinel_bridge as bridge
    monkeypatch.setattr(bridge, "owner_hash_from_login_config", lambda: OWNER)
    items = {i["title"]: i for i in work.list_for(OWNER) if i["kind"] == "archive"}
    assert {i["status"] for i in items.values()} == {"running", "queued"} and len(items) == 2 and any("PLTR" in t for t in items)
    assert [i for i in work.list_for(OTHER) if i["kind"] == "archive"] == []


# ---- the kernel tool ----

def test_list_work_is_an_owner_only_unnumbered_kernel_read_with_a_phrase():
    from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, schemas
    from app.kernel import loop, progress, toolrun
    assert definitions()["list_work"].level == "read" and "list_work" in OWNER_ONLY and "list_work" in KERNEL_ONLY
    assert "list_work" in loop.READ_TOOLS and progress.TOOL_PHRASES["list_work"] == "看手上的事"
    assert "list_work" in toolrun._UNNUMBERED and "list_work" in toolrun._OWN_STATE_READS
    assert any(s["function"]["name"] == "list_work" for s in schemas(owner=True, kernel=True))
    assert not any(s["function"]["name"] == "list_work" for s in schemas(owner=True))        # the old engine is not offered it
    assert not any(s["function"]["name"] == "list_work" for s in schemas(owner=False, kernel=True))


def test_the_tool_lists_the_owners_work_and_refuses_a_guest(job_status):
    from app.agent_workflow import tools
    conversation = _conversation()
    work.start_turn(OWNER, conversation, str(uuid.uuid4()), "在问的事")
    context = SimpleNamespace(owner_hash=OWNER)
    out = asyncio.run(tools._dispatch("list_work", {}, context, True, None))
    assert out["ok"] and [row["kind"] for row in out["data"]] == ["chat"] and out["data"][0]["status_label"] == "进行中"
    refused = asyncio.run(tools._dispatch("list_work", {}, context, False, None))
    assert refused["ok"] is False and refused["error_code"] == "owner_login_required"


def test_the_watcher_is_one_of_the_background_loops():
    from app import background
    loops = {name: (seconds, job) for name, seconds, job in background.LOOPS}
    assert loops["work-watch"][0] == 60 and loops["work-watch"][1] is background.run_work_watch
