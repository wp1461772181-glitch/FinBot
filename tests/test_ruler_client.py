import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ruler.client import ask, owner_credential


def sse(event: str, payload: dict) -> bytes:
    """One Server-Sent Events frame, as the chat endpoint writes it."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@dataclass
class Recorded:
    headers: object  # email.message.Message: header lookup is case-insensitive
    body: dict


@dataclass
class FakeStream:
    """A local chat endpoint that plays the scripted bytes for each request and records the request."""

    base: str = ""
    status: int = 200
    script: list = field(default_factory=list)  # (delay seconds, raw bytes), written in order
    requests: list = field(default_factory=list)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        fake = self.server.fake
        length = int(self.headers.get("Content-Length", "0"))
        fake.requests.append(Recorded(self.headers, json.loads(self.rfile.read(length))))
        if fake.status != 200:
            body = b"".join(chunk for _, chunk in fake.script)
            self.send_response(fake.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        for delay, chunk in fake.script:
            if delay:
                time.sleep(delay)
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, format, *args):  # keep pytest output quiet
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.fake = FakeStream(base=f"http://127.0.0.1:{httpd.server_address[1]}")
    # shutdown() waits for one poll interval, so a short one keeps each test's teardown fast.
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield httpd.fake
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_happy_path_collects_answer_ids_tools_and_times(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c-1", "turn_id": "t-1"})),
        (0, sse("tool_start", {"name": "query_financials"})),
        (0, sse("tool_start", {"name": "calculate"})),
        (0.05, sse("delta", {"text": "营收 "})),
        (0, sse("delta", {"text": "1158"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 1200})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.status == "complete"
    assert outcome.answer == "营收 1158"
    assert outcome.conversation_id == "c-1"
    assert outcome.turn_id == "t-1"
    assert outcome.tools == ["query_financials", "calculate"]
    assert outcome.thinking_ms == 1200
    assert 0 <= outcome.first_event_ms <= outcome.first_delta_ms <= outcome.total_ms
    assert outcome.first_delta_ms >= 40


def test_answer_reset_drops_earlier_text_and_restarts_first_delta(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("delta", {"text": "我查一下"})),
        (0, sse("answer_reset", {})),
        (0.15, sse("delta", {"text": "营收 1158"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.answer == "营收 1158"
    assert outcome.first_delta_ms >= 150
    assert outcome.first_event_ms < 150


def test_stream_without_reset_is_unchanged(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("delta", {"text": "营收 "})),
        (0, sse("delta", {"text": "1158"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.answer == "营收 1158" and outcome.first_delta_ms is not None


def test_request_carries_message_model_conversation_and_credential(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    ask(server.base, "cred-xyz", "问题", catalog_model="haiku-5.5", conversation_id="c1")
    ask(server.base, "cred-xyz", "问题", catalog_model="haiku-5.5")
    with_conversation, without_conversation = server.requests
    assert with_conversation.body == {"message": "问题", "catalog_model": "haiku-5.5", "conversation_id": "c1", "via": "ruler"}
    assert with_conversation.headers["X-Chat-Session"] == "cred-xyz"
    assert without_conversation.body == {"message": "问题", "catalog_model": "haiku-5.5", "via": "ruler"}
    assert without_conversation.headers["X-Chat-Session"] == "cred-xyz"


def test_stream_cut_without_done_is_incomplete(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("delta", {"text": "半句"})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.status == "incomplete"
    assert outcome.answer == "半句"
    assert outcome.error is None


def test_error_event_sets_status_error(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("error", {"code": "provider_unavailable", "message": "x"})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.status == "error"
    assert outcome.error == "provider_unavailable"


def test_http_409_is_reported_with_detail(server):
    server.status = 409
    server.script = [(0, b'{"detail":"conversation_busy"}')]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.status == "http_409"
    assert outcome.error == "conversation_busy"
    assert outcome.total_ms >= 0


def test_unreachable_server():
    outcome = ask("http://127.0.0.1:1", "cred", "问题")
    assert outcome.status == "unreachable"
    assert outcome.answer == ""


def test_environment_proxy_does_not_divert_the_request(server, monkeypatch):
    # 127.0.0.1:9 is a closed port: a request sent through it could not complete.
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.status == "complete"


def test_empty_delta_does_not_count_as_first_delta(server):
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("delta", {"text": ""})),
        (0.05, sse("delta", {"text": "字"})),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.first_delta_ms >= 40
    assert outcome.answer == "字"


def test_multi_line_data_and_utf8_split_across_chunks(server):
    # One delta: its JSON is split over two data: lines, and the three bytes of 好 arrive in two writes.
    line_one = b'event: delta\ndata: {"text":\n'
    line_two = 'data: "好世界"}\n\n'.encode("utf-8")
    cut = line_two.index("好".encode("utf-8")) + 2
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, line_one + line_two[:cut]),
        (0.02, line_two[cut:]),
        (0, sse("done", {"status": "complete", "reason": None, "thinking_ms": 0})),
    ]
    outcome = ask(server.base, "cred", "问题")
    assert outcome.answer == "好世界"
    assert "�" not in outcome.answer


def test_credential_never_appears_in_outcome(server):
    credential = "cred-must-not-leak-42"
    server.status = 409
    server.script = [(0, b'{"detail":"conversation_busy"}')]
    busy = ask(server.base, credential, "问题")
    assert credential not in repr(busy)

    server.status = 200
    server.script = [
        (0, sse("conversation", {"conversation_id": "c1", "turn_id": "t1"})),
        (0, sse("error", {"code": "provider_unavailable", "message": "x"})),
    ]
    failed = ask(server.base, credential, "问题")
    assert credential not in repr(failed)


def test_owner_credential_returns_the_configured_credential(monkeypatch):
    monkeypatch.setattr("app.agent_chat_identity._load_config", lambda: (b"salt", b"hash", 100_000, "owner-cred"))
    assert owner_credential() == "owner-cred"


def test_owner_credential_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr("app.agent_chat_identity._load_config", lambda: None)
    with pytest.raises(RuntimeError, match="no owner credential configured"):
        owner_credential()
