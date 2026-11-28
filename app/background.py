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
KNOWLEDGE_INDEX_SECONDS = 120   # a pass syncs a page per source kind and indexes up to box_index.MAX_CHUNKS chunks
HOURLY_SECONDS = 3600
NEWS_SECONDS = 900         # configured news sources; until this loop the library was only refreshed while a chat turn waited on it
RELEASE_FIGURES_SECONDS = 600   # 8-K earnings-release figures for a quarter whose 10-Q/10-K is not filed yet
COMPANY_FACTS_SECONDS = 6 * 3600   # rebuild every company's code-built facts (the hooks do it per symbol as filings are stored; this catches the rest)
MEMORY_JOBS_SECONDS = 600   # the memory calendar looks for a job that is due
WORK_WATCH_SECONDS = 60     # a job started from a card that has ended gets its message within a minute
EARNINGS_SECONDS = 60      # picks up events the response-time task missed, due follow-ups, and anything left over from a restart
BRIEF_SECONDS = 60         # the morning brief looks whether today's is due (08:05–12:00 Beijing) and not written yet
SELFCHECK_SECONDS = 60     # the missed-alert check looks whether today's is due (07:45–12:00 Beijing) and not run yet
PREP_SECONDS = 60         # the evening preparation looks whether tonight's is due (20:00–23:00 Beijing) and not written yet
EARNINGS_CALENDAR_SECONDS = 6 * 3600   # the calendar itself refetches once a day (earnings_calendar.STALE_AFTER)


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


def run_earnings_calendar() -> None:
    """The earnings calendar and consensus (app.earnings_calendar): refetched when the last fetch is older than 20 hours; no key, no fetch."""
    from . import earnings_calendar
    from .sentinel_bridge import owner_hash_from_login_config

    owner = owner_hash_from_login_config()
    if not owner:
        return
    done = earnings_calendar.refresh(owner)
    if not done["skipped"]:
        log.info("earnings calendar: symbols=%s rows=%s errors=%s", done["symbols"], done["rows"], done["errors"])


def run_earnings_prep() -> None:
    """The kernel's evening-before preparation (app.kernel.prep): once a Beijing evening, 20:00–23:00, when a company reports within half a day."""
    from datetime import UTC, datetime

    from .kernel import prep
    from .sentinel_bridge import owner_hash_from_login_config

    owner = owner_hash_from_login_config()
    if not owner:
        return
    row = asyncio.run(prep.run_once(owner, datetime.now(UTC)))
    if row:
        log.info("earnings prep %s: %s (%s)", row["day"], row["outcome"], row.get("symbols"))


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


def run_selfcheck() -> None:
    """The kernel's missed-alert check (app.kernel.selfcheck): run once a Beijing day, from 07:45; a day already run is left alone."""
    from datetime import UTC, datetime

    from .kernel import selfcheck
    from .sentinel_bridge import owner_hash_from_login_config

    owner = owner_hash_from_login_config()
    if not owner:
        return
    row = selfcheck.run_once(owner, datetime.now(UTC))
    if row:
        log.info("missed-alert check %s: %s (%s found, errors %s)", row.get("day"), row.get("outcome"), len(row.get("findings") or []),
                 sorted((row.get("checked") or {}).get("errors") or {}))


_KNOWLEDGE_PARTS = None
_TOLD: set = set()


def _tell_once(message: str) -> None:
    if message not in _TOLD:
        _TOLD.add(message)
        log.info(message)


def run_knowledge_index() -> None:
    """The knowledge index's write side on the box (app.knowledge.box_index): new sources synced, chunked, embedded and written to
    pgvector.  Off with FINBOT_KNOWLEDGE_INDEX=off; does nothing where its tokenizer and the two login files are not (a checkout, CI)."""
    from .agent_workflow.fp_flags import flag
    from .knowledge import box_index

    if not flag("FINBOT_KNOWLEDGE_INDEX", True):
        return
    if box_index.shadow_writing_live():
        _tell_once("knowledge index not run: the shadow database must not write the live vector table")
        return
    global _KNOWLEDGE_PARTS
    if _KNOWLEDGE_PARTS is None:       # loaded once (a 17 MB tokenizer, an HTTP client) and kept; looked for again while missing
        _KNOWLEDGE_PARTS, why = box_index.load_parts()
        if _KNOWLEDGE_PARTS is None:
            _tell_once(f"knowledge index not run: {why}")
            return
    result = box_index.run_once(parts=_KNOWLEDGE_PARTS)
    if result.get("skipped"):
        _tell_once(f"knowledge index not run: {result['skipped']}")
        return
    if result.get("embedding_down"):
        log.warning("knowledge index: embedding service unavailable (%s); trying again next pass", result["embedding_down"])
        return
    indexed = result.get("indexed") or {}
    accepted = sum((v or {}).get("accepted") or 0 for v in (result.get("synced") or {}).values())
    if accepted or indexed.get("indexed") or indexed.get("failed"):
        log.info("knowledge index: %s new documents, %s chunks indexed, %s failed", accepted, indexed.get("indexed", 0), indexed.get("failed", 0))


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
    ("duty-selfcheck", SELFCHECK_SECONDS, run_selfcheck),
    ("earnings-calendar", EARNINGS_CALENDAR_SECONDS, run_earnings_calendar),
    ("earnings-prep", PREP_SECONDS, run_earnings_prep),
    ("knowledge-index", KNOWLEDGE_INDEX_SECONDS, run_knowledge_index),
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
