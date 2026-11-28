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
    assert [r.role for r in rows] == ["user", "assistant"] and rows[1].turn_id == rows[0].turn_id and rows[1].status == "failed"
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


def _stored(conversation):
    return [{"turn_id": str(r.turn_id), "sequence": r.sequence, "role": r.role, "content": r.content, "status": r.status,
             "tool_calls": r.tool_calls} for r in _rows(conversation)]


def test_every_reader_sees_the_swept_turn_as_one_ordinary_failed_turn():
    conversation, turn = _conversation_with_user_row("英伟达的营收")
    work.start_turn(OWNER, conversation, turn, "英伟达的营收")
    with SessionLocal() as db:  # the partial record the turn had stored before the restart stays as it was
        db.add(AgentMessage(conversation_id=uuid.UUID(conversation), turn_id=uuid.UUID(turn), sequence=2, role="assistant", content="",
                            tool_calls={"calls": [{"id": "c1"}]}, status="complete"))
        db.add(AgentMessage(conversation_id=uuid.UUID(conversation), turn_id=uuid.UUID(turn), sequence=3, role="tool", content="{}",
                            tool_call_id="c1", status="complete"))
        db.commit()
    work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1))
    rows = _rows(conversation)
    assert [(r.role, r.sequence) for r in rows] == [("user", 1), ("assistant", 2), ("tool", 3), ("assistant", 4)]
    assert {r.turn_id for r in rows} == {rows[0].turn_id} and rows[3].status == "failed"
    stored = _stored(conversation)

    # the web list (owned_message_page, through eligible groups): the question and the message are shown
    from app.agent_chat_store import _eligible_turn_groups
    groups = _eligible_turn_groups(_rows(conversation))
    assert len(groups) == 1 and groups[0][-1].content.startswith("上一轮在 ")
    # the next turn's history: unfinished and failed, exactly as a failed turn is carried; in no complete layer
    assert layers.trailing_unfinished(stored) == [{"turn_id": turn, "content": "英伟达的营收", "state": "failed"}]
    assert layers.complete_turns(stored) == []
    # the line is not busy (it ended)
    from app.agent_tasks import line_busy
    with SessionLocal() as db:
        assert line_busy(db, uuid.UUID(conversation), datetime.now(UTC)) is False
    # the backstage reads the turn's last assistant row: failed, like the exception path's
    from app.backstage_api import derive_status
    assert derive_status("failed", True) == "failed"


def test_a_turn_whose_answer_was_stored_before_the_crash_is_closed_without_a_message():
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "q")
    with SessionLocal() as db:
        db.add(AgentMessage(conversation_id=uuid.UUID(conversation), turn_id=uuid.UUID(turn), sequence=2, role="assistant",
                            content="答案", status="complete"))
        db.commit()
    assert work.sweep_interrupted(datetime.now(UTC) + timedelta(seconds=1)) == 0
    assert _item(turn).status == "done" and len(_rows(conversation)) == 2


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


# ---- Task 2: detached by default, the notice when nobody was reading, the turn time limit ----

from app.agent_chat_models import AgentBot, AgentChannelPref, AgentTelegramMessage  # noqa: E402


@pytest.fixture
def outbox(monkeypatch):
    """The tables a notice touches, emptied; Telegram counts as bound."""
    for table in (AgentBot.__table__, AgentChannelPref.__table__, AgentTelegramMessage.__table__):
        table.create(engine, checkfirst=True)
    with SessionLocal() as db:
        db.query(AgentTelegramMessage).delete()
        db.commit()
    import app.channels as channels
    monkeypatch.setattr(channels, "available", lambda db, owner, channel, bot: channel == "telegram")
    monkeypatch.delenv("FINBOT_WORK_DAILY_CAP", raising=False)


def _notices():
    with SessionLocal() as db:
        return db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.source == "work")).all()


def _finished(status="done", reader=False, owner=OWNER, text="苹果的营收是多少", reason=None):
    conversation, turn = _conversation_with_user_row(text)
    work.start_turn(owner, conversation, turn, text)
    work.end_turn(turn, status, reason, reader_present=reader)
    return turn


def test_one_notice_when_nobody_was_reading_and_never_a_second(outbox):
    turn = _finished("done")
    assert work.notify_if_unattended(turn) is True
    assert work.notify_if_unattended(turn) is False  # a retry, a second worker: the item is claimed once
    [notice] = _notices()
    assert "苹果的营收是多少" in notice.text and "答完" in notice.text and "对话" in notice.text and len(notice.text) < 200
    assert notice.owner_hash == OWNER


def test_a_failed_turn_says_why_in_one_line(outbox):
    turn = _finished("failed", reason="超过 20 分钟还没答完，已经停下")
    assert work.notify_if_unattended(turn) is True
    [notice] = _notices()
    assert "没答完" in notice.text and "超过 20 分钟还没答完，已经停下" in notice.text and "\n\n" not in notice.text.split("\n", 1)[1]


@pytest.mark.parametrize("status,reader", [("done", True), ("done", None), ("stopped", False), ("running", None)])
def test_no_notice_when_the_reader_was_there_or_the_turn_was_stopped_or_still_runs(outbox, status, reader):
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "q")
    if status != "running":
        work.end_turn(turn, status, "x" if status != "done" else None, reader_present=reader)
    assert work.notify_if_unattended(turn) is False and _notices() == []


def test_a_deep_research_turn_comes_back_to_him_even_while_he_reads(outbox):
    """Design 4.4: deep research said 「做完来找你」, so its end is pushed whether or not a page was still reading it."""
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "q")
    work.end_turn(turn, "done", None, reader_present=True)
    assert work.notify_if_unattended(turn) is False                  # an ordinary turn with a reader: no news
    assert work.notify_if_unattended(turn, deep=True) is True
    assert work.notify_if_unattended(turn, deep=True) is False       # once
    [notice] = _notices()
    assert "深度研究" in notice.text and "做完了" in notice.text


def test_a_stopped_deep_turn_is_not_pushed(outbox):
    conversation, turn = _conversation_with_user_row()
    work.start_turn(OWNER, conversation, turn, "q")
    work.end_turn(turn, "stopped", "x", reader_present=True)
    assert work.notify_if_unattended(turn, deep=True) is False and _notices() == []


def test_work_notices_have_their_own_daily_count_and_do_not_use_the_bots_cap(outbox, monkeypatch):
    from app import agent_bots
    bot = agent_bots.ensure_default_bot(OWNER)
    with SessionLocal() as db:
        db.get(AgentBot, bot.id).daily_notify_cap = 0
        db.commit()
    monkeypatch.setenv("FINBOT_WORK_DAILY_CAP", "2")
    results = [work.notify_if_unattended(_finished("done")) for _ in range(3)]
    assert results == [True, True, False] and len(_notices()) == 2
    from app.agent_telegram import UNCAPPED
    assert "work" in UNCAPPED


def test_a_notice_that_cannot_be_queued_leaves_the_item_for_a_later_try(outbox, monkeypatch):
    import app.channels as channels
    turn = _finished("done")
    monkeypatch.setattr(channels, "available", lambda *a: False)
    assert work.notify_if_unattended(turn) is False and _notices() == []
    monkeypatch.setattr(channels, "available", lambda db, owner, channel, bot: channel == "telegram")
    assert work.notify_if_unattended(turn) is True and len(_notices()) == 1


def test_detached_is_the_default_and_a_closed_page_gets_one_notice_and_one_stored_answer(stream_fixture, outbox, cid_t2, monkeypatch):
    stored = stream_fixture[4]
    _quiet(monkeypatch)
    monkeypatch.delenv("FINBOT_FP13_DETACHED_TURNS", raising=False)
    monkeypatch.setattr(stream, "_is_owner", lambda credential: True)
    monkeypatch.setattr(stream, "owner_hash", lambda credential: OWNER)
    gate = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        gate["event"] = asyncio.Event()
        response = await _start(cid_t2, detach=True)
        body = response.body_iterator
        first = await body.__anext__()
        assert first.startswith(": detached")  # no env set: the flag defaults on
        for _ in range(2):
            await body.__anext__()
        await body.aclose()  # the page is closed
        task = stream.TURNS[cid_t2]["task"]
        gate["event"].set()
        await task
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(scenario())
    assert len([1 for args, kw in stored if len(args) > 2 and args[2] == "assistant" and kw.get("status") == "complete"]) == 1
    [notice] = _notices()
    assert "show AAPL prices" in notice.text and "答完" in notice.text


def test_a_guest_turn_with_nobody_reading_sends_no_notice(stream_fixture, outbox, cid_t2, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(stream, "_is_owner", lambda credential: False)
    gate = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid_t2, detach=True)).body_iterator
        for _ in range(3):
            await body.__anext__()
        await body.aclose()
        task = stream.TURNS[cid_t2]["task"]
        gate["event"].set()
        await task
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(scenario())
    assert _notices() == [] and _only_item(cid_t2).status == "done"


@pytest.fixture
def cid_t2():
    return str(uuid.uuid4())


@pytest.mark.parametrize("detach", [False, True])
def test_a_turn_past_the_time_limit_is_stopped_failed_and_its_lock_released(stream_fixture, outbox, cid_t2, monkeypatch, detach):
    stored = stream_fixture[4]
    _quiet(monkeypatch)
    monkeypatch.setattr(stream, "MAX_TURN_SECONDS", 0.3)
    monkeypatch.setattr(stream, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")
    ran = {}

    async def workflow(**_):
        yield {"event": "delta", "text": "partial answer"}
        try:
            await asyncio.sleep(60)
        finally:
            ran["stopped"] = True
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        body = (await _start(cid_t2, detach=detach)).body_iterator
        parts = [part async for part in body]
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
        return "".join(parts)
    wire = _run(scenario())
    assert "event: error" in wire and "turn_timeout" in wire and "event: done" not in wire
    item = _only_item(cid_t2)
    assert item.status == "failed" and item.reason == stream.turn_timeout_reason()
    assert cid_t2 not in stream.LOCKS and cid_t2 not in stream.TURNS and ran.get("stopped")
    failed_rows = [(args, kw) for args, kw in stored if len(args) > 2 and args[2] == "assistant" and kw.get("status") == "failed"]
    assert len(failed_rows) == 1 and not [1 for args, kw in stored if kw.get("status") == "cancelled"]
    text = failed_rows[0][0][3]
    assert text == "partial answer\n\n（超过 1 分钟还没答完，已经停下。）".replace("1 分钟", f"{max(1, round(stream.MAX_TURN_SECONDS / 60))} 分钟")
    assert {"finished": "failed"} in [kw for _, kw in stored]
    assert "（超过" in wire


def test_the_time_limit_reason_counts_the_minutes_of_the_constant(monkeypatch):
    assert stream.turn_timeout_reason() == "超过 20 分钟还没答完，已经停下"
    monkeypatch.setattr(stream, "MAX_TURN_SECONDS", 600)
    assert stream.turn_timeout_reason() == "超过 10 分钟还没答完，已经停下"


def _timeout_setup(monkeypatch, limit=0.3):
    _quiet(monkeypatch)
    monkeypatch.setattr(stream, "MAX_TURN_SECONDS", limit)
    monkeypatch.setattr(stream, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")


def test_a_timed_out_turn_with_no_partial_answer_stores_the_sentence_alone(stream_fixture, outbox, cid_t2, monkeypatch):
    stored = stream_fixture[4]
    _timeout_setup(monkeypatch)

    async def workflow(**_):
        await asyncio.sleep(60)
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        await _drain_detached(cid_t2)
    _run(scenario())
    rows = [(args[3], kw) for args, kw in stored if len(args) > 2 and args[2] == "assistant"]
    assert rows[-1][0] == f"（{stream.turn_timeout_reason()}。）" and rows[-1][1]["status"] == "failed"


async def _drain_detached(cid):
    body = (await _start(cid, detach=True)).body_iterator
    parts = [part async for part in body]
    for pending in list(stream._BACKGROUND):
        await asyncio.gather(pending, return_exceptions=True)
    return "".join(parts)


def test_a_pump_that_always_has_an_event_ready_still_hits_the_limit(stream_fixture, outbox, cid_t2, monkeypatch):
    _timeout_setup(monkeypatch, 0.3)

    async def workflow(**_):
        while True:
            yield {"event": "narration", "text": "…"}
            await asyncio.sleep(0)
    monkeypatch.setattr(stream, "stream_workflow", workflow)
    wire = _run(_drain_detached(cid_t2))
    assert "turn_timeout" in wire and _only_item(cid_t2).status == "failed"


def test_a_stop_during_the_timeout_writes_still_ends_the_item_failed_with_the_reason(stream_fixture, outbox, cid_t2, monkeypatch):
    stored = stream_fixture[4]
    _timeout_setup(monkeypatch)
    real_append = stream.append_message

    async def slow_append(*args, **kwargs):
        if len(args) > 2 and args[2] == "assistant" and kwargs.get("status") == "failed":
            await asyncio.sleep(0.4)
        return await real_append(*args, **kwargs)
    monkeypatch.setattr(stream, "append_message", slow_append)

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        await asyncio.sleep(60)
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    # drive by hand: wait for the limit, then stop while the slow write is in flight
    async def hand():
        response = await _start(cid_t2, detach=True)
        body = response.body_iterator
        task = stream.TURNS[cid_t2]["task"]
        for _ in range(3):
            await body.__anext__()
        await asyncio.sleep(0.45)      # past the 0.3 s limit: the slow failed-row write is in flight
        task.cancel()                  # the stop button
        await asyncio.gather(task, return_exceptions=True)
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
        await asyncio.sleep(0.2)
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(hand())
    item = _only_item(cid_t2)
    assert item.status == "failed" and item.reason == stream.turn_timeout_reason()
    assert [kw for args, kw in stored if len(args) > 2 and args[2] == "assistant" and kw.get("status") == "failed"]


def test_a_stop_while_the_done_path_ends_the_item_does_not_lose_the_end_or_the_notice(stream_fixture, outbox, cid_t2, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")
    monkeypatch.setattr(stream, "_is_owner", lambda credential: True)
    monkeypatch.setattr(stream, "owner_hash", lambda credential: OWNER)
    real_end = work.end_turn

    def slow_end(*args, **kwargs):
        import time
        time.sleep(0.3)
        return real_end(*args, **kwargs)
    monkeypatch.setattr(work, "end_turn", slow_end)

    async def workflow(**_):
        yield {"event": "delta", "text": "partial"}
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def hand():
        body = (await _start(cid_t2, detach=True)).body_iterator
        task = stream.TURNS[cid_t2]["task"]
        await body.__anext__()
        await body.aclose()            # nobody reading
        await asyncio.sleep(0.1)       # the done path is inside its slow end_turn
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0.5)
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(hand())
    item = _only_item(cid_t2)
    assert item.status in ("done", "stopped") and item.status != "running" and item.ended_at is not None


def test_a_cancel_during_start_turn_leaves_no_running_row(stream_fixture, outbox, cid_t2, monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setenv("FINBOT_FP13_DETACHED_TURNS", "on")
    real_start = work.start_turn

    def slow_start(*args, **kwargs):
        import time
        time.sleep(0.3)
        return real_start(*args, **kwargs)
    monkeypatch.setattr(work, "start_turn", slow_start)

    async def workflow(**_):
        await asyncio.sleep(60)
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def hand():
        body = (await _start(cid_t2, detach=True)).body_iterator
        task = stream.TURNS[cid_t2]["task"]
        await body.__anext__()
        await asyncio.sleep(0.1)       # inside the slow insert
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0.6)
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(hand())
    assert _only_item(cid_t2).status == "stopped"


@pytest.mark.parametrize("detach", [True, False])
def test_a_deep_turn_read_to_the_end_is_pushed_only_on_the_web(stream_fixture, outbox, cid_t2, monkeypatch, detach):
    """Deep research (tier max) said it would come back to him: on the web (a detached turn) its end is pushed even though the page
    read it to the end; a bridge (not detached) reads its turn to the end and sends the answer itself, so no second line."""
    _quiet(monkeypatch)
    monkeypatch.delenv("FINBOT_FP13_DETACHED_TURNS", raising=False)
    monkeypatch.setattr(stream, "_is_owner", lambda credential: True)
    monkeypatch.setattr(stream, "owner_hash", lambda credential: OWNER)

    async def workflow(**_):
        yield {"event": "tier", "tier": "max"}
        yield {"event": "delta", "text": "研究结论"}
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        body = (await _start(cid_t2, detach=detach)).body_iterator
        [part async for part in body]
        for pending in list(stream._BACKGROUND):
            await asyncio.gather(pending, return_exceptions=True)
    _run(scenario())
    notices = _notices()
    if detach:
        assert len(notices) == 1 and "深度研究" in notices[0].text and "做完了" in notices[0].text
    else:
        assert notices == []

def test_the_web_reads_the_same_list_owner_only(monkeypatch):
    """手上的事 on the web (GET /agent-chat/work) is the list the kernel's list_work reads; a guest gets 403."""
    from fastapi.testclient import TestClient
    from app import work_api
    from app.main import app as api
    seen = []
    monkeypatch.setattr(work_api, "_owner_only", lambda credential: (_ for _ in ()).throw(stream.HTTPException(403, "owner_only")) if credential != CRED else credential)
    monkeypatch.setattr(work_api, "owner_hash", lambda credential: OWNER)
    monkeypatch.setattr(work, "list_for", lambda owner: seen.append(owner) or [{"kind": "chat", "id": "t1", "title": "回答：x", "status": "running"}])
    client = TestClient(api)
    assert client.get("/agent-chat/work", headers={"X-Chat-Session": "g" * 40}).status_code == 403
    answer = client.get("/agent-chat/work", headers={"X-Chat-Session": CRED})
    assert answer.status_code == 200 and answer.json() == {"items": [{"kind": "chat", "id": "t1", "title": "回答：x", "status": "running"}]} and seen == [OWNER]
