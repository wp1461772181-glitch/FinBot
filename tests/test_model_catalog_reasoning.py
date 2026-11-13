"""The catalog says which reasoning-effort tiers a model takes (supported_efforts / reasoning_supported).

An OpenRouter entry is answered by the OpenRouter model list.  Any other provider is answered by the provider's own
table (agent_chat_provider.NATIVE_EFFORTS, the tiers its request really distinguishes); a provider outside that table
gets no fields, as before.

The OpenRouter model list is stubbed everywhere: no test reaches the network.  The index is advisory: when it cannot
be read, the catalog answers as before, just without those two fields.
"""
import logging

import httpx
import pytest

from app import agent_chat_provider as chat
from app import agent_model_catalog as catalog
from app.agent_chat_provider import REASONING_EFFORTS, reasoning_options
from tests.test_agent_bots import H, KEY_A, owner  # noqa: F401  (fixture)

# What OpenRouter declared for these ids on 2026-11-13 (effort-look report, section 1).  Must keep coming out unchanged.
REAL_OPENROUTER = {
    "anthropic/claude-haiku-5.5": ["max", "xhigh", "high", "medium", "low", "none"],
    "meta/muse-ember": ["max", "xhigh", "high", "medium", "low", "minimal"],
    "openai/gpt-6.1-terra": ["max", "xhigh", "high", "medium", "low", "none"],
}

DEEPSEEK = "deepseek/deepseek-v4.1-flash-1017"
GLM = "z-ai/glm-5.3-flash"
PLAIN = "acme/plain-chat"
ANY = "acme/accepts-all"
PAYLOAD = {"data": [
    {"id": DEEPSEEK, "reasoning": {"supported_efforts": ["max", "high", "low", "none"], "default_effort": "high", "mandatory": False}},
    {"id": GLM, "reasoning": {"supported_efforts": ["max", "high", "low"], "default_effort": "max", "mandatory": True}},
    {"id": PLAIN},
    {"id": ANY, "reasoning": {"supported_efforts": None, "default_effort": None, "mandatory": False}},
]}


@pytest.fixture
def models(monkeypatch):
    """Serve PAYLOAD for the OpenRouter list, counting the fetches; a fresh cache for each test."""
    state = {"payload": PAYLOAD, "calls": 0, "error": None}

    def fetch():
        state["calls"] += 1
        if state["error"] is not None:
            raise state["error"]
        return state["payload"]
    monkeypatch.setattr(catalog, "_load_openrouter_models", fetch)
    monkeypatch.setattr(catalog, "_reasoning", {"at": None, "ttl": 0.0, "index": {}})
    return state


def _entry(name, model, provider="openrouter"):
    return catalog.save_entry(name, provider=provider, model=model, api_key=KEY_A, create=True)


def _listed(name):
    return next(item for item in catalog.list_public()["models"] if item["name"] == name)


def test_openrouter_entries_carry_what_their_model_takes(owner, models):
    _entry("deep", DEEPSEEK)
    _entry("glm", GLM)
    _entry("plain", PLAIN)
    _entry("any", ANY)
    deep, glm, plain, anything = (_listed(n) for n in ("deep", "glm", "plain", "any"))
    assert deep["supported_efforts"] == ["max", "high", "low", "none"] and deep["reasoning_supported"] is True
    assert glm["supported_efforts"] == ["max", "high", "low"] and glm["reasoning_supported"] is True
    assert anything["supported_efforts"] is None and anything["reasoning_supported"] is True
    # In the index, but no reasoning block: it takes no effort at all, so no tier list is given.
    assert plain["reasoning_supported"] is False and "supported_efforts" not in plain
    assert models["calls"] == 1, "one fetch serves every entry"


def test_no_guessing_outside_the_entrys_own_slug(owner, models):
    # An OpenRouter model missing from the index takes no fields.  The same slug under another provider is answered by
    # that provider's own table, never by OpenRouter's declaration of the id (the index row for DEEPSEEK is different).
    _entry("unknown", "acme/not-in-the-list")
    _entry("elsewhere", DEEPSEEK, provider="deepseek")
    unknown = _listed("unknown")
    assert "supported_efforts" not in unknown and "reasoning_supported" not in unknown
    # The fields are additions: the rest of the entry is what it was.
    assert unknown["model"] == "acme/not-in-the-list" and unknown["key_status"] == "configured"
    elsewhere = _listed("elsewhere")
    assert elsewhere["supported_efforts"] == ["none", "high", "max"] and elsewhere["reasoning_supported"] is True
    assert elsewhere["supported_efforts"] != ["max", "high", "low", "none"], "OpenRouter's declaration was not borrowed"


def test_zhipu_entries_take_the_tiers_its_api_accepts(owner, models):
    _entry("glm", "glm-5.3-flash", provider="zhipu")
    listed = _listed("glm")
    assert listed["supported_efforts"] == ["low", "high", "max"] and listed["reasoning_supported"] is True


def test_siliconflow_entries_take_no_effort_and_the_fields_say_so(owner, models):
    # Nothing is sent for SiliconFlow (reasoning_options has no branch for it): no tier list, and no effort offered.
    _entry("sf", "deepseek-ai/DeepSeek-V4-Flash", provider="siliconflow")
    listed = _listed("sf")
    assert listed["reasoning_supported"] is False and "supported_efforts" not in listed
    assert listed["key_status"] == "configured"


@pytest.mark.parametrize("provider,model", [("kimi", "kimi-k3"), ("qwen", "qwen3-max")])
def test_providers_outside_the_table_keep_the_fallback(owner, models, provider, model):
    _entry("other", model, provider=provider)
    listed = _listed("other")
    assert "supported_efforts" not in listed and "reasoning_supported" not in listed
    assert listed["key_status"] == "configured"


@pytest.mark.parametrize("model", sorted(REAL_OPENROUTER))
def test_openrouter_entries_keep_their_declared_tiers(owner, models, model):
    models["payload"] = {"data": [{"id": m, "reasoning": {"supported_efforts": tiers}} for m, tiers in REAL_OPENROUTER.items()]}
    _entry("entry", model)
    listed = _listed("entry")
    assert listed["supported_efforts"] == REAL_OPENROUTER[model] and listed["reasoning_supported"] is True


def test_native_table_is_what_the_request_really_sends():
    # A tier the table declares must be one the request carries (not dropped); a provider with no tier sends no effort.
    for provider, tiers in chat.NATIVE_EFFORTS.items():
        assert set(tiers) <= set(REASONING_EFFORTS), provider
        if not tiers:
            assert reasoning_options(provider, "high") == {}, provider
        for tier in tiers:
            assert reasoning_options(provider, tier) != {}, f"{provider} declares {tier} but the request drops it"


def test_a_declared_tier_the_server_does_not_know_is_logged_once_per_model(caplog):
    # Advisory and log-only: the index keeps the list as declared, and the tier is noted once per model per build.
    with caplog.at_level(logging.INFO, logger="app.agent_model_catalog"):
        index = catalog._index_of({"data": [
            {"id": "a/ultra", "reasoning": {"supported_efforts": ["high", "ultra", "turbo"]}},
            {"id": "a/fine", "reasoning": {"supported_efforts": ["high"]}},
        ]})
    assert index["a/ultra"]["supported_efforts"] == ["high", "ultra", "turbo"]
    notes = [r.getMessage() for r in caplog.records if r.name == "app.agent_model_catalog"]
    assert len(notes) == 1 and "a/ultra" in notes[0] and "ultra" in notes[0] and "turbo" in notes[0]


def test_endpoint_answers_with_the_fields_and_without_them(owner, client, models):
    _entry("deep", DEEPSEEK)
    body = client.get("/agent-chat/model-catalog", headers=H)
    assert body.status_code == 200
    deep = next(item for item in body.json()["models"] if item["name"] == "deep")
    assert deep["supported_efforts"] == ["max", "high", "low", "none"] and deep["reasoning_supported"] is True
    assert KEY_A not in body.text


@pytest.mark.parametrize("failure", [RuntimeError("network down"), TimeoutError("slow"), ValueError("bad json")])
def test_a_failed_fetch_leaves_the_fields_out_and_the_endpoint_answers(owner, client, models, failure):
    _entry("deep", DEEPSEEK)
    models["error"] = failure
    catalog._reasoning.update(at=None)  # the index is read again, and the read fails
    body = client.get("/agent-chat/model-catalog", headers=H)
    assert body.status_code == 200
    listed = body.json()["models"]
    assert [item["name"] for item in listed] == ["deep"]
    assert "supported_efforts" not in listed[0] and "reasoning_supported" not in listed[0]
    assert listed[0]["key_status"] == "configured"


def test_a_list_without_data_is_a_failure_too(owner, models):
    models["payload"] = {"error": "unexpected"}
    _entry("deep", DEEPSEEK)
    assert "reasoning_supported" not in _listed("deep")
    assert catalog.reasoning_index() == {}


def test_index_is_kept_six_hours_and_a_failure_is_retried_sooner(owner, models):
    _entry("deep", DEEPSEEK)
    _listed("deep")
    _listed("deep")
    assert models["calls"] == 1, "a fresh index is reused"
    catalog._reasoning["at"] -= catalog.REASONING_TTL + 1
    _listed("deep")
    assert models["calls"] == 2, "an expired index is refreshed on the next call"

    catalog._reasoning.update(at=None)
    models["error"] = RuntimeError("down")
    assert catalog.reasoning_index() == {}
    assert catalog.reasoning_index() == {}
    assert models["calls"] == 3, "a failure is remembered for the short retry window"
    catalog._reasoning["at"] -= catalog.REASONING_RETRY + 1
    models["error"] = None
    assert "reasoning_supported" in _listed("deep")
    assert models["calls"] == 4


def test_the_real_fetch_uses_the_models_url_and_the_discovery_transport(monkeypatch):
    import app.agent_chat_api as chat_api
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=PAYLOAD)
    bases = []
    monkeypatch.setattr(chat_api, "model_transport", lambda base_url, **kw: bases.append(base_url) or httpx.MockTransport(handler))
    assert catalog._load_openrouter_models() == PAYLOAD
    assert seen == ["https://openrouter.ai/api/v1/models"]
    assert bases == ["https://openrouter.ai/api/v1"]


@pytest.mark.parametrize("response", [
    httpx.Response(500, json=PAYLOAD),
    httpx.Response(302, headers={"location": "https://example.com/"}),
    httpx.Response(200, content=b"<html>not json</html>"),
])
def test_non_200_or_unreadable_answers_give_an_empty_index(monkeypatch, response):
    import app.agent_chat_api as chat_api
    monkeypatch.setattr(chat_api, "model_transport", lambda base_url, **kw: httpx.MockTransport(lambda request: response))
    monkeypatch.setattr(catalog, "_reasoning", {"at": None, "ttl": 0.0, "index": {}})
    assert catalog.reasoning_index() == {}


def test_reasoning_block_shapes_are_read_as_documented():
    index = catalog._index_of({"data": [
        {"id": "a/list", "reasoning": {"supported_efforts": ["low"]}},
        {"id": "a/null", "reasoning": {"supported_efforts": None}},
        {"id": "a/absent", "reasoning": {"default_effort": "low"}},
        {"id": "a/junk", "reasoning": {"supported_efforts": "low"}},
        {"id": "a/none", "reasoning": None},
        {"no": "id"},
    ]})
    assert index["a/list"] == {"reasoning": True, "supported_efforts": ["low"]}
    assert index["a/null"] == {"reasoning": True, "supported_efforts": None}
    assert index["a/absent"] == {"reasoning": True}
    assert index["a/junk"] == {"reasoning": True}
    assert index["a/none"] == {"reasoning": False}
    assert len(index) == 5
