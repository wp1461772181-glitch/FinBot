import asyncio

from app import background


def test_loops_isolated_and_survive_errors():
    calls = {"bad": 0, "good": 0}

    def bad():
        calls["bad"] += 1
        raise RuntimeError("boom")

    def good():
        calls["good"] += 1

    async def run():
        tasks = background.start((("bad", 0.01, bad), ("good", 0.01, good)))
        await asyncio.sleep(0.15)
        await background.stop(tasks)

    asyncio.run(run())
    assert calls["bad"] >= 2 and calls["good"] >= 2  # failure did not stop either loop


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("BACKGROUND_LOOPS", raising=False)
    assert not background.enabled()
    monkeypatch.setenv("BACKGROUND_LOOPS", "true")
    assert background.enabled()


def test_default_intervals():
    assert {n: i for n, i, _ in background.LOOPS} == {"routine-tasks": 300, "sec-monitor": 3600, "market-refresh": 3600, "earnings-monitor": 60,
                                                         "news-poll": 900, "release-figures": 600, "company-facts": 21600}


def test_news_poll_runs_one_refresh_and_the_switch_turns_it_off(monkeypatch):
    from app import fin_news_engine as news
    calls = []
    monkeypatch.setattr(news, "background_refresh", lambda: calls.append(1) or {"polled_sources": ["a"], "saved_count": 3, "errors": {}})
    monkeypatch.setenv("FINBOT_NEWS_BACKGROUND_POLL", "off")
    background.run_news_poll()
    assert calls == []
    monkeypatch.setenv("FINBOT_NEWS_BACKGROUND_POLL", "on")
    background.run_news_poll()
    assert calls == [1]


def test_background_refresh_is_skipped_while_another_refresh_runs(monkeypatch):
    from app import fin_news_engine as news
    polled = []
    monkeypatch.setattr(news, "poll_once", lambda *a, **k: polled.append(1) or {"ok": True, "polled_sources": ["a"], "saved_count": 1, "errors": {}})
    assert news._REFRESH_LOCK.acquire(blocking=False)
    try:
        assert news.background_refresh()["skipped"] == "refresh_in_progress" and polled == []
    finally:
        news._REFRESH_LOCK.release()
    assert news.background_refresh()["polled_sources"] == ["a"] and polled == [1]
    assert news._REFRESH_LOCK.acquire(blocking=False)
    news._REFRESH_LOCK.release()


def test_the_company_facts_sweep_refreshes_every_symbol_and_logs_one_line(monkeypatch, caplog):
    from app import company_facts
    monkeypatch.setattr(company_facts, "refresh_all", lambda: {"symbols": 3, "facts": 40, "ratios": 20, "check_failures": [], "errors": {"XYZ": "boom"}})
    with caplog.at_level("INFO", logger="app.background"):
        background.run_company_facts()
    assert [r.getMessage() for r in caplog.records if "company facts" in r.getMessage()] == ["company facts: symbols=3 facts=40 ratios=20 errors=['XYZ']"]
