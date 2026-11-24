"""The model-call ledger: every call the app makes to a model is one row, tagged with what it was for.

Real PostgreSQL (the test database).  The provider transport is faked at the HTTP layer, so the real recording
point, retry code and kernel loop run.
"""
import asyncio
import copy
import json
import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

import app.agent_chat_provider as provider
from app import agent_model_catalog as catalog
from app import model_usage
from app.agent_chat_models import AgentBot, AgentModelEntry, AgentModelRole, ModelCall
from app.agent_workflow import tools
from app.database import Base, SessionLocal, engine
from app.kernel import act, loop, prompt

SECRET = "sk-SECRET-KEY-0123456789abcdef"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
         "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10}


@pytest.fixture(autouse=True)
def table():
    ModelCall.__table__.create(engine, checkfirst=True)
    model_usage.flush(timeout=10)
    model_usage._skip_until = 0.0              # a pause after an earlier test's failed write must not leak into this one
    model_usage._outage_logged = False
    yield
    model_usage.flush(timeout=10)


def rows(**where):
    model_usage.flush()
    with SessionLocal() as db:
        query = select(ModelCall).order_by(ModelCall.created_at, ModelCall.id)
        for key, value in where.items():
            query = query.where(getattr(ModelCall, key) == value)
        return list(db.scalars(query))


def unique():
    return uuid.uuid4().hex


# --- usage shapes ---------------------------------------------------------------------------------------------

class Attr:
    """An SDK usage object: attributes, no dict."""
    prompt_tokens, completion_tokens = 7, 3


@pytest.mark.parametrize("usage, expected", [
    ({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, (100, 20, 0, 0)),
    # OpenAI / Zhipu: the prompt is whole, the cached part is inside it; the ledger keeps the uncached input.
    ({"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}}, (60, 20, 40, 0)),
    ({"prompt_tokens": 50, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 10}}, (40, 5, 10, 0)),
    # OpenRouter also reports what was written to the cache.
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 10}}, (70, 2, 20, 10)),
    # DeepSeek / SiliconFlow: hit and miss counts at the top level.
    ({"prompt_tokens": 100, "completion_tokens": 5, "prompt_cache_hit_tokens": 70, "prompt_cache_miss_tokens": 30}, (30, 5, 70, 0)),
    ({"completion_tokens": 5, "prompt_cache_hit_tokens": 70, "prompt_cache_miss_tokens": 30}, (30, 5, 70, 0)),
    # Anthropic's own: input_tokens already leaves out what the cache served or wrote.
    ({"input_tokens": 50, "output_tokens": 9, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10}, (50, 9, 30, 10)),
    ({"input_tokens": 50, "output_tokens": 9}, (50, 9, 0, 0)),
    # The shape the app normalises to (anthropic_native.usage_to_openai) and the kernel reads: whole prompt plus the two cache fields.
    (USAGE, (60, 20, 30, 10)),
    ({"total_tokens": 80}, (80, 0, 0, 0)),
    ({}, (0, 0, 0, 0)),
    (None, (0, 0, 0, 0)),
    ("not usage", (0, 0, 0, 0)),
    ({"prompt_tokens": None, "completion_tokens": "x", "total_tokens": -5}, (0, 0, 0, 0)),
    (Attr(), (7, 3, 0, 0)),
])
def test_usage_in_every_shape_the_app_handles(usage, expected):
    got = model_usage.parse_usage(usage)
    assert (got["input_tokens"], got["output_tokens"], got["cache_read_tokens"], got["cache_write_tokens"]) == expected


# --- purposes --------------------------------------------------------------------------------------------------

def test_a_call_outside_any_purpose_is_other():
    marker = f"m-{unique()}"
    model_usage.record(provider="p", model=marker, ok=True, ms=5)
    (row,) = rows(model=marker)
    assert row.purpose == "other" and row.owner_hash is None and row.turn_id is None and row.attempt == 1
    assert row.streamed is False and row.input_tokens == 0 and row.error is None


def test_nested_purposes_override_only_the_fields_they_set():
    marker, owner, turn = f"m-{unique()}", unique(), str(uuid.uuid4())
    with model_usage.purpose("chat", owner_hash=owner, turn_id=turn, job="outer"):
        with model_usage.purpose("query_expansion"):
            model_usage.record(provider="p", model=marker, ok=True, ms=1)
        with model_usage.purpose("summary", job="inner"):
            model_usage.record(provider="p", model=marker, ok=True, ms=1)
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
    inner, summary, outer = rows(model=marker)
    assert (inner.purpose, inner.owner_hash, str(inner.turn_id), inner.job) == ("query_expansion", owner, turn, "outer")
    assert (summary.purpose, summary.owner_hash, summary.job) == ("summary", owner, "inner")
    assert (outer.purpose, outer.job) == ("chat", "outer")
    model_usage.record(provider="p", model=marker, ok=True, ms=1)
    assert rows(model=marker)[-1].purpose == "other"       # the tag ends with its block


def test_an_unknown_purpose_name_is_other_and_the_names_are_the_agreed_ones():
    assert model_usage.PURPOSES == ("chat", "summary", "profile", "judge", "forecast", "earnings", "material_analysis",
                                    "news", "routine", "query_expansion", "localization", "knowledge", "other")
    marker = f"m-{unique()}"
    with model_usage.purpose("nonsense"):
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
    assert rows(model=marker)[0].purpose == "other"


def test_the_purpose_follows_awaited_work_and_threads_that_copy_the_context():
    marker = f"m-{unique()}"

    async def work():
        await asyncio.to_thread(model_usage.record, provider="p", model=marker, ok=True, ms=1)
        model_usage.record(provider="p", model=marker, ok=True, ms=1)     # from the event loop: written off it

    async def main():
        with model_usage.purpose("forecast", job="j1"):
            await work()

    asyncio.run(main())
    assert [(r.purpose, r.job) for r in rows(model=marker)] == [("forecast", "j1")] * 2


def test_over_long_fields_are_cut_to_the_column():
    marker = f"m-{unique()}"
    with model_usage.purpose("routine", job="j" * 200):
        model_usage.record(provider="p", model=marker, ok=False, error="E" * 200, ms=1)
    (row,) = rows(model=marker)
    assert len(row.job) == 64 and len(row.error) == 64


# --- recording never breaks a call -------------------------------------------------------------------------------

def test_a_database_failure_is_swallowed_and_logged_once(monkeypatch, caplog):
    class Broken:
        def __enter__(self):
            raise RuntimeError(f"connection lost {SECRET}")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(model_usage, "_make_session", lambda: Broken())
    monkeypatch.setattr(model_usage, "_skip_until", 0.0)
    monkeypatch.setattr(model_usage, "_outage_logged", False)
    with caplog.at_level(logging.WARNING, logger="app.model_usage"):
        model_usage.record(provider="p", model="m", ok=True, ms=1)
        model_usage.flush()
        model_usage.record(provider="p", model="m", ok=True, ms=1)      # inside the 60 s pause: dropped, not tried
        model_usage.flush()
    assert len([r for r in caplog.records if "not written" in r.getMessage()]) == 1
    assert SECRET not in caplog.text
    assert model_usage.dropped_rows() >= 1


def test_after_the_pause_the_next_write_is_tried_again_and_a_new_outage_logs_again(monkeypatch, caplog):
    calls = []

    class Broken:
        def __enter__(self):
            calls.append(1)
            raise RuntimeError("down")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(model_usage, "_make_session", lambda: Broken())
    monkeypatch.setattr(model_usage, "_skip_until", 0.0)
    monkeypatch.setattr(model_usage, "_outage_logged", False)
    with caplog.at_level(logging.WARNING, logger="app.model_usage"):
        model_usage.record(provider="p", model="m", ok=True, ms=1)
        model_usage.flush()
        monkeypatch.setattr(model_usage, "_skip_until", 0.0)            # the 60 s are over
        model_usage.record(provider="p", model="m", ok=True, ms=1)
        model_usage.flush()
    assert len(calls) == 2
    assert len([r for r in caplog.records if "not written" in r.getMessage()]) == 1     # still the same outage: logged once


def test_a_call_returns_at_the_same_speed_with_the_database_down_and_with_the_queue_full(monkeypatch):
    import time

    def slow_and_broken():
        time.sleep(3)
        raise RuntimeError("down")

    def timed():
        fake_transport(monkeypatch, [respond(answer_body("好"))])
        began = time.monotonic()
        _, message = asyncio.run(provider.decision_request("siliconflow", "m", SECRET, [{"role": "user", "content": "q"}], []))
        assert message["content"] == "好"
        return time.monotonic() - began

    monkeypatch.setattr(model_usage, "_skip_until", 0.0)
    monkeypatch.setattr(model_usage, "_make_session", slow_and_broken)
    down = timed()
    assert down < 1.0                                                  # not the 3 s of the broken insert, nor a pool wait
    monkeypatch.setattr(model_usage, "_MAX_PENDING", 0)                # the queue counts as full
    before = model_usage.dropped_rows()
    full = timed()
    assert full < 1.0 and model_usage.dropped_rows() == before + 1
    monkeypatch.undo()
    model_usage.flush(timeout=10)             # the slow insert of the first call finishes inside the pause it starts


def test_record_itself_never_raises_on_bad_input():
    model_usage.record(provider=None, model=None, ok=True, ms="soon", usage=object())
    model_usage.flush()


def test_measure_records_the_call_and_lets_the_failure_through():
    marker = f"m-{unique()}"
    with model_usage.measure("p", marker) as call:
        call.usage = USAGE
    with pytest.raises(ValueError):
        with model_usage.measure("p", marker, streamed=True):
            raise ValueError(f"boom {SECRET}")
    good, bad = rows(model=marker)
    assert good.ok and good.error is None and good.input_tokens == 60 and good.cache_write_tokens == 10
    assert not bad.ok and bad.error == "ValueError" and bad.streamed is True


def test_error_codes_are_short_names_never_text():
    err = model_usage.error_code
    assert err(provider.ProviderFailure("provider_rate_or_quota_error", stage="x", provider_status=429)) == "provider_rate_or_quota_error"
    assert err(asyncio.CancelledError()) == "cancelled"
    assert err(RuntimeError(f"url with {SECRET}")) == "RuntimeError"
    assert err(type("APIStatusError", (Exception,), {"status_code": 503})(f"{SECRET}")) == "http_503"
    assert len(err(type("N" * 100, (Exception,), {})())) == 64


# --- through the real transport ----------------------------------------------------------------------------------

def sse(*events):
    return b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events) + b"data: [DONE]\n\n"


def answer_body(text, usage=USAGE):
    return sse({"choices": [{"delta": {"content": text}, "finish_reason": None}]},
               {"choices": [{"delta": {}, "finish_reason": "stop"}]}, {"choices": [], "usage": usage})


def tool_body(call_id, name, arguments, usage=USAGE):
    call = {"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
    return sse({"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": None}]},
               {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}, {"choices": [], "usage": usage})


def respond(body, status=200):
    headers = {"content-type": "text/event-stream"} if status == 200 else {"x-request-id": "req-1"}
    return httpx.Response(status, headers=headers, content=body)


def fake_transport(monkeypatch, replies):
    """The provider's HTTP client, answering from ``replies`` in order; returns the requests it saw."""
    seen = []

    def handler(request):
        seen.append(request)
        return replies.pop(0)

    @asynccontextmanager
    async def client(base_url):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield http

    monkeypatch.setattr(provider, "_decision_client", client)
    return seen


def test_a_plain_decision_is_one_row_with_its_tokens_and_no_key(monkeypatch):
    marker, owner = f"m-{unique()}", unique()
    fake_transport(monkeypatch, [respond(answer_body("好"))])
    with model_usage.purpose("summary", owner_hash=owner):
        data, message = asyncio.run(provider.decision_request("siliconflow", marker, SECRET, [{"role": "user", "content": "q"}], []))
    assert message["content"] == "好"
    (row,) = rows(owner_hash=owner)
    assert (row.purpose, row.provider, row.model, row.ok, row.attempt) == ("summary", "siliconflow", marker, True, 1)
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_write_tokens) == (60, 20, 30, 10)
    assert row.ms >= 0 and row.created_at.tzinfo is not None and row.streamed is False


def test_a_failed_call_is_a_row_with_a_short_code_and_the_caller_sees_the_same_error(monkeypatch):
    owner = unique()
    fake_transport(monkeypatch, [respond(b"", 429)])
    with model_usage.purpose("profile", owner_hash=owner):
        with pytest.raises(provider.ProviderFailure) as caught:
            asyncio.run(provider.decision_request("siliconflow", "m", SECRET, [{"role": "user", "content": "q"}], []))
    assert caught.value.detail == "provider_rate_or_quota_error"
    (row,) = rows(owner_hash=owner)
    assert row.ok is False and row.error == "provider_rate_or_quota_error" and row.input_tokens == 0


def test_no_column_of_any_row_holds_the_key_or_a_url(monkeypatch):
    owner = unique()
    fake_transport(monkeypatch, [respond(answer_body("好")), respond(b"", 401)])
    with model_usage.purpose("judge", owner_hash=owner):
        asyncio.run(provider.decision_request("custom", "m", SECRET, [{"role": "user", "content": "q"}], [], "https://example.test/v1"))
        with pytest.raises(provider.ProviderFailure):
            asyncio.run(provider.decision_request("custom", "m", SECRET, [{"role": "user", "content": "q"}], [], "https://example.test/v1"))
    found = rows(owner_hash=owner)
    assert len(found) == 2
    for row in found:
        for column in ModelCall.__table__.columns:
            value = str(getattr(row, column.name))
            assert SECRET not in value and "example.test" not in value and "Bearer" not in value
        assert row.error is None or len(row.error) <= 64


@pytest.fixture
def kernel(monkeypatch):
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(prompt, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(act, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(loop, "RETRY_WAIT_SECONDS", 0)

    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        return {"ok": True, "data": [{"id": "r1", "symbol": "AAPL", "source_type": "official_filing",
                                      "excerpt": "Revenue was 100 (USD billions)."}], "source": "saved"}

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    return monkeypatch


def run_kernel(owner, turn, marker="m"):
    context = SimpleNamespace(provider="siliconflow", model=marker, api_key=SECRET, base_url=None, reasoning_effort=None,
                              tool_scope=None, bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash=owner)
    events = []

    async def emit(event):
        events.append(event)

    async def main():
        with model_usage.purpose("chat", owner_hash=owner, turn_id=turn):
            return await loop.run_turn("问题", context, emit, [{"role": "system", "content": "s"}, {"role": "user", "content": "问题"}], {})

    return asyncio.run(main())


def test_a_provider_that_fails_once_then_answers_is_two_rows_one_per_attempt(kernel):
    owner, turn = unique(), str(uuid.uuid4())
    fake_transport(kernel, [respond(b"", 503), respond(answer_body("好"))])
    result = run_kernel(owner, turn)
    assert result["answer"] == "好" and result["status"] == "succeeded"
    first, second = rows(owner_hash=owner)
    assert (first.attempt, first.ok, first.error) == (1, False, "provider_error")
    assert (second.attempt, second.ok, second.error) == (2, True, None)
    assert first.purpose == second.purpose == "chat" and str(first.turn_id) == str(second.turn_id) == turn
    assert first.input_tokens == 0 and second.input_tokens == 60


def test_a_kernel_turn_with_two_model_calls_is_two_chat_rows_that_agree_with_the_kernel(kernel):
    owner, turn = unique(), str(uuid.uuid4())
    fake_transport(kernel, [respond(tool_body("c1", "query_financials", {"symbol": "AAPL"})), respond(answer_body("收入 100 [1]"))])
    result = run_kernel(owner, turn)
    assert result["audit"]["model_calls"] == 2
    found = rows(owner_hash=owner)
    assert [r.purpose for r in found] == ["chat", "chat"] and {str(r.turn_id) for r in found} == {turn}
    assert [r.attempt for r in found] == [1, 1]
    for row, line in zip(found, result["audit"]["calls"]):
        # The kernel's total counts the whole prompt, the ledger's input leaves the cache out: the four columns add up to it.
        assert row.input_tokens + row.cache_read_tokens + row.cache_write_tokens + row.output_tokens == line["tokens"]
        assert (row.cache_read_tokens, row.cache_write_tokens) == (line["cache_read"], line["cache_write"])
    assert sum(r.input_tokens + r.cache_read_tokens + r.cache_write_tokens + r.output_tokens for r in found) == result["audit"]["token_usage"]
    assert sum(r.cache_read_tokens for r in found) == result["audit"]["cache_read_tokens"]


def test_the_backup_model_is_recorded_under_its_own_catalog_name(kernel):
    owner, turn = unique(), str(uuid.uuid4())
    kernel.setattr(loop.roles, "fallback_for", lambda owner_hash: {"name": "backup-model", "provider": "siliconflow", "model": "m2",
                                                                    "api_key": SECRET, "base_url": None})
    fake_transport(kernel, [respond(b"", 401), respond(answer_body("备用回答"))])
    context = SimpleNamespace(provider="siliconflow", model="m1", api_key=SECRET, base_url=None, reasoning_effort=None, tool_scope=None,
                              bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash=owner, catalog_name="primary-model")

    async def emit(event):
        pass

    async def main():
        with model_usage.purpose("chat", owner_hash=owner, turn_id=turn):
            return await loop.run_turn("问题", context, emit, [{"role": "system", "content": "s"}, {"role": "user", "content": "问题"}], {})

    asyncio.run(main())
    failed, answered = rows(owner_hash=owner)
    assert (failed.model, failed.catalog_name, failed.ok) == ("m1", "primary-model", False)
    assert (answered.model, answered.catalog_name, answered.ok) == ("m2", "backup-model", True)


# --- background entry points -------------------------------------------------------------------------------------

def test_the_summariser_rows_are_tagged_summary(monkeypatch):
    from app import agent_context as layers
    from app import agent_context_summary as summary
    from app import agent_chat_store
    fake_transport(monkeypatch, [respond(answer_body(json.dumps({"summary": "用户连续询问苹果 AAPL 的营收。"}, ensure_ascii=False)))])
    overflow = [layers.Turn(1, 2, "第一个问题：苹果 AAPL 的营收" + "问" * 3000, "答" * 3000)]

    async def context(*_a, **_k):
        return {"overflow": overflow, "segments": []}

    async def append(*_a, **_k):
        return True

    monkeypatch.setattr(agent_chat_store, "conversation_context", context)
    monkeypatch.setattr(agent_chat_store, "append_summary", append)
    monkeypatch.setattr(summary, "MIN_PENDING_BYTES", 1)
    conversation = str(uuid.uuid4())
    with model_usage.purpose("chat", turn_id=str(uuid.uuid4())):
        assert asyncio.run(summary.summarize_pending(conversation, "credential", provider="siliconflow", model="m", api_key=SECRET, base_url=None))
    (row,) = rows(conversation_id=uuid.UUID(conversation))
    assert row.purpose == "summary" and row.input_tokens == 60 and row.turn_id is not None
    assert row.owner_hash == agent_chat_store.owner_hash("credential")


def test_the_forecast_processor_rows_are_tagged_forecast_with_the_job(monkeypatch):
    from app.agent_forecast_processor import AgentForecastProcessor
    fake_transport(monkeypatch, [respond(answer_body("{}"))])
    marker = f"m-{unique()}"

    def process(self, job):
        asyncio.run(provider.decision_request("siliconflow", marker, SECRET, [{"role": "user", "content": "q"}], []))
        return "draft"

    monkeypatch.setattr(AgentForecastProcessor, "_process", process)
    processor = AgentForecastProcessor(session_factory=SessionLocal, decision_mode="research_only")
    job = SimpleNamespace(id=uuid.uuid4(), symbol="AMD")
    assert processor(job) == "draft"
    (row,) = rows(model=marker)
    assert row.purpose == "forecast" and row.job == str(job.id)


def test_the_event_provider_records_each_call_and_each_failure():
    from app.event_provider import DeepSeekEventProvider, EventProviderError
    marker, owner = f"m-{unique()}", unique()

    class Completions:
        def __init__(self, outcomes):
            self.outcomes = outcomes

        def create(self, **kwargs):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class Status(Exception):
        status_code = 429

    message = SimpleNamespace(content='{"a": 1}', refusal=None)
    good = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)], model=marker,
                           usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}))
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions([Status(f"429 {SECRET}"), good])))
    event_provider = DeepSeekEventProvider(model=marker, api_key=SECRET, client=client)
    with model_usage.purpose("localization", owner_hash=owner):
        with pytest.raises(EventProviderError):
            event_provider.extract(system_prompt="s", document_payload="d", model=marker)
        event_provider.extract(system_prompt="s", document_payload="d", model=marker)
    bad, ok = rows(owner_hash=owner)
    assert (bad.purpose, bad.ok, bad.error, bad.model) == ("localization", False, "http_429", marker)
    assert (ok.ok, ok.input_tokens, ok.output_tokens) == (True, 11, 4)
    assert SECRET not in str([getattr(bad, c.name) for c in ModelCall.__table__.columns])


def test_the_openai_compatible_provider_and_knowledge_extraction_record_too():
    from app.model_providers import OpenAICompatibleProvider
    marker, owner = f"m-{unique()}", unique()
    message = SimpleNamespace(content='{"a": 1}', refusal=None)
    good = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)], model=marker,
                           usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 5, "completion_tokens": 2}))
    compat = OpenAICompatibleProvider(provider="deepseek", base_url="https://api.deepseek.com", model=marker, api_key=SECRET)
    compat._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: good)))
    with model_usage.purpose("material_analysis", owner_hash=owner):
        compat.extract(system_prompt="s", document_payload="d", model=marker)
    (row,) = rows(owner_hash=owner)
    assert (row.purpose, row.provider, row.model, row.input_tokens) == ("material_analysis", "deepseek", marker, 5)


# --- prices and cost ----------------------------------------------------------------------------------------------

def row_of(plain=0, output=0, read=0, write=0):
    return SimpleNamespace(input_tokens=plain, output_tokens=output, cache_read_tokens=read, cache_write_tokens=write)


def test_cost_needs_input_and_output_prices_and_never_guesses():
    assert model_usage.price_of({"name": "a"}) is None
    assert model_usage.price_of({"price_input": 1.0}) is None                 # one side only: no figure
    prices = model_usage.price_of({"price_input": 1.0, "price_output": 4.0})
    assert model_usage.cost(row_of(1_000_000, 500_000), prices) == pytest.approx(3.0)
    assert model_usage.cost(row_of(1_000_000, 500_000), None) is None
    assert model_usage.missing_price(row_of(5), {"price_output": 1}) == "input"
    assert model_usage.missing_price(row_of(5), {"price_input": 1}) == "output"


def test_cache_tokens_are_priced_by_their_own_prices_and_never_by_the_input_price():
    row = row_of(plain=400_000, output=10_000, read=600_000, write=100_000)
    entry = {"price_input": 2.0, "price_output": 4.0}
    assert model_usage.cost(row, model_usage.price_of(entry)) is None          # cache tokens, no cache price: unpriced
    assert model_usage.missing_price(row, entry) == "cache_read"
    only_read = {**entry, "price_cache_read": 0.5}
    assert model_usage.cost(row, model_usage.price_of(only_read)) is None and model_usage.missing_price(row, only_read) == "cache_write"
    full = {**only_read, "price_cache_write": 2.5}
    assert model_usage.cost(row, model_usage.price_of(full)) == pytest.approx((400_000 * 2 + 10_000 * 4 + 600_000 * 0.5 + 100_000 * 2.5) / 1e6)
    # A call without cache tokens does not need the cache prices.
    assert model_usage.cost(row_of(plain=1_000_000), model_usage.price_of(entry)) == pytest.approx(2.0)
    assert model_usage.missing_price(row_of(plain=1), entry) is None


def test_every_usage_shape_prices_the_same_way_through_parse_usage():
    prices = model_usage.price_of({"price_input": 1.0, "price_output": 2.0, "price_cache_read": 0.1, "price_cache_write": 1.25})
    shapes = [
        {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 20},
        {"prompt_tokens": 100, "completion_tokens": 10, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 20},
        {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 20}},
    ]
    costs = [model_usage.cost(model_usage.parse_usage(shape), prices) for shape in shapes]
    assert costs[0] == pytest.approx((50 * 1 + 10 * 2 + 30 * 0.1 + 20 * 1.25) / 1e6)
    assert costs == [pytest.approx(costs[0])] * 3
    deepseek = model_usage.parse_usage({"prompt_tokens": 100, "completion_tokens": 10, "prompt_cache_hit_tokens": 70, "prompt_cache_miss_tokens": 30})
    assert model_usage.cost(deepseek, prices) == pytest.approx((30 * 1 + 10 * 2 + 70 * 0.1) / 1e6)
    assert model_usage.cost(deepseek, model_usage.price_of({"price_input": 1, "price_output": 2, "price_cache_read": 0.1})) == pytest.approx((30 + 20 + 7) / 1e6)


def test_the_cost_is_fixed_when_the_row_is_written_and_a_later_price_edit_changes_only_later_rows(clean_catalog):
    catalog.save_entry("fixed", display_name="fixed", provider="deepseek", model="m-fixed", api_key="k" * 12, create=True)
    marker = f"m-{unique()}"
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}

    def call():
        model_usage.record(provider="deepseek", model=marker, catalog_name="fixed", ok=True, ms=1, usage=usage)
        model_usage.flush()

    call()                                                                       # no price yet
    catalog.save_entry("fixed", prices={"price_input": 1, "price_output": 2})
    call()
    catalog.save_entry("fixed", prices={"price_input": 3})                      # a typo fixed later
    call()
    catalog.save_entry("fixed", prices={"price_input": None})                   # a price removed later
    call()
    unpriced, first, second, removed = rows(model=marker)
    assert (unpriced.cost_usd, first.cost_usd, removed.cost_usd) == (None, pytest.approx(1.0), None)
    assert second.cost_usd == pytest.approx(3.0)
    assert first.cost_usd == pytest.approx(1.0)                                  # still what it was


def test_a_call_without_a_catalog_entry_has_no_cost(clean_catalog):
    marker = f"m-{unique()}"
    model_usage.record(provider="p", model=marker, ok=True, ms=1, usage={"prompt_tokens": 5})
    model_usage.record(provider="p", model=marker, catalog_name="gone", ok=True, ms=1, usage={"prompt_tokens": 5})
    assert [r.cost_usd for r in rows(model=marker)] == [None, None]


@pytest.fixture
def clean_catalog():
    Base.metadata.create_all(engine, tables=[AgentModelEntry.__table__, AgentBot.__table__, AgentModelRole.__table__])
    with SessionLocal() as db:
        db.query(AgentModelEntry).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(AgentModelEntry).delete()
        db.commit()


def test_catalog_entries_carry_optional_prices(clean_catalog):
    saved = catalog.save_entry("priced", display_name="priced", provider="deepseek", model="m-priced", api_key="k" * 12, create=True)
    assert all(saved[key] is None for key in ("price_input", "price_output", "price_cache_read", "price_cache_write"))
    assert "price_since" not in saved
    saved = catalog.save_entry("priced", prices={"price_input": 0.5, "price_output": 2})
    assert (saved["price_input"], saved["price_output"], saved["price_cache_read"]) == (0.5, 2.0, None)
    changed = catalog.save_entry("priced", prices={"price_output": 3, "price_cache_read": 0.1})
    assert (changed["price_input"], changed["price_output"], changed["price_cache_read"]) == (0.5, 3.0, 0.1)
    cleared = catalog.save_entry("priced", prices={"price_input": None, "price_output": None, "price_cache_read": None})
    assert cleared["price_input"] is None and model_usage.price_of(cleared) is None
    catalog.save_entry("priced", prices={"price_input": 1, "price_output": 2})
    other = catalog.save_entry("priced", display_name="renamed only")          # an edit that sends no prices leaves them alone
    assert (other["price_input"], other["price_output"]) == (1.0, 2.0)


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "x", 10 ** 7, True])
def test_a_bad_price_is_refused(clean_catalog, bad):
    catalog.save_entry("priced", display_name="p", provider="deepseek", model="m-priced", api_key="k" * 12, create=True)
    with pytest.raises(catalog.CatalogError) as caught:
        catalog.save_entry("priced", prices={"price_input": bad})
    assert str(caught.value) == "invalid_price"


def test_a_rename_keeps_the_price_and_the_old_rows_keep_the_name_they_were_called_by(clean_catalog):
    catalog.save_entry("before", display_name="before", provider="deepseek", model="m-r", api_key="k" * 12, create=True,
                       prices={"price_input": 1, "price_output": 2})
    marker = f"m-{unique()}"
    model_usage.record(provider="deepseek", model=marker, catalog_name="before", ok=True, ms=1)
    renamed = catalog.save_entry("before", rename_to="after")
    assert renamed["price_input"] == 1.0
    (row,) = rows(model=marker)
    assert row.catalog_name == "before"


def test_the_public_entry_never_leaks_more_than_the_prices(clean_catalog):
    saved = catalog.save_entry("priced", display_name="p", provider="deepseek", model="m-priced", api_key="k" * 12, create=True,
                               prices={"price_input": 1, "price_output": 2})
    assert "ciphertext" not in saved and "api_key" not in saved
    listed = catalog.list_public()["models"][0]
    assert listed["price_input"] == 1.0 and listed["price_output"] == 2.0


# --- the places work starts ---------------------------------------------------------------------------------------

from tests.test_agent_chat_stream import stream_fixture  # noqa: E402,F401  (fixture)


def test_a_chat_turn_tags_every_call_it_makes_with_owner_conversation_and_turn(stream_fixture, monkeypatch):
    import app.agent_chat_stream as stream
    send, *_ = stream_fixture
    marker = f"m-{unique()}"

    async def workflow(**kwargs):
        # Two calls from two awaited layers of the turn, as both engines make them.
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
        await asyncio.to_thread(model_usage.record, provider="p", model=marker, ok=True, ms=1)
        yield {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {}, "citations": [], "route": "A", "trace": []}

    monkeypatch.setattr(stream, "stream_workflow", workflow)
    asyncio.run(send())
    first, second = rows(model=marker)
    assert first.purpose == second.purpose == "chat"
    assert first.owner_hash == second.owner_hash == stream.owner_hash("x" * 40)
    assert first.conversation_id is not None and first.turn_id is not None and first.turn_id == second.turn_id


def test_query_expansion_inside_a_turn_is_its_own_purpose_with_the_turns_ids():
    from app.knowledge.query_understanding import query_variants, use_expander
    marker, turn = f"m-{unique()}", str(uuid.uuid4())

    async def expander(query):
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
        return [query + " revenue"]

    async def main():
        with model_usage.purpose("chat", turn_id=turn), use_expander(expander):
            return await query_variants("AAPL 营收")

    asyncio.run(main())
    (row,) = rows(model=marker)
    assert row.purpose == "query_expansion" and str(row.turn_id) == turn


def test_a_routine_run_is_tagged_with_the_task_as_job(monkeypatch):
    from app import agent_task_runner as runner
    marker = f"m-{unique()}"
    seen = {}

    async def fake_stream_workflow(**kwargs):
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
        seen.update(kwargs)
        yield {"event": "done", "status": "complete", "final_protocol": {}, "audit": {}, "citations": []}

    async def noop(*args, **kwargs):
        return str(uuid.uuid4())

    async def profile(*args, **kwargs):
        return None

    import app.agent_chat_store as store
    import app.agent_chat_stream as chat_stream
    import app.agent_workflow.graph as graph
    monkeypatch.setattr(store, "create_conversation", noop)
    monkeypatch.setattr(store, "append_message", noop)
    monkeypatch.setattr(store, "finish_conversation", noop)
    monkeypatch.setattr(store, "set_conversation_title", noop)
    monkeypatch.setattr(chat_stream, "_profile_block", profile)
    monkeypatch.setattr(graph, "stream_workflow", fake_stream_workflow)
    task_id = uuid.uuid4()
    with model_usage.purpose("routine", job=str(task_id)):
        result = asyncio.run(runner.run_unattended_turn("c" * 40, "q", {"provider": "p", "model": marker, "api_key": SECRET}, title="t"))
    assert result["status"] == "complete"
    (row,) = rows(model=marker)
    assert row.purpose == "routine" and row.job == str(task_id) and row.owner_hash and row.turn_id and row.conversation_id


def test_the_background_loop_names_its_job_and_inner_purposes_win():
    from app import background
    marker = f"m-{unique()}"
    calls = []

    def job():
        model_usage.record(provider="p", model=marker, ok=True, ms=1)
        with model_usage.purpose("earnings"):
            model_usage.record(provider="p", model=marker, ok=True, ms=1)
        calls.append(1)

    async def one_pass():
        task = background.start((("release-figures", 3600, job),))[0]
        while not calls:
            await asyncio.sleep(0.01)
        await background.stop([task])

    asyncio.run(one_pass())
    plain, inner = rows(model=marker)
    assert (plain.purpose, plain.job) == ("other", "release-figures") and (inner.purpose, inner.job) == ("earnings", "release-figures")


def test_the_knowledge_extractor_records_its_call(monkeypatch):
    import openai
    from app.knowledge import extraction
    marker, owner = f"m-{unique()}", unique()
    message = SimpleNamespace(content='{"candidates": []}')
    completion = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 9, "completion_tokens": 1}))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: completion)))
    monkeypatch.setattr(openai, "OpenAI", lambda **options: client)
    monkeypatch.setenv("KNOWLEDGE_OPERATOR_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_OPERATOR_API_KEY", SECRET)
    monkeypatch.setenv("KNOWLEDGE_OPERATOR_MODEL", marker)
    call = extraction.create_operator_provider()
    with model_usage.purpose("chat", owner_hash=owner):
        assert call({"turns": []}) == {"candidates": []}
    (row,) = rows(model=marker)
    assert (row.purpose, row.owner_hash, row.input_tokens) == ("knowledge", owner, 9)


# --- the catalog's schema and API ------------------------------------------------------------------------------------

def test_the_price_columns_are_added_to_a_catalog_table_made_before_them(clean_catalog):
    from sqlalchemy import text
    with engine.begin() as connection:
        for column in catalog.PRICE_KEYS:
            connection.execute(text(f"ALTER TABLE agent_model_catalog DROP COLUMN IF EXISTS {column}"))
    catalog.ensure_price_columns()
    catalog.ensure_price_columns()           # again: nothing to add, nothing breaks
    saved = catalog.save_entry("old", display_name="old", provider="deepseek", model="m-old", api_key="k" * 12, create=True,
                               prices={"price_input": 1, "price_output": 2})
    assert saved["price_input"] == 1.0


def test_the_catalog_api_takes_and_returns_prices_and_refuses_a_bad_one(clean_catalog, client, monkeypatch):
    from tests.test_agent_bots import H, GUEST
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda value: value == H["X-Chat-Session"])
    body = {"name": "apiprice", "display_name": "p", "provider": "deepseek", "model": "m-api", "api_key": "k" * 12, "price_input": 0.5, "price_output": 2}
    added = client.post("/agent-chat/model-catalog", headers=H, json=body)
    assert added.status_code == 200, added.text
    model = added.json()["model"]
    assert (model["price_input"], model["price_output"], model["price_cache_read"]) == (0.5, 2.0, None)
    kept = client.patch("/agent-chat/model-catalog/apiprice", headers=H, json={"name": "apiprice", "display_name": "renamed"}).json()["model"]
    assert kept["price_input"] == 0.5
    cleared = client.patch("/agent-chat/model-catalog/apiprice", headers=H, json={"name": "apiprice", "price_input": None, "price_output": None}).json()["model"]
    assert cleared["price_input"] is None and cleared["price_output"] is None
    bad = client.patch("/agent-chat/model-catalog/apiprice", headers=H, json={"name": "apiprice", "price_input": -3})
    assert bad.status_code == 422
    assert client.patch("/agent-chat/model-catalog/apiprice", headers={"X-Chat-Session": GUEST}, json={"price_input": 1}).status_code == 403


def test_the_old_engines_retry_is_a_second_attempt_row(monkeypatch):
    from app.agent_workflow import direct
    from app.agent_workflow.state import AgentRuntimeContext
    owner = unique()
    fake_transport(monkeypatch, [respond(b"", 502), respond(answer_body("好"))])

    async def emit(_):
        pass

    turn = direct.Turn("q", AgentRuntimeContext("siliconflow", "m", SECRET), emit, [], {})

    async def main():
        with model_usage.purpose("chat", owner_hash=owner):
            return await turn.provider_request([{"role": "user", "content": "q"}], [])

    _, message = asyncio.run(main())
    assert message["content"] == "好" and turn.audit["provider_retries"] == 1
    first, second = rows(owner_hash=owner)
    assert (first.attempt, first.ok, second.attempt, second.ok) == (1, False, 2, True)


# --- fix round 1 ---------------------------------------------------------------------------------------------------

def test_a_chat_turn_that_runs_the_judge_on_another_model_gives_two_rows_with_two_catalog_names(kernel):
    from app.agent_workflow import claim_judge
    owner, turn = unique(), str(uuid.uuid4())
    fake_transport(kernel, [respond(tool_body("c1", "query_financials", {"symbol": "AAPL"})), respond(answer_body("{}")),
                            respond(answer_body("收入 100 [1]"))])

    async def invoke_with_judge(name, args, context, *, emit=None, page_chars=None):
        await claim_judge._default_call({"provider": "siliconflow", "model": "judge-m", "api_key": SECRET, "name": "judge-glm"}, "s", "u")
        return {"ok": True, "data": [{"id": "r1", "symbol": "AAPL", "source_type": "official_filing", "excerpt": "Revenue was 100."}], "source": "saved"}

    kernel.setattr(tools, "invoke", invoke_with_judge)
    context = SimpleNamespace(provider="siliconflow", model="chat-m", api_key=SECRET, base_url=None, reasoning_effort=None, tool_scope=None,
                              bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash=owner, catalog_name="chat-model")

    async def emit(event):
        pass

    async def main():
        with model_usage.purpose("chat", owner_hash=owner, turn_id=turn):
            return await loop.run_turn("问题", context, emit, [{"role": "system", "content": "s"}, {"role": "user", "content": "问题"}], {})

    asyncio.run(main())
    found = rows(owner_hash=owner)
    assert [(r.purpose, r.model, r.catalog_name) for r in found] == [("chat", "chat-m", "chat-model"), ("judge", "judge-m", "judge-glm"),
                                                                    ("chat", "chat-m", "chat-model")]
    assert {str(r.turn_id) for r in found} == {turn}


def test_a_nested_call_without_a_catalog_entry_carries_no_catalog_name():
    marker, owner = f"m-{unique()}", unique()
    with model_usage.purpose("chat", owner_hash=owner):
        with model_usage.purpose("summary"):
            model_usage.record(provider="p", model=marker, ok=True, ms=1)
    assert rows(model=marker)[0].catalog_name is None


def test_a_cancelled_streamed_turn_is_one_failed_row_with_its_turn(kernel):
    owner, turn = unique(), str(uuid.uuid4())

    async def slow_body():
        yield b'data: {"choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
        await asyncio.sleep(30)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=slow_body())

    @asynccontextmanager
    async def client(base_url):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield http

    kernel.setattr(provider, "_decision_client", client)
    context = SimpleNamespace(provider="siliconflow", model="m", api_key=SECRET, base_url=None, reasoning_effort=None, tool_scope=None,
                              bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash=owner)

    async def emit(event):
        pass

    async def main():
        with model_usage.purpose("chat", owner_hash=owner, turn_id=turn):
            task = asyncio.create_task(loop.run_turn("问题", context, emit, [{"role": "system", "content": "s"}, {"role": "user", "content": "问题"}], {}))
            await asyncio.sleep(0.4)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(main())
    (row,) = rows(owner_hash=owner)
    assert (row.ok, row.error, str(row.turn_id), row.purpose) == (False, "cancelled", turn, "chat")


def test_two_concurrent_turns_keep_their_own_turn_ids(kernel):
    first_owner, second_owner = unique(), unique()
    first_turn, second_turn = str(uuid.uuid4()), str(uuid.uuid4())
    fake_transport(kernel, [respond(answer_body("甲")), respond(answer_body("乙"))])

    def context(owner):
        return SimpleNamespace(provider="siliconflow", model="m", api_key=SECRET, base_url=None, reasoning_effort=None, tool_scope=None,
                               bot_block=None, profile_block=None, identity_credential="x" * 64, owner_hash=owner)

    async def emit(event):
        pass

    async def one(owner, turn):
        with model_usage.purpose("chat", owner_hash=owner, turn_id=turn):
            await asyncio.sleep(0)
            return await loop.run_turn("问题", context(owner), emit, [{"role": "system", "content": "s"}, {"role": "user", "content": "问题"}], {})

    async def main():
        await asyncio.gather(one(first_owner, first_turn), one(second_owner, second_turn))

    asyncio.run(main())
    (a,), (b,) = rows(owner_hash=first_owner), rows(owner_hash=second_owner)
    assert str(a.turn_id) == first_turn and str(b.turn_id) == second_turn


def test_the_jev_channel_is_recorded_as_judge_calls(monkeypatch):
    from app import jev_claim_support as jev
    owner = unique()
    client = jev._UrllibClient()
    replies = [jev._TransportResponse(200, b"{}"), jev._TransportResponse(503, b""), TimeoutError("slow " + SECRET)]

    def fake_post(self, url, *, json, headers, timeout):
        outcome = replies.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(jev._UrllibClient, "_post", fake_post)
    with model_usage.purpose("chat", owner_hash=owner):
        for _ in range(3):
            try:
                client.post("https://openrouter.test/decisions", json={"model": "typesafe/jev-1.13"}, headers={"Authorization": f"Bearer {SECRET}"}, timeout=5)
            except TimeoutError:
                pass
    ok, bad, timeout = rows(owner_hash=owner)
    assert [(r.purpose, r.ok, r.error) for r in (ok, bad, timeout)] == [("judge", True, None), ("judge", False, "http_503"), ("judge", False, "TimeoutError")]
    assert SECRET not in str([getattr(r, c.name) for r in (ok, bad, timeout) for c in ModelCall.__table__.columns])


def test_the_chat_endpoint_hands_the_catalog_name_of_the_turn_down(stream_fixture, monkeypatch):
    import app.agent_chat_stream as stream
    send, *_ = stream_fixture
    seen = {}

    async def workflow(**kwargs):
        seen.update(kwargs)
        yield {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {}, "citations": [], "route": "A", "trace": []}

    monkeypatch.setattr(stream, "stream_workflow", workflow)
    monkeypatch.setattr(stream, "_catalog_turn", lambda name, credential: {"name": "haiku-5.5", "provider": "siliconflow", "model": "m", "api_key": SECRET,
                                                                           "base_url": None, "context_window": None})

    async def go():
        payload = stream.StreamRequest(catalog_model="haiku-5.5", message="hi")
        response = await stream.stream_chat(payload, SimpleNamespace(), "x" * 40)
        return [part async for part in response.body_iterator]

    asyncio.run(go())
    assert seen["catalog_name"] == "haiku-5.5"
