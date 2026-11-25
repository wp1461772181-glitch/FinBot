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
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text, Boolean, DateTime, String, Text, UniqueConstraint, Uuid, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from .agent_chat_models import AgentConversation, AgentMessage, AgentTelegramMessage
from .database import Base, SessionLocal

log = logging.getLogger(__name__)

RUNNING, DONE, FAILED, STOPPED = "running", "done", "failed", "stopped"
STATUSES = (RUNNING, DONE, FAILED, STOPPED)
STATUS_LABELS = {RUNNING: "进行中", DONE: "完成", FAILED: "失败", STOPPED: "已停"}
CHAT_TURN = "chat_turn"
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


def notify_if_unattended(turn_id: str) -> bool:
    """One line to the owner's channel for a chat turn that ended while nobody was reading (done or failed; a turn the owner stopped
    or whose reader was there is no news): what it was, the outcome, where to read it.  Never the answer.  The item is claimed
    (``notified_at``) in the same transaction that queues the line, so a retry or a second worker sends nothing twice, and a line
    the outbox cannot take (no channel, over the cap) leaves the claim undone.  Source ``work``: counted on its own, not against the bot's cap."""
    from . import agent_telegram as telegram
    with SessionLocal() as db:
        item = db.scalars(select(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id))).first()
        if (item is None or item.status not in NOTICE_OUTCOMES or item.reader_present is not False or item.notified_at is not None):
            return False
        owner, summary, status, reason, conversation_id = item.owner_hash, item.summary, item.status, item.reason, item.conversation_id
    now = datetime.now(UTC)
    with SessionLocal() as db:
        claimed = db.execute(update(AgentWork).where(AgentWork.kind == CHAT_TURN, AgentWork.ref == str(turn_id), AgentWork.notified_at.is_(None))
                             .values(notified_at=now)).rowcount
        if not claimed:
            db.rollback()
            return False
        # One notice at a time per owner, so two turns ending together cannot both pass the count.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"work-notice:{owner}"})
        bot = _notice_bot(db, owner, conversation_id)
        today = db.scalar(select(func.count(func.distinct(func.coalesce(AgentTelegramMessage.group_id, AgentTelegramMessage.id))))
                          .where(AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source == "work",
                                 AgentTelegramMessage.created_at >= telegram._day_start(now)))
        if int(today or 0) >= daily_cap():
            db.rollback()
            return False
        line = f"你问的「{summary}」{NOTICE_OUTCOMES[status]}" + (f"：{reason}" if status == FAILED and reason else "") + "。打开对话查看。"
        try:
            telegram.enqueue(db, owner, bot.id, telegram.render(bot.name, line), source="work", now=now)
        except telegram.NotifyError:
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
