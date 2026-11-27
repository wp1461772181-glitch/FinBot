"""5d-3a: the 「好／不好」 store (app/answer_feedback.py).

Record, change, the same twice, clear; another owner's conversation, a guest, a turn that stopped at a tool round, a reason only with
不好; ``resolve_last`` (the answer he means when he says it in a conversation).  Real PostgreSQL (the test database)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import answer_feedback as feedback
from app.agent_chat_models import AgentConversation, AgentMessage
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine

OWNER = owner_hash("o" * 64)
OTHER = owner_hash("x" * 64)
GUEST = owner_hash("g" * 40)
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def world(disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, feedback.AnswerFeedback.__table__])
    with SessionLocal() as db:
        db.query(feedback.AnswerFeedback).delete()
        db.query(AgentMessage).delete()
        db.query(AgentConversation).delete()
        db.commit()


def conversation(owner=OWNER):
    with SessionLocal() as db:
        row = AgentConversation(owner_hash=owner)
        db.add(row)
        db.commit()
        return row.id


def turn(cid, answer="营收 280 亿美元。\n第二行", *, tool_round_last=False, at=None, turn_id=None):
    """A stored turn: the question, one tool round, then (unless it stopped there) the answer.  Returns (turn_id, answer row id or None)."""
    turn_id = turn_id or uuid.uuid4()
    at = at or NOW
    with SessionLocal() as db:
        seq = (db.query(AgentMessage).filter(AgentMessage.conversation_id == cid).count()) + 1
        rows = [AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq, role="user", content="特斯拉营收多少", created_at=at),
                AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 1, role="assistant", content="先查一下。",
                             tool_calls={"calls": [{"id": "c1", "function": {"name": "query_financials", "arguments": "{}"}}]}, created_at=at),
                AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 2, role="tool", tool_call_id="c1", content="{}", created_at=at)]
        final = None
        if not tool_round_last:
            final = AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 3, role="assistant", content=answer,
                                 tool_calls={"route": "K", "audit": {"terminal_status": "succeeded"}}, created_at=at + timedelta(seconds=2))
            rows.append(final)
        db.add_all(rows)
        db.commit()
        return turn_id, (final.id if final is not None else None)


def count():
    with SessionLocal() as db:
        return db.query(feedback.AnswerFeedback).count()


def test_record_keeps_the_final_answer_by_its_id():
    cid = conversation()
    tid, mid = turn(cid)
    row = feedback.record(OWNER, str(cid), str(tid), "good", "web")
    assert (row["message_id"], row["conversation_id"], row["turn_id"]) == (str(mid), str(cid), str(tid))
    assert (row["verdict"], row["reason"], row["channel"]) == ("good", None, "web")
    assert feedback.of(OWNER, [mid, uuid.uuid4()]) == {str(mid): {"verdict": "good", "reason": None}}


def test_the_other_verdict_changes_it_and_the_same_twice_changes_nothing():
    cid = conversation()
    tid, mid = turn(cid)
    first = feedback.record(OWNER, cid, tid, "good", "web")
    again = feedback.record(OWNER, cid, tid, "good", "chat")
    assert again == first and count() == 1
    changed = feedback.record(OWNER, cid, tid, "bad", "chat", "数据太旧了")
    assert changed["id"] == first["id"] and (changed["verdict"], changed["reason"], changed["channel"]) == ("bad", "数据太旧了", "chat")
    assert datetime.fromisoformat(changed["updated_at"]) > datetime.fromisoformat(first["updated_at"])
    kept = feedback.record(OWNER, cid, tid, "bad", "web")                     # 不好 again with no reason: the reason stays
    assert kept == changed
    replaced = feedback.record(OWNER, cid, tid, "bad", "web", "  没回答我的问题 ")  # a new reason replaces the old
    assert replaced["reason"] == "没回答我的问题" and replaced["verdict"] == "bad"
    back = feedback.record(OWNER, cid, tid, "good", "web")                    # 好 has no reason
    assert (back["verdict"], back["reason"]) == ("good", None) and count() == 1


def test_clear_takes_it_back():
    cid = conversation()
    tid, mid = turn(cid)
    feedback.record(OWNER, cid, tid, "bad", "web", "太长")
    assert feedback.clear(OTHER, cid, tid) is False and count() == 1      # not his to take back
    assert feedback.clear(OWNER, cid, tid) is True and count() == 0
    assert feedback.clear(OWNER, cid, tid) is False
    assert feedback.of(OWNER, [mid]) == {}
    assert feedback.clear(OWNER, "not-a-uuid", tid) is False


def test_not_his_conversation_and_a_guest_record_nothing():
    cid = conversation()
    tid, mid = turn(cid)
    assert feedback.record(OTHER, cid, tid, "good", "web") is None
    assert feedback.record(GUEST, cid, tid, "bad", "web") is None
    guest_line = conversation(GUEST)
    gtid, _ = turn(guest_line)
    assert feedback.record(OWNER, guest_line, gtid, "good", "web") is None       # the turn id of another owner's conversation
    assert feedback.record(OWNER, cid, gtid, "good", "web") is None              # a turn that is not in this conversation
    assert count() == 0


def test_a_turn_that_stopped_at_a_tool_round_has_no_answer():
    cid = conversation()
    tid, mid = turn(cid, tool_round_last=True)
    assert mid is None and feedback.record(OWNER, cid, tid, "bad", "web") is None and count() == 0
    assert feedback.record(OWNER, cid, uuid.uuid4(), "good", "web") is None       # no such turn
    assert feedback.record(OWNER, "nope", "nope", "good", "web") is None


def test_a_reason_goes_only_with_bad_and_nothing_else_is_a_verdict():
    cid = conversation()
    tid, _ = turn(cid)
    for args in (("good", "web", "挺好"), ("great", "web", None), ("bad", "telegram", None), ("bad", "web", "字" * 201), ("bad", "web", 7)):
        with pytest.raises(ValueError, match="invalid_feedback"):
            feedback.record(OWNER, cid, tid, *args)
    assert count() == 0
    assert feedback.record(OWNER, cid, tid, "bad", "web", "   ")["reason"] is None     # a blank reason is no reason
    assert feedback.record(OWNER, cid, tid, "bad", "web", "字" * 200)["reason"] == "字" * 200


def test_resolve_last_is_the_newest_answer_before_the_current_turn():
    cid = conversation()
    old, _ = turn(cid, "旧的回答", at=NOW - timedelta(minutes=10))
    newer, newer_mid = turn(cid, "## 英特尔营收\n" + "很长" * 50, at=NOW - timedelta(minutes=5))
    stopped, _ = turn(cid, tool_round_last=True, at=NOW - timedelta(minutes=2))      # a turn that stopped at a tool round is no answer
    current, _ = turn(cid, "正在写的这条", at=NOW)
    found = feedback.resolve_last(OWNER, cid, current)
    assert (found["message_id"], found["turn_id"], found["conversation_id"]) == (str(newer_mid), str(newer), str(cid))
    assert found["text"] == "## 英特尔营收" and isinstance(found["at"], datetime)
    assert feedback.resolve_last(OWNER, cid, newer)["turn_id"] == str(current)        # only the turn named is left out
    assert feedback.resolve_last(OTHER, cid, current) is None
    lone = conversation()
    only, _ = turn(lone)
    assert feedback.resolve_last(OWNER, lone, only) is None                           # nothing before the first answer
    assert feedback.resolve_last(OWNER, "nope", only) is None
    assert stopped and old


def test_the_first_line_is_clipped_and_the_match_freezes_to_json():
    assert feedback.first_line("\n\n  一行  \n二行") == "一行"
    assert feedback.first_line("字" * 80) == "字" * 59 + "…"
    match = {"message_id": "m", "at": datetime(2026, 11, 27, 1, 0, tzinfo=UTC)}
    assert feedback.frozen(match)["at"] == "2026-11-27T01:00:00+00:00"
    assert feedback.when_text("2026-11-27T01:00:00+00:00") == "11-27 09:00" and feedback.when_text(None) == ""
