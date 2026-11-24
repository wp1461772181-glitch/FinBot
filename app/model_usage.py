"""The model-call ledger: one row (``model_calls``) for every attempt of every call the app makes to a model.

Who calls is told by a tag, not by the caller's arguments: ``with purpose("summary", owner_hash=...):`` marks every call
made inside the block (contextvars, so it follows awaited work and ``asyncio.to_thread``).  The provider code (the
transports in ``agent_chat_provider``, ``anthropic_native``, ``event_provider``, ``model_providers`` and the direct callers)
records at the one place a call really leaves the process, through ``measure``.

Writing a row is best-effort: it never raises, never holds the call's result back (from async code the insert runs on a
worker thread), and a database failure is logged once.  Nothing but short codes and numbers is ever written: no key, URL,
header, prompt or answer text.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import math
import re
import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from .database import SessionLocal

logger = logging.getLogger(__name__)

PURPOSES = ("chat", "summary", "profile", "judge", "forecast", "earnings", "material_analysis", "news", "routine",
            "query_expansion", "localization", "knowledge", "other")

_TAGS: ContextVar[dict | None] = ContextVar("model_usage_tags", default=None)
_ATTEMPT: ContextVar[int] = ContextVar("model_usage_attempt", default=1)
_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_INT_MAX = 2_147_483_647


@contextmanager
def purpose(name, *, owner_hash=None, conversation_id=None, turn_id=None, bot_id=None, job=None, catalog_name=None):
    """Tag every model call made inside the block.  A nested block sets its own purpose and only the other fields it
    names; whatever it leaves out (the owner, the turn) stays as the outer block set it.  An unknown name is ``other``."""
    tags = dict(_TAGS.get() or {})
    tags["purpose"] = name if name in PURPOSES else "other"
    for key, value in (("owner_hash", owner_hash), ("conversation_id", conversation_id), ("turn_id", turn_id),
                       ("bot_id", bot_id), ("job", job), ("catalog_name", catalog_name)):
        if value is not None:
            tags[key] = value
    token = _TAGS.set(tags)
    try:
        yield
    finally:
        _TAGS.reset(token)


def tagged(name, **fields):
    """A decorator for a sync entry point: its model calls are tagged ``purpose(name, **fields)``."""
    def wrap(function):
        @functools.wraps(function)
        def inner(*args, **kwargs):
            with purpose(name, **fields):
                return function(*args, **kwargs)
        return inner
    return wrap


@contextmanager
def attempt(number):
    """The calls made inside the block are attempt ``number`` (1-based) of what they were for."""
    token = _ATTEMPT.set(max(1, int(number)))
    try:
        yield
    finally:
        _ATTEMPT.reset(token)


# --- usage -----------------------------------------------------------------------------------------------------

def _number(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return 0
    return min(int(value), _INT_MAX)


def _plain(usage) -> dict:
    if isinstance(usage, Mapping):
        return usage
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        try:
            dumped = dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:  # noqa: BLE001 - an odd usage object is a missing one
            return {}
    names = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens", "cache_read_input_tokens",
             "cache_creation_input_tokens", "cache_read_tokens", "cache_write_tokens", "prompt_tokens_details", "input_tokens_details")
    return {name: getattr(usage, name) for name in names if usage is not None and hasattr(usage, name)}


def parse_usage(usage) -> dict:
    """The four token counts of a provider's usage, in any shape the app handles.  ``input_tokens`` is the whole prompt (the
    cache's share included), as the app's own normal form (``anthropic_native.usage_to_openai``) and the kernel read it.
    Whatever the provider did not say is 0."""
    data = _plain(usage)
    details = next((data[key] for key in ("prompt_tokens_details", "input_tokens_details") if isinstance(data.get(key), Mapping)), {})
    read = (_number(data.get("cache_read_input_tokens")) or _number(data.get("cache_read_tokens"))
            or _number(details.get("cached_tokens")))
    write = _number(data.get("cache_creation_input_tokens")) or _number(data.get("cache_write_tokens"))
    if "prompt_tokens" in data:
        prompt = _number(data["prompt_tokens"])
    elif "input_tokens" in data:
        # Anthropic's own count leaves out what the cache served or wrote; the OpenAI-style one does not.
        own = "cache_read_input_tokens" in data or "cache_creation_input_tokens" in data
        prompt = _number(data["input_tokens"]) + (read + write if own else 0)
    else:
        prompt = 0
    output = _number(data.get("completion_tokens")) or _number(data.get("output_tokens"))
    if not prompt and not output:
        prompt = _number(data.get("total_tokens"))
    return {"input_tokens": min(prompt, _INT_MAX), "output_tokens": output, "cache_read_tokens": read, "cache_write_tokens": write}


def error_code(failure) -> str:
    """A short name for a failure: the code the provider code gave it, an HTTP status, or the exception's class name.
    Never the exception's text, which can carry a request's details."""
    detail = getattr(failure, "detail", None)
    if isinstance(detail, str) and _CODE.fullmatch(detail):
        return detail
    status = getattr(failure, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status < 600:
        return f"http_{status}"
    return type(failure).__name__[:64]


# --- writing ---------------------------------------------------------------------------------------------------

_EXECUTOR: ThreadPoolExecutor | None = None
_PENDING: set[Future] = set()
_LOCK = threading.Lock()
_failure_logged = False


def _uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _text(value, limit):
    return None if value is None else str(value)[:limit]


def _insert(values: dict) -> None:
    global _failure_logged
    try:
        from .agent_chat_models import ModelCall
        with SessionLocal() as db:
            db.add(ModelCall(**values))
            db.commit()
        _failure_logged = False
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a call
        if not _failure_logged:
            _failure_logged = True
            logger.warning("model call ledger: a row was not written (%s); further failures are not logged until one succeeds",
                           type(exc).__name__)


def _submit(values: dict) -> None:
    global _EXECUTOR
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        _insert(values)         # no event loop here: this thread may block on its own insert
        return
    with _LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="model-usage")
        future = _EXECUTOR.submit(_insert, values)
        _PENDING.add(future)
    future.add_done_callback(lambda done: _PENDING.discard(done))


def flush(timeout: float = 10.0) -> None:
    """Wait for rows still being written from async code (tests, shutdown)."""
    with _LOCK:
        waiting = list(_PENDING)
    if waiting:
        wait(waiting, timeout=timeout)


def record(*, provider, model, catalog_name=None, attempt=None, ok, error=None, ms, usage=None, streamed=False) -> None:
    """One ledger row for one attempt, tagged from the enclosing ``purpose``.  Never raises."""
    try:
        tags = _TAGS.get() or {}
        values = {
            "created_at": datetime.now(UTC),
            "owner_hash": _text(tags.get("owner_hash"), 64),
            "purpose": tags.get("purpose", "other"),
            "provider": _text(provider or "", 32),
            "model": _text(model or "", 160),
            "catalog_name": _text(catalog_name or tags.get("catalog_name"), 40),
            "conversation_id": _uuid(tags.get("conversation_id")) if tags.get("conversation_id") is not None else None,
            "turn_id": _uuid(tags.get("turn_id")) if tags.get("turn_id") is not None else None,
            "bot_id": _uuid(tags.get("bot_id")) if tags.get("bot_id") is not None else None,
            "job": _text(tags.get("job"), 64),
            "attempt": max(1, int(attempt if attempt is not None else _ATTEMPT.get())),
            "ok": bool(ok),
            "error": None if ok and not error else _text(error or "error", 64),
            "ms": _number(ms),
            "streamed": bool(streamed),
            **parse_usage(usage),
        }
        _submit(values)
    except Exception as exc:  # noqa: BLE001
        logger.debug("model call ledger: a row was not built (%s)", type(exc).__name__)


class _Call:
    """What a ``measure`` block hands back: set ``usage`` when the provider's reply carries it."""
    usage = None


@contextmanager
def measure(provider, model, *, streamed=False, catalog_name=None):
    """Time one attempt and record it when the block ends, as a failure (with its short code) when it raises.  The exception
    goes on unchanged; the block's ``call.usage`` is read at its end, so a failure after the usage arrived still counts it."""
    call = _Call()
    began = time.monotonic()
    try:
        yield call
    except BaseException as failure:
        record(provider=provider, model=model, catalog_name=catalog_name, ok=False, error=error_code(failure),
               ms=(time.monotonic() - began) * 1000, usage=call.usage, streamed=streamed)
        raise
    else:
        record(provider=provider, model=model, catalog_name=catalog_name, ok=True,
               ms=(time.monotonic() - began) * 1000, usage=call.usage, streamed=streamed)


# --- prices ----------------------------------------------------------------------------------------------------

def _price(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def price_of(entry) -> dict | None:
    """The prices (USD per million tokens) of a catalog entry, or None unless both the input and the output price are set."""
    if not isinstance(entry, Mapping):
        return None
    input_price, output_price = _price(entry.get("price_input")), _price(entry.get("price_output"))
    if input_price is None or output_price is None:
        return None
    return {"input": input_price, "output": output_price, "cache_read": _price(entry.get("price_cache_read")),
            "cache_write": _price(entry.get("price_cache_write")), "since": entry.get("price_since")}


def _moment(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _field(row, name):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def cost(row, prices) -> float | None:
    """USD for one ledger row, or None when its model has no price or the price was set after the call.  The cache's share of
    the prompt is priced at the cache prices; an unset cache price means the ordinary input price."""
    if not prices:
        return None
    since, made = _moment(prices.get("since")), _moment(_field(row, "created_at"))
    if since is not None and (made is None or made < since):
        return None
    prompt, output = _number(_field(row, "input_tokens")), _number(_field(row, "output_tokens"))
    read, write = _number(_field(row, "cache_read_tokens")), _number(_field(row, "cache_write_tokens"))
    plain = max(0, prompt - read - write)
    read_price = prices["input"] if prices.get("cache_read") is None else prices["cache_read"]
    write_price = prices["input"] if prices.get("cache_write") is None else prices["cache_write"]
    return (plain * prices["input"] + read * read_price + write * write_price + output * prices["output"]) / 1_000_000
