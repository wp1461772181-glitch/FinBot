"""HTTP client for ruler: send one question to the streaming chat endpoint and time the answer."""

import codecs
import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

READ_BYTES = 65536


@dataclass
class TurnOutcome:
    status: str  # the done event's status; or "incomplete", "error", "http_<code>", "unreachable"
    reason: str | None
    answer: str
    conversation_id: str | None
    turn_id: str | None
    first_event_ms: int | None  # the first event that is not "conversation"
    first_delta_ms: int | None  # the first delta whose text is not empty
    total_ms: int
    tools: list[str]  # the name of each tool_start, in order
    thinking_ms: int | None  # from the done event
    error: str | None


def owner_credential() -> str:
    # Imported here so that importing ruler.client never loads the application.
    from app.agent_chat_identity import _load_config

    config = _load_config()
    if config is None:
        raise RuntimeError("no owner credential configured")
    return config[3]


def ask(base: str, credential: str, text: str, *, catalog_model: str = "",
        conversation_id: str | None = None, timeout: float = 1300, clock=time.monotonic) -> TurnOutcome:
    """Send one question and time the streamed answer. Failures come back as a status, never as an exception."""
    body = {"message": text, "catalog_model": catalog_model, "via": "ruler"}      # its conversations are marked: not his words for the memory review
    if conversation_id:
        body["conversation_id"] = conversation_id
    start = clock()
    turn = _Turn(clock, start)
    # No environment proxy: the harness talks to one known backend, and a proxy must not divert the request.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(
            f"{base.rstrip('/')}/agent-chat/stream",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"X-Chat-Session": credential, "Content-Type": "application/json"},
            method="POST",
        )
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return turn.finish(f"http_{exc.code}", error=_http_detail(exc))
    except (OSError, http.client.HTTPException, ValueError):
        return turn.finish("unreachable")
    return _read_stream(response, turn)


def _http_detail(exc: urllib.error.HTTPError) -> str | None:
    """The server's {"detail": ...} message, when the error body carries one."""
    try:
        payload = json.loads(exc.read(READ_BYTES))
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        exc.close()
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail if isinstance(detail, str) else None


def _read_stream(response, turn: "_Turn") -> TurnOutcome:
    parser = _SseParser()
    with response:
        while True:
            try:
                chunk = response.read1(READ_BYTES)
            except (OSError, http.client.HTTPException) as exc:
                return turn.finish("incomplete", error=type(exc).__name__)
            if not chunk:
                return turn.finish("incomplete")
            try:
                events = parser.feed(chunk)
            except ValueError:
                return turn.finish("error", error="malformed_stream")
            for event, data in events:
                if turn.apply(event, data):
                    return turn.finish()


class _SseParser:
    """Split a Server-Sent Events byte stream into (event, data) pairs as each event completes."""

    def __init__(self):
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._open_line = ""
        self._event = None
        self._data = []

    def feed(self, chunk: bytes) -> list[tuple[str, str]]:
        # A character can arrive split across chunks; the incremental decoder keeps the unfinished bytes.
        self._open_line += self._decoder.decode(chunk)
        *lines, self._open_line = self._open_line.split("\n")
        events = []
        for line in lines:
            line = line.rstrip("\r")
            if not line:
                if self._data:
                    events.append((self._event or "message", "\n".join(self._data)))
                self._event, self._data = None, []
            elif line.startswith(":"):
                continue  # a comment, such as the heartbeat frame
            else:
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    self._event = value
                elif field == "data":
                    self._data.append(value)
        return events


class _Turn:
    """One turn's events and the moments they arrived, folded in as the stream comes."""

    def __init__(self, clock, start: float):
        self._clock = clock
        self._start = start
        self._answer_parts: list[str] = []
        self._tools: list[str] = []
        self.status: str | None = None
        self.reason: str | None = None
        self.error: str | None = None
        self.conversation_id: str | None = None
        self.turn_id: str | None = None
        self.first_event_ms: int | None = None
        self.first_delta_ms: int | None = None
        self.thinking_ms: int | None = None

    def _elapsed_ms(self) -> int:
        return int((self._clock() - self._start) * 1000)

    def apply(self, event: str, data: str) -> bool:
        """Fold one event in. Return True once the stream has said the turn is over."""
        try:
            payload = json.loads(data)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self.status, self.error = "error", "malformed_event"
            return True
        if event == "conversation":
            self.conversation_id = _str_or_none(payload.get("conversation_id"))
            self.turn_id = _str_or_none(payload.get("turn_id"))
            return False
        if self.first_event_ms is None:
            self.first_event_ms = self._elapsed_ms()
        if event == "tool_start":
            self._tools.append(str(payload.get("name", "")))
        elif event == "delta":
            text = payload.get("text")
            if isinstance(text, str) and text:
                if self.first_delta_ms is None:
                    self.first_delta_ms = self._elapsed_ms()
                self._answer_parts.append(text)
        elif event == "answer_reset":
            # The streamed text is being discarded: what counts is the answer written after the last reset.
            self._answer_parts.clear()
            self.first_delta_ms = None
        elif event == "done":
            status = payload.get("status")
            if isinstance(status, str):
                self.status = status
            else:
                self.status, self.error = "error", "malformed_event"
            self.reason = _str_or_none(payload.get("reason"))
            self.thinking_ms = _int_or_none(payload.get("thinking_ms"))
            return True
        elif event == "error":
            self.status = "error"
            self.error = _str_or_none(payload.get("code"))
            return True
        return False

    def finish(self, status: str = "incomplete", error: str | None = None) -> TurnOutcome:
        """Build the outcome. A status the stream itself reported (done or error) takes precedence."""
        if self.status is None:
            self.status, self.error = status, error
        return TurnOutcome(
            status=self.status,
            reason=self.reason,
            answer="".join(self._answer_parts),
            conversation_id=self.conversation_id,
            turn_id=self.turn_id,
            first_event_ms=self.first_event_ms,
            first_delta_ms=self.first_delta_ms,
            total_ms=self._elapsed_ms(),
            tools=list(self._tools),
            thinking_ms=self.thinking_ms,
            error=self.error,
        )


def _str_or_none(value) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
