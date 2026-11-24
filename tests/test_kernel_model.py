"""Kernel model-call layer: stream_decision (answer text piece by piece, thinking kept, cache markers).

Nothing here reaches the network: ``anthropic_native._stream`` is replaced by a scripted async generator.
"""
import asyncio
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
import app.anthropic_native as native

MODEL = "claude-haiku-5-5"
CACHE = {"type": "ephemeral"}
SCHEMAS = [{"type": "function", "function": {"name": "f", "description": "d",
                                              "parameters": {"type": "object", "properties": {"a": {"type": "integer"}}}}}]
MESSAGES = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": '{"a":1}'}}]},
    {"role": "tool", "tool_call_id": "t1", "content": "res"},
]


@pytest.fixture(autouse=True)
def _default_binding(monkeypatch):
    monkeypatch.delenv("FINBOT_ANTHROPIC_THINKING_BINDING", raising=False)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def thinking_block(text):
    return SimpleNamespace(type="thinking", thinking=text, signature="sig")


def tool_block(call_id, name, args):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=args)


def final_of(blocks, stop="end_turn", usage=None):
    usage = usage or {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=SimpleNamespace(**usage))


def script(monkeypatch, *events):
    """Replace _stream with a generator that yields ``events``; the arguments it was called with are recorded."""
    calls = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        for event in events:
            yield event

    monkeypatch.setattr(native, "_stream", fake)
    return calls


def run(**kwargs):
    pieces = []

    async def on_text(piece):
        pieces.append(piece)

    params = dict(messages=MESSAGES, schemas=SCHEMAS, on_text=on_text)
    params.update(kwargs)
    if params["on_text"] is None:
        params.pop("on_text")
    data, message = asyncio.run(provider.stream_decision("anthropic", MODEL, "key", **params))
    return data, message, pieces


def test_text_pieces_reach_on_text_in_order(monkeypatch):
    script(monkeypatch, ("thinking", "想"), ("text", "营收 "), ("text", "1158"), ("final", final_of([thinking_block("想"), text_block("营收 1158")])))
    data, message, pieces = run()
    assert pieces == ["营收 ", "1158"]
    assert message["content"] == "营收 1158"
    assert data["choices"][0]["message"] is message


def test_no_on_text_is_fine(monkeypatch):
    script(monkeypatch, ("text", "a"), ("final", final_of([text_block("a")])))
    _, message, _ = run(on_text=None)
    assert message["content"] == "a"


def test_tool_calls_are_returned_in_openai_shape(monkeypatch):
    script(monkeypatch, ("final", final_of([tool_block("toolu_1", "f", {"a": 2})], stop="tool_use")))
    data, message, _ = run()
    assert message["tool_calls"][0] == {"id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": '{"a": 2}'}}
    assert data["choices"][0]["finish_reason"] == "tool_calls"


def test_keep_thinking_attaches_raw_blocks(monkeypatch):
    blocks = [thinking_block("想"), text_block("答")]
    script(monkeypatch, ("final", final_of(blocks)))
    _, kept, _ = run(keep_thinking=True)
    assert kept["_anthropic_content"] == [{"type": "thinking", "thinking": "想", "signature": "sig"}, {"type": "text", "text": "答"}]
    script(monkeypatch, ("final", final_of(blocks)))
    _, dropped, _ = run(keep_thinking=False)
    assert "_anthropic_content" not in dropped


def test_keep_thinking_and_cache_are_passed_to_the_stream(monkeypatch):
    calls = script(monkeypatch, ("final", final_of([text_block("a")])))
    run(keep_thinking=False, cache=False)
    assert calls[0][1]["keep_thinking"] is False and calls[0][1]["cache"] is False


def test_cache_marks_system_and_last_message():
    params, _ = native.build_request(MODEL, MESSAGES, SCHEMAS, cache=True)
    assert params["tools"][-1]["cache_control"] == CACHE
    assert params["system"][-1]["cache_control"] == CACHE
    assert params["messages"][-1]["content"][-1]["cache_control"] == CACHE
    # only the last block of the last message is marked
    assert all("cache_control" not in m["content"][-1] for m in params["messages"][:-1])

    plain, _ = native.build_request(MODEL, MESSAGES, SCHEMAS)
    assert plain["tools"][-1]["cache_control"] == CACHE
    assert "cache_control" not in plain["system"][-1]
    assert all("cache_control" not in block for m in plain["messages"] for block in m["content"])


def test_build_request_default_is_unchanged():
    params, betas = native.build_request(MODEL, MESSAGES, SCHEMAS, effort="high")
    assert betas == []
    assert params == {
        "model": MODEL,
        "max_tokens": native._p.MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "res"}]},
        ],
        "system": [{"type": "text", "text": "SYS"}],
        "tools": [{"name": "f", "input_schema": {"type": "object", "properties": {"a": {"type": "integer"}}}, "description": "d",
                   "cache_control": CACHE}],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "high"},
    }


def test_keep_thinking_request_binds_thinking_blocks():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
         "_anthropic_content": [{"type": "thinking", "thinking": "x", "signature": "s"}, {"type": "tool_use", "id": "t1", "name": "f", "input": {}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "r"},
    ]
    default, default_betas = native.build_request(MODEL, history, SCHEMAS)
    assert default_betas == [] and "block_binding" not in default["thinking"]
    assert all(b["type"] != "thinking" for m in default["messages"] for b in m["content"])

    kept, betas = native.build_request(MODEL, history, SCHEMAS, keep_thinking=True)
    assert betas == [native.THINKING_BINDING_BETA]
    assert kept["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert kept["messages"][1]["content"][0]["type"] == "thinking"

    stripped, stripped_betas = native.build_request(MODEL, history, SCHEMAS, keep_thinking=False)
    assert stripped_betas == [] and "block_binding" not in stripped["thinking"]


def test_other_provider_falls_back_and_emits_once(monkeypatch):
    message = {"role": "assistant", "content": "整段回答"}
    data = {"choices": [{"message": message, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1}}
    seen = []

    async def fake(prov, model, api_key, messages, schemas, base_url=None, reasoning_effort=None):
        seen.append((prov, model, base_url, reasoning_effort))
        return data, message

    monkeypatch.setattr(provider, "decision_request", fake)
    pieces = []

    async def on_text(piece):
        pieces.append(piece)

    result = asyncio.run(provider.stream_decision("siliconflow", "m", "key", MESSAGES, SCHEMAS, base_url="http://x", reasoning_effort="low", on_text=on_text))
    assert result == (data, message)
    assert pieces == ["整段回答"]
    assert seen == [("siliconflow", "m", "http://x", "low")]


def test_other_provider_without_text_emits_nothing(monkeypatch):
    message = {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}

    async def fake(*args, **kwargs):
        return {"choices": []}, message

    monkeypatch.setattr(provider, "decision_request", fake)
    pieces = []

    async def on_text(piece):
        pieces.append(piece)

    asyncio.run(provider.stream_decision("siliconflow", "m", "key", MESSAGES, SCHEMAS, on_text=on_text))
    assert pieces == []


def test_usage_is_passed_through(monkeypatch):
    usage = {"input_tokens": 10, "output_tokens": 7, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 40}
    script(monkeypatch, ("final", final_of([text_block("a")], usage=usage)))
    data, _, _ = run()
    assert data["usage"]["prompt_tokens"] == 350
    assert data["usage"]["completion_tokens"] == 7
    assert data["usage"]["cache_read_input_tokens"] == 300
    assert data["usage"]["cache_creation_input_tokens"] == 40
