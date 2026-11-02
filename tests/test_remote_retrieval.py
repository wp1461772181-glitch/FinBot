import asyncio
import subprocess
import sys
import time

import httpx
import pytest

from app.knowledge import remote as remote_module
from app.knowledge.remote import KnowledgeOffline, RemoteKnowledgeRuntime
from app.knowledge.runtime import research_context
from app.knowledge.settings import KnowledgeSettings


def _runtime(url="http://127.0.0.1:9"):
    return RemoteKnowledgeRuntime(KnowledgeSettings.from_env(validate_model=False), url, "tok")


def test_offline_fails_fast():
    # Port 9 (discard) refuses; an unroutable address exercises the connect timeout.
    for url in ("http://127.0.0.1:9", "http://10.255.255.1:8765"):
        started = time.monotonic()
        with pytest.raises(KnowledgeOffline):
            asyncio.run(_runtime(url).search_strategy("hybrid", "q", 'scope == "public"', 10))
        assert time.monotonic() - started < 5


def test_scope_is_forwarded(monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = __import__("json").loads(request.content)
        seen["token"] = request.headers["X-Retrieval-Token"]
        return httpx.Response(200, json={"hits": [{"id": "a", "distance": 0.5}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(remote_module.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    from datetime import UTC, datetime
    cutoff = datetime(2025, 1, 2, tzinfo=UTC)
    runtime = _runtime()
    with research_context("owner-123", cutoff=cutoff):
        hits = asyncio.run(runtime.search_strategy("hybrid", "q", 'owner_hash == "owner-123"', 7))
    assert hits == [{"id": "a", "distance": 0.5}]
    assert seen["token"] == "tok"
    assert seen["body"]["owner_hash"] == "owner-123"
    assert seen["body"]["cutoff"] == cutoff.isoformat()
    assert seen["body"]["filter"] == 'owner_hash == "owner-123"' and seen["body"]["limit"] == 7
    assert seen["body"]["generation"] == runtime.settings.generation


def test_no_torch_import():
    code = (
        "import os, sys; os.environ['RAG_REMOTE_URL']='http://127.0.0.1:9'; os.environ['RAG_ENABLED']='true'\n"
        "from app.knowledge.runtime import start_runtime\n"
        "import app.knowledge.retrieval, app.main\n"
        "r = start_runtime(); assert r is not None and hasattr(r, 'url')\n"
        "assert 'torch' not in sys.modules, 'torch imported'\n"
        "assert 'FlagEmbedding' not in sys.modules\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-800:]
