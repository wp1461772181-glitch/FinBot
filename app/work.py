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


def end_turn(turn_id: str, status: str, reason: str | None = None, *, reader_present: bool | None = None) -> bool:
    """Close a running chat turn.  True when this call closed it; False when it was not running (already closed by the
    turn's own end, or by the sweep) or was never recorded."""
    if status not in (DONE, FAILED, STOPPED):
        raise ValueError(f"a turn ends as done, failed or stopped, not {status!r}")
    with SessionLocal() as db:
        result = db.execute(update(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id),
                                                    AgentWork.status == RUNNING)
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
        ids = db.scalars(select(AgentWork.id).where(AgentWork.kind == CHAT_TURN, AgentWork.status == RUNNING,
                                                    AgentWork.started_at <= now).order_by(AgentWork.started_at)).all()
    closed = 0
    for work_id in ids:
        try:
            with SessionLocal() as db:
                row = db.execute(update(AgentWork).where(AgentWork.id == work_id, AgentWork.status == RUNNING)
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


def _item(kind: str, ref: str, title: str, status: str, *, started=None, ended=None, next_run=None, failure=None, conversation_id=None) -> dict:
    return {"kind": kind, "id": ref, "title": title, "status": status, "status_label": STATUS_LABELS[status], "started_at": _iso(started),
            "ended_at": _iso(ended), "next_run_at": _iso(next_run), "failure": failure,
            "conversation_id": str(conversation_id) if conversation_id else None}


JOB_ACTIONS = {"forecast": "预测", "analyze": "分析"}
JOB_FAILURE = "过程中出错了，可以让我重试"
JOB_STATES = {"running": RUNNING, "succeeded": DONE, "partially_succeeded": DONE, "failed": FAILED}
JOB_PAGES = {"forecast": "结果在「预测」页。", "analyze": "结果在「资料」页。"}


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
        log.exception("reading the live status of an action request failed")
        db.rollback()
        return {"status": request["status"], "job_status": request["status"], "result": {}}


def _what(consent, request: dict) -> str:
    title = " ".join(str((consent.display or {}).get("title") or "").split()) if consent is not None else ""
    return title[:60] or f"{JOB_ACTIONS.get(request['action'], request['action'])}任务"


def list_for(owner: str, *, now: datetime | None = None, limit: int = LIST_LIMIT) -> list[dict]:
    """The owner's work in one list, newest first, at most ``limit``: chat turns (running, and failed or stopped within a day), routines
    (queued for their time, running, or failed within a day), jobs started from a card (live status, running or ended within a day) and
    the archive builds he asked for.  Another owner's work is never in it.  Each item: kind, id, a short Chinese title, status
    (running/done/failed/stopped, or queued) with its label, started_at, ended_at, next_run_at, failure (one Chinese sentence), conversation_id."""
    now = now or datetime.now(UTC)
    since = now - RECENT
    items: list[dict] = []
    with SessionLocal() as db:
        for row in db.scalars(select(AgentWork).where(AgentWork.owner_hash == owner, AgentWork.kind == CHAT_TURN,
                                                      (AgentWork.status == RUNNING) | (AgentWork.status.in_((FAILED, STOPPED)) & (AgentWork.started_at >= since)))
                              .order_by(AgentWork.started_at.desc()).limit(limit)):
            items.append(_item("chat", row.ref, f"回答：{row.summary}", row.status, started=row.started_at, ended=row.ended_at,
                               failure=row.reason if row.status != RUNNING else None, conversation_id=row.conversation_id))
        try:
            requests = db.execute(text("""SELECT * FROM agent_action_requests WHERE owner_hash=:owner AND job_id IS NOT NULL
                                          AND (created_at >= :since OR status='running') ORDER BY created_at DESC LIMIT 60"""),
                                  {"owner": owner, "since": since}).mappings().all()
        except Exception:  # noqa: BLE001 - the ledger table is made by a migration; without it there are no card jobs
            db.rollback()
            requests = []
        for request in requests:
            request = dict(request)
            consent = _card_of(db, request)
            if consent is None:
                continue
            state = JOB_STATES.get(_job_state(db, request)["status"], RUNNING)
            if state != RUNNING and (request["updated_at"] or request["created_at"]) < since:
                continue
            items.append(_item("job", str(request["id"]), _what(consent, request), state, started=request["created_at"],
                               ended=None if state == RUNNING else (request["updated_at"] or request["created_at"]),
                               failure=JOB_FAILURE if state == FAILED else None, conversation_id=consent.conversation_id))
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


def report_job_ends(now: datetime | None = None) -> int:
    """The watcher pass (``background``, every minute): every job started from a card that has ended and has not been reported gets one short
    assistant message in the conversation its card came from, and, when it ran over 60 seconds and nobody is in that conversation, the channel
    notice (the same ``work`` source and daily cap as a chat turn's).  The claim is one ``agent_work`` row per request (kind and ref unique),
    taken in the transaction that writes the message: two workers or a restart cannot post twice, and a pass that fails leaves it for the next.
    Returns how many it posted."""
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        try:
            requests = [dict(r) for r in db.execute(text("""SELECT * FROM agent_action_requests WHERE job_id IS NOT NULL AND created_at >= :since
                                                            ORDER BY created_at LIMIT 100"""), {"since": now - WATCH_WINDOW}).mappings().all()]
        except Exception:  # noqa: BLE001
            db.rollback()
            return 0
        done = set(db.scalars(select(AgentWork.ref).where(AgentWork.kind == CARD_JOB, AgentWork.ref.in_([str(r["id"]) for r in requests]))))
    posted = 0
    for request in requests:
        if str(request["id"]) in done:
            continue
        try:
            with SessionLocal() as db:
                state = _job_state(db, request)
                outcome = JOB_STATES.get(state["status"])
                consent = _card_of(db, request) if outcome in (DONE, FAILED) else None
                if consent is not None and _post_end(db, request, state, outcome, consent, now):
                    posted += 1
        except Exception:  # noqa: BLE001 - one job's trouble never stops the others; the next pass tries again
            log.exception("reporting the end of action request %s failed", request.get("id"))
    return posted


def _post_end(db, request: dict, state: dict, outcome: str, consent, now: datetime) -> bool:
    from sqlalchemy.dialects.postgresql import insert
    from . import agent_bots
    from .agent_tasks import line_busy
    try:
        conversation_id = uuid.UUID(str(consent.conversation_id))
    except ValueError:
        return False
    agent_bots.ensure_default_bot(request["owner_hash"])   # before the row lock below: it moves conversations under the bot in a session of its own
    line = db.query(AgentConversation).filter(AgentConversation.id == conversation_id).with_for_update().first()
    what = _what(consent, request)
    if line is not None and line_busy(db, line.id, now):
        db.rollback()
        return False                       # a turn is being answered there: the next pass
    started = request["created_at"]
    duration = now - (started if started.tzinfo else started.replace(tzinfo=UTC))
    claim = db.execute(insert(AgentWork).values(id=uuid.uuid4(), kind=CARD_JOB, ref=str(request["id"]), owner_hash=request["owner_hash"],
                                                conversation_id=conversation_id, summary=what, status=outcome,
                                                reason=JOB_FAILURE if outcome == FAILED else None, started_at=started, ended_at=now)
                       .on_conflict_do_nothing(index_elements=["kind", "ref"]).returning(AgentWork.id)).first()
    if claim is None:
        db.rollback()
        return False                       # reported already (another worker, an earlier pass)
    if line is None:
        db.commit()                        # the conversation is gone: nothing to post into, and nothing to retry
        return False
    recent = db.scalar(select(func.max(AgentMessage.created_at)).where(AgentMessage.conversation_id == line.id))
    reading = bool(db.scalar(select(func.count()).select_from(AgentWork).where(AgentWork.conversation_id == line.id, AgentWork.kind == CHAT_TURN,
                                                                             AgentWork.status == RUNNING))) \
        or (recent is not None and now - (recent if recent.tzinfo else recent.replace(tzinfo=UTC)) < QUIET_FOR)
    _post_end_message(db, line, request, outcome, what)
    if duration > LONG_JOB and not reading:
        line_text = f"你让我做的「{what}」{'已完成' if outcome == DONE else '失败了'}。打开对话查看。"
        if _send_notice(db, request["owner_hash"], line.id, line_text, now):
            db.execute(update(AgentWork).where(AgentWork.id == claim[0]).values(notified_at=now, reader_present=False))
    db.commit()
    return True


def _post_end_message(db, line, request: dict, outcome: str, what: str) -> None:
    """The end message: a short row opened like a task's post (so the web shows the pair) and the assistant's one sentence."""
    sequence = db.scalar(select(func.coalesce(func.max(AgentMessage.sequence), 0)).where(AgentMessage.conversation_id == line.id))
    turn = uuid.uuid4()
    if outcome == DONE:
        text_out = f"你让我做的「{what}」已完成。{JOB_PAGES.get(request['action'], '')}"
    else:
        text_out = f"你让我做的「{what}」失败了（{JOB_FAILURE}）。"
    db.add(AgentMessage(conversation_id=line.id, turn_id=turn, sequence=sequence + 1, role="user", content=f"{WORK_END_HEAD}「{what}」", status="complete"))
    db.add(AgentMessage(conversation_id=line.id, turn_id=turn, sequence=sequence + 2, role="assistant", content=text_out, status="complete",
                        tool_calls={"work_end": {"request_id": str(request["id"]), "outcome": outcome}, "audit": {}}))
    line.updated_at = func.now()
