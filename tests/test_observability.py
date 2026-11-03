import asyncio
from types import SimpleNamespace

import pytest

from app import observability


class FakeObs:
    def __init__(self, log, kind, name, kwargs):
        self.log, self.kind, self.name, self.kwargs = log, kind, name, kwargs
        self.updates, self.ended = [], False
        log.append(self)

    def start_generation(self, **kw):
        return FakeObs(self.log, "generation", kw["name"], kw)

    def start_span(self, **kw):
        return FakeObs(self.log, "span", kw["name"], kw)

    def update(self, **kw):
        self.updates.append(kw)

    def update_trace(self, **kw):
        pass

    def end(self):
        self.ended = True

    def score_trace(self, **kw):
        self.log.append(("score", kw["name"], kw["value"]))


class FakeClient:
    def __init__(self):
        self.log = []

    def start_span(self, **kw):
        return FakeObs(self.log, "trace", kw["name"], kw)

    def flush(self):
        pass


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    yield
    observability._reset_for_tests(None)


def test_noop_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    observability._reset_for_tests(None)
    assert not observability.enabled()
    assert observability._client is None
    t = observability.start_turn(conversation_id="c", turn_id="t", bot_id=None, owner_hash="o", source="web", model_role="x")
    assert t is None
    assert observability.start_generation(t, name="g", model="m") is None
    assert observability.start_span(t, name="s") is None
    assert observability.end_generation(None, output="x") is None
    assert observability.end_span(None) is None
    assert observability.score(None, "a", 1) is None
    assert observability.score_citation_audit(None, verified=1, unverified=0) is None
    assert observability.end_trace(None) is None
    assert observability._client is None


def test_synthetic_turn_structure(keys):
    fake = FakeClient()
    observability._reset_for_tests(fake)
    trace = observability.start_turn(conversation_id="c1", turn_id="t1", bot_id="b1", owner_hash="oh", source="web",
                                     model_role="agent:p/m", question="q")
    gen = observability.start_generation(trace, name="model-call", model="m", role="agent", input=[{"role": "user", "content": "q"}])
    observability.end_generation(gen, output="a", usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7})
    span = observability.start_span(trace, name="tool:search", input={"argument_keys": ["query"]})
    observability.end_span(span, error="tool_failed")
    observability.score_citation_audit(trace, verified=2, unverified=1, unverified_lines=[{"line": "x"}])
    observability.end_trace(trace, output="a")

    traces = [e for e in fake.log if isinstance(e, FakeObs) and e.kind == "trace"]
    assert len(traces) == 1 and traces[0].name == "agent-turn" and traces[0].ended
    assert traces[0].kwargs["metadata"]["conversation_id"] == "c1"
    gens = [e for e in fake.log if isinstance(e, FakeObs) and e.kind == "generation"]
    assert len(gens) == 1 and gens[0].updates[0]["usage_details"] == {"input": 3, "output": 4, "total": 7}
    spans = [e for e in fake.log if isinstance(e, FakeObs) and e.kind == "span"]
    assert len(spans) == 1 and spans[0].updates[0]["level"] == "ERROR"
    scores = {e[1]: e[2] for e in fake.log if isinstance(e, tuple)}
    assert scores == {"citation_verified": 2.0, "citation_unverified": 1.0, "unverified_lines": 1.0}
    assert "sk-test" not in repr([e.kwargs for e in fake.log if isinstance(e, FakeObs)])


def test_sdk_errors_never_raise(keys):
    class Boom:
        def start_span(self, **kw):
            raise RuntimeError("down")

    observability._reset_for_tests(Boom())
    assert observability.start_trace("x") is None


def test_turn_model_seam_records_generation(keys):
    from app.agent_workflow.direct import Turn

    fake = FakeClient()
    observability._reset_for_tests(fake)
    turn = object.__new__(Turn)
    turn.context = SimpleNamespace(provider="p", model="m", token_budget=None, context_window=0)
    turn.audit = {"token_usage": 0, "model_calls": 0, "usage_mode": "actual"}
    turn.final_protocol = {}
    turn.obs = observability.start_trace("agent-turn")

    async def provider_request(messages, schemas):
        return {"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}, {"role": "assistant", "content": "hi"}

    turn.provider_request = provider_request
    message = asyncio.run(turn.model([{"role": "user", "content": "q"}], []))
    assert message["content"] == "hi"
    gens = [e for e in fake.log if isinstance(e, FakeObs) and e.kind == "generation"]
    assert len(gens) == 1 and gens[0].ended and gens[0].kwargs["model"] == "m"
