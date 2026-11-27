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

from . import model_usage

log = logging.getLogger(__name__)
ROUTINE_SECONDS = 300
HOURLY_SECONDS = 3600
NEWS_SECONDS = 900         # configured news sources; until this loop the library was only refreshed while a chat turn waited on it
RELEASE_FIGURES_SECONDS = 600   # 8-K earnings-release figures for a quarter whose 10-Q/10-K is not filed yet
COMPANY_FACTS_SECONDS = 6 * 3600   # rebuild every company's code-built facts (the hooks do it per symbol as filings are stored; this catches the rest)
MEMORY_JOBS_SECONDS = 600   # the memory calendar looks for a job that is due
WORK_WATCH_SECONDS = 60     # a job started from a card that has ended gets its message within a minute
EARNINGS_SECONDS = 60      # picks up events the response-time task missed, due follow-ups, and anything left over from a restart
BRIEF_SECONDS = 60         # the morning brief looks whether today's is due (08:05–12:00 Beijing) and not written yet


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


def run_release_figures() -> None:
    """FINBOT_RELEASE_FIGURES (default on): read the newest earnings press releases into query_financials' figures."""
    from .agent_workflow.fp_flags import flag

    if not flag("FINBOT_RELEASE_FIGURES", True):
        return
    from .release_figures import run_once

    done = run_once()
    if done["candidates"]:
        log.info("release figures: %s", done)


def run_work_watch() -> None:
    """The end of every job started from a card (analysis, forecast) is told once, in the conversation its card came from (app.work)."""
    from . import work

    posted = work.report_job_ends()
    if posted:
        log.info("work watch: %s end messages", posted)


def run_company_facts() -> None:
    """Every symbol with saved figures, one transaction each.  The loop runs its job when it starts, so this is also the once-at-startup pass."""
    from .company_facts import refresh_all

    try:  # the owner's holdings and research queue decide which companies the archive keeps (a problem here never stops the facts sweep)
        from .archive_subjects import sync_owner_subjects
        from .sentinel_bridge import owner_hash_from_login_config

        owner = owner_hash_from_login_config()
        if owner:
            log.info("archive subjects: %s", sync_owner_subjects(owner))
    except Exception:  # noqa: BLE001
        log.exception("archive subjects sync failed")
    done = refresh_all()
    log.info("company facts: symbols=%s facts=%s ratios=%s errors=%s", done["symbols"], done["facts"], done["ratios"], sorted(done["errors"]))


def run_memory_jobs() -> None:
    """The memory calendar (app.memory_schedule): the jobs that are due run once; a restart neither reruns nor skips one."""
    from . import memory_schedule

    ran = memory_schedule.tick()
    if ran:
        log.info("memory jobs: %s run", ran)


def run_morning_brief() -> None:
    """The kernel's morning brief (app.kernel.brief): written once a Beijing day, from 08:05; a day already written is left alone."""
    from datetime import UTC, datetime

    from .kernel import brief
    from .sentinel_bridge import owner_hash_from_login_config

    owner = owner_hash_from_login_config()
    if not owner:
        return
    row = asyncio.run(brief.run_once(owner, datetime.now(UTC)))
    if row:
        log.info("morning brief %s: %s (%s)", row.get("day"), row.get("outcome"), row.get("delivery") or row.get("reason") or "-")


LOOPS = (
    ("routine-tasks", ROUTINE_SECONDS, run_routine_tasks),
    ("sec-monitor", HOURLY_SECONDS, run_sec_monitor),
    ("market-refresh", HOURLY_SECONDS, run_market_refresh),
    ("earnings-monitor", EARNINGS_SECONDS, run_earnings_monitor),
    ("news-poll", NEWS_SECONDS, run_news_poll),
    ("release-figures", RELEASE_FIGURES_SECONDS, run_release_figures),
    ("company-facts", COMPANY_FACTS_SECONDS, run_company_facts),
    ("work-watch", WORK_WATCH_SECONDS, run_work_watch),
    ("memory-jobs", MEMORY_JOBS_SECONDS, run_memory_jobs),
    ("morning-brief", BRIEF_SECONDS, run_morning_brief),
)


async def _loop(name: str, interval: float, job) -> None:
    while True:
        try:
            # The model-call ledger: whatever this loop's work asks a model, the row names the loop (its own purpose replaces "other").
            with model_usage.purpose("other", job=name):
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
