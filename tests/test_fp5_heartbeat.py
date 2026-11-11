"""FP5: SSE heartbeat frames, the pump that carries workflow events, and the writes made when a turn is cancelled."""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.agent_chat_store import owner_hash
from app.agent_chat_stream import StreamRequest
from tests.test_agent_chat_stream import stream_fixture  # noqa: F401  (fixture)

CID = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
OWNER = owner_hash("x" * 40)
HB = ": hb\n\n"


def _done():
    return {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {},
            "citations": [], "route": "A", "trace": []}


def _frames(wire):
    """(event, data) for each named block; a comment block such as a heartbeat is not a frame."""
    out = []
    for block in wire.split("\n\n"):
        lines = block.split("\n")
        if lines[0].startswith("event: "):
            out.append((lines[0][7:], json.loads(lines[1][6:])))
    return out


@pytest.fixture
def pinned(monkeypatch):
    """Fixed turn id and thinking time, so two runs of one stream can be compared byte for byte."""
    import app.agent_chat_stream as stream
    monkeypatch.setattr(stream, "uuid", SimpleNamespace(uuid4=lambda: TURN, UUID=UUID))
    monkeypatch.setattr(stream, "time", SimpleNamespace(monotonic=lambda: 0.0))
    return stream


def _slow_workflow(stream, monkeypatch, seconds=0.2):
    async def workflow(**_kwargs):
        await asyncio.sleep(seconds)
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)


def test_heartbeat_frames_arrive_while_the_workflow_thinks_and_nothing_else_changes(stream_fixture, pinned, monkeypatch):
    send, *_ = stream_fixture
    monkeypatch.setattr(pinned, "HEARTBEAT_SECONDS", 0.05)
    _slow_workflow(pinned, monkeypatch)
    monkeypatch.setenv("FINBOT_FP5_HEARTBEAT", "on")
    with_hb = asyncio.run(send(cid=CID))
    monkeypatch.setenv("FINBOT_FP5_HEARTBEAT", "off")
    without_hb = asyncio.run(send(cid=CID))
    assert HB in with_hb and with_hb.index(HB) < with_hb.index("event: done")
    assert with_hb.replace(HB, "") == without_hb


def test_flag_off_sends_no_heartbeat_even_with_a_short_interval(stream_fixture, pinned, monkeypatch):
    send, *_ = stream_fixture
    monkeypatch.setattr(pinned, "HEARTBEAT_SECONDS", 0.05)
    _slow_workflow(pinned, monkeypatch)
    monkeypatch.setenv("FINBOT_FP5_HEARTBEAT", "off")
    wire = asyncio.run(send(cid=CID))
    assert ": hb" not in wire and "event: done" in wire


def test_workflow_exception_crosses_the_queue_as_the_same_object(stream_fixture, pinned, monkeypatch):
    send, *_ = stream_fixture

    async def workflow(**_kwargs):
        raise HTTPException(502, "x_code")
        yield  # makes this an async generator

    monkeypatch.setattr(pinned, "stream_workflow", workflow)

    async def no_mark(*_):
        pass

    monkeypatch.setattr(pinned, "mark_terminal_status", no_mark)
    errors = [data for event, data in _frames(asyncio.run(send(cid=CID))) if event == "error"]
    assert errors == [{"code": "x_code", "status": "failed"}]


def test_event_order_through_the_pump_matches_the_workflow(stream_fixture, pinned, monkeypatch):
    send, *_ = stream_fixture

    async def workflow(**_kwargs):
        yield {"event": "tool_start", "call_id": "c1", "name": "query_stock_prices", "arguments": {"symbol": "AAPL"}}
        yield {"event": "tool_result", "call_id": "c1", "name": "query_stock_prices", "result": {"ok": True, "data": []}}
        yield {"event": "delta", "text": "AAPL"}
        yield _done()

    monkeypatch.setattr(pinned, "stream_workflow", workflow)
    wire = asyncio.run(send(cid=CID))
    assert [event for event, _ in _frames(wire)] == ["conversation", "tool_start", "tool_result", "delta", "done"]


def test_telegram_reader_skips_a_heartbeat_block():
    from app.agent_telegram import sse_events
    events = sse_events('event: delta\ndata: {"text":"a"}\n\n: hb\n\nevent: delta\ndata: {"text":"b"}\n\n')
    assert events == [("delta", {"text": "a"}), ("delta", {"text": "b"})]


def _record_fakes(stream, monkeypatch, fail=None):
    """Replace the three cancelled-turn writes with recorders; ``fail`` makes that step (0, 1 or 2) raise."""
    calls = []

    def fake(name, index):
        async def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            if fail == index:
                raise RuntimeError(f"{name} failed")
        return call

    monkeypatch.setattr(stream, "append_message", fake("append", 0))
    monkeypatch.setattr(stream, "finish_conversation", fake("finish", 1))
    monkeypatch.setattr(stream, "mark_terminal_status", fake("mark", 2))
    return calls


@pytest.mark.parametrize("citations, tool_calls", [([], None), ([{"ordinal": 1}], {"citations": [{"ordinal": 1}]})])
def test_cancelled_turn_writes_three_steps_in_order_with_their_arguments(pinned, monkeypatch, citations, tool_calls):
    calls = _record_fakes(pinned, monkeypatch)
    asyncio.run(pinned._record_cancelled(CID, TURN, OWNER, "partial", citations))
    assert calls == [
        ("append", (CID, TURN, "assistant", "partial"), {"status": "cancelled", "tool_calls": tool_calls}),
        ("finish", (CID, "cancelled"), {}),
        ("mark", (OWNER, CID, "cancelled", "partial"), {}),
    ]


@pytest.mark.parametrize("failing", [0, 1, 2])
def test_a_failing_cancelled_step_does_not_stop_the_later_steps(pinned, monkeypatch, failing):
    calls = _record_fakes(pinned, monkeypatch, fail=failing)
    asyncio.run(pinned._record_cancelled(CID, TURN, OWNER, "partial", []))
    assert [name for name, *_ in calls] == ["append", "finish", "mark"]


def test_a_pump_cancelled_while_waiting_to_hand_over_ends_the_turn_instead_of_hanging(stream_fixture, pinned, monkeypatch):
    """Provider shape: a yield inside an idle watchdog (agent_chat_provider.stream_answer). A client stall long enough
    for the watchdog to fire cancels the pump while it waits to hand over an event. The consumer must end the turn with
    an error frame; it must not wait forever behind heartbeats."""
    monkeypatch.setattr(pinned, "HEARTBEAT_SECONDS", 0.05)

    async def no_mark(*_):
        pass

    monkeypatch.setattr(pinned, "mark_terminal_status", no_mark)

    async def workflow(**_kwargs):
        async with asyncio.timeout(0.05):
            for text in ("a", "b", "c", "d", "e"):
                yield {"event": "delta", "text": text}
            await asyncio.sleep(10)
            yield _done()

    monkeypatch.setattr(pinned, "stream_workflow", workflow)

    async def scenario():
        payload = StreamRequest(provider="deepseek", model="deepseek-chat", api_key="abcdefgh",
                                message="show AAPL prices", conversation_id=CID)
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await pinned.stream_chat(payload, request, "x" * 40)
        body = response.body_iterator
        seen = [await body.__anext__(), await body.__anext__()]  # the conversation frame, then the first delta
        await asyncio.sleep(0.2)  # the client stalls; the watchdog fires while the pump waits to hand over
        async for part in body:
            seen.append(part)
        return "".join(seen)

    wire = asyncio.run(asyncio.wait_for(scenario(), 3))
    frames = _frames(wire)
    assert frames[-1] == ("error", {"code": "workflow_incomplete", "status": "failed"})
    assert "event: done" not in wire


def test_disconnect_stops_the_turn_and_hands_the_cancelled_record_to_a_background_task(stream_fixture, pinned, monkeypatch):
    monkeypatch.setattr(pinned, "HEARTBEAT_SECONDS", 0.05)
    stopped, recorded = [], []

    async def workflow(**_kwargs):
        try:
            yield {"event": "delta", "text": "partial"}
            await asyncio.sleep(10)
        finally:
            stopped.append(True)

    async def record(*args):
        recorded.append(args)

    monkeypatch.setattr(pinned, "stream_workflow", workflow)
    monkeypatch.setattr(pinned, "_record_cancelled", record)

    async def scenario():
        payload = StreamRequest(provider="deepseek", model="deepseek-chat", api_key="abcdefgh",
                                message="show AAPL prices", conversation_id=CID)
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await pinned.stream_chat(payload, request, "x" * 40)

        async def consume():
            async for _ in response.body_iterator:
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        # Checked here, before asyncio.run tears down leftover tasks (which would also stop the workflow).
        assert stopped == [True], "the workflow must stop when the client disconnects"
        assert recorded == [(CID, TURN, OWNER, "partial", [])]
        assert not pinned._BACKGROUND

    asyncio.run(scenario())
