"""The catalog says which reasoning-effort tiers an OpenRouter model takes (supported_efforts / reasoning_supported).

The OpenRouter model list is stubbed everywhere: no test reaches the network.  The index is advisory: when it cannot
be read, the catalog answers as before, just without those two fields.
"""
import httpx
import pytest

from app import agent_model_catalog as catalog
from tests.test_agent_bots import H, KEY_A, owner  # noqa: F401  (fixture)

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
    _entry("unknown", "acme/not-in-the-list")
    _entry("elsewhere", DEEPSEEK, provider="deepseek")  # same slug, another provider: not OpenRouter's answer
    for name in ("unknown", "elsewhere"):
        listed = _listed(name)
        assert "supported_efforts" not in listed and "reasoning_supported" not in listed
    # The fields are additions: the rest of the entry is what it was.
    assert _listed("unknown")["model"] == "acme/not-in-the-list" and _listed("unknown")["key_status"] == "configured"


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
