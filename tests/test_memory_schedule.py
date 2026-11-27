"""4b Task 1: the memory calendar.  Review Focus 1 (two workers, one run), 3 (the box was down: one run, next due 30 days later);
claim expiry; a restart; the work list; the model ledger purpose."""
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import memory_schedule as sched
from app import model_usage
from app.agent_chat_models import AgentConversation, AgentMessage, MemoryJob
from app.database import Base, SessionLocal, engine

OWNER = "owner-hash-memory-schedule"
OTHER = "other-hash-memory-schedule"
JOB = "monthly_review"
NOW = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def tables(monkeypatch):
    import app.agent_tasks  # noqa: F401  (registers its tables)
    from app import work
    Base.metadata.create_all(engine, tables=[MemoryJob.__table__, AgentConversation.__table__, AgentMessage.__table__, work.AgentWork.__table__,
                                             *(t for t in Base.metadata.tables.values() if t.name in ("agent_tasks", "agent_task_runs", "archive_subjects"))])
    with SessionLocal() as db:
        db.query(MemoryJob).delete()
        db.query(AgentMessage).delete()
        db.query(AgentConversation).delete()
        db.commit()
    for name in ("FINBOT_MEMORY_REVIEW_DAYS", "FINBOT_MEMORY_REVIEW_MIN_MESSAGES"):
        monkeypatch.delenv(name, raising=False)


def _register(created: datetime, owner=OWNER):
    sched.register(JOB, owner)
    with SessionLocal() as db:
        db.query(MemoryJob).filter_by(job=JOB, owner_hash=owner).update({"created_at": created})
        db.commit()


def _messages(count, when, owner=OWNER, role="user"):
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=owner)
        db.add(conversation)
        db.flush()
        for i in range(count):
            db.add(AgentMessage(conversation_id=conversation.id, turn_id=uuid.uuid4(), sequence=i, role=role, content=f"m{i}", created_at=when))
        db.commit()


def _row(owner=OWNER):
    with SessionLocal() as db:
        return db.query(MemoryJob).filter_by(job=JOB, owner_hash=owner).one()


def test_the_registry_names_the_monthly_review_and_register_is_idempotent():
    assert sched.JOBS["monthly_review"] == "app.memory_review:run"
    sched.register(JOB, OWNER)
    first = _row().created_at
    sched.register(JOB, OWNER)
    with SessionLocal() as db:
        assert db.query(MemoryJob).count() == 1
    assert _row().created_at == first


def test_a_new_job_is_due_thirty_days_after_it_was_registered():
    _register(NOW - timedelta(days=29, hours=23))
    assert sched.due(NOW) == []
    assert sched.due(NOW + timedelta(hours=2)) == [(JOB, OWNER)]


def test_the_days_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("FINBOT_MEMORY_REVIEW_DAYS", "7")
    _register(NOW - timedelta(days=8))
    assert sched.due(NOW) == [(JOB, OWNER)]


def test_enough_owner_messages_since_the_last_run_make_it_due_early():
    _register(NOW - timedelta(days=60))
    assert claim_and_finish(NOW - timedelta(days=5))          # last ran five days ago
    _messages(39, NOW - timedelta(days=1))
    _messages(5, NOW - timedelta(days=1), role="assistant")    # only his own messages count
    _messages(50, NOW - timedelta(days=1), owner=OTHER)
    _messages(50, NOW - timedelta(days=9))                     # before the last run
    assert sched.owner_messages_since(OWNER, NOW - timedelta(days=5)) == 39
    assert sched.due(NOW) == []
    _messages(1, NOW - timedelta(hours=1))
    assert sched.owner_messages_since(OWNER, NOW - timedelta(days=5)) == 40
    assert sched.due(NOW) == [(JOB, OWNER)]


def test_the_message_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("FINBOT_MEMORY_REVIEW_MIN_MESSAGES", "3")
    _register(NOW - timedelta(days=2))
    _messages(3, NOW - timedelta(days=1))
    assert sched.due(NOW) == [(JOB, OWNER)]
    assert sched.owner_messages_since(OWNER, None) == 3        # no start: all of them


def claim_and_finish(when):
    assert sched.claim(JOB, OWNER, when, worker="w")
    sched.finish(JOB, OWNER, "done", None, when)
    return True


def test_a_run_records_its_outcome_and_the_next_due_time_is_thirty_days_on():
    _register(NOW - timedelta(days=31))
    assert sched.claim(JOB, OWNER, NOW, worker="w1")
    assert _row().claimed_by == "w1"
    sched.finish(JOB, OWNER, "done", None, NOW)
    row = _row()
    assert (row.last_outcome, row.last_reason, row.last_run_at, row.claimed_at, row.claimed_by) == ("done", None, NOW, None, None)
    assert sched.next_due(JOB, OWNER) == NOW + timedelta(days=30)
    assert sched.due(NOW + timedelta(days=29)) == []
    assert sched.due(NOW + timedelta(days=30)) == [(JOB, OWNER)]


def test_review_focus_1_two_workers_tick_in_the_same_second_and_exactly_one_runs():
    _register(NOW - timedelta(days=31))
    results, barrier = [], threading.Barrier(2)

    def worker(name):
        barrier.wait()
        won = sched.claim(JOB, OWNER, NOW, worker=name)
        if won:                                                   # runs its job at once and finishes before the other looks again
            sched.finish(JOB, OWNER, "done", None, NOW)
        results.append(won)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, True]
    assert sched.claim(JOB, OWNER, NOW, worker="late") is False   # a late third finds it no longer due


def test_a_held_claim_blocks_others_and_expires_after_thirty_minutes():
    _register(NOW - timedelta(days=31))
    assert sched.claim(JOB, OWNER, NOW, worker="a")
    assert sched.claim(JOB, OWNER, NOW + timedelta(minutes=29), worker="b") is False
    assert sched.claim(JOB, OWNER, NOW + timedelta(minutes=31), worker="b") is True
    assert _row().claimed_by == "b"


def test_a_restart_in_the_middle_leaves_the_claim_to_expire_then_the_job_runs_again():
    _register(NOW - timedelta(days=31))
    assert sched.claim(JOB, OWNER, NOW, worker="before-restart")          # the process died here: no finish
    sched.register(JOB, OWNER)                                             # startup registers again: nothing changes
    assert _row().claimed_by == "before-restart"
    assert sched.claim(JOB, OWNER, NOW + timedelta(minutes=10), worker="after") is False
    assert sched.claim(JOB, OWNER, NOW + timedelta(minutes=40), worker="after") is True


def test_review_focus_3_the_box_was_down_for_forty_days_one_run_then_thirty_days_later():
    _register(NOW - timedelta(days=100))
    sched.claim(JOB, OWNER, NOW - timedelta(days=70), worker="w")
    sched.finish(JOB, OWNER, "done", None, NOW - timedelta(days=70))      # the last run, 70 days ago; due 40 days ago
    calls = []
    ran = sched.tick(NOW, runner=lambda job, owner, now, last: calls.append((job, owner, now, last)) or {"outcome": "done", "reason": None})
    assert ran == 1 and len(calls) == 1 and calls[0][3] == NOW - timedelta(days=70)
    assert sched.tick(NOW + timedelta(minutes=10), runner=lambda *a: calls.append(a) or {"outcome": "done"}) == 0
    assert len(calls) == 1
    assert sched.next_due(JOB, OWNER) == NOW + timedelta(days=30)


def test_a_skipped_run_waits_for_the_next_due_time_and_a_failed_one_is_tried_again_later():
    _register(NOW - timedelta(days=31))
    sched.tick(NOW, runner=lambda *a: {"outcome": "skipped", "reason": "too_few"})
    row = _row()
    assert (row.last_outcome, row.last_reason, row.last_run_at) == ("skipped", "too_few", NOW)
    assert sched.due(NOW + timedelta(days=1)) == []
    _register(NOW - timedelta(days=31), owner=OTHER)
    sched.tick(NOW, runner=lambda *a: {"outcome": "failed", "reason": "模型没有回应"})
    other = _row(OTHER)
    assert (other.last_outcome, other.last_reason) == ("failed", "模型没有回应")
    assert (JOB, OTHER) not in sched.due(NOW + timedelta(minutes=10))     # not at once
    assert (JOB, OTHER) in sched.due(NOW + timedelta(hours=7))            # but within the day


def test_a_job_that_raises_or_returns_nonsense_is_a_failed_run_and_the_loop_goes_on():
    _register(NOW - timedelta(days=31))
    _register(NOW - timedelta(days=31), owner=OTHER)

    def runner(job, owner, now, last):
        if owner == OWNER:
            raise RuntimeError("boom")
        return "nonsense"
    assert sched.tick(NOW, runner=runner) == 2
    assert _row().last_outcome == "failed" and _row(OTHER).last_outcome == "failed"
    assert _row().last_reason and _row(OTHER).last_reason
    assert _row().claimed_at is None


def test_a_job_whose_module_is_not_there_yet_fails_with_its_own_reason(monkeypatch):
    monkeypatch.setitem(sched.JOBS, JOB, "app.no_such_memory_module:run")
    _register(NOW - timedelta(days=31))
    assert sched.tick(NOW) == 1                                            # the default runner imports app.memory_review lazily
    row = _row()
    assert (row.last_outcome, row.last_reason) == ("failed", "整理程序还没装好")


def test_the_default_runner_calls_the_registered_function_under_the_memory_purpose(monkeypatch):
    import sys
    import types
    seen = {}

    def run(owner_hash, now, last_run_at):
        seen["tags"] = dict(model_usage._TAGS.get() or {})
        seen["args"] = (owner_hash, now, last_run_at)
        return {"outcome": "done", "reason": None, "proposed": 2}
    module = types.ModuleType("app.memory_review")
    module.run = run
    monkeypatch.setitem(sys.modules, "app.memory_review", module)
    _register(NOW - timedelta(days=31))
    assert sched.tick(NOW) == 1
    assert seen["args"] == (OWNER, NOW, None)
    assert (seen["tags"]["purpose"], seen["tags"]["owner_hash"], seen["tags"]["job"]) == ("memory", OWNER, JOB)
    assert _row().last_outcome == "done"


def test_memory_is_a_ledger_purpose():
    assert "memory" in model_usage.PURPOSES


def test_the_work_list_shows_the_job_queued_then_with_its_last_outcome():
    from app import work
    _register(NOW - timedelta(days=2))
    item = next(i for i in work.list_for(OWNER, now=NOW) if i["kind"] == "memory")
    assert (item["title"], item["status"], item["status_label"], item["failure"]) == ("每月整理记忆", "queued", "排队中", None)
    assert item["next_run_at"] == (NOW - timedelta(days=2) + timedelta(days=30)).isoformat() and item["next_run_local"]
    assert not any(i["kind"] == "memory" for i in work.list_for(OTHER, now=NOW))
    sched.claim(JOB, OWNER, NOW - timedelta(days=1), worker="w")
    sched.finish(JOB, OWNER, "failed", "模型没有回应", NOW - timedelta(days=1))
    item = next(i for i in work.list_for(OWNER, now=NOW) if i["kind"] == "memory")
    assert (item["status"], item["failure"]) == ("failed", "模型没有回应")
    sched.finish(JOB, OWNER, "done", None, NOW - timedelta(hours=1))
    item = next(i for i in work.list_for(OWNER, now=NOW) if i["kind"] == "memory")
    assert (item["status"], item["failure"], item["ended_at"]) == ("done", None, (NOW - timedelta(hours=1)).isoformat())


def test_the_loop_is_registered_and_registering_follows_the_configured_owner(monkeypatch):
    from app import background
    assert {n: i for n, i, _ in background.LOOPS}["memory-jobs"] == 600
    monkeypatch.setattr("app.sentinel_bridge.owner_hash_from_login_config", lambda: OWNER)
    sched.register_for_configured_owner()
    assert _row().owner_hash == OWNER
    monkeypatch.setattr("app.sentinel_bridge.owner_hash_from_login_config", lambda: None)
    sched.register_for_configured_owner()                                   # no owner configured: nothing, no error


# --- 5d-3c: the weekly self-check on the same calendar ------------------------------------------------------------------

def _register_job(job, created, owner=OWNER):
    sched.register(job, owner)
    with SessionLocal() as db:
        db.query(MemoryJob).filter_by(job=job, owner_hash=owner).update({"created_at": created})
        db.commit()


def test_the_weekly_self_check_is_due_every_seven_days_and_a_busy_week_does_not_bring_it_forward(monkeypatch):
    assert sched.JOBS["weekly_quality"] == "app.quality_review:run" and sched.JOB_TITLES["weekly_quality"] == "每周自检"
    monkeypatch.setenv("FINBOT_MEMORY_REVIEW_MIN_MESSAGES", "3")
    _register_job("weekly_quality", NOW - timedelta(days=6, hours=23))
    _messages(50, NOW - timedelta(days=1))
    assert ("weekly_quality", OWNER) not in sched.due(NOW), "messages bring only the monthly review forward"
    assert ("weekly_quality", OWNER) in sched.due(NOW + timedelta(hours=2))
    monkeypatch.setenv("FINBOT_QUALITY_DAYS", "3")
    assert ("weekly_quality", OWNER) in sched.due(NOW)


def test_the_weekly_self_check_counts_its_model_calls_as_quality(monkeypatch):
    import sys
    import types
    seen = {}

    def run(owner_hash, now, last_run_at):
        seen["purpose"] = (model_usage._TAGS.get() or {}).get("purpose")
        return {"outcome": "done", "reason": None}
    module = types.ModuleType("app.quality_review")
    module.run = run
    module.days = lambda: 7
    monkeypatch.setitem(sys.modules, "app.quality_review", module)
    _register_job("weekly_quality", NOW - timedelta(days=8))
    assert sched.tick(NOW) == 1 and seen["purpose"] == "quality"
    assert "quality" in model_usage.PURPOSES


def test_the_memory_page_calendar_lists_the_memory_jobs_only(monkeypatch):
    from app import memory_overview
    _register_job("monthly_review", NOW - timedelta(days=1))
    _register_job("weekly_quality", NOW - timedelta(days=1))
    assert [job["job"] for job in memory_overview._jobs(OWNER)] == ["monthly_review"]
