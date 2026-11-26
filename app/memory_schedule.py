"""A small calendar for the memory jobs (monthly now, quarterly later): each job's last run is kept in ``memory_jobs``, so a restart neither
reruns nor skips one, and two API workers never run the same job (a row claim under ``FOR UPDATE SKIP LOCKED``).

A job is a function named in ``JOBS`` as ``module:function``: ``run(owner_hash, now, last_run_at) -> {"outcome": "done"|"skipped"|"failed",
"reason": str | None, ...}``.  The calendar records the outcome and the reason and works out the next due time.  A job that was due while the box
was down runs once at the next tick (no catch-up of several missed runs); the next one is due a full period after that run.
"""
from __future__ import annotations

import importlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from . import model_usage
from .agent_chat_models import AgentConversation, AgentMessage, MemoryJob
from .agent_recall import owner_message_clause
from .database import SessionLocal

log = logging.getLogger(__name__)

JOBS: dict[str, str] = {"monthly_review": "app.memory_review:run", "quarterly_settle": "app.memory_settle:run"}
JOB_TITLES = {"monthly_review": "每月整理记忆", "quarterly_settle": "每季整理记忆（含看法复盘）"}
ANCHORED = ("quarterly_settle",)        # due at the first calendar anchor after the last run, not a period after it
DEFAULT_ANCHORS = "02-15,05-15,08-15,11-15"
CLAIM_TTL = timedelta(minutes=30)       # a claim older than this is dead: its worker was cut off
RETRY_AFTER = timedelta(hours=6)        # a failed run is tried again after this, never at every tick
OUTCOMES = ("done", "skipped", "failed")
NOT_INSTALLED = "整理程序还没装好"
RAN_BADLY = "整理时出错了"
ODD_RESULT = "整理程序返回了看不懂的结果"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "").strip() or default))
    except ValueError:
        return default


def review_days() -> int:
    return _int_env("FINBOT_MEMORY_REVIEW_DAYS", 30)


def review_min_messages() -> int:
    return _int_env("FINBOT_MEMORY_REVIEW_MIN_MESSAGES", 40)


def quarter_anchors() -> list[tuple[int, int]]:
    """(month, day) pairs of ``FINBOT_MEMORY_QUARTER_ANCHORS`` (UTC dates, sorted); an entry that is not a real date is skipped."""
    found = set()
    for chunk in (os.getenv("FINBOT_MEMORY_QUARTER_ANCHORS", "").strip() or DEFAULT_ANCHORS).split(","):
        try:
            month, day = (int(x) for x in chunk.strip().split("-"))
            datetime(2024, month, day)
            found.add((month, day))
        except ValueError:
            continue
    return sorted(found) or [(2, 15), (5, 15), (8, 15), (11, 15)]


def next_anchor(after: datetime) -> datetime:
    """The first anchor (00:00 UTC of its date) strictly after ``after``."""
    after = after.astimezone(UTC) if after.tzinfo else after.replace(tzinfo=UTC)
    for year in (after.year, after.year + 1):
        for month, day in quarter_anchors():
            try:
                at = datetime(year, month, day, tzinfo=UTC)
            except ValueError:      # 02-29 in a year without one
                continue
            if at > after:
                return at
    raise RuntimeError("no anchor found")


def period(job: str) -> timedelta:
    return timedelta(days=review_days())


def owner_messages_since(owner_hash: str, since: datetime | None) -> int:
    """How many messages the owner himself sent (user rows of his conversations) after ``since``; every one when ``since`` is None."""
    with SessionLocal() as db:
        return _count_messages(db, owner_hash, since)


def _count_messages(db, owner_hash: str, since: datetime | None) -> int:
    query = (select(func.count()).select_from(AgentMessage).join(AgentConversation, AgentConversation.id == AgentMessage.conversation_id)
             .where(AgentConversation.owner_hash == owner_hash, owner_message_clause()))
    if since is not None:
        query = query.where(AgentMessage.created_at > since)
    return int(db.scalar(query) or 0)


def _base(row: MemoryJob) -> datetime:
    return row.last_run_at or row.created_at


def _is_due(db, row: MemoryJob, now: datetime) -> bool:
    if row.retry_at is not None and now < row.retry_at:
        return False
    base = _base(row)
    if row.job in ANCHORED:
        return now >= next_anchor(base)
    if now >= base + period(row.job):
        return True
    return _count_messages(db, row.owner_hash, base) >= review_min_messages()


def register(job: str, owner_hash: str) -> None:
    """Make the calendar know the job for this owner.  Idempotent: a second call changes nothing."""
    with SessionLocal() as db:
        if db.get(MemoryJob, (job, owner_hash)) is None:
            db.add(MemoryJob(job=job, owner_hash=owner_hash, created_at=datetime.now(UTC)))
            try:
                db.commit()
            except Exception:  # noqa: BLE001 - another worker registered it first
                db.rollback()


def register_for_configured_owner() -> None:
    """Startup, where the background loops are on: every job for the site's one owner (nothing when no owner is configured)."""
    from .sentinel_bridge import owner_hash_from_login_config
    owner = owner_hash_from_login_config()
    if not owner:
        return
    for job in JOBS:
        register(job, owner)


def due(now: datetime) -> list[tuple[str, str]]:
    """The (job, owner) pairs due at ``now`` and not held by a live claim."""
    found = []
    with SessionLocal() as db:
        for row in db.scalars(select(MemoryJob).where(MemoryJob.job.in_(list(JOBS)))):
            if row.claimed_at is not None and now - row.claimed_at < CLAIM_TTL:
                continue
            if _is_due(db, row, now):
                found.append((row.job, row.owner_hash))
    return found


def next_due(job: str, owner_hash: str) -> datetime | None:
    """When the calendar alone makes the job due (the message rule can make it earlier)."""
    with SessionLocal() as db:
        row = db.get(MemoryJob, (job, owner_hash))
        return None if row is None else _next_due(row)


def _next_due(row: MemoryJob) -> datetime:
    at = next_anchor(_base(row)) if row.job in ANCHORED else _base(row) + period(row.job)
    return max(at, row.retry_at) if row.retry_at is not None else at


def claim(job: str, owner_hash: str, now: datetime, worker: str | None = None) -> bool:
    """Take the job for one run.  True for exactly one caller: the row is locked with SKIP LOCKED (a worker that finds it locked has lost), and
    once the lock is ours the job must still be due and unclaimed, so a worker that comes late, after the run has finished, finds nothing to do."""
    worker = worker or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        row = db.execute(select(MemoryJob).where(MemoryJob.job == job, MemoryJob.owner_hash == owner_hash)
                         .with_for_update(skip_locked=True)).scalar_one_or_none()
        if row is None:
            return False
        if row.claimed_at is not None and now - row.claimed_at < CLAIM_TTL:
            return False
        if not _is_due(db, row, now):
            return False
        row.claimed_at, row.claimed_by = now, worker
        db.commit()
        return True


def finish(job: str, owner_hash: str, outcome: str, reason: str | None, now: datetime) -> None:
    """Record how the run ended and release the claim.  A done or skipped run is the last run (the next is due a period later); a failed one
    is not, so it is tried again after ``RETRY_AFTER``."""
    with SessionLocal() as db:
        row = db.get(MemoryJob, (job, owner_hash))
        if row is None:
            return
        row.last_outcome, row.last_reason, row.finished_at = outcome, (reason or None) and str(reason)[:200], now
        if outcome == "failed":
            row.retry_at = now + RETRY_AFTER
        else:
            row.last_run_at, row.retry_at = now, None
        row.claimed_at = row.claimed_by = None
        db.commit()


def _call(job: str, owner_hash: str, now: datetime, last_run_at: datetime | None) -> dict:
    """The registered function, imported when it is needed: a module that is not there yet is a failed run, not a broken loop."""
    module_name, _, function = JOBS[job].partition(":")
    try:
        module = importlib.import_module(module_name)
        run = getattr(module, function)
    except (ImportError, AttributeError) as exc:
        if isinstance(exc, ModuleNotFoundError) and exc.name and exc.name != module_name and not module_name.startswith(exc.name):
            raise                                  # the module is there but one of its own imports is not: a real error
        return {"outcome": "failed", "reason": NOT_INSTALLED}
    return run(owner_hash, now, last_run_at)


def _last_run(job: str, owner_hash: str) -> datetime | None:
    with SessionLocal() as db:
        row = db.get(MemoryJob, (job, owner_hash))
        return None if row is None else row.last_run_at


def tick(now: datetime | None = None, runner=None) -> int:
    """Run what is due (called by the ``memory-jobs`` loop, in a thread).  Returns how many runs it made.  A job that raises or answers with
    nonsense is a failed run; the others still go."""
    now = now or datetime.now(UTC)
    runner = runner or _call
    ran = 0
    for job, owner in due(now):
        if not claim(job, owner, now):
            continue
        ran += 1
        outcome, reason = "failed", RAN_BADLY
        try:
            with model_usage.purpose("memory", owner_hash=owner, job=job):
                result = runner(job, owner, now, _last_run(job, owner))
            if isinstance(result, dict) and result.get("outcome") in OUTCOMES:
                outcome, reason = result["outcome"], result.get("reason")
            else:
                reason = ODD_RESULT
        except Exception:  # noqa: BLE001 - one failed job never stops the others
            log.exception("memory job %s failed", job)
        finish(job, owner, outcome, reason, now)
    return ran
