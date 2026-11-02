import asyncio
import json
import httpx
import pytest
from app import agent_chat_api as api

PUBLIC = 'https://api.example.com/v1'


def _run(coro):
    return asyncio.run(coro)


def test_env_unset_returns_pinned_transport(monkeypatch):
    monkeypatch.delenv('MODEL_EGRESS_PROXY', raising=False)
    assert type(api.model_transport(PUBLIC)) is api.PinnedPublicTransport


def test_env_empty_returns_pinned_transport(monkeypatch):
    monkeypatch.setenv('MODEL_EGRESS_PROXY', '')
    assert type(api.model_transport(PUBLIC)) is api.PinnedPublicTransport


def test_env_set_returns_proxy_transport_and_is_read_at_call_time(monkeypatch):
    monkeypatch.delenv('MODEL_EGRESS_PROXY', raising=False)
    assert type(api.model_transport(PUBLIC)) is api.PinnedPublicTransport
    monkeypatch.setenv('MODEL_EGRESS_PROXY', 'http://127.0.0.1:3128')
    assert type(api.model_transport(PUBLIC)) is api.ProxiedPublicTransport


def test_https_proxy_env_is_not_used_implicitly(monkeypatch):
    monkeypatch.delenv('MODEL_EGRESS_PROXY', raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:3128')
    assert type(api.model_transport(PUBLIC)) is api.PinnedPublicTransport


@pytest.mark.parametrize('url', [
    'http://api.example.com/v1/models',
    'https://user:pw@api.example.com/v1/models',
    'https://api.example.com/v1/models#frag',
    'https://api.example.com/v1/models?x=1',
])
def test_proxy_mode_rejects_unsafe_urls_without_network(monkeypatch, url):
    monkeypatch.setenv('MODEL_EGRESS_PROXY', 'http://127.0.0.1:3128')
    t = api.ProxiedPublicTransport('http://127.0.0.1:3128', inner=httpx.MockTransport(lambda _: pytest.fail('reached network')))
    with pytest.raises(httpx.ConnectError, match='unsafe_endpoint'):
        _run(t.handle_async_request(httpx.Request('GET', url)))


def test_proxy_mode_allows_query_only_with_allow_internal_query_and_forwards_unmodified(monkeypatch):
    seen = []
    inner = httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200, json={}))
    t = api.ProxiedPublicTransport('http://127.0.0.1:3128', inner=inner, allow_internal_query=True)
    _run(t.handle_async_request(httpx.Request('GET', 'https://api.example.com/v1/models?a=1')))
    assert seen == ['https://api.example.com/v1/models?a=1']


def test_model_transport_passes_allow_internal_query_in_proxy_mode(monkeypatch):
    monkeypatch.setenv('MODEL_EGRESS_PROXY', 'http://127.0.0.1:3128')
    t = api.model_transport(PUBLIC, allow_internal_query=True)
    assert type(t) is api.ProxiedPublicTransport and t.allow_internal_query is True


def test_local_endpoints_unchanged_with_proxy_set(monkeypatch):
    base = 'http://127.0.0.1:11434/v1'
    monkeypatch.setenv('AGENT_LOCAL_MODEL_BASE_URLS', json.dumps([base]))
    monkeypatch.setenv('MODEL_EGRESS_PROXY', 'http://127.0.0.1:3128')
    assert type(api.model_transport(base)) is api.LocalModelTransport
