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
    assert {n: i for n, i, _ in background.LOOPS} == {"routine-tasks": 300, "sec-monitor": 3600, "market-refresh": 3600, "earnings-monitor": 60}
