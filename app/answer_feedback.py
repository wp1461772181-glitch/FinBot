"""「好／不好」 on an answer (5d-3a).

The owner's verdict on one answer the assistant gave: the final answer of a turn (the last assistant row of that turn with text, never a
tool round) in one of his conversations, kept by that row's id.  One row per owner and answer: pressing the other verdict changes it, the
same verdict again changes nothing except that a new reason replaces the old one; ``clear`` takes his verdict back (the web's second
press on the same thumb).  A reason (one line, at most ``REASON_MAX`` characters) goes only with 「不好」.  ``resolve_last`` finds the
answer he means when he says it in a conversation (「刚才那个回答不好」).  The backstage's 回答 tab reads ``of``.  Nothing here holds a
key or a credential.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

VERDICTS = ("good", "bad")
CHANNELS = ("web", "chat")            # chat: said in a conversation, on any channel (the kernel's rate_answer)
VERDICT_WORDS = {"good": "好", "bad": "不好"}
REASON_MAX = 200
LINE_MAX = 60                         # how much of the answer's first line names it
RESOLVE_ROWS = 200                    # assistant rows read back to find the previous answer (tool rounds included)
BEIJING = ZoneInfo("Asia/Shanghai")


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"
    __table_args__ = (UniqueConstraint("owner_hash", "message_id", name="uq_answer_feedback_message"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)                    # the stored assistant answer row
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    verdict: Mapped[str] = mapped_column(String(4), nullable=False)                        # good | bad
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)                         # only with bad
    channel: Mapped[str] = mapped_column(String(4), nullable=False)                        # web | chat: where the last change came from


def as_dict(row: AnswerFeedback) -> dict:
    return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None, "message_id": str(row.message_id),
            "conversation_id": str(row.conversation_id), "turn_id": str(row.turn_id), "verdict": row.verdict, "reason": row.reason,
            "channel": row.channel}


def _uuid(value) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def clean_reason(reason) -> str | None:
    """The reason as one line of at most ``REASON_MAX`` characters; None for no reason (absent, blank)."""
    if reason is None:
        return None
    if not isinstance(reason, str):
        raise ValueError("invalid_feedback")
    line = " ".join(reason.split())
    if len(line) > REASON_MAX:
        raise ValueError("invalid_feedback")
    return line or None


def _is_answer(row) -> bool:
    """An assistant row with text that is not a tool request (a tool round can carry a line of narration)."""
    record = row.tool_calls if isinstance(row.tool_calls, dict) else {}
    return row.role == "assistant" and bool((row.content or "").strip()) and not record.get("calls")


def _owned(db, owner_hash: str, conversation_id: uuid.UUID) -> bool:
    from .agent_chat_models import AgentConversation
    return db.scalar(select(AgentConversation.id).where(AgentConversation.id == conversation_id,
                                                        AgentConversation.owner_hash == owner_hash)) is not None


def answer_of(owner_hash: str, conversation_id, turn_id):
    """The final answer row of one turn of his conversation (the last assistant row of the turn with text); None when there is none:
    a turn with no answer, one that stopped at a tool round, another owner's conversation, an id that is not one."""
    from .agent_chat_models import AgentMessage
    cid, tid = _uuid(conversation_id), _uuid(turn_id)
    if cid is None or tid is None:
        return None
    with SessionLocal() as db:
        if not _owned(db, owner_hash, cid):
            return None
        rows = db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == cid, AgentMessage.turn_id == tid,
                                                     AgentMessage.role == "assistant").order_by(AgentMessage.sequence.desc())).all()
        if not rows or not _is_answer(rows[0]):
            return None                       # the turn's last assistant row is not an answer: it stopped at a tool round, or never wrote one
        db.expunge(rows[0])
        return rows[0]


def record(owner_hash: str, conversation_id, turn_id, verdict: str, channel: str, reason: str | None = None, *, only_if_absent: bool = False) -> dict | None:
    """Store his verdict on the final answer of one turn and return the row; None when the turn has no answer of his.

    The other verdict replaces the one there (a reason goes only with 不好, so 好 clears it); the same verdict again changes nothing,
    except that a reason given now replaces the old one.  ``ValueError("invalid_feedback")`` for a verdict, a channel or a reason that
    is not one (a reason with 好, a reason over ``REASON_MAX``).  ``only_if_absent``: keep a verdict already there and return it unchanged
    (the browser's one-time upload of an old note must not overwrite one he gave since, in a conversation or on another device)."""
    if verdict not in VERDICTS or channel not in CHANNELS:
        raise ValueError("invalid_feedback")
    reason = clean_reason(reason)
    if reason is not None and verdict != "bad":
        raise ValueError("invalid_feedback")
    answer = answer_of(owner_hash, conversation_id, turn_id)
    if answer is None:
        return None
    where = (AnswerFeedback.owner_hash == owner_hash, AnswerFeedback.message_id == answer.id)
    for _ in range(2):
        now = datetime.now(UTC)
        with SessionLocal() as db:
            row = db.scalar(select(AnswerFeedback).where(*where).with_for_update())
            if row is None:
                row = AnswerFeedback(owner_hash=owner_hash, message_id=answer.id, conversation_id=answer.conversation_id, turn_id=answer.turn_id,
                                     verdict=verdict, reason=reason, channel=channel, created_at=now, updated_at=now)
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:          # another press wrote the row first: update that one
                    db.rollback()
                    continue
                db.refresh(row)
                return as_dict(row)
            if only_if_absent:
                return as_dict(row)
            # The other verdict brings its own reason (none for 好); the same verdict keeps the old reason unless a new one is given.
            new_reason = reason if row.verdict != verdict or reason is not None else row.reason
            if row.verdict != verdict or new_reason != row.reason:
                row.verdict, row.reason, row.channel, row.updated_at = verdict, new_reason, channel, now
                db.commit()
                db.refresh(row)
            return as_dict(row)
    raise RuntimeError("answer_feedback_conflict")


def clear(owner_hash: str, conversation_id, turn_id) -> bool:
    """Take back his verdict on the answer of one turn; whether there was one to take back."""
    cid, tid = _uuid(conversation_id), _uuid(turn_id)
    if cid is None or tid is None:
        return False
    with SessionLocal() as db:
        rows = db.scalars(select(AnswerFeedback).where(AnswerFeedback.owner_hash == owner_hash, AnswerFeedback.conversation_id == cid,
                                                       AnswerFeedback.turn_id == tid)).all()
        for row in rows:
            db.delete(row)
        db.commit()
        return bool(rows)


def of(owner_hash: str, message_ids) -> dict[str, dict]:
    """``{message id: {"verdict", "reason"}}`` for the answers among ``message_ids`` that have his verdict."""
    ids = [i for i in (_uuid(value) for value in message_ids or ()) if i is not None]
    if not ids:
        return {}
    with SessionLocal() as db:
        rows = db.execute(select(AnswerFeedback.message_id, AnswerFeedback.verdict, AnswerFeedback.reason)
                          .where(AnswerFeedback.owner_hash == owner_hash, AnswerFeedback.message_id.in_(ids))).all()
    return {str(message_id): {"verdict": verdict, "reason": reason} for message_id, verdict, reason in rows}


# --- which answer he means (said in a conversation) -------------------------------------------------------------------------

def first_line(text) -> str:
    """The first line of an answer with text, clipped to ``LINE_MAX`` characters (an ellipsis says it was clipped)."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    line = lines[0] if lines else ""
    return line if len(line) <= LINE_MAX else line[:LINE_MAX - 1] + "…"


def resolve_last(owner_hash: str, conversation_id, before_turn) -> dict | None:
    """The newest answer of his conversation that is not the one being written now (the turn ``before_turn``):
    ``{"message_id", "conversation_id", "turn_id", "text", "at"}``, or None when the conversation has none yet or is not his."""
    from .agent_chat_models import AgentMessage
    cid = _uuid(conversation_id)
    if cid is None:
        return None
    current = _uuid(before_turn)
    with SessionLocal() as db:
        if not _owned(db, owner_hash, cid):
            return None
        query = select(AgentMessage).where(AgentMessage.conversation_id == cid, AgentMessage.role == "assistant")
        if current is not None:
            query = query.where(AgentMessage.turn_id != current)
        seen: set = set()
        # the newest rows are enough: the answer before this turn is among the last few turns' rows
        for row in db.scalars(query.order_by(AgentMessage.sequence.desc()).limit(RESOLVE_ROWS)):
            if row.turn_id in seen:
                continue                  # a turn's earlier rows: its last assistant row decided already
            seen.add(row.turn_id)
            if _is_answer(row):
                return {"message_id": str(row.id), "conversation_id": str(row.conversation_id), "turn_id": str(row.turn_id),
                        "text": first_line(row.content), "at": row.created_at}
    return None


def frozen(match: dict) -> dict:
    """``match`` as it is frozen into an operation: plain JSON (the time as an ISO string)."""
    at = match.get("at")
    return {**match, "at": at.astimezone(UTC).isoformat() if isinstance(at, datetime) else at}


def when_text(at) -> str:
    """Beijing time of a match, ``%m-%d %H:%M``; empty when it has none."""
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return ""
    if not isinstance(at, datetime):
        return ""
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(BEIJING).strftime("%m-%d %H:%M")
