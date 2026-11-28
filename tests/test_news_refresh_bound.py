"""FINBOT_NEWS_REFRESH_BOUND: the refresh before a configured-news search is time-bounded (default on); off is the old unbounded wait."""
import asyncio
import json
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from app import fin_news_engine as engine_mod
from app.agent_chat_models import NewsItem
from app.agent_tool_catalog import definitions
from app.agent_workflow import tools
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>F</title><item>
<title>NVIDIA (NVDA) fresh headline</title><link>https://finance.yahoo.com/news/fresh-1</link>
<pubDate>Thu, 19 Nov 2026 09:00:00 GMT</pubDate><description>NVDA fresh.</description></item></channel></rss>"""


@pytest.fixture
def news_db(monkeypatch, disposable_database, tmp_path):
    Base.metadata.create_all(engine, tables=[NewsItem.__table__])
    with SessionLocal() as db:
        db.query(NewsItem).delete()
        db.add(NewsItem(source_id="yahoo-finance-rss", source_name="Y", dedupe_key="old", title="NVDA stored headline",
                        url="https://example.com/old", summary="stored", published_at=datetime.now(UTC) - timedelta(hours=3),
                        fetched_at=datetime.now(UTC) - timedelta(hours=2), tickers=["NVDA"], keywords_hit=[], language="en"))
        db.commit()
    cfg_path = tmp_path / "news_sources.yaml"
    cfg_path.write_text(engine_mod.config_path().read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("FINBOT_NEWS_SOURCES_CONFIG", str(cfg_path))
    engine_mod.clear_runtime_state()
    cfg = engine_mod.load_config(cfg_path)
    for src in cfg["sources"]:
        src["enabled"] = src["id"] == "yahoo-finance-rss"
    engine_mod.save_config(cfg, cfg_path)
    release = threading.Event()
    yield release
    release.set()                                   # let any background refresh finish before the next test
    assert engine_mod._REFRESH_LOCK.acquire(timeout=10)
    engine_mod._REFRESH_LOCK.release()
    engine_mod.set_http_fetcher(None)


def _blocking_fetcher(release):
    def fetch(url, headers, timeout):
        release.wait(20)
        return 200, RSS
    return fetch


def test_slow_refresh_returns_in_time_with_stored_news(news_db, monkeypatch):
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "on")
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_TIMEOUT_SECONDS", "1")
    engine_mod.set_http_fetcher(_blocking_fetcher(news_db))
    start = time.monotonic()
    res = engine_mod.search_configured_news(tickers=["NVDA"], refresh_first=True)
    assert time.monotonic() - start < 6
    assert res["ok"] and [i["title"] for i in res["items"]] == ["NVDA stored headline"]
    assert res["meta"]["refreshed"] is False and res["meta"]["refresh_note"] == "refresh_timed_out"
    assert res["meta"]["latest_fetched_at"] and res["meta"]["latest_fetched_at"] < datetime.now(UTC).isoformat()
    # a second search while the first refresh is still running does not start another
    start = time.monotonic()
    second = engine_mod.search_configured_news(tickers=["NVDA"], refresh_first=True)
    assert time.monotonic() - start < 1 and second["meta"]["refresh_note"] == "refresh_in_progress" and second["items"]
    # the background run is not abandoned: once released it saves what it fetched
    news_db.set()
    assert engine_mod._REFRESH_LOCK.acquire(timeout=10)
    engine_mod._REFRESH_LOCK.release()
    assert "NVIDIA (NVDA) fresh headline" in [i["title"] for i in engine_mod.search_configured_news(tickers=["NVDA"])["items"]]


def test_fast_refresh_behaves_as_before(news_db, monkeypatch):
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "on")
    engine_mod.set_http_fetcher(lambda url, headers, timeout: (200, RSS))
    res = engine_mod.search_configured_news(tickers=["NVDA"], refresh_first=True)
    assert res["meta"]["refreshed"] is True and "refresh_note" not in res["meta"] and "latest_fetched_at" not in res["meta"]
    assert {i["title"] for i in res["items"]} == {"NVDA stored headline", "NVIDIA (NVDA) fresh headline"}


def test_failed_refresh_is_reported_not_fatal(news_db, monkeypatch):
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "on")
    engine_mod.set_http_fetcher(lambda url, headers, timeout: (403, "Forbidden"))
    res = engine_mod.search_configured_news(tickers=["NVDA"], refresh_first=True)
    assert res["ok"] and res["items"] and res["meta"]["refreshed"] is False and res["meta"]["refresh_note"] == "refresh_failed"


def test_switch_off_waits_as_before(news_db, monkeypatch):
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "off")
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_TIMEOUT_SECONDS", "1")

    def slow(url, headers, timeout):
        time.sleep(2)
        return 200, RSS
    engine_mod.set_http_fetcher(slow)
    start = time.monotonic()
    res = engine_mod.search_configured_news(tickers=["NVDA"], refresh_first=True)
    assert time.monotonic() - start >= 2
    assert res["meta"]["refreshed"] is True and "refresh_note" not in res["meta"]


def test_tool_call_has_total_limit(news_db, monkeypatch):
    def hang(**kwargs):
        time.sleep(4)
        return {"ok": True, "items": [], "data": []}
    monkeypatch.setattr(engine_mod, "search_configured_news", hang)
    ctx = AgentRuntimeContext("custom", "test", "dummy")
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "on")
    monkeypatch.setenv("FINBOT_NEWS_SEARCH_TOOL_TIMEOUT_SECONDS", "1")
    async def timed():                              # asyncio.run itself waits for the abandoned worker thread at exit
        start = time.monotonic()
        out = await tools.invoke("search_configured_news", {"query": "nvda"}, ctx)
        return out, time.monotonic() - start
    out, took = asyncio.run(timed())
    assert took < 3 and out["ok"] is False and out["error_code"] == "tool_timeout"
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "off")
    monkeypatch.setattr(engine_mod, "search_configured_news", lambda **kw: {"ok": True, "items": [], "data": []})
    assert asyncio.run(tools.invoke("search_configured_news", {"query": "nvda"}, ctx))["ok"] is True


def test_description_names_the_refresh_fields_only_when_on(monkeypatch):
    monkeypatch.setenv("FINBOT_PH2_NEWS_RANK", "off")
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "off")
    old = definitions()["search_configured_news"].description
    monkeypatch.setenv("FINBOT_NEWS_REFRESH_BOUND", "on")
    new = definitions()["search_configured_news"].description
    assert "refresh_note" not in old and new.startswith(old) and "refresh_timed_out" in new and "latest_fetched_at" in new


