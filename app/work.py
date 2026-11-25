"""A durable record of the work FinBot does: every chat turn from its start to its end, and the startup sweep that closes
the turns a restart cut off.

Statuses are exactly ``running``, ``done``, ``failed``, ``stopped`` (shown 进行中、完成、失败、已停).  A failed or stopped
item carries a one-sentence Chinese reason a person can read.  The API's chat endpoint writes the rows; only the API's
startup runs the sweep (the bridges and the sentinel do not).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text, Boolean, DateTime, String, Text, UniqueConstraint, Uuid, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from .agent_chat_models import AgentConversation, AgentMessage, AgentTelegramMessage
from .agent_recall import WORK_END_HEAD   # the row an end message opens with in the conversation (like agent_tasks.POST_HEAD): not the owner's question
from .database import Base, SessionLocal

log = logging.getLogger(__name__)

RUNNING, DONE, FAILED, STOPPED = "running", "done", "failed", "stopped"
QUEUED = "queued"      # in the list only: a piece of work that has not started (a routine waiting for its time, an archive build in line)
STATUSES = (RUNNING, DONE, FAILED, STOPPED)
STATUS_LABELS = {RUNNING: "进行中", DONE: "完成", FAILED: "失败", STOPPED: "已停", QUEUED: "排队中"}
CHAT_TURN = "chat_turn"
CARD_JOB = "card_job"    # the claim row of a job started from a card whose end has been reported (kind + ref unique: once)
LIST_LIMIT = 30
RECENT = timedelta(days=1)
QUIET_FOR = timedelta(seconds=120)   # a conversation with a message newer than this has someone in it
LONG_JOB = timedelta(seconds=60)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
RESTART_REASON = "系统重启打断了这一轮，没有答完。"
SUMMARY_CHARS = 80


class AgentWork(Base):
    """One piece of work.  A chat turn is keyed by (kind, ref) = ("chat_turn", its turn id): the key is unique, so a claim on
    an item (the end of a turn, the sweep's message) can happen once however many workers race for it."""
    __tablename__ = "agent_work"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ref: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RUNNING)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reader_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # at the end: was a client reading the answer?
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # the channel notice's claim: set once
    __table_args__ = (UniqueConstraint("kind", "ref", name="uq_agent_work_kind_ref"),)


def _head(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS - 1] + "…"


def start_turn(owner: str, conversation_id: str, turn_id: str, text: str) -> None:
    """Record that a chat turn is running.  Called once the user's row is stored; a repeat of the same turn is a no-op."""
    with SessionLocal() as db:
        if db.scalar(select(AgentWork.id).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id))) is not None:
            return
        db.add(AgentWork(kind=CHAT_TURN, ref=str(turn_id), owner_hash=owner, conversation_id=uuid.UUID(str(conversation_id)),
                         summary=_head(text), status=RUNNING))
        db.commit()


DEFAULT_CONCURRENT = 3


def concurrent_limit() -> int:
    """How many chat turns one owner has running at once (``FINBOT_CONCURRENT_WORK``, default 3); the next ones wait in line."""
    try:
        return max(1, int(os.environ.get("FINBOT_CONCURRENT_WORK", DEFAULT_CONCURRENT)))
    except ValueError:
        return DEFAULT_CONCURRENT


def _count(db, owner: str, status: str) -> int:
    return int(db.scalar(select(func.count()).select_from(AgentWork).where(AgentWork.owner_hash == owner, AgentWork.kind == CHAT_TURN,
                                                                           AgentWork.status == status)) or 0)


def _slot_lock(db, owner: str) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"work-slots:{owner}"})


def enter_turn(owner: str, conversation_id: str, turn_id: str, text_: str, limit: int | None = None) -> tuple[str, int]:
    """Record a chat turn that wants to start: ``running`` when the owner has a free slot and nobody waits in front of it, else ``queued``
    (first in, first out).  Returns (status, ahead): ahead is how many pieces of work are in front of a queued turn.  A repeat of the same
    turn gives its present state."""
    limit = limit or concurrent_limit()
    with SessionLocal() as db:
        _slot_lock(db, owner)
        item = db.scalars(select(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id))).first()
        if item is not None:
            return item.status, 0
        running, queued = _count(db, owner, RUNNING), _count(db, owner, QUEUED)
        status = RUNNING if running < limit and queued == 0 else QUEUED
        db.add(AgentWork(kind=CHAT_TURN, ref=str(turn_id), owner_hash=owner, conversation_id=uuid.UUID(str(conversation_id)),
                         summary=_head(text_), status=status))
        db.commit()
        return status, (0 if status == RUNNING else running + queued)


def promote(turn_id: str, limit: int | None = None) -> tuple[bool, int]:
    """A queued turn asks for its slot: (True, 0) once it is the oldest in line and a slot is free (it is running from then on);
    otherwise (False, ahead).  A turn that is already running is (True, 0); one that is gone or ended is (False, 0)."""
    limit = limit or concurrent_limit()
    with SessionLocal() as db:
        item = db.scalars(select(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id))).first()
        if item is None:
            return False, 0
        if item.status == RUNNING:
            return True, 0
        if item.status != QUEUED:
            return False, 0
        _slot_lock(db, item.owner_hash)
        db.refresh(item)
        if item.status != QUEUED:
            return item.status == RUNNING, 0
        running = _count(db, item.owner_hash, RUNNING)
        older = int(db.scalar(select(func.count()).select_from(AgentWork).where(
            AgentWork.owner_hash == item.owner_hash, AgentWork.kind == CHAT_TURN, AgentWork.status == QUEUED,
            AgentWork.started_at < item.started_at)) or 0)
        if running < limit and older == 0:
            item.status, item.started_at = RUNNING, func.now()
            db.commit()
            return True, 0
        return False, running + older


def end_turn(turn_id: str, status: str, reason: str | None = None, *, reader_present: bool | None = None) -> bool:
    """Close a running (or queued) chat turn.  True when this call closed it; False when it was not open (already closed by the
    turn's own end, or by the sweep) or was never recorded."""
    if status not in (DONE, FAILED, STOPPED):
        raise ValueError(f"a turn ends as done, failed or stopped, not {status!r}")
    with SessionLocal() as db:
        result = db.execute(update(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id),
                                                    AgentWork.status.in_((RUNNING, QUEUED)))
                            .values(status=status, reason=reason if status != DONE else None, reader_present=reader_present,
                                    ended_at=func.now()))
        db.commit()
        return bool(result.rowcount)


def interrupted_message(started_at: datetime) -> str:
    when = (started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)).astimezone(LOCAL_TZ)
    return f"上一轮在 {when:%H:%M} 被系统重启打断了，没有答完；要我接着做吗？"


def sweep_interrupted(now: datetime | None = None) -> int:
    """Close the chat turns still ``running`` that started before ``now`` (the API's startup: nothing started before it can
    still be running in this process): each becomes ``failed`` with the restart reason, and its conversation gets one short
    assistant message.  Claiming a row (running to failed) and writing its message are one transaction, so a second worker or
    a second pass never posts twice, and a failed write leaves the row running for the next start.

    The message is the cut-off turn's own assistant row, status ``failed`` (an ordinary failed turn for every reader)."""
    # Single API process (the box runs one): a second worker's sweep would also close the first one's live turns.
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        ids = db.scalars(select(AgentWork.id).where(AgentWork.kind == CHAT_TURN, AgentWork.status.in_((RUNNING, QUEUED)),
                                                    AgentWork.started_at <= now).order_by(AgentWork.started_at)).all()
    closed = 0
    for work_id in ids:
        try:
            with SessionLocal() as db:
                row = db.execute(update(AgentWork).where(AgentWork.id == work_id, AgentWork.status.in_((RUNNING, QUEUED)))
                                 .values(status=FAILED, reason=RESTART_REASON, reader_present=None, ended_at=func.now())
                                 .returning(AgentWork.conversation_id, AgentWork.started_at, AgentWork.ref)).first()
                if row is None:
                    db.rollback()
                    continue
                conversation_id, started_at, ref = row
                line = (db.query(AgentConversation).filter(AgentConversation.id == conversation_id).with_for_update().first()
                        if conversation_id is not None else None)
                if line is not None:
                    turn = uuid.UUID(ref)
                    rows = db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == line.id, AgentMessage.turn_id == turn)
                                      .order_by(AgentMessage.sequence)).all()
                    if rows and rows[-1].role == "assistant" and rows[-1].status in ("complete", "failed", "cancelled") \
                            and not (isinstance(rows[-1].tool_calls, dict) and rows[-1].tool_calls.get("calls")):
                        # The turn's own answer was stored (a crash between it and the item's end): the turn finished, say nothing.
                        final = rows[-1].status
                        db.execute(update(AgentWork).where(AgentWork.id == work_id)
                                   .values(status={"complete": DONE, "cancelled": STOPPED}.get(final, FAILED),
                                           reason=None if final == "complete" else RESTART_REASON))
                        db.commit()
                        continue
                    sequence = db.scalar(select(func.coalesce(func.max(AgentMessage.sequence), 0))
                                         .where(AgentMessage.conversation_id == line.id))
                    # The message is the cut-off turn's own answer row (failed), after whatever the turn had stored: to every reader it is
                    # one ordinary failed turn (the web list, the history, the next turn's unfinished note, the line's busy check).
                    db.add(AgentMessage(conversation_id=line.id, turn_id=turn, sequence=sequence + 1, role="assistant",
                                        content=interrupted_message(started_at), status="failed",
                                        tool_calls={"work_interrupted": {"work_id": str(work_id)}, "audit": {}}))
                    line.updated_at = func.now()
                db.commit()
                closed += 1
        except Exception:
            log.exception("sweeping the interrupted turn %s failed", work_id)
    return closed


DEFAULT_DAILY_CAP = 10
NOTICE_OUTCOMES = {DONE: "已经答完", FAILED: "没答完"}


def daily_cap() -> int:
    """How many work notices one day may send (``FINBOT_WORK_DAILY_CAP``, default 10): a count of its own, apart from the bot's notify cap."""
    try:
        return max(0, int(os.environ.get("FINBOT_WORK_DAILY_CAP", DEFAULT_DAILY_CAP)))
    except ValueError:
        return DEFAULT_DAILY_CAP


def _send_notice(db, owner: str, conversation_id, line: str, now: datetime) -> bool:
    """Queue one line for the owner's channel (source ``work``) inside the caller's transaction: under the owner's preference, the
    work daily count and one notice at a time per owner.  False (nothing queued) when over the cap or no channel can take it."""
    from . import agent_telegram as telegram
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"work-notice:{owner}"})
    bot = _notice_bot(db, owner, conversation_id)
    today = db.scalar(select(func.count(func.distinct(func.coalesce(AgentTelegramMessage.group_id, AgentTelegramMessage.id))))
                      .where(AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source == "work",
                             AgentTelegramMessage.created_at >= telegram._day_start(now)))
    if int(today or 0) >= daily_cap():
        return False
    try:
        telegram.enqueue(db, owner, bot.id, telegram.render(bot.name, line), source="work", now=now)
    except telegram.NotifyError:
        return False
    return True


def notify_if_unattended(turn_id: str) -> bool:
    """One line to the owner's channel for a chat turn that ended while nobody was reading (done or failed; a turn the owner stopped
    or whose reader was there is no news): what it was, the outcome, where to read it.  Never the answer.  The item is claimed
    (``notified_at``) in the same transaction that queues the line, so a retry or a second worker sends nothing twice, and a line
    the outbox cannot take (no channel, over the cap) leaves the claim undone.  Source ``work``: counted on its own, not against the bot's cap."""
    with SessionLocal() as db:
        item = db.scalars(select(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id))).first()
        if (item is None or item.status not in NOTICE_OUTCOMES or item.reader_present is not False or item.notified_at is not None):
            return False
        owner, summary, status, reason, conversation_id = item.owner_hash, item.summary, item.status, item.reason, item.conversation_id
    now = datetime.now(UTC)
    with SessionLocal() as db:
        claimed = db.execute(update(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id), AgentWork.notified_at.is_(None))
                             .values(notified_at=now)).rowcount
        line = f"你问的「{summary}」{NOTICE_OUTCOMES[status]}" + (f"：{reason}" if status == FAILED and reason else "") + "。打开对话查看。"
        if not claimed or not _send_notice(db, owner, conversation_id, line, now):
            db.rollback()
            return False
        db.commit()
    return True


def _notice_bot(db, owner: str, conversation_id):
    """The bot whose line the turn was on (so the notice carries its name), else the owner's default bot."""
    from . import agent_bots
    from .agent_chat_models import AgentBot
    line = db.get(AgentConversation, conversation_id) if conversation_id is not None else None
    bot = db.get(AgentBot, line.bot_id) if line is not None and line.bot_id is not None else None
    if bot is not None and bot.owner_hash == owner:
        return bot
    return db.get(AgentBot, agent_bots.ensure_default_bot(owner).id)


# --- the owner's list of work ------------------------------------------------------------------------------------------

def _iso(value) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def _local(value) -> str | None:
    """``MM-DD HH:MM`` in the owner's zone, so the model need not convert the UTC strings itself."""
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(LOCAL_TZ).strftime("%m-%d %H:%M")


def _item(kind: str, ref: str, title: str, status: str, *, started=None, ended=None, next_run=None, failure=None, conversation_id=None) -> dict:
    return {"kind": kind, "id": ref, "title": title, "status": status, "status_label": STATUS_LABELS[status], "started_at": _iso(started),
            "started_local": _local(started), "ended_at": _iso(ended), "ended_local": _local(ended), "next_run_at": _iso(next_run),
            "next_run_local": _local(next_run), "failure": failure, "conversation_id": str(conversation_id) if conversation_id else None}


JOB_ACTIONS = {"forecast": "预测", "analyze": "分析"}
JOB_STATES = {"running": RUNNING, "succeeded": DONE, "partially_succeeded": DONE, "failed": FAILED}
JOB_PAGES = {"forecast": "结果在「预测」页。", "analyze": "结果在「资料」页。"}
# Why a job did not finish, in words a person can read (never the code).  ``blocked_data`` is not an error: the job found it could not be done.
BLOCKED_REASONS = {"no_content": "这份材料没有可用的正文，这次没有做", "source_snapshot_missing": "没找到这份材料的原文，这次没有做",
                   "analysis_model_unconfigured": "分析用的模型还没配置，这次没有做"}
BLOCKED_DEFAULT = "数据不够，这次没有做"
FAILED_REASONS = {"provider_error": "模型服务出错", "invalid_model_output": "模型的输出没通过核对", "processor_error": "处理过程出错"}
FAILED_DEFAULT = "过程中出错了"


def job_reason(status: str | None, code: str | None) -> tuple[str, bool]:
    """(the short Chinese reason, whether it is a block rather than an error) for a job's own status and error code; the generic sentence only
    when the job gives nothing."""
    code = str(code or "")
    if status == "blocked_data":
        return BLOCKED_REASONS.get(code, BLOCKED_DEFAULT), True
    if "timeout" in code or "timed_out" in code:
        return "超时", False
    return FAILED_REASONS.get(code, FAILED_DEFAULT), False


def _job_facts(db, request: dict) -> dict:
    """The job's own record, by kind: the start (``started_at``, else ``created_at``), the end (``completed_at``), its status and its error code
    (forecast: ``forecast_jobs_v2.error_type``; analysis: ``material_analysis_jobs.safe_error_code``).  A time the job table does not have is None:
    nothing is guessed."""
    kind, job_id = request.get("job_kind"), request.get("job_id")
    table, code = {"forecast": ("forecast_jobs_v2", "error_type"), "analysis": ("material_analysis_jobs", "safe_error_code")}.get(kind, (None, None))
    if table is None or job_id is None:
        return {}
    try:
        row = db.execute(text(f"SELECT started_at, created_at, completed_at, status, {code} AS code FROM {table} WHERE id=:id"), {"id": job_id}).mappings().first()
    except Exception:  # noqa: BLE001
        db.rollback()
        _log_once(("facts", str(request.get("id"))), "reading the job record of action request %s failed", request.get("id"))
        return {}
    return {} if row is None else {"started": row["started_at"] or row["created_at"], "ended": row["completed_at"], "status": row["status"], "code": row["code"]}


_LOGGED: set = set()


def _log_once(key, message: str, *args) -> None:
    """One traceback per trouble, not one a minute."""
    if key not in _LOGGED and len(_LOGGED) < 1000:
        _LOGGED.add(key)
        log.exception(message, *args)


def _card_of(db, request: dict):
    """The card (consent) that started an action request: its key is ``<consent id>.<operation index>``.  None for a request made without one."""
    from .agent_workflow.models import AgentConsent
    head = str(request.get("request_key") or "").rsplit(".", 1)[0]
    try:
        consent = db.get(AgentConsent, uuid.UUID(head))
    except ValueError:
        return None
    return consent if consent is not None and consent.owner_hash == request["owner_hash"] else None


def _job_state(db, request: dict) -> dict:
    from .agent_workflow import actions
    try:
        return actions._status(db, request)
    except Exception:  # noqa: BLE001 - a job table that cannot be read: the ledger's own status stands
        _log_once(("state", str(request.get("id"))), "reading the live status of action request %s failed", request.get("id"))
        db.rollback()
        return {"status": request["status"], "job_status": request["status"], "result": {}}


def _what(consent, request: dict) -> str:
    title = " ".join(str((consent.display or {}).get("title") or "").split()) if consent is not None else ""
    title = title[:60] or f"{JOB_ACTIONS.get(request['action'], request['action'])}任务"
    if consent is not None and len(consent.operations or []) > 1:     # one card, several operations: say which
        try:
            title += f"（第 {int(str(request['request_key']).rsplit('.', 1)[1]) + 1} 项）"
        except (ValueError, IndexError):
            pass
    return title


def list_for(owner: str, *, now: datetime | None = None, limit: int = LIST_LIMIT) -> list[dict]:
    """The owner's work in one list, newest first, at most ``limit``: chat turns (running, and failed or stopped within a day), routines
    (queued for their time, running, or failed within a day), jobs started from a card (live status, running or ended within a day) and
    the archive builds he asked for.  Another owner's work is never in it.  Each item: kind, id, a short Chinese title, status
    (running/done/failed/stopped, or queued) with its label, started_at, ended_at (None when the job has no end time of its own),
    next_run_at (each with a ``_local`` time in the owner's zone), failure (one Chinese sentence), conversation_id."""
    now = now or datetime.now(UTC)
    since = now - RECENT
    items: list[dict] = []
    with SessionLocal() as db:
        for row in db.scalars(select(AgentWork).where(AgentWork.owner_hash == owner, AgentWork.kind == CHAT_TURN,
                                                      (AgentWork.status.in_((RUNNING, QUEUED))) | (AgentWork.status.in_((FAILED, STOPPED)) & (AgentWork.started_at >= since)))
                              .order_by(AgentWork.started_at.desc()).limit(limit)):
            items.append(_item("chat", row.ref, f"回答：{row.summary}", row.status, started=row.started_at, ended=row.ended_at,
                               failure=row.reason if row.status not in (RUNNING, QUEUED) else None, conversation_id=row.conversation_id))
        try:
            requests = db.execute(text("""SELECT * FROM agent_action_requests WHERE owner_hash=:owner AND job_id IS NOT NULL
                                          AND (created_at >= :since OR status='running') ORDER BY created_at DESC LIMIT 60"""),
                                  {"owner": owner, "since": since}).mappings().all()
        except Exception:  # noqa: BLE001 - the ledger table is made by a migration; without it there are no card jobs
            db.rollback()
            _log_once(("ledger", "list"), "reading the action ledger failed")
            requests = []
        for request in requests:
            request = dict(request)
            consent = _card_of(db, request)
            if consent is None:
                continue
            live = _job_state(db, request)
            state = JOB_STATES.get(live["status"], RUNNING)
            facts = _job_facts(db, request)
            ended = facts.get("ended") if state != RUNNING else None
            if state != RUNNING and ended is not None and ended < since:
                continue
            if state != RUNNING and ended is None and request["created_at"] < since:
                continue
            failure = job_reason(facts.get("status"), facts.get("code"))[0] if state == FAILED else None
            items.append(_item("job", str(request["id"]), _what(consent, request), state, started=facts.get("started") or request["created_at"],
                               ended=ended, failure=failure, conversation_id=consent.conversation_id))
    from . import agent_tasks
    for task in agent_tasks.list_tasks(owner):
        if not task["enabled"] or task["finished"]:
            continue
        last = datetime.fromisoformat(task["last_run_at"]) if task["last_run_at"] else None
        nxt = datetime.fromisoformat(task["next_run_at"]) if task["next_run_at"] else None
        title = f"例行任务：{task['name']}"
        if task["last_status"] == "running":
            items.append(_item("routine", task["id"], title, RUNNING, started=last))
        elif task["last_status"] == "failed" and last is not None and last >= since:
            items.append(_item("routine", task["id"], title, FAILED, started=last, ended=last, next_run=nxt, failure="这次例行任务没有跑成功"))
        else:
            items.append(_item("routine", task["id"], title, QUEUED, next_run=nxt))
    items.extend(_archive_items(owner, now, since))
    items.sort(key=lambda item: item["started_at"] or _iso(now), reverse=True)
    return items[:max(1, int(limit))]


def _archive_items(owner: str, now: datetime, since: datetime) -> list[dict]:
    """The archive builds the owner asked for (a company he mentioned), in line, running, or finished within a day.  Archive subjects belong to
    the one owner of the site, so another login sees none."""
    from .models import ArchiveSubject
    from .sentinel_bridge import owner_hash_from_login_config
    try:
        if owner_hash_from_login_config() != owner:
            return []
    except Exception:  # noqa: BLE001
        return []
    found = []
    with SessionLocal() as db:
        for subject in db.scalars(select(ArchiveSubject).where(ArchiveSubject.asked_at.is_not(None), ArchiveSubject.asked_at >= now - timedelta(days=7))):
            title = f"建 {subject.symbol} 的资料库"
            if subject.build_status == "queued":
                found.append(_item("archive", subject.symbol, title, QUEUED))
            elif subject.build_status == "building":
                found.append(_item("archive", subject.symbol, title, RUNNING, started=subject.build_started_at))
            elif subject.build_status in ("ok", "failed", "partial") and subject.build_finished_at is not None and subject.build_finished_at >= since:
                failed = subject.build_status != "ok"
                found.append(_item("archive", subject.symbol, title, FAILED if failed else DONE, started=subject.build_started_at,
                                   ended=subject.build_finished_at, failure="资料库没有建完整，可以让我重试" if failed else None))
    return found


# --- the end of a job started from a card -------------------------------------------------------------------------------

WATCH_WINDOW = timedelta(days=1)
WATCH_BATCH = 50          # unclaimed card jobs one pass looks at, newest first: a backlog cannot starve a new job
BASELINE = "baseline"     # agent_work kind of the watcher's durable start marker (ref ``card_jobs``)
GIVEN_UP = "不会再汇报这件事："


def _claim(db, request: dict, *, status: str, reason: str | None, conversation_id=None, summary: str = "", started=None, ended=None):
    """The one claim row of an action request (kind ``card_job``, ref its id).  None when it already exists (another pass, another worker).
    A claim is final: a job reported failed that were ever requeued and then succeeded would not be reported again (not reachable today: failed and
    blocked jobs are terminal)."""
    from sqlalchemy.dialects.postgresql import insert
    return db.execute(insert(AgentWork).values(id=uuid.uuid4(), kind=CARD_JOB, ref=str(request["id"]), owner_hash=request["owner_hash"],
                                               conversation_id=conversation_id, summary=summary, status=status, reason=reason,
                                               started_at=started or request["created_at"], ended_at=ended or datetime.now(UTC))
                      .on_conflict_do_nothing(index_elements=["kind", "ref"]).returning(AgentWork.id)).first()


def _unclaimed(db, since: datetime, limit: int) -> list[dict]:
    return [dict(r) for r in db.execute(text("""SELECT r.* FROM agent_action_requests r WHERE r.job_id IS NOT NULL AND r.created_at >= :since
        AND NOT EXISTS (SELECT 1 FROM agent_work w WHERE w.kind = 'card_job' AND w.ref = CAST(r.id AS text))
        ORDER BY r.created_at DESC LIMIT :limit"""), {"since": since, "limit": limit}).mappings().all()]


def _baseline(now: datetime) -> bool:
    """True when this call made the watcher's first pass ever: the marker row and a silent claim for every job that has already ended (no message,
    no notice) are one transaction, so a second process either waits and sees them or is the one that made them.  Only jobs that end after this
    are reported."""
    from sqlalchemy.dialects.postgresql import insert
    with SessionLocal() as db:
        made = db.execute(insert(AgentWork).values(id=uuid.uuid4(), kind=BASELINE, ref="card_jobs", owner_hash="", summary="", status=DONE,
                                                   started_at=now, ended_at=now).on_conflict_do_nothing(index_elements=["kind", "ref"])
                          .returning(AgentWork.id)).first()
        if made is None:
            db.rollback()
            return False
        for request in _unclaimed(db, now - WATCH_WINDOW, 1000):
            if JOB_STATES.get(_job_state(db, request)["status"]) in (DONE, FAILED):
                _claim(db, request, status=DONE, reason="已在监视开始前结束，不再汇报", summary="baseline")
        db.commit()
    return True


def report_job_ends(now: datetime | None = None) -> int:
    """The watcher pass (``background``, every minute): every job started from a card that has ended and has not been reported gets one short
    assistant message in the conversation its card came from, and, when it ran over 60 seconds (by the job's own start and end) and nobody is in that
    conversation, the channel notice (the same ``work`` source and daily cap as a chat turn's).  The first pass ever only records a baseline (jobs
    that ended before it are not reported).  The claim is one ``agent_work`` row per request (kind and ref unique), taken in the transaction that
    writes the message: two workers or a restart cannot post twice, and a pass that fails leaves it for the next.  A request that can never be
    posted (no card, a conversation that is gone or archived) is claimed as given up so it is not visited again.  Returns how many it posted."""
    now = now or datetime.now(UTC)
    try:
        if _baseline(now):
            return 0
        with SessionLocal() as db:
            requests = _unclaimed(db, now - WATCH_WINDOW, WATCH_BATCH)
    except Exception:  # noqa: BLE001 - the ledger or work table may be missing (a migration not run): nothing to watch
        _log_once(("ledger", "watch"), "the work watcher could not read the action ledger")
        return 0
    posted = 0
    for request in requests:
        try:
            with SessionLocal() as db:
                consent = _card_of(db, request)
                if consent is None:
                    _claim(db, request, status=STOPPED, reason=GIVEN_UP + "不是从卡片发起的")
                    db.commit()
                    continue
                state = _job_state(db, request)
                outcome = JOB_STATES.get(state["status"])
                if outcome in (DONE, FAILED) and _post_end(db, request, outcome, consent, now):
                    posted += 1
        except Exception:  # noqa: BLE001 - one job's trouble never stops the others; the next pass tries again
            _log_once(("report", str(request.get("id"))), "reporting the end of action request %s failed", request.get("id"))
    return posted


def _post_end(db, request: dict, outcome: str, consent, now: datetime) -> bool:
    from . import agent_bots
    from .agent_tasks import line_busy
    try:
        conversation_id = uuid.UUID(str(consent.conversation_id))
    except ValueError:
        _claim(db, request, status=STOPPED, reason=GIVEN_UP + "找不到发起的对话")
        db.commit()
        return False
    agent_bots.ensure_default_bot(request["owner_hash"])   # before the row lock below: it moves conversations under the bot in a session of its own
    line = db.query(AgentConversation).filter(AgentConversation.id == conversation_id).with_for_update().first()
    if line is None or line.archived_at is not None or line.owner_hash != request["owner_hash"]:
        _claim(db, request, status=STOPPED, reason=GIVEN_UP + "发起的对话已不在")
        db.commit()
        return False
    if line_busy(db, line.id, now):
        db.rollback()
        return False                       # a turn is being answered there: the next pass
    what = _what(consent, request)
    facts = _job_facts(db, request)
    started, ended = facts.get("started") or request["created_at"], facts.get("ended")
    reason, blocked = job_reason(facts.get("status"), facts.get("code")) if outcome == FAILED else (None, False)
    claim = _claim(db, request, status=outcome, reason=reason, conversation_id=conversation_id, summary=what, started=started, ended=ended)
    if claim is None:
        db.rollback()
        return False                       # reported already (another worker, an earlier pass)
    recent = db.scalar(select(func.max(AgentMessage.created_at)).where(AgentMessage.conversation_id == line.id))
    reading = bool(db.scalar(select(func.count()).select_from(AgentWork).where(AgentWork.conversation_id == line.id, AgentWork.kind == CHAT_TURN,
                                                                             AgentWork.status == RUNNING))) \
        or (recent is not None and now - (recent if recent.tzinfo else recent.replace(tzinfo=UTC)) < QUIET_FOR)
    _post_end_message(db, line, request, outcome, what, reason, blocked)
    # The notice: the job ran over 60 seconds by its own record (no end time on record: not counted as long) and nobody is in the conversation.
    long_job = ended is not None and started is not None and ended - (started if started.tzinfo else started.replace(tzinfo=UTC)) > LONG_JOB
    if long_job and not reading:
        verdict = "已完成" if outcome == DONE else ("没有做成：" + reason if blocked else "失败了：" + reason)
        if _send_notice(db, request["owner_hash"], line.id, f"你让我做的「{what}」{verdict}。打开对话查看。", now):
            db.execute(update(AgentWork).where(AgentWork.id == claim[0]).values(notified_at=now, reader_present=False))
    db.commit()
    return True


def _post_end_message(db, line, request: dict, outcome: str, what: str, reason: str | None, blocked: bool) -> None:
    """The end message: a head row marked as the system's (``WORK_END_HEAD`` and the note routine posts carry, so neither the web nor the model takes it
    for the owner's words) and the assistant's one sentence."""
    sequence = db.scalar(select(func.coalesce(func.max(AgentMessage.sequence), 0)).where(AgentMessage.conversation_id == line.id))
    turn = uuid.uuid4()
    if outcome == DONE:
        text_out = f"你让我做的「{what}」已完成。{JOB_PAGES.get(request['action'], '')}"
    elif blocked:
        text_out = f"你让我做的「{what}」没有做成：{reason}。"
    else:
        text_out = f"你让我做的「{what}」失败了（{reason}）。可以让我重试。"
    from .agent_tasks import POST_NOTE
    db.add(AgentMessage(conversation_id=line.id, turn_id=turn, sequence=sequence + 1, role="user", content=f"{WORK_END_HEAD}「{what}」{POST_NOTE}", status="complete"))
    db.add(AgentMessage(conversation_id=line.id, turn_id=turn, sequence=sequence + 2, role="assistant", content=text_out, status="complete",
                        tool_calls={"work_end": {"request_id": str(request["id"]), "outcome": outcome}, "audit": {}}))
    line.updated_at = func.now()
