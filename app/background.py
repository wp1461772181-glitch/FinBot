"""In-process background loops for the single-VM deployment (BACKGROUND_LOOPS=true).

Replaces the separate launchd jobs: routine tasks every 300 s, SEC monitoring and
market-data refresh every 3600 s. Each loop runs its blocking work in a thread
and a failure in one loop never stops itself or the others. The forecast worker
is not a loop here: the sentinel starts it with ``--once`` (Task 5).
"""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)
ROUTINE_SECONDS = 300
HOURLY_SECONDS = 3600
NEWS_SECONDS = 900         # configured news sources; until this loop the library was only refreshed while a chat turn waited on it
EARNINGS_SECONDS = 60      # picks up events the response-time task missed, due follow-ups, and anything left over from a restart


def enabled() -> bool:
    return os.getenv("BACKGROUND_LOOPS", "false").strip().lower() in {"1", "true", "yes"}


def run_routine_tasks() -> None:
    from .agent_task_runner import tick

    log.info("routine tick: %s", tick())


def run_sec_monitor() -> None:
    from .database import SessionLocal

    if os.getenv("OFFICIAL_MONITOR_MODE", "legacy") == "v2":
        from .official_monitor_v2 import monitor_tick

        with SessionLocal() as db:
            result = monitor_tick(db=db, observed_at=None, max_pages=3, max_filings=1_000)
        from .agent_task_runner import run_alert_hooks

        run_alert_hooks("filings")
    else:
        from .official_monitor import run_once

        with SessionLocal() as db:
            result = run_once(db=db, observed_at=None)
    log.info("sec monitor: %s", result.as_dict())


def run_market_refresh() -> None:
    from .market_data_refresh_worker import refresh_once

    log.info("market refresh: %s", refresh_once())


def run_earnings_monitor() -> None:
    from .earnings_monitor import tick

    done = tick()
    if done["first"] or done["followup"]:
        log.info("earnings monitor: %s", done)


def run_news_poll() -> None:
    """FINBOT_NEWS_BACKGROUND_POLL (default on): keep the configured-news library current so a search rarely needs its own refresh."""
    from .agent_workflow.fp_flags import flag

    if not flag("FINBOT_NEWS_BACKGROUND_POLL", True):
        return
    from .fin_news_engine import background_refresh

    done = background_refresh()
    log.info("news poll: polled=%s saved=%s failed=%s skipped=%s", len(done.get("polled_sources") or []), done.get("saved_count"),
             sorted(done.get("errors") or {}), done.get("skipped"))


LOOPS = (
    ("routine-tasks", ROUTINE_SECONDS, run_routine_tasks),
    ("sec-monitor", HOURLY_SECONDS, run_sec_monitor),
    ("market-refresh", HOURLY_SECONDS, run_market_refresh),
    ("earnings-monitor", EARNINGS_SECONDS, run_earnings_monitor),
    ("news-poll", NEWS_SECONDS, run_news_poll),
)


async def _loop(name: str, interval: float, job) -> None:
    while True:
        try:
            await asyncio.to_thread(job)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one broken loop must not affect the others
            log.exception("background loop %s failed; retrying in %ss", name, interval)
        await asyncio.sleep(interval)


def start(loops=LOOPS) -> list[asyncio.Task]:
    """Create one task per loop on the running event loop."""
    return [asyncio.create_task(_loop(name, interval, job), name=f"bg-{name}") for name, interval, job in loops]


async def stop(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
