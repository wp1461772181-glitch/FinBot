"""3b Task 1: every chat turn has a durable work item (running, done, failed, stopped); a restart's sweep closes the turns it cut off.

The work table lives in the disposable test database.  The stream tests use the stream fixture of test_agent_chat_stream.py with a
fake workflow, so each test decides how and when the turn ends; every scenario runs under asyncio.wait_for.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.requests import Request

import app.agent_chat_stream as stream
from app import agent_context as layers
from app import work
from app.agent_chat_models import AgentConversation, AgentMessage
from app.agent_chat_stream import StreamRequest
from app.database import SessionLocal, engine
from tests.test_agent_chat_stream import stream_fixture  # noqa: F401  (fixture)

CRED = "x" * 40
OWNER = "owner-hash-for-work-tests"


@pytest.fixture(autouse=True)
def work_table():
    for table in (AgentConversation.__table__, AgentMessage.__table__, work.AgentWork.__table__):
        table.create(engine, checkfirst=True)
    with SessionLocal() as db:
        db.query(work.AgentWork).delete()
        db.commit()
    yield


def _conversation_with_user_row(text="苹果的营收是多少"):
    """A conversation whose last turn has the user's row and nothing after it: what a restart leaves behind."""
    turn = uuid.uuid4()
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=OWNER)
        db.add(conversation)
        db.flush()
        db.add(AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=1, role="user", content=text, status="complete"))
        db.commit()
        return str(conversation.id), str(turn)


def _item(turn):
    with SessionLocal() as db:
        return db.scalars(select(work.AgentWork).where(work.AgentWork.ref == str(turn))).one()


def _rows(conversation_id):
    with SessionLocal() as db:
        return db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == uuid.UUID(conversation_id))
                          .order_by(AgentMessage.sequence)).all()


def test_start_and_end_a_turn_once():
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "苹果的营收是多少")
    work.start_turn(OWNER, conversation, turn, "苹果的营收是多少")  # a repeat is a no-op
    item = _item(turn)
    assert (item.status, item.kind, item.summary, item.ended_at) == ("running", "chat_turn", "苹果的营收是多少", None)

    assert work.end_turn(turn, "failed", "模型没有回应。", reader_present=False) is True
    assert work.end_turn(turn, "done") is False  # already ended: the first end stands
    item = _item(turn)
    assert (item.status, item.reason, item.reader_present) == ("failed", "模型没有回应。", False) and item.ended_at is not None


def test_a_turn_ends_only_as_done_failed_or_stopped():
    with pytest.raises(ValueError):
        work.end_turn(str(uuid.uuid4()), "running")


def test_sweep_fails_the_cut_off_turn_and_leaves_one_message_in_its_conversation():
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "苹果的营收是多少")
    started = _item(turn).started_at

    assert work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1)) == 1

    item = _item(turn)
    assert (item.status, item.reason) == ("failed", work.RESTART_REASON) and item.ended_at is not None
    rows = _rows(conversation)
    assert [r.role for r in rows] == ["user", "assistant"] and rows[1].turn_id != rows[0].turn_id and rows[1].status == "complete"
    assert rows[1].content == work.interrupted_message(started)
    assert rows[1].content.startswith("上一轮在 ") and rows[1].content.endswith("被系统重启打断了，没有答完；要我接着做吗？")
    # a second pass (a second worker, another restart) posts nothing more
    assert work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1)) == 0
    assert len(_rows(conversation)) == 2


def test_sweep_leaves_finished_turns_and_turns_started_after_it():
    done_conversation, done_turn = _conversation_with_user_row()
    work.start_turn(OWNER, done_conversation, done_turn, "q")
    work.end_turn(done_turn, "done")
    live_conversation, live_turn = _conversation_with_user_row()
    work.start_turn(OWNER, live_conversation, live_turn, "q")

    assert work.sweep_interrupted(datetime.now(UTC) - timedelta(minutes=1)) == 0

    assert _item(done_turn).status == "done" and _item(live_turn).status == "running"
    assert len(_rows(done_conversation)) == len(_rows(live_conversation)) == 1


def test_a_failed_message_write_leaves_the_turn_running_for_the_next_start(monkeypatch):
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "q")
    monkeypatch.setattr(work, "interrupted_message", lambda _started: (_ for _ in ()).throw(RuntimeError("boom")))

    assert work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1)) == 0

    assert _item(turn).status == "running" and len(_rows(conversation)) == 1


def test_the_next_turns_history_reads_the_swept_turn_as_unfinished_exactly_as_before():
    conversation, turn = _conversation_with_user_row("英伟达的营收")
    work.start_turn(OWNER, conversation, turn, "英伟达的营收")

    def stored():
        return [{"turn_id": str(r.turn_id), "sequence": r.sequence, "role": r.role, "content": r.content, "status": r.status}
                for r in _rows(conversation)]
    before = layers.trailing_unfinished(stored())
    work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1))
    after = layers.trailing_unfinished(stored())

    assert before == after == [{"turn_id": turn, "content": "英伟达的营收", "state": "interrupted"}]
    assert layers.complete_turns(stored()) == []  # the message is in no layer of the model's history
    from app.agent_tasks import line_busy
    with SessionLocal() as db:
        assert line_busy(db, uuid.UUID(conversation), datetime.now(UTC)) is False


def test_the_api_startup_runs_the_sweep_once(monkeypatch):
    import app.main as main
    calls = []
    monkeypatch.setattr(work, "sweep_interrupted", lambda *a, **k: calls.append(1) or 0)
    main.create_tables()
    assert calls == [1]


# ---- the chat endpoint ----

def _done():
    return {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {},
            "citations": [], "route": "A", "trace": []}


def _quiet(monkeypatch):
    async def no_mark(*_):
        pass
    monkeypatch.setattr(stream, "mark_terminal_status", no_mark)


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 5))


async def _start(cid, detach=False, message="show AAPL prices"):
    payload = StreamRequest(provider="deepseek", model="deepseek-chat", api_key="abcdefgh", message=message,
                            conversation_id=cid, detach=detach)
    request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
    return await stream.stream_chat(payload, request, CRED)


def _only_item(cid):
    with SessionLocal() as db:
        return db.scalars(select(work.AgentWork).where(work.AgentWork.conversation_id == uuid.UUID(cid))).one()


@pytest.fixture
def cid():
    return str(uuid.uuid4())


def test_a_completed_turn_is_done_with_a_reader(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)

    async def workflow(**_):
        yield {"event": "delta", "text": "AAPL"}
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        body = (await _start(cid)).body_iterator
        seen = []
        async for _ in body:
            seen.append(_)
            if "event: delta" in _:
                running = _only_item(cid)
                assert running.status == "running"  # while the turn runs, it is on the list
    _run(scenario())
    item = _only_item(cid)
    assert (item.status, item.reason, item.reader_present, item.summary) == ("done", None, True, "show AAPL prices")


def test_a_failed_answer_and_a_raised_error_both_end_failed_with_a_chinese_reason(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)

    async def failing_answer(**_):
        yield {**_done(), "status": "failed"}
    monkeypatch.setattr(stream, "stream_workflow", failing_answer)
    _run(_drain(cid))
    item = _only_item(cid)
    assert item.status == "failed" and item.reason == stream.WORK_FAILED_REASON

    async def raises(**_):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover
    monkeypatch.setattr(stream, "stream_workflow", raises)
    other = str(uuid.uuid4())
    _run(_drain(other))
    item = _only_item(other)
    assert item.status == "failed" and item.reason and "RuntimeError" not in item.reason and "exploded" not in item.reason


async def _drain(cid):
    body = (await _start(cid)).body_iterator
    return [part async for part in body]


def test_a_consumer_that_hangs_up_mid_turn_leaves_a_stopped_item_with_no_reader(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    gate = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid)).body_iterator
        for _ in range(2):
            await body.__anext__()
        await body.aclose()  # the client is gone
        await asyncio.sleep(0.2)
        for task in list(stream._BACKGROUND):
            await task
    _run(scenario())
    item = _only_item(cid)
    assert (item.status, item.reader_present, item.reason) == ("stopped", False, stream.WORK_STOPPED_REASON)


def test_a_detached_turn_whose_page_closed_finishes_done_and_records_that_nobody_was_reading(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")
    gate = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid, detach=True)).body_iterator
        for _ in range(3):
            await body.__anext__()
        await body.aclose()
        task = stream.TURNS[cid]["task"]
        assert _only_item(cid).status == "running"
        gate["event"].set()
        await task
    _run(scenario())
    item = _only_item(cid)
    assert (item.status, item.reader_present) == ("done", False)


def test_the_stop_button_ends_a_detached_turn_as_stopped_with_the_reader_still_there(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")
    gate = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid, detach=True)).body_iterator
        for _ in range(3):
            await body.__anext__()
        task = stream.TURNS[cid]["task"]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
        await body.aclose()
    _run(scenario())
    item = _only_item(cid)
    assert (item.status, item.reader_present, item.reason) == ("stopped", True, stream.WORK_STOPPED_REASON)
