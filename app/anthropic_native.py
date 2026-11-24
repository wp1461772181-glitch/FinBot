"""Anthropic's native Messages API for provider ``anthropic``.

FinBot keeps OpenAI-shaped messages internally (``role``/``content``/``tool_calls``/``tool``).  This module is the only
place that knows the Messages API: it converts a request out (pure functions), sends it with the official SDK, and
converts the streamed answer back to the shape ``agent_chat_provider`` returns for every other provider.

Why not the OpenAI-compatible endpoint: it ignores ``reasoning_effort``, has no prompt caching and is documented as
not for production.  Design: docs/superpowers/specs/2026-11-21-anthropic-native-provider-design.md; what was verified
against the official docs and what was decided: ...-implementation.md.

The SDK is imported lazily, so a box without it still imports this module, shows the catalogue, and (with
FINBOT_ANTHROPIC_NATIVE=off) still reaches Anthropic through the compatible endpoint.

Rules kept here:
* thinking is ``adaptive`` and effort goes in ``output_config.effort``; no temperature / top_p.
* history is sent without thinking blocks by default (``strip``): FinBot rebuilds its prompt every step, so a block would
  fail the API's prefix check anyway.  ``drop_block`` / ``off`` send them back and are options for a test.
* a key is never put in an exception, a log line, an audit stage or a repr: SDK errors are reduced to the codes below,
  and an empty key is refused here instead of letting the SDK fall back to the environment.
"""
from __future__ import annotations

import copy
import functools
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager, contextmanager

from fastapi import HTTPException

from . import agent_chat_provider as _p
from . import model_usage
from .agent_progress import mark_progress, progress_watchdog
from .agent_workflow.fp_flags import flag

log = logging.getLogger(__name__)

# The address is fixed: a user-typed Base URL is not accepted for this provider, so none of the SSRF pinning the
# custom endpoints need applies; the operator's MODEL_EGRESS_PROXY still does.
NATIVE_BASE_URL = "https://api.anthropic.com"
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
# What the three 5.5 models take, from the docs' model pages.  Used when the Models API cannot be read, and only for them.
STATIC_EFFORTS = ("low", "medium", "high", "xhigh", "max")
STATIC_MODEL_PREFIXES = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
CAPS_TTL_SECONDS = 6 * 3600
CAPS_RETRY_SECONDS = 300
BINDING_MODES = ("strip", "drop_block", "off")
_WORKSPACE_ID = re.compile(r"^wrkspc_[A-Za-z0-9]{8,64}$")
# Read by the SDK on its own, whatever is passed in: masked while a client is built / the SDK is imported.
_SDK_ENV_MASKED = ("ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_LOG")
# Only these fixed FinBot instructions (compared whole, never by prefix) are sent with system authority in the middle of a conversation.
# Every other message that comes after the first user turn - the understanding hint (carries the user's words), status and
# catalogue (tool errors, titles and previews of fetched documents), evidence, recalls, a nudge that quotes the model's draft -
# can contain text someone else wrote, so it goes in as user text.  An allowlist, not a list of what to exclude.
STRUCTURED_CALLS_NOTE = "Use native structured function calls. Never print tool protocol markup."   # direct.Turn.model's retry note
_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(message)


# --------------------------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------------------------
def native_enabled() -> bool:
    """FINBOT_ANTHROPIC_NATIVE (default on).  Off: provider ``anthropic`` goes through the compatible endpoint again."""
    return flag("FINBOT_ANTHROPIC_NATIVE", True)


def use_native(provider) -> bool:
    return provider == "anthropic" and native_enabled()


def workspace_id() -> str | None:
    """Optional ``anthropic-workspace-id``.  The docs require it for a key that is not scoped to one workspace (a personal
    or service-account key that spans workspaces) and forbid nothing for a scoped key.  Operator setting, not per entry."""
    value = (os.getenv("FINBOT_ANTHROPIC_WORKSPACE_ID") or "").strip()
    if value and not _WORKSPACE_ID.fullmatch(value):
        _warn_once("workspace", "FINBOT_ANTHROPIC_WORKSPACE_ID is set but is not a workspace id (wrkspc_...): ignored")
        return None
    return value or None


def binding_mode() -> str:
    """What to do with thinking blocks in the history.  FinBot rebuilds its prompt every step (a status counter, the evidence),
    so a block fails the API's prefix check, which on the 5.5 models is "possibly a 400".
    ``strip`` (default): send none; needs no beta and is the same to the model as a dropped block.
    ``drop_block``: send them with the beta control that makes a stale block dropped (unbilled) instead of an error.
    ``off``: send them with no control (a test of what the API does)."""
    value = (os.getenv("FINBOT_ANTHROPIC_THINKING_BINDING") or "strip").strip().lower()
    if value not in BINDING_MODES:
        _warn_once("binding", f"FINBOT_ANTHROPIC_THINKING_BINDING must be one of {', '.join(BINDING_MODES)}: using strip")
        return "strip"
    return value


def keeps_thinking() -> bool:
    return binding_mode() != "strip"


def _warn_sdk_environment() -> None:
    present = [name for name in (*_SDK_ENV_MASKED, "ANTHROPIC_OPEN_TELEMETRY", "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE") if os.environ.get(name)]
    if present:
        _warn_once("sdk-env", "ignored for provider anthropic (the SDK would read them): " + ", ".join(present))


@contextmanager
def _masked_env():
    saved = {name: os.environ.pop(name) for name in _SDK_ENV_MASKED if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _sdk():
    """The anthropic package, imported on first use.  Missing is a named failure of this provider, not an ImportError."""
    try:
        with _masked_env():
            import anthropic
    except ImportError:
        raise HTTPException(502, "provider_sdk_missing") from None
    return anthropic


# --------------------------------------------------------------------------------------------------------------------
# Models: what each can take
# --------------------------------------------------------------------------------------------------------------------
_CAPS: dict[str, tuple[float, dict | None]] = {}


def _leaf(node, *path):
    for key in path:
        node = node.get(key) if isinstance(node, dict) else getattr(node, key, None)
        if node is None:
            return None
    return node


def static_caps(model) -> dict:
    """What is known without asking: the three 5.5 models (and an unnamed one, for the catalogue's default view) take adaptive
    thinking and the five tiers; any other model is not assumed to take either."""
    if model is None or str(model).startswith(STATIC_MODEL_PREFIXES):
        return {"adaptive": True, "efforts": STATIC_EFFORTS}
    return {"adaptive": False, "efforts": ()}


def supports_system_role(model) -> bool:
    """A ``role: "system"`` message inside the conversation is accepted by the 5.5 models (no beta); not assumed for others."""
    return str(model or "").startswith(STATIC_MODEL_PREFIXES)


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


def _fresh(entry) -> bool:
    return entry is not None and time.monotonic() - entry[0] < (CAPS_TTL_SECONDS if entry[1] is not None else CAPS_RETRY_SECONDS)


def cached_caps(model) -> dict | None:
    entry = _CAPS.get(model)
    return entry[1] if _fresh(entry) else None


async def read_caps(client, model) -> dict | None:
    """Capabilities of one model, from the cache or one GET /v1/models/{id}.  Any failure gives None (the static table
    applies) and is not asked again for a few minutes; a read never fails or stalls a request."""
    entry = _CAPS.get(model)
    if _fresh(entry):
        return entry[1]
    try:
        caps = caps_from_model(await client.models.retrieve(model, timeout=15.0))
    except Exception:  # noqa: BLE001 - the catalogue and the request fall back to the static table
        caps = None
    _CAPS[model] = (time.monotonic(), caps)
    return caps


def efforts_for(model) -> tuple:
    """The tiers shown for an entry: the Models API's answer when it was read, else the static table."""
    caps = cached_caps(model)
    return caps["efforts"] if caps is not None else static_caps(model)["efforts"]


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


def _assistant_blocks(message, keep_thinking) -> list[dict]:
    """The content blocks of one assistant turn.  Blocks the API returned (kept in ``_anthropic_content`` when thinking is kept)
    are used as they are; they are rebuilt from content/tool_calls when missing or no longer describing the same calls."""
    calls = message.get("tool_calls") or []
    raw = message.get("_anthropic_content")
    if keep_thinking and isinstance(raw, list) and raw and all(isinstance(b, dict) and isinstance(b.get("type"), str) for b in raw):
        if [b.get("id") for b in raw if b.get("type") == "tool_use"] == [c.get("id") for c in calls]:
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


@functools.lru_cache(maxsize=1)
def trusted_notes() -> frozenset:
    """The whole-string instructions that may be sent as ``role: "system"`` mid-conversation (see STRUCTURED_CALLS_NOTE)."""
    from .agent_workflow import direct
    return frozenset({direct.CITATION_V2_NOTE, direct.CLOSING_RETRY_NOTE, STRUCTURED_CALLS_NOTE})


def is_trusted_note(text: str) -> bool:
    return text in trusted_notes()


def _no_result(call_id):
    return {"type": "tool_result", "tool_use_id": call_id, "content": "no result was recorded for this call", "is_error": True}


CACHE_POINT = "_cache_point"   # private marker on a converted block: a message with ``"cache_point": True`` ended here


def convert_messages(messages, *, keep_thinking=False, system_role=False) -> tuple[list[dict], list[dict]]:
    """OpenAI-shaped messages -> (``system`` blocks, Messages API ``messages``).

    * The system messages before the first conversation message become the top-level ``system``.
    * A system message that comes later is sent as ``role: "system"`` (the operator channel) only when it is one of FinBot's
      fixed instruction strings (``trusted_notes``), with ``system_role``, right after a user turn and followed by an
      assistant turn or nothing; consecutive ones are merged into one.  Anything else - and any of these where the API would
      not accept one - is a text block of the user turn: such messages can carry the user's words, tool output or document text.
    * ``tool_calls`` -> ``tool_use``; the ``tool`` messages that answer one assistant turn -> ``tool_result`` blocks of
      ONE user message, before any text.  A call nobody answered gets an error result; a result nobody asked for is dropped.
    * Thinking blocks are left out unless ``keep_thinking``.
    * A message with ``"cache_point": True`` leaves ``CACHE_POINT`` on the last block it contributed (``build_request`` uses and strips it).
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
            elif system_role and is_trusted_note(text) and out and out[-1]["role"] == "user":
                out[-1].setdefault("_system", []).append(text)
            else:
                _push_user(out, [{"type": "text", "text": text}])
            continue
        leading = False
        before = sum(len(m["content"]) for m in out)
        if role == "user":
            text = _text_of(message.get("content"))
            if text.strip():
                _push_user(out, [{"type": "text", "text": text}])
        elif role == "assistant":
            blocks = _assistant_blocks(message, keep_thinking)
            if not keep_thinking:
                blocks = [b for b in blocks if b.get("type") not in {"thinking", "redacted_thinking"}]
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
        if message.get("cache_point") is True and role != "system" and sum(len(m["content"]) for m in out) > before:
            out[-1]["content"][-1][CACHE_POINT] = True   # the last block this message contributed; build_request reads and removes it
    return system, _expand(_settle(out))


def _settle(out) -> list[dict]:
    """Make every tool_use answered exactly once, tool results first in their message, and the list start with a user turn."""
    settled, previous_ids = [], []
    for message in out:
        if message["role"] == "user":
            results = [b for b in message["content"] if b.get("type") == "tool_result"]
            others = [b for b in message["content"] if b.get("type") != "tool_result"]
            seen = {b["tool_use_id"] for b in results}
            kept = [b for b in results if b["tool_use_id"] in previous_ids]
            kept += [_no_result(i) for i in previous_ids if i not in seen]
            content = kept + others
            previous_ids = []
            notes = message.get("_system", [])
            if not content and notes:   # nothing left to follow: the notes become the turn's text
                content, notes = [{"type": "text", "text": "\n\n".join(notes)}], []
            if content:
                settled.append({"role": "user", "content": content, **({"_system": notes} if notes else {})})
            continue
        if previous_ids:  # an assistant turn that follows unanswered calls
            settled.append({"role": "user", "content": [_no_result(i) for i in previous_ids]})
        previous_ids = [b["id"] for b in message["content"] if b.get("type") == "tool_use"]
        settled.append(message)
    if previous_ids:
        settled.append({"role": "user", "content": [_no_result(i) for i in previous_ids]})
    if not settled or settled[0]["role"] != "user":
        settled.insert(0, {"role": "user", "content": [{"type": "text", "text": "(begin)"}]})
    return settled


def _expand(settled) -> list[dict]:
    """Turn each user turn's collected instruction notes into one ``role: "system"`` message right after it."""
    out = []
    for message in settled:
        notes = message.pop("_system", None)
        out.append(message)
        if notes:
            out.append({"role": "system", "content": "\n\n".join(notes)})
    return out


def has_thinking(messages) -> bool:
    return any(b.get("type") in {"thinking", "redacted_thinking"} for m in messages if m["role"] == "assistant" for b in m["content"])


def build_request(model, messages, schemas, *, effort=None, caps=None, keep_thinking=None, cache=False) -> tuple[dict, list[str]]:
    """The keyword arguments of one Messages API call and the beta headers it needs (usually none).  Pure.

    Caching: one explicit breakpoint on the last tool definition.  FinBot rewrites its system prompt and the tail of the
    conversation every step, so an automatic breakpoint on the last block would only ever write the cache (1.25x) and never
    read it; the tool list is the one stable prefix.

    ``keep_thinking`` None follows FINBOT_ANTHROPIC_THINKING_BINDING; True keeps the thinking blocks of the history under the
    drop_block control (unless the mode is ``off``); False strips them.  ``cache`` True adds a breakpoint on the last system block
    and on the last block of the last message, for a caller whose prompt only grows between calls; a message marked
    ``"cache_point": True`` also gets one on its own last block (the last such message only).  The key is never sent."""
    caps = caps if caps is not None else static_caps(model)
    keep = keeps_thinking() if keep_thinking is None else keep_thinking
    system, converted = convert_messages(messages, keep_thinking=keep, system_role=supports_system_role(model))
    params: dict = {"model": model, "max_tokens": _p.MAX_OUTPUT_TOKENS, "messages": converted}
    if system:
        params["system"] = system
    tools = convert_tools(schemas)
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
        params["tools"] = tools
        params["tool_choice"] = {"type": "auto"}
    betas: list[str] = []
    if caps["adaptive"]:
        params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if has_thinking(converted) and (binding_mode() == "drop_block" or (keep_thinking and binding_mode() != "off")):
            params["thinking"]["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
            betas.append(THINKING_BINDING_BETA)
    if effort in caps["efforts"]:
        params["output_config"] = {"effort": effort}
    marked = [b for m in converted if isinstance(m["content"], list) for b in m["content"] if b.get(CACHE_POINT)]
    for m in converted:
        if isinstance(m["content"], list):
            for b in m["content"]:
                b.pop(CACHE_POINT, None)
    if cache:
        if system:
            system[-1]["cache_control"] = {"type": "ephemeral"}
        if marked:   # the end of the history the next turn will carry; only the last mark counts (four breakpoints at most)
            marked[-1]["cache_control"] = {"type": "ephemeral"}
        tail = [m for m in converted if isinstance(m["content"], list) and m["content"]]
        if tail:
            tail[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return params, betas


def request_effort(effort) -> str | None:
    """The tier a call carries: a bot's own setting, else the environment default (AGENT_REASONING_EFFORT, low unless it says
    "default"), as for every other provider.  none and minimal do not exist on Claude: they mean the lightest tier, low."""
    value = _p.sent_effort(effort)
    return "low" if value in {"none", "minimal"} else value


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


def transformations_of(final) -> list[dict]:
    """The API's report of thinking blocks it dropped or let through (beta thinking-binding-controls), bounded; [] when absent."""
    items = getattr(final, "input_transformations", None)
    if not isinstance(items, list):
        return []
    return [{"type": str(getattr(t, "type", ""))[:40], "path": str(getattr(t, "path", ""))[:60], "reason": str(getattr(t, "reason", ""))[:60]} for t in items[:50]]


class ProviderRefusal(_p.ProviderFailure):
    """The model declined (stop_reason ``refusal``).  ``category`` is the API's stop_details.category (may be None)."""
    def __init__(self, *, stage, category=None, request_id=None):
        super().__init__("provider_refusal", stage=stage, request_id=request_id)
        self.category = category


def message_from_final(final, *, stage, calls_cap, over_cap_code, allow_tools=True, keep_thinking=None) -> tuple[dict, str]:
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
    if keeps_thinking() if keep_thinking is None else keep_thinking:
        message["_anthropic_content"] = blocks   # sent back with the next step (only in drop_block / off)
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
    return _sdk().DefaultAsyncHttpxClient(**options)


def make_client(api_key, wid=None):
    """Everything is explicit: the SDK would otherwise read credentials, the base URL, profile files, custom headers and
    tracing settings from the environment.  An empty key is refused rather than left to that fallback."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise _p.ProviderFailure("provider_invalid_key", stage="client")
    anthropic = _sdk()
    _warn_sdk_environment()
    headers = {"anthropic-workspace-id": wid} if wid else None
    with _masked_env():
        return anthropic.AsyncAnthropic(api_key=api_key, base_url=NATIVE_BASE_URL, max_retries=0,
                                        timeout=anthropic.Timeout(_p.PROVIDER_REQUEST_SECONDS, connect=15.0),
                                        default_headers=headers, open_telemetry={"traces": False}, http_client=_http_client())


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
    anthropic = _sdk()
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
    import httpx2
    anthropic = _sdk()
    if isinstance(exc, (TimeoutError, httpx2.TimeoutException)):
        return HTTPException(504, "provider_timeout")
    if isinstance(exc, anthropic.AnthropicError):
        return failure_from_sdk(exc, stage)
    if isinstance(exc, httpx2.HTTPError):
        return HTTPException(502, "provider_network_error")
    if isinstance(exc, (ValueError, KeyError, IndexError, TypeError, AttributeError, RuntimeError, AssertionError)):
        return _p.ResponseCheckFailed("provider_incompatible_response", "sdk_event_shape")  # a stream the SDK could not assemble
    return None


def _require_key(api_key, stage):
    if not isinstance(api_key, str) or not api_key.strip():
        raise _p.ProviderFailure("provider_invalid_key", stage=stage)


async def _stream(api_key, model, messages, schemas, effort, stage, keep_thinking=None, cache=False):
    """Yield ('text', str) and ('thinking', str) as they arrive, then ('final', message).  Every event renews the progress clock.
    Only sending and reading are translated into provider codes; building the request is FinBot's own code and its bugs propagate."""
    _require_key(api_key, stage)
    _sdk()
    async with client_for(api_key) as client:
        caps = await read_caps(client, model)
        params, betas = build_request(model, messages, schemas, effort=effort, caps=caps if caps is not None else static_caps(model),
                                      keep_thinking=keep_thinking, cache=cache)
        manager = client.beta.messages.stream(betas=betas, **params) if betas else client.messages.stream(**params)
        seen = reasoning = 0
        try:
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
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - reduced to a code; anything unrecognised still propagates
            translated = translate(exc, stage)
            if translated is None:
                raise
            raise translated from None
        yield "final", final


def _calls_cap():
    return (_p.TOOL_CALL_STREAM_GUARD, "tool_call_batch_too_large") if flag("FINBOT_SW1D_TOOLCALL_CAP", True) else (12, "provider_incompatible_response")


async def decision_request(model, api_key, messages, schemas, reasoning_effort=None):
    """Same contract as agent_chat_provider.decision_request: (data, message) in the OpenAI shape.
    ``data`` also carries ``input_transformations`` when the API reported any."""
    with model_usage.measure("anthropic", model) as call:      # the ledger's recording point for this transport
        return await _decision_request(call, model, api_key, messages, schemas, reasoning_effort)


async def _decision_request(call, model, api_key, messages, schemas, reasoning_effort):
    stage = "tool_decision" if schemas else "classification"
    cap, over = _calls_cap()
    try:
        async with progress_watchdog(_p.PROVIDER_REQUEST_SECONDS):
            final = None
            async for kind, value in _stream(api_key, model, messages, schemas, request_effort(reasoning_effort), stage):
                if kind == "final":
                    final = value
            if final is None:
                raise HTTPException(502, "provider_incomplete_stream")
            call.usage = usage_to_openai(final.usage)
            message, finish = message_from_final(final, stage=stage, calls_cap=cap, over_cap_code=over)
            mark_progress()
            data = {"choices": [{"message": message, "finish_reason": finish}], "usage": usage_to_openai(final.usage)}
            if transformed := transformations_of(final):
                data["input_transformations"] = transformed
            return data, message
    except TimeoutError as exc:
        raise HTTPException(504, "provider_timeout") from exc


async def stream_decision(model, api_key, messages, schemas, reasoning_effort=None, *, on_text=None, keep_thinking=True, cache=True):
    """decision_request that also awaits ``on_text(piece)`` for each piece of answer text as it arrives (thinking pieces are not
    passed on).  ``keep_thinking`` puts the raw blocks in ``message["_anthropic_content"]`` and keeps those of the history;
    ``cache`` marks the system prompt and the end of the conversation for the prompt cache."""
    with model_usage.measure("anthropic", model, streamed=on_text is not None) as call:
        return await _stream_decision(call, model, api_key, messages, schemas, reasoning_effort, on_text, keep_thinking, cache)


async def _stream_decision(call, model, api_key, messages, schemas, reasoning_effort, on_text, keep_thinking, cache):
    stage = "tool_decision" if schemas else "classification"
    cap, over = _calls_cap()
    try:
        async with progress_watchdog(_p.PROVIDER_REQUEST_SECONDS):
            final = None
            async for kind, value in _stream(api_key, model, messages, schemas, request_effort(reasoning_effort), stage,
                                             keep_thinking=keep_thinking, cache=cache):
                if kind == "text" and on_text is not None:
                    await on_text(value)
                elif kind == "final":
                    final = value
            if final is None:
                raise HTTPException(502, "provider_incomplete_stream")
            call.usage = usage_to_openai(final.usage)
            message, finish = message_from_final(final, stage=stage, calls_cap=cap, over_cap_code=over, keep_thinking=keep_thinking)
            mark_progress()
            data = {"choices": [{"message": message, "finish_reason": finish}], "usage": usage_to_openai(final.usage)}
            if transformed := transformations_of(final):
                data["input_transformations"] = transformed
            return data, message
    except TimeoutError as exc:
        raise HTTPException(504, "provider_timeout") from exc


async def stream_answer(model, api_key, messages, reasoning_collector=None):
    """Same contract as agent_chat_provider.stream_answer: yields the answer text; thinking summaries and usage go to the collector."""
    with model_usage.measure("anthropic", model, streamed=True) as call:
        async for piece in _stream_answer(call, model, api_key, messages, reasoning_collector):
            yield piece


async def _stream_answer(call, model, api_key, messages, reasoning_collector):
    try:
        async with progress_watchdog(_p.PROVIDER_STREAM_SECONDS):
            final = None
            async for kind, value in _stream(api_key, model, messages, None, request_effort(None), "final_answer"):
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
            call.usage = usage_to_openai(final.usage)
            message_from_final(final, stage="final_answer", calls_cap=0, over_cap_code="provider_incomplete_stream", allow_tools=False)
            if isinstance(reasoning_collector, dict):
                reasoning_collector["_usage"] = usage_to_openai(final.usage)
    except TimeoutError as exc:
        raise HTTPException(504, "provider_timeout") from exc
