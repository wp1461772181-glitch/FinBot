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
    work._LOGGED.clear()
    _watching()          # the watcher has had its first pass (the baseline tests remove this)
    yield


def _watching():
    with SessionLocal() as db:
        db.add(work.AgentWork(kind=work.BASELINE, ref="card_jobs", owner_hash="", summary="", status="done"))
        db.commit()


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
    """Live job statuses by request, as the job tables would report them (the watcher and the list read them through actions._status), and
    ``live.facts[request]``: the job's own record (started, ended, status, code) that ``work._job_facts`` would read; absent means no record."""
    class Live(dict):
        facts = {}
    live = Live()
    live.facts = {}
    monkeypatch.setattr(work, "_job_facts", lambda db, request: live.facts.get(str(request["id"]), {}))
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


def _ran(live, request, seconds, *, created, status="failed", code=None):
    """The job's own record: it started when its card ran and ended ``seconds`` later."""
    live.facts[request] = {"started": created, "ended": created + timedelta(seconds=seconds), "status": status, "code": code}


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
    created = datetime.now(UTC) - timedelta(minutes=3)
    request, _ = _card_job(conversation, created=created, title="预测 AAPL")
    job_status[request] = "failed"
    _ran(job_status, request, 150, created=created, code="provider_error")

    assert work.report_job_ends() == 1
    assert work.report_job_ends() == 0   # the watcher's next minute: nothing again

    rows = _messages(conversation)
    assert [r.role for r in rows][-2:] == ["user", "assistant"] and rows[-1].status == "complete"
    assert rows[-2].content.startswith(work.WORK_END_HEAD) and "预测 AAPL" in rows[-1].content
    assert "失败了" in rows[-1].content and "你让我做的「预测 AAPL」" in rows[-1].content and "模型服务出错" in rows[-1].content
    assert "provider_error" not in rows[-1].content
    [notice] = _notices()                        # ran 150 s (over 60), nobody reading
    assert "预测 AAPL" in notice.text and "失败" in notice.text and "模型服务出错" in notice.text


def test_a_job_that_succeeds_says_where_to_see_it_and_a_short_job_or_a_reader_gets_no_notice(job_status):
    quiet = _conversation()
    created = datetime.now(UTC) - timedelta(minutes=5)
    short, _ = _card_job(quiet, created=created, title="预测 MSFT")   # it ran 20 s; the watcher saw it minutes later
    reading = _conversation(quiet=False)       # the owner's last message there was seconds ago
    slow, _ = _card_job(reading, created=created, title="预测 NVDA")
    job_status[short] = job_status[slow] = "succeeded"
    _ran(job_status, short, 20, created=created, status="succeeded")
    _ran(job_status, slow, 200, created=created, status="succeeded")

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
    created = datetime.now(UTC) - timedelta(minutes=3)
    request, _ = _card_job(conversation, created=created)
    job_status[request] = "failed"
    _ran(job_status, request, 150, created=created)
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
    forecast, _ = _card_job(conversation, title="预测 TSLA", created=now - timedelta(hours=20), updated=now - timedelta(hours=20))
    job_status[forecast] = "failed"
    _ran(job_status, forecast, 180, created=now - timedelta(hours=20), code="provider_error")
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
    assert (failed_job["status"], failed_job["status_label"]) == ("failed", "失败") and failed_job["failure"] == "模型服务出错"
    # the end shown is the job's own (3 minutes after it started), not the ledger's launch stamp; local times are given too
    assert failed_job["ended_at"] == (now - timedelta(hours=20) + timedelta(seconds=180)).astimezone(UTC).isoformat()
    assert failed_job["started_local"] and failed_job["ended_local"] and routine["next_run_local"]
    assert not any("别人" in i["title"] for i in items) and len(items) == 4 and by_kind
    assert work.list_for("someone-else-entirely") == []     # a guest's own hash has nothing


def test_yesterdays_ended_work_and_old_turns_drop_off_and_the_list_is_bounded(job_status):
    now = datetime.now(UTC)
    conversation = _conversation()
    old_request, _ = _card_job(conversation, title="很久以前", created=now - timedelta(days=3), updated=now - timedelta(days=3))
    job_status[old_request] = "failed"
    _ran(job_status, old_request, 100, created=now - timedelta(days=3))
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


# ---- Task 3 fix round 1 ----

def _baseline_off():
    with SessionLocal() as db:
        db.query(work.AgentWork).filter(work.AgentWork.kind == work.BASELINE).delete()
        db.commit()


def test_the_first_pass_ever_only_records_a_baseline_and_a_later_one_reports_what_ends_after(job_status):
    _baseline_off()
    conversation = _conversation()
    old_created = datetime.now(UTC) - timedelta(hours=5)
    old, _ = _card_job(conversation, created=old_created, title="早就结束的")
    job_status[old] = "failed"
    _ran(job_status, old, 300, created=old_created)
    live_created = datetime.now(UTC) - timedelta(minutes=10)
    still, _ = _card_job(conversation, created=live_created, title="还在跑的")
    job_status[still] = "running"

    assert work.report_job_ends() == 0                                  # the baseline pass: nothing posted, nothing queued
    assert len(_messages(conversation)) == 2 and _notices() == []
    job_status[still] = "succeeded"
    _ran(job_status, still, 400, created=live_created, status="succeeded")
    assert work.report_job_ends() == 1                                  # it ended after the baseline
    assert "还在跑的" in _messages(conversation)[-1].content and len(_notices()) == 1
    assert work.report_job_ends() == 0                                  # and the old one never is


def test_a_job_is_long_by_its_own_record_not_by_when_the_watcher_looked(job_status):
    conversation = _conversation()
    created = datetime.now(UTC) - timedelta(minutes=10)
    quick, _ = _card_job(conversation, created=created, title="很快的")
    job_status[quick] = "succeeded"
    _ran(job_status, quick, 20, created=created, status="succeeded")
    unknown, _ = _card_job(conversation, created=created, title="没有结束时间")
    job_status[unknown] = "succeeded"         # no job record at all: nothing is guessed, so it is not counted as long
    assert work.report_job_ends() == 2 and _notices() == []


def test_each_failure_has_its_own_reason_and_a_block_is_not_called_an_error():
    assert work.job_reason("blocked_data", "no_content")[0] == "这份材料没有可用的正文，这次没有做"
    assert work.job_reason("blocked_data", None) == ("数据不够，这次没有做", True)
    assert work.job_reason("failed", "provider_error") == ("模型服务出错", False)
    assert work.job_reason("failed", "invalid_model_output") == ("模型的输出没通过核对", False)
    assert work.job_reason("failed", "stage_timeout") == ("超时", False)
    assert work.job_reason("failed", None) == ("过程中出错了", False)
    assert work.job_reason("failed", "weird_code_x")[0] == "过程中出错了"      # an unknown code is never shown


def test_a_blocked_job_says_it_was_not_done_not_that_it_failed(job_status):
    conversation = _conversation()
    created = datetime.now(UTC) - timedelta(minutes=4)
    request, _ = _card_job(conversation, created=created, action="analyze", title="分析 AAPL 10-Q")
    job_status[request] = "failed"
    _ran(job_status, request, 100, created=created, status="blocked_data", code="no_content")
    assert work.report_job_ends() == 1
    text_out = _messages(conversation)[-1].content
    assert "没有做成：这份材料没有可用的正文" in text_out and "出错" not in text_out and "重试" not in text_out
    assert "没有做成" in _notices()[0].text


def test_the_job_facts_are_read_from_each_kinds_own_columns():
    class Rows:
        def __init__(self, row): self.row = row
        def mappings(self): return self
        def first(self): return self.row

    class FakeDb:
        def __init__(self, row): self.sql, self.row = [], row
        def execute(self, statement, params=None):
            self.sql.append(str(statement))
            return Rows(self.row)
        def rollback(self): pass
    started, ended = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 1, 0, 3, tzinfo=UTC)
    db = FakeDb({"started_at": None, "created_at": started, "completed_at": ended, "status": "failed", "code": "provider_error"})
    facts = work._job_facts(db, {"id": uuid.uuid4(), "job_kind": "analysis", "job_id": uuid.uuid4()})
    assert facts == {"started": started, "ended": ended, "status": "failed", "code": "provider_error"}
    assert "material_analysis_jobs" in db.sql[0] and "safe_error_code" in db.sql[0]
    db = FakeDb({"started_at": started, "created_at": started, "completed_at": None, "status": "running", "code": None})
    assert work._job_facts(db, {"id": uuid.uuid4(), "job_kind": "forecast", "job_id": uuid.uuid4()})["ended"] is None
    assert "forecast_jobs_v2" in db.sql[0] and "error_type" in db.sql[0]
    assert work._job_facts(FakeDb(None), {"id": uuid.uuid4(), "job_kind": "other", "job_id": uuid.uuid4()}) == {}


def test_the_head_row_is_marked_as_the_systems_and_the_model_sees_that(job_status):
    from app import agent_context as layers
    from app.agent_tasks import POST_NOTE
    conversation = _conversation()
    created = datetime.now(UTC) - timedelta(minutes=4)
    request, _ = _card_job(conversation, created=created, title="预测 NVDA")
    job_status[request] = "succeeded"
    _ran(job_status, request, 100, created=created, status="succeeded")
    work.report_job_ends()
    head, answer = _messages(conversation)[-2:]
    assert head.content == f"{work.WORK_END_HEAD}「预测 NVDA」{POST_NOTE}" and head.role == "user"
    rows = [{"role": r.role, "content": r.content, "tool_calls": r.tool_calls, "tool_call_id": r.tool_call_id, "status": r.status,
             "turn_id": str(r.turn_id), "sequence": r.sequence} for r in (head, answer)]
    shown = [m for group in layers.complete_turns(rows) for m in layers.project_turn_history(group)]
    assert POST_NOTE in shown[0]["content"] and shown[0]["role"] == "user"        # the history says it is not the owner's words
    from app import agent_recall
    assert head.content.startswith(agent_recall.WORK_END_HEAD)                     # and recall skips it as a question


def test_requests_that_can_never_be_posted_are_given_up_once_and_a_backlog_cannot_starve_a_new_job(job_status, monkeypatch):
    monkeypatch.setattr(work, "WATCH_BATCH", 3)
    conversation = _conversation()
    now = datetime.now(UTC)
    with SessionLocal() as db:  # a request made without a card
        db.execute(text("""INSERT INTO agent_action_requests (id,owner_hash,request_key,action,payload_digest,status,job_kind,job_id,result,created_at)
                           VALUES (:i,:o,'direct-1','forecast','d','failed','forecast',:j,'{}'::jsonb,:c)"""),
                   {"i": uuid.uuid4(), "o": OWNER, "j": uuid.uuid4(), "c": now - timedelta(hours=3)})
        db.commit()
    gone = str(uuid.uuid4())                      # a card whose conversation does not exist
    gone_request, _ = _card_job(gone, created=now - timedelta(hours=2), title="没有对话")
    job_status[gone_request] = "failed"
    running = [_card_job(conversation, created=now - timedelta(hours=1, minutes=i), title=f"还在跑{i}")[0] for i in range(1)]
    for request in running:
        job_status[request] = "running"
    newest_created = now - timedelta(minutes=10)
    newest, _ = _card_job(conversation, created=newest_created, title="最新的")
    job_status[newest] = "succeeded"
    _ran(job_status, newest, 30, created=newest_created, status="succeeded")

    assert work.report_job_ends() == 1                     # the newest is seen first, whatever is waiting behind it
    assert "最新的" in _messages(conversation)[-1].content
    work.report_job_ends()
    work.report_job_ends()
    with SessionLocal() as db:
        given = db.scalars(select(work.AgentWork).where(work.AgentWork.kind == work.CARD_JOB, work.AgentWork.status == "stopped")).all()
    assert len(given) == 2 and all(row.reason.startswith(work.GIVEN_UP) for row in given)   # both are visited once and never again
    assert len(_messages(conversation)) == 4


def test_an_archived_conversation_is_given_up_not_posted_into(job_status):
    conversation = _conversation()
    with SessionLocal() as db:
        db.get(AgentConversation, uuid.UUID(conversation)).archived_at = datetime.now(UTC)
        db.commit()
    created = datetime.now(UTC) - timedelta(minutes=3)
    request, _ = _card_job(conversation, created=created)
    job_status[request] = "succeeded"
    assert work.report_job_ends() == 0 and len(_messages(conversation)) == 2
    assert work.report_job_ends() == 0
    with SessionLocal() as db:
        assert db.scalars(select(work.AgentWork).where(work.AgentWork.ref == request)).one().status == "stopped"


def test_two_operations_of_one_card_are_told_apart(job_status):
    conversation = _conversation()
    with SessionLocal() as db:
        consent = AgentConsent(owner_hash=OWNER, conversation_id=conversation, capability_hash=uuid.uuid4().hex + uuid.uuid4().hex, payload_digest="d",
                               operations=[{"name": "a"}, {"name": "b"}], display={"title": "预测 AAPL 和 MSFT"},
                               expires_at=datetime.now(UTC), status="executed")
        db.add(consent)
        db.commit()
        card = {"action": "forecast", "request_key": f"{consent.id}.1"}
        assert work._what(consent, card) == "预测 AAPL 和 MSFT（第 2 项）"
