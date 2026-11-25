"""The model-call ledger: one row (``model_calls``) for every attempt of every call the app makes to a model.

Who calls is told by a tag, not by the caller's arguments: ``with purpose("summary", owner_hash=...):`` marks every call
made inside the block (contextvars, so it follows awaited work and ``asyncio.to_thread``).  The provider code (the
transports in ``agent_chat_provider``, ``anthropic_native``, ``event_provider``, ``model_providers`` and the direct callers)
records at the one place a call really leaves the process, through ``measure``.

Writing a row is best-effort and never touches the caller's thread or the app's connection pool: ``record`` puts the row on
a bounded queue and one worker thread writes it through a small engine of its own (pool of 1, 2 s connect timeout).  A full
queue drops the row (counted, logged at most once a minute); after a failed write the worker skips writes for 60 s and then
tries again (logged once per outage).  Nothing but short codes and numbers is ever written: no key, URL, header, prompt or
answer text.

``cost_usd`` is worked out once, when the row is written, from the catalog prices in effect at that moment; a later price edit
changes only later rows.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import math
import queue
import re
import threading
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from .config import DATABASE_URL

logger = logging.getLogger(__name__)

PURPOSES = ("chat", "summary", "profile", "judge", "forecast", "earnings", "material_analysis", "news", "routine", "duty",
            "query_expansion", "localization", "knowledge", "helper", "memory", "other")

_TAGS: ContextVar[dict | None] = ContextVar("model_usage_tags", default=None)
_ATTEMPT: ContextVar[int] = ContextVar("model_usage_attempt", default=1)
_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_INT_MAX = 2_147_483_647


@contextmanager
def purpose(name, *, owner_hash=None, conversation_id=None, turn_id=None, bot_id=None, job=None):
    """Tag every model call made inside the block.  A nested block sets its own purpose and only the other fields it
    names; whatever it leaves out (the owner, the turn) stays as the outer block set it.  An unknown name is ``other``.
    The tag says what the work is for, never which model: each transport records the catalog name of the model it calls."""
    tags = dict(_TAGS.get() or {})
    tags["purpose"] = name if name in PURPOSES else "other"
    for key, value in (("owner_hash", owner_hash), ("conversation_id", conversation_id), ("turn_id", turn_id),
                       ("bot_id", bot_id), ("job", job)):
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
    """The four token counts of a provider's usage, in any shape the box's providers send, as four numbers that add up without
    double counting: ``input_tokens`` is the input that was NOT served from or written to the cache, ``cache_read_tokens`` and
    ``cache_write_tokens`` are the cache's parts, ``output_tokens`` is the completion.  This differs from the kernel's
    ``token_usage`` (``_add_usage``), which adds the provider's ``total_tokens`` (the whole prompt, cache included, plus the
    completion): for one call, input + cache_read + cache_write + output equals that total.  Whatever the provider did not say is 0.

    Shapes: Anthropic (``input_tokens`` already excludes the cache; ``cache_read_input_tokens``, ``cache_creation_input_tokens``);
    OpenAI, OpenRouter and Zhipu (``prompt_tokens`` is the whole prompt; ``prompt_tokens_details.cached_tokens``, and OpenRouter's
    ``cache_write_tokens`` there); DeepSeek and SiliconFlow (``prompt_cache_hit_tokens``, ``prompt_cache_miss_tokens``); the app's
    own normal form (``anthropic_native.usage_to_openai``: whole ``prompt_tokens`` plus the two Anthropic cache fields)."""
    data = _plain(usage)
    details = next((data[key] for key in ("prompt_tokens_details", "input_tokens_details") if isinstance(data.get(key), Mapping)), {})
    read = (_number(data.get("cache_read_input_tokens")) or _number(data.get("cache_read_tokens"))
            or _number(data.get("prompt_cache_hit_tokens")) or _number(details.get("cached_tokens")))
    write = (_number(data.get("cache_creation_input_tokens")) or _number(data.get("cache_write_tokens"))
             or _number(details.get("cache_write_tokens")))
    anthropic_own = "cache_read_input_tokens" in data or "cache_creation_input_tokens" in data
    if "prompt_tokens" in data:
        plain = max(0, _number(data["prompt_tokens"]) - read - write)
    elif "prompt_cache_miss_tokens" in data:
        plain = _number(data["prompt_cache_miss_tokens"])
    elif "input_tokens" in data:
        plain = _number(data["input_tokens"]) if anthropic_own else max(0, _number(data["input_tokens"]) - read - write)
    else:
        plain = 0
    output = _number(data.get("completion_tokens")) or _number(data.get("output_tokens"))
    if not plain and not output and not read and not write:
        plain = _number(data.get("total_tokens"))
    return {"input_tokens": min(plain, _INT_MAX), "output_tokens": output, "cache_read_tokens": read, "cache_write_tokens": write}


def error_code(failure) -> str:
    """A short name for a failure: the code the provider code gave it, an HTTP status, or the exception's class name.
    Never the exception's text, which can carry a request's details."""
    if isinstance(failure, asyncio.CancelledError):
        return "cancelled"
    if isinstance(failure, GeneratorExit):
        return "closed"
    detail = getattr(failure, "detail", None)
    if isinstance(detail, str) and _CODE.fullmatch(detail):
        return detail
    status = getattr(failure, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status < 600:
        return f"http_{status}"
    return type(failure).__name__[:64]


# --- writing ---------------------------------------------------------------------------------------------------

MAX_PENDING = 1000          # rows waiting for the worker; past this a row is dropped, never waited for
SKIP_SECONDS = 60           # after a failed write, no write is tried for this long
_MAX_PENDING = MAX_PENDING
_QUEUE: queue.Queue = queue.Queue()
_LOCK = threading.Lock()
_worker: threading.Thread | None = None
_engine = None
_skip_until = 0.0
_outage_logged = False
_dropped = 0
_drop_logged_at = -1e9


def _make_session():
    """A session on the ledger's own engine: one connection, a short connect timeout, never the app's pool."""
    global _engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    with _LOCK:
        if _engine is None:
            _engine = create_engine(DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=2, pool_pre_ping=True,
                                    connect_args={"connect_timeout": 2, "options": "-c statement_timeout=5000"})
    return Session(_engine, expire_on_commit=False)


def _uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _text(value, limit):
    return None if value is None else str(value)[:limit]


_PRICE_CACHE: dict = {}
_PRICE_TTL = 10.0


def forget_prices() -> None:
    """The catalog's prices changed: the next row reads them again."""
    _PRICE_CACHE.clear()


def _prices_at_write(db, name):
    """The prices of catalog entry ``name`` now (a config-file entry, else the catalog table), or None.  Read on the worker."""
    if not name:
        return None
    hit = _PRICE_CACHE.get(name)
    if hit and time.monotonic() - hit[0] < _PRICE_TTL:
        return hit[1]
    from . import agent_model_catalog as catalog
    from .agent_chat_models import AgentModelEntry
    entry = next((item for item in catalog._read_file()[0] if item["name"] == name), None)
    if entry is None:
        row = db.get(AgentModelEntry, name)
        entry = {key: getattr(row, key) for key in catalog.PRICE_KEYS} if row is not None else {}
    prices = price_of(entry)
    _PRICE_CACHE[name] = (time.monotonic(), prices)
    return prices


def _write(values: dict) -> None:
    global _skip_until, _outage_logged
    if time.monotonic() < _skip_until:
        _count_drop()
        return
    try:
        from .agent_chat_models import ModelCall
        with _make_session() as db:
            try:
                values["cost_usd"] = cost(values, _prices_at_write(db, values.get("catalog_name")))
            except Exception:  # noqa: BLE001 - an unreadable price is an unpriced row, not a lost one
                db.rollback()
                values["cost_usd"] = None
            db.add(ModelCall(**values))
            db.commit()
        _outage_logged = False
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a call
        _skip_until = time.monotonic() + SKIP_SECONDS
        if not _outage_logged:
            _outage_logged = True
            logger.warning("model call ledger: a row was not written (%s); writes pause for %s s", type(exc).__name__, SKIP_SECONDS)


def _count_drop() -> None:
    global _dropped, _drop_logged_at
    _dropped += 1
    if time.monotonic() - _drop_logged_at >= 60:
        _drop_logged_at = time.monotonic()
        logger.warning("model call ledger: rows are being dropped (%s so far)", _dropped)


def _run_worker() -> None:
    while True:
        values = _QUEUE.get()
        try:
            _write(values)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _QUEUE.task_done()


def _submit(values: dict) -> None:
    """Hand a row to the one worker.  Never waits: a full queue drops the row."""
    global _worker
    if _QUEUE.qsize() >= _MAX_PENDING:
        _count_drop()
        return
    with _LOCK:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="model-usage", daemon=True)
            _worker.start()
    _QUEUE.put(values)


def dropped_rows() -> int:
    """How many rows were dropped (queue full, or inside a pause after a failed write) since the process started."""
    return _dropped


def flush(timeout: float = 10.0) -> None:
    """Wait for the rows queued so far to be written or dropped (tests, shutdown)."""
    end = time.monotonic() + timeout
    while _QUEUE.unfinished_tasks and time.monotonic() < end:
        time.sleep(0.005)


def record(*, provider, model, catalog_name=None, attempt=None, ok, error=None, ms, usage=None, streamed=False) -> None:
    """One ledger row for one attempt, tagged from the enclosing ``purpose``.  ``catalog_name`` is the catalog entry of the
    model actually called (None: not a catalog entry).  Never raises, never waits."""
    try:
        tags = _TAGS.get() or {}
        values = {
            "created_at": datetime.now(UTC),
            "owner_hash": _text(tags.get("owner_hash"), 64),
            "purpose": tags.get("purpose", "other"),
            "provider": _text(provider or "", 32),
            "model": _text(model or "", 160),
            "catalog_name": _text(catalog_name, 40),
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
            "cache_write": _price(entry.get("price_cache_write"))}


def _field(row, name):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def cost(row, prices) -> float | None:
    """USD for one call: uncached input x input price + output x output price + cache-read tokens x cache-read price + cache-write
    tokens x cache-write price.  None when the model has no input and output price, or when the call has cache tokens and that
    cache price is not set (the input price is never borrowed for it)."""
    if not prices:
        return None
    plain, output = _number(_field(row, "input_tokens")), _number(_field(row, "output_tokens"))
    read, write = _number(_field(row, "cache_read_tokens")), _number(_field(row, "cache_write_tokens"))
    if (read and prices.get("cache_read") is None) or (write and prices.get("cache_write") is None):
        return None
    total = plain * prices["input"] + output * prices["output"]
    total += read * (prices.get("cache_read") or 0.0) + write * (prices.get("cache_write") or 0.0)
    return total / 1_000_000


def missing_price(row, entry) -> str | None:
    """Which price of catalog ``entry`` (a dict with the ``price_*`` keys; None for a call with no catalog entry) keeps ``row``
    unpriced: ``input``, ``output``, ``cache_read`` or ``cache_write``; None when the call is priced."""
    entry = entry if isinstance(entry, Mapping) else {}
    if _price(entry.get("price_input")) is None:
        return "input"
    if _price(entry.get("price_output")) is None:
        return "output"
    if _number(_field(row, "cache_read_tokens")) and _price(entry.get("price_cache_read")) is None:
        return "cache_read"
    if _number(_field(row, "cache_write_tokens")) and _price(entry.get("price_cache_write")) is None:
        return "cache_write"
    return None
