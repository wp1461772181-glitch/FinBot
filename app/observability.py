"""Langfuse Cloud tracing, fully off unless configured.

Enabled only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are in the environment (LANGFUSE_HOST optional,
default https://cloud.langfuse.com) and the ``langfuse`` package imports.  Otherwise every function here returns
None after a dict lookup.  Nothing here raises into the caller: each SDK call is wrapped.

Handles are explicit objects (a trace handle, an observation handle) that the caller keeps on its own per-turn
object; there is no global "current trace", so nothing can cross turns.  Keys are read from the environment and
never put into trace content.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://cloud.langfuse.com"
_MAX_TEXT = 20000

_lock = threading.Lock()
_client: Any = None
_client_key: tuple | None = None
_import_failed = False


def _config() -> tuple[str, str, str] | None:
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public or not secret:
        return None
    return public, secret, os.environ.get("LANGFUSE_HOST", "").strip() or DEFAULT_HOST


def _get_client() -> Any:
    """The shared client, or None when unconfigured / the SDK is unavailable."""
    global _client, _client_key, _import_failed
    cfg = _config()
    if cfg is None or _import_failed:
        return None
    if _client is not None and _client_key == cfg:
        return _client
    with _lock:
        if _client is not None and _client_key == cfg:
            return _client
        try:
            from langfuse import Langfuse
            _client = Langfuse(public_key=cfg[0], secret_key=cfg[1], host=cfg[2])
            _client_key = cfg
        except ImportError:
            _import_failed = True
            _client = None
        except Exception:
            log.warning("langfuse client could not be created; tracing off")
            _client = None
        return _client


def enabled() -> bool:
    return _get_client() is not None


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "…"
    return value


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


class Handle:
    """A started observation (trace root, generation or span).  Opaque to callers."""

    __slots__ = ("obs", "started")

    def __init__(self, obs: Any):
        self.obs = obs
        self.started = time.monotonic()


def start_trace(name: str, *, metadata: dict | None = None, input: Any = None) -> Handle | None:
    client = _get_client()
    if client is None:
        return None
    try:
        obs = client.start_span(name=name, input=_clip(input), metadata=dict(metadata or {}))
        _safe(obs.update_trace, name=name, metadata=dict(metadata or {}))
        return Handle(obs)
    except Exception:
        return None


def start_turn(*, conversation_id: str, turn_id: str, bot_id: str | None, owner_hash: str, source: str,
               model_role: str | None, question: str = "") -> Handle | None:
    return start_trace("agent-turn", input=question, metadata={
        "conversation_id": conversation_id, "turn_id": turn_id, "bot_id": bot_id, "owner_hash": owner_hash,
        "source": source, "model_role": model_role})


def start_generation(parent: Handle | None, *, name: str, model: str | None, role: str | None = None,
                     input: Any = None, metadata: dict | None = None) -> Handle | None:
    if parent is None:
        return None
    try:
        obs = parent.obs.start_generation(name=name, model=model, input=_clip(input) if isinstance(input, str) else input,
                                          metadata={"role": role, **(metadata or {})})
        return Handle(obs)
    except Exception:
        return None


def start_span(parent: Handle | None, *, name: str, input: Any = None, metadata: dict | None = None) -> Handle | None:
    if parent is None:
        return None
    try:
        return Handle(parent.obs.start_span(name=name, input=input, metadata=dict(metadata or {})))
    except Exception:
        return None


def end_generation(handle: Handle | None, *, output: Any = None, usage: dict | None = None,
                   error: str | None = None) -> None:
    """Close a generation: output text, token usage when the provider returned it, latency, error status."""
    if handle is None:
        return
    try:
        update: dict[str, Any] = {"output": _clip(output), "metadata": {
            "latency_ms": int((time.monotonic() - handle.started) * 1000)}}
        if isinstance(usage, dict):
            details = {}
            for src, dst in (("prompt_tokens", "input"), ("completion_tokens", "output"), ("total_tokens", "total")):
                v = usage.get(src)
                if isinstance(v, int) and not isinstance(v, bool):
                    details[dst] = v
            if details:
                update["usage_details"] = details
        if error:
            update["level"] = "ERROR"
            update["status_message"] = error
        handle.obs.update(**update)
        handle.obs.end()
    except Exception:
        return None


def end_span(handle: Handle | None, *, output: Any = None, error: str | None = None,
             metadata: dict | None = None) -> None:
    if handle is None:
        return
    try:
        update: dict[str, Any] = {"output": output, "metadata": {
            "duration_ms": int((time.monotonic() - handle.started) * 1000), "success": error is None,
            **(metadata or {})}}
        if error:
            update["level"] = "ERROR"
            update["status_message"] = error
        handle.obs.update(**update)
        handle.obs.end()
    except Exception:
        return None


def score(trace: Handle | None, name: str, value: float | int | str, *, comment: str | None = None) -> None:
    if trace is None:
        return
    try:
        if isinstance(value, str):
            trace.obs.score_trace(name=name, value=value, data_type="CATEGORICAL", comment=comment)
        else:
            trace.obs.score_trace(name=name, value=float(value), data_type="NUMERIC", comment=comment)
    except Exception:
        return None


def end_trace(trace: Handle | None, *, output: Any = None, metadata: dict | None = None,
              error: str | None = None) -> None:
    if trace is None:
        return
    try:
        update: dict[str, Any] = {"output": _clip(output)}
        if metadata:
            update["metadata"] = metadata
        if error:
            update["level"] = "ERROR"
            update["status_message"] = error
        trace.obs.update(**update)
        trace.obs.end()
        client = _get_client()
        if client is not None:
            _safe(client.flush)
    except Exception:
        return None


def score_citation_audit(trace: Handle | None, *, verified: int, unverified: int,
                         unverified_lines: list | None = None, truncation_events: int | None = None,
                         insufficient: int | None = None, scope: dict | None = None) -> None:
    """The turn's own audit result as trace scores; no second audit pass.

    ``truncation_events`` is the number of machine-path cuts the turn recorded (audit.truncation_events);
    ``insufficient`` the lines left unchecked because their source was partial, apart from the unsupported ones.
    ``scope`` is audit.scope: what the number check looked at.  Its counts are scores; the values of the
    figures it left alone (``unmarked_exempted``) and of those no source holds (``unmarked_no_holder``) go in
    the comment, because those lists are the ones to read by hand."""
    if trace is None:
        return
    if isinstance(scope, dict) and isinstance(scope.get("counts"), dict):
        for name, count in scope["counts"].items():
            comment = None
            if name in {"unmarked_exempted", "unmarked_no_holder"} and count:
                items = scope.get(name) or []
                comment = " | ".join(f"{item.get('value')}: {item.get('line')}" for item in items[:10] if isinstance(item, dict))[:900]
            score(trace, "scope_" + name, int(count), comment=comment)
    score(trace, "citation_verified", int(verified))
    score(trace, "citation_unverified", int(unverified))
    if truncation_events is not None:
        score(trace, "truncation_events", int(truncation_events))
    if insufficient:
        score(trace, "citation_insufficient", int(insufficient))
    if unverified_lines:
        lines = [str(x.get("line") if isinstance(x, dict) else x)[:200] for x in unverified_lines[:5]]
        score(trace, "unverified_lines", len(unverified_lines), comment=" | ".join(lines))


def _reset_for_tests(client: Any = None) -> None:
    """Install a fake client (or clear state).  Test hook only."""
    global _client, _client_key, _import_failed
    _import_failed = False
    _client = client
    _client_key = _config() if client is not None else None
