"""FP13-a: a turn sent with detach=true keeps running after its response is dropped; POST .../cancel stops it.

Built on the stream fixture of test_agent_chat_stream.py.  The workflow is a fake: it yields what the test gives it,
then waits for an asyncio.Event the test controls, so each test decides when the turn ends.  Every test runs under
asyncio.wait_for(..., 5): a turn that hangs fails instead of blocking the run.
"""
import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.agent_chat_stream as stream
from app.agent_chat_stream import StreamRequest
from tests.test_agent_chat_stream import stream_fixture  # noqa: F401  (fixture)

CRED = "x" * 40
DETACH = ": detached\n\n"
FLAG = "FINBOT_FP13_DETACHED_TURNS"


@pytest.fixture
def cid():
    return str(uuid4())


def _done():
    return {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {},
            "citations": [], "route": "A", "trace": []}


def _events(wire):
    """Event names of the named blocks; comment blocks (the detached marker, heartbeats) are not events."""
    return [block.split("\n")[0][7:] for block in wire.split("\n\n") if block.startswith("event: ")]


def _delta_text(chunk):
    return json.loads(chunk.split("\n")[1][6:])["text"]


def _workflow(monkeypatch, before=(), gate=None):
    """Yield ``before``; if ``gate`` is given, wait for ``gate["event"]``; then yield done."""
    async def workflow(**_kwargs):
        for event in before:
            yield event
        if gate is not None:
            await gate["event"].wait()
        yield _done()
    monkeypatch.setattr(stream, "stream_workflow", workflow)


def _quiet(monkeypatch):
    async def no_mark(*_):
        pass
    monkeypatch.setattr(stream, "mark_terminal_status", no_mark)


def _set_flag(monkeypatch, value):
    monkeypatch.setenv(FLAG, value)


async def _start(cid, detach=True):
    payload = StreamRequest(provider="deepseek", model="deepseek-chat", api_key="abcdefgh",
                            message="show AAPL prices", conversation_id=cid, detach=detach)
    request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
    return await stream.stream_chat(payload, request, CRED)


async def _take(body, count):
    return [await body.__anext__() for _ in range(count)]


async def _drain(body):
    return "".join([part async for part in body])


def _stored_assistant(stored, status):
    return [kwargs for args, kwargs in stored if len(args) > 2 and args[2] == "assistant" and kwargs.get("status") == status]


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 5))


def test_flag_on_and_detach_marks_the_stream_and_keeps_the_event_order(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    _workflow(monkeypatch, [{"event": "status", "status": "working"}, {"event": "delta", "text": "AAPL"}])

    async def run(flag, detach):
        _set_flag(monkeypatch, flag)
        response = await _start(cid, detach=detach)
        return await _drain(response.body_iterator)

    async def scenario():
        return await run("on", True), await run("off", True)

    on, off = _run(scenario())
    assert on.startswith(DETACH)
    assert _events(on) == _events(off) == ["conversation", "status", "delta", "done"]
    assert cid not in stream.TURNS and cid not in stream.LOCKS


def test_dropping_the_body_leaves_the_turn_running_and_its_answer_is_stored(stream_fixture, cid, monkeypatch):
    stored = stream_fixture[4]
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid)).body_iterator
        await _take(body, 3)  # the marker, the conversation frame, the first delta: the turn is under way
        await body.aclose()  # the client is gone
        task = stream.TURNS[cid]["task"]
        assert not task.done() and cid in stream.LOCKS
        gate["event"].set()
        await task
        assert cid not in stream.TURNS and cid not in stream.LOCKS

    _run(scenario())
    assert _stored_assistant(stored, "complete")
    assert {"finished": "active"} in [kwargs for _, kwargs in stored]


def test_disconnect_at_the_asgi_layer_does_not_cancel_the_turn(stream_fixture, cid, monkeypatch):
    stored = stream_fixture[4]
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        response = await _start(cid)
        delta_sent = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body" and b"event: delta" in message.get("body", b""):
                delta_sent.set()

        async def receive():
            # The client drops once the turn has streamed a delta.
            await delta_sent.wait()
            return {"type": "http.disconnect"}

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "POST", "path": "/agent-chat/stream", "scheme": "http", "headers": [], "query_string": b""}
        await response(scope, receive, send)  # returns once the disconnect has been handled
        task = stream.TURNS[cid]["task"]
        assert not task.done() and cid in stream.LOCKS
        gate["event"].set()
        await task
        assert cid not in stream.TURNS and cid not in stream.LOCKS

    _run(scenario())
    assert _stored_assistant(stored, "complete")


def test_explicit_cancel_stops_the_turn_through_the_normal_cancel_path(stream_fixture, cid, monkeypatch):
    recorded = []

    async def record(*args):
        recorded.append(args)

    monkeypatch.setattr(stream, "_record_cancelled", record)
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid)).body_iterator
        await _take(body, 3)
        turn = stream.TURNS[cid]["turn_id"]
        result = await stream.cancel_turn_endpoint(cid, stream.CancelBody(), CRED)
        assert result == {"cancelled": True, "turn_id": turn}
        await _drain(body)  # the response ends on its own: it does not hang
        assert cid not in stream.TURNS and cid not in stream.LOCKS
        return turn

    turn = _run(scenario())
    assert len(recorded) == 1 and recorded[0][:2] == (cid, turn)


def test_cancel_while_frames_stream_back_to_back_records_once_with_the_streamed_text(stream_fixture, cid, monkeypatch):
    recorded = []

    async def record(*args):
        recorded.append(args)

    monkeypatch.setattr(stream, "_record_cancelled", record)
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    deltas = [f"{i:03d}|" for i in range(400)]
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": text} for text in deltas], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        body = (await _start(cid)).body_iterator
        chunks = await _take(body, 30)  # the marker, the conversation frame, then 28 deltas
        seen = "".join(_delta_text(chunk) for chunk in chunks if chunk.startswith("event: delta"))
        result = await stream.cancel_turn_endpoint(cid, stream.CancelBody(), CRED)
        await _drain(body)
        return seen, result

    seen, result = _run(scenario())
    assert result["cancelled"] is True
    assert len(recorded) == 1
    text = recorded[0][3]  # (cid, turn, owner, text_out, citations)
    full = "".join(deltas)
    assert seen and text.startswith(seen) and full.startswith(text)


def test_cancel_answers_no_running_turn_turn_mismatch_and_404_for_a_stranger(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)
    original_verify = stream.verify_conversation

    async def deny(*_args):
        return False

    async def scenario():
        none = await stream.cancel_turn_endpoint(cid, stream.CancelBody(), CRED)
        assert none == {"cancelled": False, "reason": "no_running_turn"}

        gate["event"] = asyncio.Event()
        body = (await _start(cid)).body_iterator
        await _take(body, 3)
        turn = stream.TURNS[cid]["turn_id"]
        task = stream.TURNS[cid]["task"]

        mismatch = await stream.cancel_turn_endpoint(cid, stream.CancelBody(turn_id=str(uuid4())), CRED)
        assert mismatch == {"cancelled": False, "reason": "turn_mismatch"}
        assert not task.done()

        stream.verify_conversation = deny
        try:
            with pytest.raises(HTTPException) as stranger:
                await stream.cancel_turn_endpoint(cid, stream.CancelBody(turn_id=turn), "y" * 40)
        finally:
            stream.verify_conversation = original_verify
        assert stranger.value.status_code == 404
        assert not task.done()

        gate["event"].set()
        wire = await _drain(body)
        assert "event: done" in wire
        after = await stream.cancel_turn_endpoint(cid, stream.CancelBody(), CRED)
        assert after == {"cancelled": False, "reason": "no_running_turn"}

    _run(scenario())


def test_flag_off_keeps_the_plain_response_even_for_a_detach_request(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "off")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        response = await _start(cid, detach=True)
        assert isinstance(response, stream._ResourceStreamingResponse)
        body = response.body_iterator
        await _take(body, 2)  # the conversation frame, the first delta: the turn runs inside the response
        assert cid not in stream.TURNS
        gate["event"].set()
        wire = await _drain(body)
        assert DETACH not in wire and "event: done" in wire
        assert cid not in stream.TURNS and cid not in stream.LOCKS

    _run(scenario())


def test_flag_on_but_a_legacy_request_without_detach_keeps_the_plain_response(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")
    gate = {}
    _workflow(monkeypatch, [{"event": "delta", "text": "partial"}], gate)

    async def scenario():
        gate["event"] = asyncio.Event()
        response = await _start(cid, detach=False)
        assert isinstance(response, stream._ResourceStreamingResponse)
        body = response.body_iterator
        await _take(body, 2)
        assert cid not in stream.TURNS
        gate["event"].set()
        wire = await _drain(body)
        assert DETACH not in wire and "event: done" in wire
        assert cid not in stream.TURNS and cid not in stream.LOCKS

    _run(scenario())


def test_a_failed_detached_turn_sends_the_error_frame_through_the_relay(stream_fixture, cid, monkeypatch):
    _quiet(monkeypatch)
    _set_flag(monkeypatch, "on")

    async def workflow(**_kwargs):
        raise HTTPException(502, "x_code")
        yield  # makes this an async generator

    monkeypatch.setattr(stream, "stream_workflow", workflow)

    async def scenario():
        response = await _start(cid)
        wire = await _drain(response.body_iterator)
        assert cid not in stream.TURNS and cid not in stream.LOCKS
        return wire

    wire = _run(scenario())
    errors = [json.loads(block.split("\n")[1][6:]) for block in wire.split("\n\n")
              if block.startswith("event: error")]
    assert errors == [{"code": "x_code", "status": "failed"}]


def test_a_request_without_detach_still_validates_and_defaults_to_false():
    legacy = StreamRequest.model_validate({"provider": "deepseek", "model": "deepseek-chat",
                                           "api_key": "abcdefgh", "message": "news"})
    assert legacy.detach is False
    assert StreamRequest(provider="deepseek", model="deepseek-chat", api_key="abcdefgh",
                         message="news", detach=True).detach is True
