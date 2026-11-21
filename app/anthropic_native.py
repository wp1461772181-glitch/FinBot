"""Anthropic's native Messages API for provider ``anthropic``.

FinBot keeps OpenAI-shaped messages internally (``role``/``content``/``tool_calls``/``tool``).  This module is the only
place that knows the Messages API: it converts a request out (pure functions), sends it with the official SDK, and
converts the streamed answer back to the shape ``agent_chat_provider`` returns for every other provider.

Why not the OpenAI-compatible endpoint: it ignores ``reasoning_effort``, has no prompt caching and is documented as
not for production.  Design: docs/superpowers/specs/2026-11-21-anthropic-native-provider-design.md.

Rules kept here (each verified against the official docs, 2026-11-21; see the design note for sources):
* thinking is ``adaptive`` and effort goes in ``output_config.effort``; no temperature / top_p.
* an assistant turn is sent back exactly as returned (thinking blocks included) while a tool call is open.
* a key is never put in an exception, a log line, an audit stage or a repr: SDK errors are reduced to the codes below.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from contextlib import asynccontextmanager

import anthropic
import httpx2
from fastapi import HTTPException

from . import agent_chat_provider as _p
from .agent_progress import mark_progress, progress_watchdog
from .agent_workflow.fp_flags import flag

# The address is fixed: a user-typed Base URL is not accepted for this provider, so none of the SSRF pinning the
# custom endpoints need applies; the operator's MODEL_EGRESS_PROXY still does.
NATIVE_BASE_URL = "https://api.anthropic.com"
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
# What the three 5.5 models take, from the docs' model pages.  Used when the Models API cannot be read.
STATIC_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CAPS_TTL_SECONDS = 6 * 3600
CAPS_RETRY_SECONDS = 300
_WORKSPACE_ID = re.compile(r"^wrkspc_[A-Za-z0-9]{8,64}$")


def native_enabled() -> bool:
    """FINBOT_ANTHROPIC_NATIVE (default on).  Off: provider ``anthropic`` goes through the compatible endpoint again."""
    return flag("FINBOT_ANTHROPIC_NATIVE", True)


def use_native(provider) -> bool:
    return provider == "anthropic" and native_enabled()


def workspace_id() -> str | None:
    """Optional ``anthropic-workspace-id``.  The docs require it for a key that is not scoped to one workspace (a personal
    or service-account key that spans workspaces) and forbid nothing for a scoped key.  Operator setting, not per entry."""
    value = (os.getenv("FINBOT_ANTHROPIC_WORKSPACE_ID") or "").strip()
    return value if _WORKSPACE_ID.fullmatch(value) else None


# --------------------------------------------------------------------------------------------------------------------
# Capabilities (Models API), cached
# --------------------------------------------------------------------------------------------------------------------
_CAPS: dict[str, tuple[float, dict | None]] = {}


def _leaf(node, *path):
    for key in path:
        node = node.get(key) if isinstance(node, dict) else getattr(node, key, None)
        if node is None:
            return None
    return node


def caps_from_model(info) -> dict | None:
    """{'adaptive': bool, 'efforts': tuple} from a Models API object (or its dict), None when it has no usable capabilities."""
    caps = info.get("capabilities") if isinstance(info, dict) else getattr(info, "capabilities", None)
    if caps is None:
        return None
    effort = _leaf(caps, "effort")
    if effort is None:
        return None
    efforts = ()
    if _leaf(effort, "supported"):
        efforts = tuple(t for t in STATIC_EFFORTS if _leaf(effort, t, "supported") is True)
    return {"adaptive": _leaf(caps, "thinking", "types", "adaptive", "supported") is True, "efforts": efforts}


def cached_caps(model) -> dict | None:
    entry = _CAPS.get(model)
    if entry is not None and time.monotonic() - entry[0] < (CAPS_TTL_SECONDS if entry[1] is not None else CAPS_RETRY_SECONDS):
        return entry[1]
    return None


async def read_caps(client, model) -> dict | None:
    """Capabilities of one model, from the cache or one GET /v1/models/{id}.  Any failure gives None (the static table
    applies) and is not asked again for a few minutes; a read never fails or stalls a request."""
    entry = _CAPS.get(model)
    if entry is not None and time.monotonic() - entry[0] < (CAPS_TTL_SECONDS if entry[1] is not None else CAPS_RETRY_SECONDS):
        return entry[1]
    try:
        caps = caps_from_model(await client.with_options(timeout=15.0).models.retrieve(model))
    except Exception:  # noqa: BLE001 - the catalogue and the request fall back to the static table
        caps = None
    _CAPS[model] = (time.monotonic(), caps)
    return caps


def efforts_for(model) -> tuple:
    """The tiers shown for an entry: the Models API's answer when it was read, else the static table."""
    caps = cached_caps(model)
    return caps["efforts"] if caps is not None else STATIC_EFFORTS


def display_efforts(model) -> tuple:
    """What the catalogue offers: nothing while the native channel is off (the compatible endpoint ignores effort)."""
    return efforts_for(model) if native_enabled() else ()


# --------------------------------------------------------------------------------------------------------------------
# Request conversion (pure)
# --------------------------------------------------------------------------------------------------------------------
def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def convert_tools(schemas) -> list[dict]:
    tools = []
    for schema in schemas or []:
        function = schema.get("function") if isinstance(schema, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            parameters = {"type": "object", "properties": (parameters or {}).get("properties", {}) if isinstance(parameters, dict) else {}}
        tool = {"name": function["name"], "input_schema": parameters}
        if function.get("description"):
            tool["description"] = function["description"]
        tools.append(tool)
    return tools


def _arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _assistant_blocks(message) -> list[dict]:
    """The content blocks of one assistant turn.  The blocks the API returned (kept in ``_anthropic_content``) are used
    as they are, thinking included; they are rebuilt from content/tool_calls only when they are missing or no longer
    describe the same calls."""
    calls = message.get("tool_calls") or []
    raw = message.get("_anthropic_content")
    if isinstance(raw, list) and raw and all(isinstance(b, dict) and isinstance(b.get("type"), str) for b in raw):
        raw_ids = [b.get("id") for b in raw if b.get("type") == "tool_use"]
        if raw_ids == [c.get("id") for c in calls]:
            return copy.deepcopy(raw)
    blocks = []
    text = _text_of(message.get("content"))
    if text.strip():
        blocks.append({"type": "text", "text": text})
    for call in calls:
        function = call.get("function") or {}
        blocks.append({"type": "tool_use", "id": call.get("id"), "name": function.get("name"), "input": _arguments(function.get("arguments"))})
    return blocks


def _push_user(out, blocks):
    if not blocks:
        return
    if out and out[-1]["role"] == "user":
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": "user", "content": list(blocks)})


def convert_messages(messages) -> tuple[list[dict], list[dict]]:
    """OpenAI-shaped messages -> (``system`` blocks, Messages API ``messages``).

    * The system messages before the first conversation message become the top-level ``system``.  A system message
      that comes later (status, evidence, a nudge after a tool result) is not moved up: it stays where it was, as a
      text block in the user turn, so the leading ``system`` is not rewritten step after step and a mid-conversation
      ``role: "system"`` entry (which the API only accepts in a few positions) is never needed.
    * ``tool_calls`` -> ``tool_use``; the ``tool`` messages that answer one assistant turn -> ``tool_result`` blocks of
      ONE user message, before any text.  A call nobody answered gets an error result; a result nobody asked for is dropped.
    """
    system, out, leading = [], [], True
    for message in messages or []:
        role = message.get("role")
        if role == "system":
            text = _text_of(message.get("content"))
            if not text.strip():
                continue
            if leading:
                system.append({"type": "text", "text": text})
            else:
                _push_user(out, [{"type": "text", "text": text}])
            continue
        leading = False
        if role == "user":
            text = _text_of(message.get("content"))
            if text.strip():
                _push_user(out, [{"type": "text", "text": text}])
        elif role == "assistant":
            blocks = _assistant_blocks(message)
            if not blocks:
                continue
            if out and out[-1]["role"] == "assistant":
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.get("tool_call_id")}
            text = _text_of(message.get("content"))
            if text:
                block["content"] = text
            _push_user(out, [block])
    return system, _settle(out)


def _settle(out) -> list[dict]:
    """Make every tool_use answered exactly once, tool results first in their message, and the list start with a user turn."""
    settled, previous_ids = [], []
    for message in out:
        if message["role"] == "user":
            results = [b for b in message["content"] if b.get("type") == "tool_result"]
            others = [b for b in message["content"] if b.get("type") != "tool_result"]
            seen = {b["tool_use_id"] for b in results}
            kept = [b for b in results if b["tool_use_id"] in previous_ids]
            kept += [{"type": "tool_result", "tool_use_id": i, "content": "no result was recorded for this call", "is_error": True}
                     for i in previous_ids if i not in seen]
            content = kept + others
            previous_ids = []
            if content:
                settled.append({"role": "user", "content": content})
            continue
        if previous_ids:  # an assistant turn that follows unanswered calls
            settled.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": i,
                                                          "content": "no result was recorded for this call", "is_error": True} for i in previous_ids]})
        previous_ids = [b["id"] for b in message["content"] if b.get("type") == "tool_use"]
        settled.append(message)
    if previous_ids:
        settled.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": i,
                                                      "content": "no result was recorded for this call", "is_error": True} for i in previous_ids]})
    if not settled or settled[0]["role"] != "user":
        settled.insert(0, {"role": "user", "content": [{"type": "text", "text": "(begin)"}]})
    return settled


def has_thinking(messages) -> bool:
    return any(b.get("type") in {"thinking", "redacted_thinking"} for m in messages if m["role"] == "assistant" for b in m["content"])


def binding_mode() -> str | None:
    """What to do with a thinking block the API finds stale.  FinBot rebuilds its prompt every step (a status counter, the
    evidence), so a block can fail the API's prefix check; on the 5.5 models that is "possibly a 400".  ``drop_block``
    (default) turns it into a dropped, unbilled block.  ``off`` sends nothing (the API's own default)."""
    value = (os.getenv("FINBOT_ANTHROPIC_THINKING_BINDING") or "drop_block").strip().lower()
    return value if value == "drop_block" else None


def build_request(model, messages, schemas, *, effort=None, caps=None) -> tuple[dict, list[str]]:
    """The keyword arguments of one Messages API call and the beta headers it needs (usually none).  Pure."""
    system, converted = convert_messages(messages)
    params: dict = {"model": model, "max_tokens": _p.MAX_OUTPUT_TOKENS, "messages": converted, "cache_control": {"type": "ephemeral"}}
    if system:
        params["system"] = system
    tools = convert_tools(schemas)
    if tools:
        params["tools"] = tools
        params["tool_choice"] = {"type": "auto"}
    betas: list[str] = []
    if caps is None or caps["adaptive"]:
        params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if has_thinking(converted) and binding_mode():
            params["thinking"]["block_binding"] = {"prefix_mismatch_behavior": binding_mode()}
            betas.append(THINKING_BINDING_BETA)
    # Only a tier the bot chose is sent; none means the model's own default.  none/minimal do not exist here.
    tiers = caps["efforts"] if caps is not None else STATIC_EFFORTS
    if effort in tiers:
        params["output_config"] = {"effort": effort}
    return params, betas


# --------------------------------------------------------------------------------------------------------------------
# Response conversion (pure)
# --------------------------------------------------------------------------------------------------------------------
def block_to_param(block) -> dict:
    """One response content block as the request would send it back."""
    kind = block.type
    if kind == "text":
        return {"type": "text", "text": block.text}
    if kind == "thinking":
        return {"type": "thinking", "thinking": block.thinking or "", "signature": block.signature}
    if kind == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    if kind == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input if isinstance(block.input, dict) else {}}
    return block.model_dump(exclude_none=True)


def usage_to_openai(usage) -> dict:
    """input_tokens counts only what was not served from or written to the cache; the OpenAI field is the whole prompt."""
    def number(name):
        value = getattr(usage, name, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    read, written = number("cache_read_input_tokens"), number("cache_creation_input_tokens")
    prompt, completion = number("input_tokens") + read + written, number("output_tokens")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": read}, "cache_read_input_tokens": read, "cache_creation_input_tokens": written}


class ProviderRefusal(_p.ProviderFailure):
    """The model declined (stop_reason ``refusal``).  ``category`` is the API's stop_details.category (may be None)."""
    def __init__(self, *, stage, category=None, request_id=None):
        super().__init__("provider_refusal", stage=stage, request_id=request_id)
        self.category = category


def message_from_final(final, *, stage, calls_cap, over_cap_code, allow_tools=True) -> tuple[dict, str]:
    """The OpenAI-shaped assistant message and finish reason of a finished stream.  Raises the code a failed check maps to."""
    reason = getattr(final, "stop_reason", None)
    if reason is None:
        raise HTTPException(502, "provider_incomplete_stream")
    if reason == "refusal":
        details = getattr(final, "stop_details", None)
        category = getattr(details, "category", None)
        raise ProviderRefusal(stage=stage, category=category if isinstance(category, str) else None, request_id=getattr(final, "_request_id", None))
    if reason not in {"end_turn", "tool_use", "max_tokens", "stop_sequence"}:
        raise HTTPException(502, "provider_incomplete_response")  # pause_turn and anything unknown: no server tools are used
    blocks = [block_to_param(b) for b in final.content]
    text = "".join(b["text"] for b in blocks if b["type"] == "text")
    thinking = "".join(b["thinking"] for b in blocks if b["type"] == "thinking")
    uses = [b for b in blocks if b["type"] == "tool_use"]
    if len(uses) > calls_cap:
        raise _p.ResponseCheckFailed(over_cap_code, "tool_index", tool_index=calls_cap)
    if uses and not allow_tools:
        raise HTTPException(502, "provider_incomplete_stream")
    message: dict = {"role": "assistant", "content": text}
    if thinking:
        message["reasoning_content"] = thinking
    finish = {"end_turn": "stop", "stop_sequence": "stop", "tool_use": "tool_calls", "max_tokens": "length"}[reason]
    if finish == "length" and (uses or not text.strip()):
        raise HTTPException(502, "provider_incomplete_response")  # out of tokens: text is still an answer, a cut call is not
    if uses:
        if finish != "tool_calls" or any(not u["id"] or not u["name"] for u in uses):
            raise HTTPException(502, "provider_incomplete_stream")
        message["tool_calls"] = [{"id": u["id"], "type": "function", "function": {"name": u["name"], "arguments": json.dumps(u["input"], ensure_ascii=False)}} for u in uses]
    elif finish == "tool_calls":
        raise HTTPException(502, "provider_incomplete_stream")
    message["_anthropic_content"] = blocks
    return message, finish


# --------------------------------------------------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------------------------------------------------
def _http_client():
    """The SDK's own httpx2 client: no environment proxy (the operator's MODEL_EGRESS_PROXY only), no redirects."""
    options = {"trust_env": False, "follow_redirects": False}
    proxy = (os.getenv("MODEL_EGRESS_PROXY") or "").strip()
    if proxy:
        options["proxy"] = proxy
    return anthropic.DefaultAsyncHttpxClient(**options)


def make_client(api_key, wid=None):
    # Everything is explicit: the SDK would otherwise read ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / profile files.
    headers = {"anthropic-workspace-id": wid} if wid else None
    return anthropic.AsyncAnthropic(api_key=api_key, base_url=NATIVE_BASE_URL, max_retries=0,
                                    timeout=anthropic.Timeout(_p.PROVIDER_REQUEST_SECONDS, connect=15.0),
                                    default_headers=headers, http_client=_http_client())


@asynccontextmanager
async def client_for(api_key):
    """One pooled client per turn (the decision_session), else one for the call.  Never keyed or logged by the key itself."""
    wid = workspace_id()
    session = _p._DECISION_SESSION.get()
    if session is None:
        async with make_client(api_key, wid) as client:
            yield client
        return
    pool = session.setdefault("anthropic", {})
    slot = (hashlib.sha256(api_key.encode()).hexdigest()[:16], wid)
    if slot not in pool:
        pool[slot] = await session["stack"].enter_async_context(make_client(api_key, wid))
    yield pool[slot]


_STATUS_CODES = {400: "provider_model_unavailable_or_invalid_request", 401: "provider_invalid_key", 403: "provider_model_access_denied",
                 404: "provider_model_unavailable_or_invalid_request", 422: "provider_model_unavailable_or_invalid_request",
                 429: "provider_rate_or_quota_error"}


def failure_from_sdk(exc, stage) -> HTTPException:
    """An SDK exception reduced to a code.  Nothing of its text is kept except a known protocol phrase's class."""
    if isinstance(exc, anthropic.APITimeoutError):
        return HTTPException(504, "provider_timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return HTTPException(502, "provider_network_error")
    if isinstance(exc, anthropic.APIStatusError):
        status = exc.status_code
        if 300 <= status < 400:
            return HTTPException(502, "provider_redirect_rejected")
        code = _STATUS_CODES.get(status, "provider_error")
        message = str(getattr(exc, "message", "") or "")
        if status == 400:
            if "anthropic-workspace-id" in message:
                code = "provider_workspace_required"
            elif "bound to a different conversation" in message:
                code = "provider_protocol_incompatible"
        request_id = getattr(exc, "request_id", None)
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", request_id):
            request_id = None
        return _p.ProviderFailure(code, stage=stage, provider_status=status, request_id=request_id,
                                  retryable=status in {429, 500, 502, 503, 504})
    return HTTPException(502, "provider_error")


def translate(exc, stage) -> HTTPException | None:
    """What an exception raised while sending or reading a response means, as FinBot's codes; None for anything else (a bug stays a bug).
    The SDK wraps a failure to send, but a timeout or disconnect while the body is being read comes through as httpx2's own error."""
    if isinstance(exc, (TimeoutError, httpx2.TimeoutException)):
        return HTTPException(504, "provider_timeout")
    if isinstance(exc, anthropic.AnthropicError):
        return failure_from_sdk(exc, stage)
    if isinstance(exc, httpx2.HTTPError):
        return HTTPException(502, "provider_network_error")
    if isinstance(exc, (ValueError, KeyError, IndexError, TypeError, AttributeError, RuntimeError, AssertionError)):
        return _p.ResponseCheckFailed("provider_incompatible_response", "sdk_event_shape")  # a stream the SDK could not assemble
    return None


async def _stream(api_key, model, messages, schemas, effort, stage):
    """Yield ('text', str) and ('thinking', str) as they arrive, then ('final', message).  Every event renews the progress clock."""
    async with client_for(api_key) as client:
        caps = await read_caps(client, model)
        params, betas = build_request(model, messages, schemas, effort=effort, caps=caps)
        manager = client.beta.messages.stream(betas=betas, **params) if betas else client.messages.stream(**params)
        seen = reasoning = 0
        async with manager as stream:
            async for event in stream:
                mark_progress()
                if event.type == "content_block_start" and event.content_block.type == "tool_use" and not schemas:
                    raise HTTPException(502, "provider_incomplete_stream")
                if event.type != "content_block_delta":
                    continue
                delta = event.delta
                if delta.type == "text_delta":
                    piece, kind = delta.text, "text"
                elif delta.type == "thinking_delta":
                    piece, kind = delta.thinking, "thinking"
                else:
                    piece, kind = getattr(delta, "partial_json", "") or "", None
                size = len(piece.encode())
                seen += size
                if seen > _p.MAX_RESPONSE_BYTES:
                    raise HTTPException(502, "provider_response_too_large")
                if kind == "thinking":
                    reasoning += size
                    if reasoning > _p.MAX_REASONING_BYTES:
                        raise HTTPException(502, "provider_protocol_too_large")
                if kind:
                    yield kind, piece
            final = await stream.get_final_message()
        yield "final", final


def _calls_cap():
    return (_p.TOOL_CALL_STREAM_GUARD, "tool_call_batch_too_large") if flag("FINBOT_SW1D_TOOLCALL_CAP", True) else (12, "provider_incompatible_response")


async def decision_request(model, api_key, messages, schemas, reasoning_effort=None):
    """Same contract as agent_chat_provider.decision_request: (data, message) in the OpenAI shape."""
    stage = "tool_decision" if schemas else "classification"
    cap, over = _calls_cap()
    effort = _p.sent_effort(reasoning_effort) if reasoning_effort else None
    try:
        async with progress_watchdog(_p.PROVIDER_REQUEST_SECONDS):
            final = None
            async for kind, value in _stream(api_key, model, messages, schemas, effort, stage):
                if kind == "final":
                    final = value
            if final is None:
                raise HTTPException(502, "provider_incomplete_stream")
            message, finish = message_from_final(final, stage=stage, calls_cap=cap, over_cap_code=over)
            mark_progress()
            return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage_to_openai(final.usage)}, message
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - reduced to a code below; anything unrecognised still propagates
        translated = translate(exc, stage)
        if translated is None:
            raise
        raise translated from None


async def stream_answer(model, api_key, messages, reasoning_collector=None):
    """Same contract as agent_chat_provider.stream_answer: yields the answer text; thinking summaries and usage go to the collector."""
    try:
        async with progress_watchdog(_p.PROVIDER_STREAM_SECONDS):
            final = None
            async for kind, value in _stream(api_key, model, messages, None, None, "final_answer"):
                if kind == "text":
                    yield value
                elif kind == "thinking" and reasoning_collector is not None:
                    if isinstance(reasoning_collector, dict):
                        reasoning_collector.setdefault("reasoning_content", []).append(value)
                    else:
                        reasoning_collector.append(value)
                elif kind == "final":
                    final = value
            if final is None:
                raise HTTPException(502, "provider_incomplete_stream")
            message_from_final(final, stage="final_answer", calls_cap=0, over_cap_code="provider_incomplete_stream", allow_tools=False)
            if isinstance(reasoning_collector, dict):
                reasoning_collector["_usage"] = usage_to_openai(final.usage)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        translated = translate(exc, "final_answer")
        if translated is None:
            raise
        raise translated from None
