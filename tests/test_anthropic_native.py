"""Provider ``anthropic`` over the native Messages API (app/anthropic_native.py).

Nothing here reaches the network: the official SDK is real, its HTTP client is an httpx2 MockTransport, so the request bytes
the SDK would send and the stream parsing it does are both exercised.  No test uses a real key.
"""
import asyncio
import json
import logging

import anthropic
import httpx
import httpx2
import pytest
from fastapi import HTTPException

import app.agent_chat_provider as provider
import app.anthropic_native as native

KEY = "sk-ant-api03-TESTKEY-0123456789abcdefghijklmnopqrstuvwxyz"
MODEL = "claude-haiku-5-5"
SIG = "EqQBCgIYAhIM-signature-bytes-must-survive-unchanged=="


# ---- a fake Anthropic server -------------------------------------------------------------------------------------------

def sse(*events):
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def stream_of(blocks, *, stop="end_turn", usage=None, details=None, finish=True, model=MODEL):
    """blocks: ('text', s) | ('thinking', s, signature) | ('tool', id, name, args_json) -> the SSE body of one response."""
    u = {"input_tokens": 10, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, **(usage or {})}
    events = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
                                                     "content": [], "stop_reason": None, "stop_sequence": None, "usage": u}}]
    for i, block in enumerate(blocks):
        if block[0] == "text":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}]
            events += [{"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": piece}} for piece in block[1]] \
                if isinstance(block[1], list) else [{"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block[1]}}]
        elif block[0] == "thinking":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": block[1]}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": block[2]}}]
        else:
            args = block[3]
            half = len(args) // 2
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": block[1], "name": block[2], "input": {}}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": args[:half]}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": args[half:]}}]
        events.append({"type": "content_block_stop", "index": i})
    if finish:
        delta = {"stop_reason": stop, "stop_sequence": None}
        if details:
            delta["stop_details"] = details
        events += [{"type": "message_delta", "delta": delta, "usage": {"output_tokens": 42}}, {"type": "message_stop"}]
    return sse(*events)


CAPS_5 = {"id": MODEL, "type": "model", "display_name": "Haiku", "created_at": "2026-09-01T00:00:00Z", "max_input_tokens": 1000000,
          "max_tokens": 128000, "capabilities": {"effort": {"supported": True, "low": {"supported": True}, "medium": {"supported": True},
                                                          "high": {"supported": True}, "xhigh": {"supported": True}, "max": {"supported": True}},
                                                 "thinking": {"supported": True, "types": {"adaptive": {"supported": True}}}}}


class Server:
    """Records every request; answers POST /v1/messages from ``replies`` and GET /v1/models/{id} with ``models``."""
    def __init__(self, replies, models=None):
        self.replies, self.models, self.requests = list(replies), models, []

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path.startswith("/v1/models/"):
            if self.models is None:
                return httpx2.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "x"}})
            return httpx2.Response(200, json=self.models)
        reply = self.replies.pop(0)
        if isinstance(reply, httpx2.Response):
            return reply
        if isinstance(reply, Exception):
            raise reply
        return httpx2.Response(200, headers={"content-type": "text/event-stream", "request-id": "req_test_1"}, content=reply)

    @property
    def posts(self):
        return [r for r in self.requests if r.method == "POST"]

    def body(self, n=-1):
        return json.loads(self.posts[n].content)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    native._CAPS.clear()
    for name in ("FINBOT_ANTHROPIC_NATIVE", "FINBOT_ANTHROPIC_THINKING_BINDING", "FINBOT_ANTHROPIC_WORKSPACE_ID", "MODEL_EGRESS_PROXY",
                 "FINBOT_SW1D_TOOLCALL_CAP", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    yield
    native._CAPS.clear()


def serve(monkeypatch, *replies, models=CAPS_5):
    server = Server(replies, models)
    monkeypatch.setattr(native, "_http_client", lambda: anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(server)))
    return server


def decide(messages=None, schemas=None, effort=None, model=MODEL):
    return asyncio.run(provider.decision_request("anthropic", model, KEY, messages or [{"role": "user", "content": "hi"}], schemas or [], None, effort))


def answer(messages=None, collector=None, model=MODEL):
    async def run():
        return [piece async for piece in provider.stream_answer("anthropic", model, KEY, messages or [{"role": "user", "content": "hi"}], collector)]
    return asyncio.run(run())


TOOL = {"type": "function", "function": {"name": "query_financials", "description": "read figures",
                                         "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}


# ---- request conversion --------------------------------------------------------------------------------------------------

def test_leading_system_messages_become_top_level_system_and_later_ones_stay_in_place():
    system, messages = native.convert_messages([
        {"role": "system", "content": "rules"}, {"role": "system", "content": "profile"},
        {"role": "user", "content": "question"}, {"role": "system", "content": "hint"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "{\"ok\":1}"}, {"role": "system", "content": "status"}])
    assert system == [{"type": "text", "text": "rules"}, {"type": "text", "text": "profile"}]
    assert messages[0] == {"role": "user", "content": [{"type": "text", "text": "question"}, {"type": "text", "text": "hint"}]}
    assert messages[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"ok\":1}"}, {"type": "text", "text": "status"}]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]


def test_parallel_tool_results_share_one_user_message_and_arguments_become_objects():
    calls = [{"id": f"t{i}", "type": "function", "function": {"name": "f", "arguments": json.dumps({"n": i})}} for i in range(3)]
    _, messages = native.convert_messages([{"role": "user", "content": "q"}, {"role": "assistant", "content": "looking", "tool_calls": calls},
                                          *[{"role": "tool", "tool_call_id": f"t{i}", "content": str(i)} for i in range(3)]])
    assert messages[1]["content"] == [{"type": "text", "text": "looking"}] + [{"type": "tool_use", "id": f"t{i}", "name": "f", "input": {"n": i}} for i in range(3)]
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["t0", "t1", "t2"] and len(messages) == 3


def test_an_unanswered_call_gets_an_error_result_and_an_unasked_result_is_dropped():
    call = lambda i: {"id": i, "type": "function", "function": {"name": "f", "arguments": "{}"}}
    _, messages = native.convert_messages([{"role": "user", "content": "q"}, {"role": "assistant", "content": "", "tool_calls": [call("a"), call("b")]},
                                          {"role": "tool", "tool_call_id": "a", "content": "ok"}, {"role": "tool", "tool_call_id": "zzz", "content": "orphan"}])
    results = messages[2]["content"]
    assert [b["tool_use_id"] for b in results] == ["a", "b"] and results[1]["is_error"] is True and "zzz" not in json.dumps(messages)


def test_tool_definitions_use_input_schema_and_keep_order():
    other = {"type": "function", "function": {"name": "calculate", "parameters": {}}}
    tools = native.convert_tools([TOOL, other])
    assert tools[0] == {"name": "query_financials", "description": "read figures", "input_schema": TOOL["function"]["parameters"]}
    assert tools[1] == {"name": "calculate", "input_schema": {"type": "object", "properties": {}}}


def test_request_shape_adaptive_thinking_cache_and_no_sampling_parameters():
    params, betas = native.build_request(MODEL, [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}], [TOOL], effort="high")
    assert params["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert params["output_config"] == {"effort": "high"}
    assert params["tool_choice"] == {"type": "auto"} and params["max_tokens"] == provider.MAX_OUTPUT_TOKENS and betas == []
    assert not {"temperature", "top_p", "top_k", "stream"} & set(params)


@pytest.mark.parametrize("effort,sent", [(None, False), ("none", False), ("minimal", False), ("low", True), ("medium", True), ("xhigh", True), ("max", True)])
def test_only_a_tier_the_bot_chose_and_the_model_has_is_sent(effort, sent):
    params, _ = native.build_request(MODEL, [{"role": "user", "content": "q"}], [], effort=effort)
    assert ("output_config" in params) is sent and (not sent or params["output_config"] == {"effort": effort})


def test_capabilities_gate_thinking_and_tiers():
    caps = {"adaptive": True, "efforts": ("low", "medium", "high", "max")}
    assert "output_config" not in native.build_request(MODEL, [{"role": "user", "content": "q"}], [], effort="xhigh", caps=caps)[0]
    old = {"adaptive": False, "efforts": ()}
    params, _ = native.build_request("claude-haiku-4-5", [{"role": "user", "content": "q"}], [], effort="high", caps=old)
    assert "thinking" not in params and "output_config" not in params


# ---- response conversion over the real SDK ---------------------------------------------------------------------------

def test_a_plain_answer_has_the_openai_shape_and_usage_counts_the_cache(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "hello"), ], usage={"input_tokens": 100, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 50}))
    data, message = decide()
    assert message["role"] == "assistant" and message["content"] == "hello" and "tool_calls" not in message
    assert data["choices"][0]["finish_reason"] == "stop" and data["choices"][0]["message"] is message
    assert data["usage"] == {"prompt_tokens": 550, "completion_tokens": 42, "total_tokens": 592, "prompt_tokens_details": {"cached_tokens": 400},
                             "cache_read_input_tokens": 400, "cache_creation_input_tokens": 50}
    request = server.posts[0]
    assert request.url == "https://api.anthropic.com/v1/messages" and request.headers["authorization"] == f"Bearer {KEY}"
    assert "x-api-key" not in request.headers   # the SDK's own choice: Authorization: Bearer is the documented primary header


def test_tool_calls_come_back_in_order_with_anthropic_ids_and_thinking_summary(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop_block")
    serve(monkeypatch, stream_of([("thinking", "plan it", SIG), ("text", "checking"), ("tool", "toolu_a", "query_financials", '{"symbol": "AAPL"}'),
                                  ("tool", "toolu_b", "calculate", '{"expression": "1+1"}')], stop="tool_use"))
    data, message = decide(schemas=[TOOL])
    assert data["choices"][0]["finish_reason"] == "tool_calls"
    assert [(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"])) for c in message["tool_calls"]] == [
        ("toolu_a", "query_financials", {"symbol": "AAPL"}), ("toolu_b", "calculate", {"expression": "1+1"})]
    assert message["content"] == "checking" and message["reasoning_content"] == "plan it"
    assert message["_anthropic_content"][0] == {"type": "thinking", "thinking": "plan it", "signature": SIG}


def test_a_refusal_is_a_named_error_with_its_category(monkeypatch):
    serve(monkeypatch, stream_of([], stop="refusal", details={"type": "refusal", "category": "cyber", "explanation": "no"}))
    with pytest.raises(native.ProviderRefusal) as error:
        decide()
    assert error.value.detail == "provider_refusal" and error.value.category == "cyber" and error.value.stage == "classification"
    serve(monkeypatch, stream_of([("text", "partial")], stop="refusal", details={"type": "refusal", "category": None}))
    with pytest.raises(native.ProviderRefusal) as error:
        answer()
    assert error.value.category is None and error.value.stage == "final_answer"


def test_out_of_tokens_keeps_text_but_a_cut_tool_call_or_empty_answer_fails(monkeypatch):
    serve(monkeypatch, stream_of([("text", "most of it")], stop="max_tokens"))
    data, message = decide()
    assert data["choices"][0]["finish_reason"] == "length" and message["content"] == "most of it"
    serve(monkeypatch, stream_of([("text", "x"), ("tool", "toolu_a", "f", '{"a": 1}')], stop="max_tokens"))
    with pytest.raises(HTTPException) as error:
        decide(schemas=[TOOL])
    assert error.value.detail == "provider_incomplete_response"
    serve(monkeypatch, stream_of([("thinking", "only thought", SIG)], stop="max_tokens"))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.detail == "provider_incomplete_response"


@pytest.mark.parametrize("stop", ["pause_turn", "something_new"])
def test_an_unexpected_stop_reason_is_incomplete(monkeypatch, stop):
    serve(monkeypatch, stream_of([("text", "x")], stop=stop))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.detail == "provider_incomplete_response"


def test_a_stream_that_never_finishes_is_incomplete(monkeypatch):
    serve(monkeypatch, stream_of([("text", "x")], finish=False))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.status_code == 502 and error.value.detail in {"provider_incomplete_stream", "provider_error"}


def test_tool_use_stop_without_a_call_or_a_call_with_end_turn_is_incomplete(monkeypatch):
    serve(monkeypatch, stream_of([("text", "x")], stop="tool_use"))
    with pytest.raises(HTTPException) as error:
        decide(schemas=[TOOL])
    assert error.value.detail == "provider_incomplete_stream"
    serve(monkeypatch, stream_of([("tool", "toolu_a", "f", '{"a": 1}')], stop="end_turn"))
    with pytest.raises(HTTPException) as error:
        decide(schemas=[TOOL])
    assert error.value.detail == "provider_incomplete_stream"


@pytest.mark.parametrize("flag_value,count,ok", [("on", 128, True), ("on", 129, False), ("off", 12, True), ("off", 13, False)])
def test_the_per_step_call_bound_follows_the_sw1d_switch(monkeypatch, flag_value, count, ok):
    monkeypatch.setenv("FINBOT_SW1D_TOOLCALL_CAP", flag_value)
    serve(monkeypatch, stream_of([("tool", f"toolu_{i}", "f", '{"n": %d}' % i) for i in range(count)], stop="tool_use"))
    if ok:
        _, message = decide(schemas=[TOOL])
        assert [c["id"] for c in message["tool_calls"]] == [f"toolu_{i}" for i in range(count)]
        return
    with pytest.raises(HTTPException) as error:
        decide(schemas=[TOOL])
    assert error.value.detail == ("tool_call_batch_too_large" if flag_value == "on" else "provider_incompatible_response")
    assert error.value.check == "tool_index"


@pytest.mark.parametrize("status,code", [(400, "provider_model_unavailable_or_invalid_request"), (401, "provider_invalid_key"), (403, "provider_model_access_denied"),
                                         (404, "provider_model_unavailable_or_invalid_request"), (429, "provider_rate_or_quota_error"), (500, "provider_error"),
                                         (529, "provider_error")])
def test_http_errors_map_to_the_existing_codes_with_no_sdk_retry(monkeypatch, status, code):
    server = serve(monkeypatch, httpx2.Response(status, headers={"request-id": "req_x"}, json={"type": "error", "error": {"type": "e", "message": "secret prompt text"}}))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.detail == code and len(server.posts) == 1
    assert "secret prompt text" not in repr(error.value) and getattr(error.value, "request_id", None) == "req_x"
    assert error.value.retryable is (status in {429, 500, 502, 503, 504})


def test_a_key_without_a_workspace_gets_its_own_code(monkeypatch):
    serve(monkeypatch, httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
          "message": "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header"}}))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.detail == "provider_workspace_required"


def test_timeouts_and_network_failures_keep_their_codes(monkeypatch):
    serve(monkeypatch, httpx2.ReadTimeout("slow"))
    with pytest.raises(HTTPException) as error:
        decide()
    assert (error.value.status_code, error.value.detail) == (504, "provider_timeout")
    serve(monkeypatch, httpx2.ConnectError("down"))
    with pytest.raises(HTTPException) as error:
        decide()
    assert (error.value.status_code, error.value.detail) == (502, "provider_network_error")


class _Breaks(httpx2.AsyncByteStream):
    """A 200 stream that delivers its first chunk and then fails, as a connection does."""
    def __init__(self, first, error):
        self.first, self.error = first, error

    async def __aiter__(self):
        yield self.first
        raise self.error


@pytest.mark.parametrize("error,status,code", [(httpx2.ReadTimeout("slow"), 504, "provider_timeout"), (httpx2.ReadError("reset"), 502, "provider_network_error"),
                                               (httpx2.RemoteProtocolError("cut"), 502, "provider_network_error")])
def test_a_failure_while_the_body_is_being_read_keeps_its_code(monkeypatch, error, status, code):
    first = stream_of([("text", "par")], finish=False)[:200]
    serve(monkeypatch, httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=_Breaks(first, error)))
    with pytest.raises(HTTPException) as error_info:
        decide()
    assert (error_info.value.status_code, error_info.value.detail) == (status, code)
    serve(monkeypatch, httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=_Breaks(first, error)))
    with pytest.raises(HTTPException) as error_info:
        answer()
    assert error_info.value.detail == code


def test_an_error_event_inside_the_stream_is_a_provider_error(monkeypatch):
    start = stream_of([("text", "x")], finish=False)
    serve(monkeypatch, start + sse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.status_code == 502 and error.value.detail in {"provider_error", "provider_incomplete_stream"}
    assert "Overloaded" not in repr(error.value)


def test_a_stream_the_sdk_cannot_assemble_is_an_incompatible_response_not_a_crash(monkeypatch):
    broken = sse({"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "model": MODEL, "content": [],
                                                       "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}},
                 {"type": "content_block_delta", "index": 3, "delta": {"type": "text_delta", "text": "orphan"}})
    serve(monkeypatch, broken)
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.status_code == 502 and error.value.detail == "provider_incompatible_response" and error.value.check == "sdk_event_shape"


def test_a_bug_that_is_not_a_provider_failure_still_propagates(monkeypatch):
    serve(monkeypatch, stream_of([("text", "x")]))
    monkeypatch.setattr(native, "usage_to_openai", lambda usage: (_ for _ in ()).throw(ZeroDivisionError("bug")))
    with pytest.raises(ZeroDivisionError):
        decide()


def test_every_stream_event_renews_the_progress_clock(monkeypatch):
    marks = []
    monkeypatch.setattr(native, "mark_progress", lambda: marks.append(1))
    serve(monkeypatch, stream_of([("text", ["a", "b", "c"])]))
    decide()
    assert len(marks) >= 9   # message_start, block start, 3 deltas, block stop, message_delta, message_stop (+ the final mark)


# ---- stream_answer -------------------------------------------------------------------------------------------------------

def test_stream_answer_yields_text_and_fills_the_collector(monkeypatch):
    serve(monkeypatch, stream_of([("thinking", "weigh it", SIG), ("text", ["The ", "answer."])], usage={"cache_read_input_tokens": 7}))
    collector = {}
    assert answer(collector=collector) == ["The ", "answer."]
    assert collector["reasoning_content"] == ["weigh it"] and collector["_usage"]["cache_read_input_tokens"] == 7
    listed = []
    serve(monkeypatch, stream_of([("thinking", "t", SIG), ("text", "ok")]))
    assert answer(collector=listed) == ["ok"] and listed == ["t"]


def test_stream_answer_rejects_a_tool_call_and_an_unfinished_stream(monkeypatch):
    serve(monkeypatch, stream_of([("tool", "toolu_a", "f", '{"a": 1}')], stop="tool_use"))
    with pytest.raises(HTTPException) as error:
        answer()
    assert error.value.detail == "provider_incomplete_stream"
    serve(monkeypatch, stream_of([("text", "x")], finish=False))
    with pytest.raises(HTTPException):
        answer()


# ---- thinking blocks go back unchanged -------------------------------------------------------------------------------------

def _first_step(monkeypatch):
    server = serve(monkeypatch, stream_of([("thinking", "plan it", SIG), ("text", "looking"), ("tool", "toolu_a", "query_financials", '{"symbol": "AAPL"}')], stop="tool_use"),
                   stream_of([("text", "done")]))
    _, first = decide([{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}], schemas=[TOOL], effort="high")
    return server, first


def test_the_second_request_carries_the_first_steps_thinking_block_unchanged(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop_block")
    server, first = _first_step(monkeypatch)
    assistant = {"role": "assistant", **{k: v for k, v in first.items() if k in {"content", "tool_calls", "reasoning_content", "_anthropic_content"}}}
    decide([{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}, assistant,
            {"role": "tool", "tool_call_id": "toolu_a", "content": "{\"ok\": true}"}], schemas=[TOOL], effort="high")
    second = server.body(1)
    sent = second["messages"][1]
    assert sent["role"] == "assistant"
    assert sent["content"][0] == {"type": "thinking", "thinking": "plan it", "signature": SIG}
    assert sent["content"][1:] == [{"type": "text", "text": "looking"}, {"type": "tool_use", "id": "toolu_a", "name": "query_financials", "input": {"symbol": "AAPL"}}]
    assert second["messages"][2]["content"][0]["tool_use_id"] == "toolu_a"
    # FinBot rebuilds its prompt every step, so a stale block is dropped by the API instead of failing the request.
    assert second["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert "thinking-binding-controls-2026-08-01" in server.posts[1].headers["anthropic-beta"]
    # The first request had no thinking to send back: no beta, no binding.
    assert "anthropic-beta" not in server.posts[0].headers and "block_binding" not in server.body(0)["thinking"]


def test_the_binding_control_can_be_turned_off_while_thinking_is_still_sent(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "off")
    server, first = _first_step(monkeypatch)
    assistant = {"role": "assistant", **{k: v for k, v in first.items() if k in {"content", "tool_calls", "_anthropic_content"}}}
    decide([{"role": "user", "content": "q"}, assistant, {"role": "tool", "tool_call_id": "toolu_a", "content": "{}"}], schemas=[TOOL])
    assert "anthropic-beta" not in server.posts[1].headers and "block_binding" not in server.body(1)["thinking"]
    assert server.body(1)["messages"][1]["content"][0]["type"] == "thinking"


def test_raw_blocks_that_no_longer_match_the_calls_are_rebuilt_without_thinking(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop_block")
    stale = {"role": "assistant", "content": "x", "tool_calls": [{"id": "new", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
             "_anthropic_content": [{"type": "thinking", "thinking": "t", "signature": SIG}, {"type": "tool_use", "id": "old", "name": "f", "input": {}}]}
    _, messages = native.convert_messages([{"role": "user", "content": "q"}, stale, {"role": "tool", "tool_call_id": "new", "content": "r"}], keep_thinking=True)
    assert [b["type"] for b in messages[1]["content"]] == ["text", "tool_use"] and messages[1]["content"][1]["id"] == "new"


def test_the_tool_loop_keeps_the_raw_blocks_between_steps(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop_block")
    """FinBot's own loop (direct.py) copies the model's reply into its protocol through a field list; the raw blocks must survive it."""
    from test_sw1b_closing_complete import call, text
    from test_sw1d_toolcall_cap import fixture_executor, run_with_decider
    from sw1_filings import CUTOFF, aapl_filings, new_symbol  # noqa: F401
    from test_sw1b_closing_complete import rows_of
    symbol = new_symbol()
    rows = {symbol: rows_of(symbol, aapl_filings())}
    scope = {"category": "A", "mode": "financials", "symbol": symbol, "symbols": [symbol], "days_back": None}
    step = call("query_financials", symbol=symbol, latest=True, limit=4)
    use = step["tool_calls"][0]
    step["reasoning_content"] = "plan it"
    step["_anthropic_content"] = [{"type": "thinking", "thinking": "plan it", "signature": SIG},
                                  {"type": "tool_use", "id": use["id"], "name": "query_financials", "input": json.loads(use["function"]["arguments"])}]
    seen = []
    result = run_with_decider(f"{symbol} 营收", scope, [step, text("ok [1]")], seen, executor=fixture_executor(rows))
    assert result["status"] == "succeeded" and len(seen) >= 2
    second_step = seen[1]
    assistant = [m for m in second_step if m.get("role") == "assistant" and m.get("tool_calls")]
    assert len(assistant) == 1 and assistant[0]["_anthropic_content"] == step["_anthropic_content"]
    _, converted = native.convert_messages(second_step, keep_thinking=True)
    sent = [m for m in converted if m["role"] == "assistant"][0]
    assert sent["content"][0] == {"type": "thinking", "thinking": "plan it", "signature": SIG}


# ---- keys, addresses, switches ---------------------------------------------------------------------------------------------

def test_the_key_appears_only_in_the_auth_header(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("anthropic").setLevel(logging.DEBUG)
    server = serve(monkeypatch, stream_of([("text", "ok")]), httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
    decide()
    with pytest.raises(HTTPException) as error:
        decide()
    request = server.posts[0]
    assert KEY not in str(request.url) and KEY not in request.content.decode()
    assert [name for name, value in request.headers.items() if KEY in value] == ["authorization"]
    exc = error.value
    assert KEY not in repr(exc) and KEY not in str(exc.detail) and KEY not in repr(vars(exc))
    assert KEY not in caplog.text
    client = native.make_client(KEY)
    assert KEY not in repr(client) and KEY not in str(client)


def test_environment_credentials_and_base_url_are_never_consulted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-ENVKEY-should-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "env-token")
    server = serve(monkeypatch, stream_of([("text", "ok")]))
    decide()
    request = server.posts[0]
    assert request.url.host == "api.anthropic.com" and request.headers["authorization"] == f"Bearer {KEY}" and "x-api-key" not in request.headers


def test_the_egress_proxy_goes_to_the_sdk_http_client(monkeypatch):
    seen = []
    monkeypatch.setattr(anthropic, "DefaultAsyncHttpxClient", lambda **kw: seen.append(kw) or httpx2.AsyncClient())
    native._http_client()
    assert seen[-1] == {"trust_env": False, "follow_redirects": False}
    monkeypatch.setenv("MODEL_EGRESS_PROXY", "http://proxy.internal:3128")
    native._http_client()
    assert seen[-1] == {"trust_env": False, "follow_redirects": False, "proxy": "http://proxy.internal:3128"}


def test_the_sdk_does_not_retry_and_has_the_finbot_timeout():
    client = native.make_client(KEY)
    assert client.max_retries == 0 and client.timeout.read == provider.PROVIDER_REQUEST_SECONDS


def test_workspace_header_is_sent_only_for_a_valid_configured_id(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "a")]), stream_of([("text", "b")]), stream_of([("text", "c")]))
    decide()
    assert "anthropic-workspace-id" not in server.posts[-1].headers
    monkeypatch.setenv("FINBOT_ANTHROPIC_WORKSPACE_ID", "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ")
    decide()
    assert server.posts[-1].headers["anthropic-workspace-id"] == "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ"
    monkeypatch.setenv("FINBOT_ANTHROPIC_WORKSPACE_ID", "not an id\r\nx-evil: 1")
    decide()
    assert "anthropic-workspace-id" not in server.posts[-1].headers and "x-evil" not in server.posts[-1].headers


def test_a_user_typed_base_url_is_ignored(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "ok")]))
    asyncio.run(provider.decision_request("anthropic", MODEL, KEY, [{"role": "user", "content": "q"}], [], "https://evil.example/v1"))
    assert server.posts[0].url.host == "api.anthropic.com"


def test_one_pooled_client_serves_a_whole_turn(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "a")]), stream_of([("text", "b")]))
    made = []
    original = native.make_client
    monkeypatch.setattr(native, "make_client", lambda *a: made.append(1) or original(*a))

    async def turn():
        async with provider.decision_session(None):
            await provider.decision_request("anthropic", MODEL, KEY, [{"role": "user", "content": "1"}], [], None, None)
            await provider.decision_request("anthropic", MODEL, KEY, [{"role": "user", "content": "2"}], [], None, None)
    asyncio.run(turn())
    assert len(made) == 1 and len(server.posts) == 2


def test_the_switch_off_returns_to_the_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", "off")
    sent = []

    async def handler(request):
        sent.append(request)
        body = b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    original = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **kw: original(**{**kw, "transport": httpx.MockTransport(handler)}))   # the pinned transport is replaced
    monkeypatch.setattr(native, "make_client", lambda *a: (_ for _ in ()).throw(AssertionError("native client used")))
    _, message = decide(effort="high")
    assert message["content"] == "hi"
    request = sent[0]
    assert str(request.url) == "https://api.anthropic.com/v1/chat/completions" and request.headers["authorization"] == f"Bearer {KEY}"
    assert "reasoning_effort" not in json.loads(request.content) and "x-api-key" not in request.headers


# ---- other providers are untouched --------------------------------------------------------------------------------------------

GOLDEN = {
    "openrouter": {"model": "test/model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 32768, "stream": True,
                   "tools": [TOOL], "tool_choice": "auto", "reasoning": {"effort": "high"}},
    "deepseek": {"model": "test/model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 32768, "stream": True,
                 "tools": [TOOL], "tool_choice": "auto", "thinking": {"type": "enabled"}, "reasoning_effort": "high"},
}


@pytest.mark.parametrize("name", ["openrouter", "deepseek"])
@pytest.mark.parametrize("native_switch", ["on", "off"])
def test_other_providers_send_the_same_body_and_headers_with_the_switch_either_way(monkeypatch, name, native_switch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", native_switch)
    monkeypatch.setattr(native, "make_client", lambda *a: (_ for _ in ()).throw(AssertionError("native client used")))
    sent = []

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    asyncio.run(provider.decision_request(name, "test/model", "test-key", [{"role": "user", "content": "hi"}], [TOOL], None, "high"))
    request = sent[0]
    assert json.loads(request.content) == GOLDEN[name]
    assert request.content == json.dumps(GOLDEN[name], separators=(",", ":")).encode() or json.loads(request.content) == GOLDEN[name]
    expected = {"authorization": "Bearer test-key", "content-type": "application/json", **({"x-title": "FinBot"} if name == "openrouter" else {})}
    assert {k: v for k, v in request.headers.items() if k in {"authorization", "content-type", "x-title", "x-api-key", "anthropic-version", "anthropic-beta"}} == expected


# ---- catalogue ---------------------------------------------------------------------------------------------------------------

def test_the_catalogue_shows_the_models_own_tiers_and_none_when_native_is_off(monkeypatch):
    from app.agent_model_catalog import _reasoning_fields
    entry = {"provider": "anthropic", "model": MODEL}
    assert _reasoning_fields(entry) == {"reasoning_supported": True, "supported_efforts": ["low", "medium", "high", "xhigh", "max"]}
    native._CAPS[MODEL] = (__import__("time").monotonic(), {"adaptive": True, "efforts": ("low", "medium", "high", "max")})
    assert _reasoning_fields(entry)["supported_efforts"] == ["low", "medium", "high", "max"]
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", "off")
    assert _reasoning_fields(entry) == {"reasoning_supported": False}


def test_capabilities_come_from_the_models_api_and_a_failure_falls_back_and_is_cached(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "a")]), stream_of([("text", "b")]), models=CAPS_5)
    decide(effort="xhigh")
    decide(effort="xhigh")
    assert sum(r.method == "GET" for r in server.requests) == 1                       # read once, cached
    assert server.body(0)["output_config"] == {"effort": "xhigh"} and native.efforts_for(MODEL) == native.STATIC_EFFORTS
    native._CAPS.clear()
    limited = json.loads(json.dumps(CAPS_5))
    limited["capabilities"]["effort"]["xhigh"] = None
    limited["capabilities"]["effort"]["max"] = {"supported": False}
    server = serve(monkeypatch, stream_of([("text", "a")]), models=limited)
    decide(effort="xhigh")
    assert "output_config" not in server.body(0) and native.efforts_for(MODEL) == ("low", "medium", "high")
    native._CAPS.clear()
    server = serve(monkeypatch, stream_of([("text", "a")]), stream_of([("text", "b")]), models=None)   # the read fails (404)
    decide(effort="max")
    decide(effort="max")
    assert server.body(0)["output_config"] == {"effort": "max"} and sum(r.method == "GET" for r in server.requests) == 1


def test_anthropic_is_a_known_provider():
    from app.agent_chat_api import PROVIDER_NAMES
    assert "anthropic" in PROVIDER_NAMES and provider.NATIVE_EFFORTS["anthropic"] == native.STATIC_EFFORTS


def test_refusal_has_a_user_notice():
    from app.agent_chat_stream import _FAILURE_NOTICES
    assert "拒绝" in _FAILURE_NOTICES["provider_refusal"] and "FINBOT_ANTHROPIC_WORKSPACE_ID" in _FAILURE_NOTICES["provider_workspace_required"]


# ==== acceptance rework (Opus review, 2026-11-21) ===========================================================================

def test_caching_is_one_explicit_breakpoint_on_the_last_tool_and_never_automatic():
    other = {"type": "function", "function": {"name": "calculate", "parameters": {}}}
    params, _ = native.build_request(MODEL, [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}], [TOOL, other])
    assert "cache_control" not in params                                  # an automatic breakpoint would only ever write, never read
    assert params["tools"][-1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in params["tools"][0]
    assert "cache_control" not in json.dumps(native.build_request(MODEL, [{"role": "user", "content": "q"}], [])[0])


def test_thinking_is_stripped_from_the_history_by_default_and_nothing_is_stored(monkeypatch):
    server = serve(monkeypatch, stream_of([("thinking", "plan it", SIG), ("text", "looking"), ("tool", "toolu_a", "query_financials", '{"symbol": "AAPL"}')], stop="tool_use"),
                   stream_of([("text", "done")]))
    _, first = decide([{"role": "user", "content": "q"}], schemas=[TOOL])
    assert "_anthropic_content" not in first and first["reasoning_content"] == "plan it"
    stored = {"role": "assistant", "content": "looking", "tool_calls": first["tool_calls"],
              "_anthropic_content": [{"type": "thinking", "thinking": "plan it", "signature": SIG}, {"type": "redacted_thinking", "data": "x"},
                                     {"type": "text", "text": "looking"}, {"type": "tool_use", "id": "toolu_a", "name": "query_financials", "input": {"symbol": "AAPL"}}]}
    decide([{"role": "user", "content": "q"}, stored, {"role": "tool", "tool_call_id": "toolu_a", "content": "{}"}], schemas=[TOOL])
    second = server.body(1)
    assert [b["type"] for b in second["messages"][1]["content"]] == ["text", "tool_use"]
    assert "block_binding" not in second["thinking"] and "anthropic-beta" not in server.posts[1].headers
    assert "plan it" not in json.dumps(second) and SIG not in json.dumps(second)


def test_the_binding_value_is_validated_and_a_typo_means_strip(monkeypatch, caplog):
    native._warned.clear()
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop-block")
    with caplog.at_level(logging.WARNING, logger="app.anthropic_native"):
        assert native.binding_mode() == "strip" and native.binding_mode() == "strip"
    assert sum("FINBOT_ANTHROPIC_THINKING_BINDING" in r.getMessage() for r in caplog.records) == 1     # once
    for value, expected in [("strip", "strip"), ("drop_block", "drop_block"), ("OFF", "off"), ("", "strip")]:
        monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", value)
        assert native.binding_mode() == expected


def test_the_apis_report_of_dropped_thinking_is_returned_and_counted_in_the_audit(monkeypatch):
    monkeypatch.setenv("FINBOT_ANTHROPIC_THINKING_BINDING", "drop_block")
    report = [{"type": "thinking_dropped", "path": "messages.1.content.0", "reason": "prefix_binding_mismatch"},
              {"type": "thinking_mismatch_allowed", "path": "messages.1.content.1", "reason": "prefix_binding_mismatch"}]
    body = stream_of([("text", "ok")]).replace(b'"stop_sequence": null}, "usage"', b'"stop_sequence": null}, "input_transformations": %s, "usage"' % json.dumps(report).encode())
    server = serve(monkeypatch, stream_of([("thinking", "t", SIG), ("tool", "toolu_a", "query_financials", '{"symbol": "AAPL"}')], stop="tool_use"), body)
    _, first = decide([{"role": "user", "content": "q"}], schemas=[TOOL])
    assistant = {"role": "assistant", **{k: v for k, v in first.items() if k in {"content", "tool_calls", "_anthropic_content"}}}
    data, _ = decide([{"role": "user", "content": "q"}, assistant, {"role": "tool", "tool_call_id": "toolu_a", "content": "{}"}], schemas=[TOOL])
    assert "thinking-binding-controls-2026-08-01" in server.posts[1].headers["anthropic-beta"]    # only a request that sends thinking back is a beta request
    assert [(t["type"], t["path"]) for t in data["input_transformations"]] == [("thinking_dropped", "messages.1.content.0"), ("thinking_mismatch_allowed", "messages.1.content.1")]
    # direct.py counts them by kind in the turn's audit
    import asyncio as aio
    from test_sw1d_toolcall_cap import make_turn
    from app.agent_workflow import direct

    async def stub(*args, **kwargs):
        return data, {"role": "assistant", "content": "ok"}
    monkeypatch.setattr(direct, "decision_request", stub)
    turn = make_turn()
    aio.run(turn.model([{"role": "user", "content": "q"}], []))
    assert turn.audit["input_transformations"] == {"thinking_dropped": 1, "thinking_mismatch_allowed": 1}


def test_a_refusal_category_goes_into_the_audit_and_is_not_retried(monkeypatch):
    import asyncio as aio
    from test_sw1d_toolcall_cap import make_turn
    from app.agent_workflow import direct
    attempts = []

    async def stub(*args, **kwargs):
        attempts.append(1)
        raise native.ProviderRefusal(stage="classification", category="cyber")
    monkeypatch.setattr(direct, "decision_request", stub)
    turn = make_turn()
    with pytest.raises(HTTPException) as error:
        aio.run(turn.model([{"role": "user", "content": "q"}], []))
    assert error.value.detail == "provider_refusal" and len(attempts) == 1 and turn.audit["refusal"] == {"category": "cyber"}


# ---- system messages inside the conversation --------------------------------------------------------------------------------

CALL = lambda i: {"id": i, "type": "function", "function": {"name": "f", "arguments": "{}"}}


def _legal(messages):
    """The API's placement rules for a role "system" entry: never first, right after a user turn, followed by an assistant turn or nothing."""
    for i, m in enumerate(messages):
        if m["role"] == "system":
            assert i > 0 and messages[i - 1]["role"] == "user", messages
            assert i == len(messages) - 1 or messages[i + 1]["role"] == "assistant", messages
    assert messages[0]["role"] == "user"


LOOP = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}, {"role": "system", "content": "understanding hint"},
        {"role": "assistant", "content": "", "tool_calls": [CALL("t1")]}, {"role": "tool", "tool_call_id": "t1", "content": "{\"ok\": 1}"},
        {"role": "system", "content": "Accepted evidence DATA (recent sources): [{\"x\": 1}]"},
        {"role": "system", "content": "Tool statuses and validation errors: []"}, {"role": "system", "content": "Server result catalogue: []"}]


def test_instruction_messages_keep_system_authority_where_the_api_accepts_one_and_evidence_is_user_text():
    system, messages = native.convert_messages(LOOP, system_role=True)
    _legal(messages)
    assert system == [{"type": "text", "text": "rules"}]
    assert [m["role"] for m in messages] == ["user", "system", "assistant", "user", "system"]
    assert messages[1]["content"] == "understanding hint"
    assert messages[3]["content"][0]["type"] == "tool_result"
    assert messages[3]["content"][1] == {"type": "text", "text": "Accepted evidence DATA (recent sources): [{\"x\": 1}]"}   # third-party text stays user text
    assert messages[4]["content"] == "Tool statuses and validation errors: []\n\nServer result catalogue: []"             # merged into one


def test_a_model_without_mid_conversation_system_support_gets_every_note_as_user_text():
    _, messages = native.convert_messages(LOOP, system_role=False)
    assert all(m["role"] != "system" for m in messages)
    assert [b["text"] for b in messages[-1]["content"] if b["type"] == "text"][-2:] == ["Tool statuses and validation errors: []", "Server result catalogue: []"]


def test_a_note_in_an_illegal_place_falls_back_to_user_text():
    messages_in = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "plain answer"}, {"role": "system", "content": "nudge: use a tool"}]
    _, messages = native.convert_messages(messages_in, system_role=True)
    _legal(messages)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"] and messages[2]["content"] == [{"type": "text", "text": "nudge: use a tool"}]
    # evidence that arrives while a note is waiting is added to the user turn before it, so the note is never followed by a user turn
    _, messages = native.convert_messages([{"role": "user", "content": "q"}, {"role": "system", "content": "note"},
                                          {"role": "system", "content": "Past conversation recalls (memory): []"}, {"role": "user", "content": "more"}], system_role=True)
    _legal(messages)
    assert [m["role"] for m in messages] == ["user", "system"] and [b["text"] for b in messages[0]["content"]] == ["q", "Past conversation recalls (memory): []", "more"]


def test_unanswered_calls_with_notes_stay_legal():
    _, messages = native.convert_messages([{"role": "user", "content": "q"}, {"role": "assistant", "content": "", "tool_calls": [CALL("a")]}, {"role": "system", "content": "note"}], system_role=True)
    _legal(messages)
    assert messages[-1]["role"] == "user" or messages[-1]["role"] == "system"


def test_real_finbot_messages_are_classified_the_way_the_conversion_assumes():
    from test_sw1d_toolcall_cap import make_turn
    from app.agent_workflow import direct
    turn = make_turn()
    turn.recalls = []
    assert native.is_data_message(turn.evidence_parts([])[0]) and native.is_data_message(turn.recall_payload())
    assert native.is_data_message(direct.OMITTED_DIGEST_HEAD + "\n[1] x")
    assert not native.is_data_message(turn.status_payload()) and not native.is_data_message(turn.catalogue_payload())
    assert not native.is_data_message(direct.UNDERSTANDING_NOTE)


def test_the_request_sends_a_system_role_only_to_the_models_that_take_one(monkeypatch):
    params, _ = native.build_request(MODEL, LOOP, [TOOL])
    assert [m["role"] for m in params["messages"]] == ["user", "system", "assistant", "user", "system"]
    params, _ = native.build_request("claude-haiku-4-5", LOOP, [TOOL], caps={"adaptive": False, "efforts": ()})
    assert all(m["role"] != "system" for m in params["messages"])


def test_the_real_sdk_accepts_and_sends_the_system_role_entries(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "ok")]))
    decide(LOOP, schemas=[TOOL])
    assert [m["role"] for m in server.body(0)["messages"]] == ["user", "system", "assistant", "user", "system"]


# ---- the key ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [None, "", "   ", "\n"])
def test_an_empty_key_is_refused_before_the_sdk_can_read_the_environment(monkeypatch, key):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-ENV-must-never-be-used")
    server = serve(monkeypatch, stream_of([("text", "x")]), stream_of([("text", "x")]))
    with pytest.raises(HTTPException) as error:
        asyncio.run(provider.decision_request("anthropic", MODEL, key, [{"role": "user", "content": "q"}], [], None, None))
    assert error.value.detail == "provider_invalid_key" and error.value.status_code == 502
    with pytest.raises(HTTPException) as error:
        async def run():
            return [p async for p in provider.stream_answer("anthropic", MODEL, key, [{"role": "user", "content": "q"}], None)]
        asyncio.run(run())
    assert error.value.detail == "provider_invalid_key"
    assert server.requests == []
    with pytest.raises(HTTPException):
        native.make_client(key)


# ---- the SDK is optional until it is used --------------------------------------------------------------------------------------

def test_the_modules_import_without_the_sdk_installed():
    import subprocess, sys
    from pathlib import Path
    code = ("import sys; sys.modules['anthropic'] = None; sys.modules['httpx2'] = None\n"
            "import app.anthropic_native as n, app.agent_chat_provider, app.agent_model_catalog as c\n"
            "assert 'anthropic' not in vars(n) and n.display_efforts('claude-haiku-5-5') == n.STATIC_EFFORTS\n"
            "assert c._reasoning_fields({'provider': 'anthropic', 'model': 'claude-haiku-5-5'})['reasoning_supported'] is True\n"
            "print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stdout.strip().endswith("ok"), result.stderr[-800:]


def test_without_the_sdk_off_still_reaches_anthropic_and_on_says_what_is_missing(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    with pytest.raises(HTTPException) as error:
        decide()
    assert error.value.status_code == 502 and error.value.detail == "provider_sdk_missing"
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", "off")
    sent = []

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr(provider.httpx, "AsyncClient", lambda **kw: original(**{**kw, "transport": httpx.MockTransport(handler)}))
    _, message = decide()
    assert message["content"] == "hi" and str(sent[0].url) == "https://api.anthropic.com/v1/chat/completions"
    from app.agent_model_catalog import _reasoning_fields
    assert _reasoning_fields({"provider": "anthropic", "model": MODEL}) == {"reasoning_supported": False}


# ---- what the SDK would read from the environment -----------------------------------------------------------------------------------

def test_custom_headers_and_tracing_settings_in_the_environment_do_not_reach_the_request(monkeypatch, caplog):
    native._warned.clear()
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "anthropic-beta: evil-beta\nx-evil: 1")
    monkeypatch.setenv("ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE", "content")
    server = serve(monkeypatch, stream_of([("text", "ok")]), stream_of([("text", "ok")]))
    with caplog.at_level(logging.WARNING, logger="app.anthropic_native"):
        decide()
        decide()
    headers = server.posts[0].headers
    assert "x-evil" not in headers and "evil-beta" not in headers.get("anthropic-beta", "")
    assert "x-evil" not in server.requests[0].headers                       # not on the capabilities read either
    warnings = [r.getMessage() for r in caplog.records if "ignored for provider anthropic" in r.getMessage()]
    assert len(warnings) == 1 and "ANTHROPIC_CUSTOM_HEADERS" in warnings[0] and "evil" not in warnings[0]
    import os
    assert os.environ["ANTHROPIC_CUSTOM_HEADERS"].startswith("anthropic-beta")   # restored for whoever else reads it


def test_a_malformed_workspace_id_is_reported_once_and_ignored(monkeypatch, caplog):
    native._warned.clear()
    monkeypatch.setenv("FINBOT_ANTHROPIC_WORKSPACE_ID", "workspace-123")
    with caplog.at_level(logging.WARNING, logger="app.anthropic_native"):
        assert native.workspace_id() is None and native.workspace_id() is None
    assert sum("FINBOT_ANTHROPIC_WORKSPACE_ID" in r.getMessage() for r in caplog.records) == 1


def test_a_bug_in_building_the_request_is_not_reported_as_a_provider_failure(monkeypatch):
    serve(monkeypatch, stream_of([("text", "x")]))
    monkeypatch.setattr(native, "convert_messages", lambda *a, **k: (_ for _ in ()).throw(ValueError("our bug")))
    with pytest.raises(ValueError, match="our bug"):
        decide()


# ---- effort follows the environment default like every other provider ----------------------------------------------------------------

@pytest.mark.parametrize("effort,expected", [(None, "low"), ("none", "low"), ("minimal", "low"), ("low", "low"), ("medium", "medium"), ("xhigh", "xhigh"), ("max", "max")])
def test_background_calls_and_legacy_tiers_send_low_and_a_chosen_tier_is_sent_as_it_is(monkeypatch, effort, expected):
    server = serve(monkeypatch, stream_of([("text", "x")]))
    decide(effort=effort)
    assert server.body(0)["output_config"] == {"effort": expected}


def test_the_environment_can_say_default_and_then_nothing_is_sent_unless_the_bot_chose(monkeypatch):
    monkeypatch.setattr(provider, "REASONING_EFFORT", "default")
    server = serve(monkeypatch, stream_of([("text", "a")]), stream_of([("text", "b")]), stream_of([("text", "c")]))
    decide()
    assert "output_config" not in server.body(0)
    decide(effort="high")
    assert server.body(1)["output_config"] == {"effort": "high"}
    answer()
    assert "output_config" not in server.body(2)


def test_the_final_answer_carries_the_default_tier(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "x")]))
    answer()
    assert server.body(0)["output_config"] == {"effort": "low"}


def test_a_model_outside_the_55_family_is_not_assumed_to_take_thinking_or_effort(monkeypatch):
    server = serve(monkeypatch, stream_of([("text", "x")], model="claude-haiku-4-5"), models=None)
    decide(effort="high", model="claude-haiku-4-5")
    body = server.body(0)
    assert "thinking" not in body and "output_config" not in body
    assert native.efforts_for("claude-haiku-4-5") == () and native.efforts_for(MODEL) == native.STATIC_EFFORTS and native.efforts_for(None) == native.STATIC_EFFORTS
