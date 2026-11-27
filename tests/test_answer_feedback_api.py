"""5d-3a: the web's 「好／不好」 on an answer: PUT / DELETE /agent-chat/conversations/{cid}/turns/{tid}/feedback (owner only), and the
history API handing each answer's verdict to the page.  Real PostgreSQL for the writes; the history page is scripted."""
import asyncio
import uuid
from datetime import UTC, datetime

import pytest

import app.agent_chat_stream as stream
from app import answer_feedback as feedback
from app.agent_chat_models import AgentConversation, AgentMessage
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine

OWNER = "o" * 64
OWNER_HASH = owner_hash(OWNER)
GUEST = "g" * 64
H = {"X-Chat-Session": OWNER}


@pytest.fixture(autouse=True)
def world(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, feedback.AnswerFeedback.__table__])
    import app.agent_chat_identity as identity
    monkeypatch.setattr(identity, "owner_credential_matches", lambda value: value == OWNER)
    with SessionLocal() as db:
        db.query(feedback.AnswerFeedback).delete()
        db.commit()


def answered(owner=OWNER_HASH, text="营收 280 亿美元。"):
    """A conversation with one answered turn: (conversation id, turn id, answer id)."""
    turn_id = uuid.uuid4()
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=owner)
        db.add(conversation)
        db.flush()
        final = AgentMessage(conversation_id=conversation.id, turn_id=turn_id, sequence=2, role="assistant", content=text,
                             tool_calls={"route": "K"}, created_at=datetime.now(UTC))
        db.add_all([AgentMessage(conversation_id=conversation.id, turn_id=turn_id, sequence=1, role="user", content="特斯拉营收"), final])
        db.commit()
        return str(conversation.id), str(turn_id), str(final.id)


def path(cid, tid):
    return f"/agent-chat/conversations/{cid}/turns/{tid}/feedback"


def test_put_records_changes_and_delete_takes_it_back(client):
    cid, tid, mid = answered()
    response = client.put(path(cid, tid), headers=H, json={"verdict": "bad"})
    assert response.status_code == 200 and response.json() == {"turn_id": tid, "message_id": mid, "verdict": "bad", "reason": None}
    response = client.put(path(cid, tid), headers=H, json={"verdict": "bad", "reason": "数据太旧了"})       # the reason field's 发送
    assert response.json()["reason"] == "数据太旧了"
    assert client.put(path(cid, tid), headers=H, json={"verdict": "good"}).json()["verdict"] == "good"
    with SessionLocal() as db:
        row = db.query(feedback.AnswerFeedback).one()
        assert (str(row.message_id), row.verdict, row.reason, row.channel) == (mid, "good", None, "web")
    response = client.delete(path(cid, tid), headers=H)
    assert response.status_code == 200 and response.json()["cleared"] is True and response.json()["verdict"] is None
    assert client.delete(path(cid, tid), headers=H).json()["cleared"] is False       # taking back one there is not is no error
    assert feedback.of(OWNER_HASH, [mid]) == {}


def test_only_the_owner_may_rate(client):
    cid, tid, mid = answered()
    for headers in ({"X-Chat-Session": GUEST}, {}):
        assert client.put(path(cid, tid), headers=headers, json={"verdict": "good"}).status_code == 403
        assert client.delete(path(cid, tid), headers=headers).status_code == 403
    assert feedback.of(OWNER_HASH, [mid]) == {}


def test_a_turn_with_no_answer_of_his_is_404_and_a_bad_body_is_422(client):
    cid, tid, _ = answered(owner=owner_hash("x" * 64))            # another owner's conversation
    assert client.put(path(cid, tid), headers=H, json={"verdict": "good"}).status_code == 404
    mine, my_turn, _ = answered()
    assert client.put(path(mine, str(uuid.uuid4())), headers=H, json={"verdict": "good"}).status_code == 404
    assert client.put(path(mine, "not-a-turn"), headers=H, json={"verdict": "good"}).status_code == 404
    for body in ({"verdict": "great"}, {"verdict": "good", "reason": "挺好"}, {"verdict": "bad", "reason": "字" * 201}, {"verdict": "bad", "extra": 1}, {}):
        assert client.put(path(mine, my_turn), headers=H, json=body).status_code == 422, body


def history(monkeypatch, credential, given):
    async def page(*_a, **_k):
        return {"messages": [
            {"id": "u1", "role": "user", "content": "苹果利润多少", "status": "complete", "turn_id": "t1", "tool_calls": None},
            {"id": "a1", "role": "assistant", "content": "利润是 88 美元。", "status": "complete", "turn_id": "t1", "tool_calls": {"route": "K"}},
            {"id": "u2", "role": "user", "content": "那营收呢", "status": "complete", "turn_id": "t2", "tool_calls": None},
            {"id": "a2", "role": "assistant", "content": "营收是 99 美元。", "status": "complete", "turn_id": "t2", "tool_calls": {"route": "K"}},
        ], "has_more": False, "next_before": None}

    asked = []
    monkeypatch.setattr(stream, "owned_message_page", page)
    monkeypatch.setattr(feedback, "of", lambda owner, ids: asked.append((owner, list(ids))) or given)
    messages = asyncio.run(stream.get_messages("conversation", before=None, limit=20, x_chat_session=credential))["messages"]
    return {m["id"]: m for m in messages if m["role"] == "assistant"}, asked


def test_the_history_carries_each_answers_feedback_for_the_owner(monkeypatch):
    answers, asked = history(monkeypatch, OWNER, {"a1": {"verdict": "bad", "reason": "太旧"}})
    assert answers["a1"]["feedback"] == {"verdict": "bad", "reason": "太旧"} and "feedback" not in answers["a2"]
    assert asked == [(OWNER_HASH, ["a1", "a2"])]


def test_a_guest_history_reads_no_feedback_and_a_failed_read_still_loads(monkeypatch):
    answers, asked = history(monkeypatch, GUEST, {"a1": {"verdict": "good", "reason": None}})
    assert asked == [] and all("feedback" not in m for m in answers.values())

    def broken(owner, ids):
        raise RuntimeError("database gone")
    monkeypatch.setattr(feedback, "of", broken)
    messages = asyncio.run(stream.get_messages("conversation", before=None, limit=20, x_chat_session=OWNER))["messages"]
    assert len(messages) == 4 and all("feedback" not in m for m in messages)


def test_the_browsers_one_time_upload_keeps_a_verdict_the_server_already_has(client):
    """Review of 5d-3a: a page loaded before he rated the answer elsewhere must not overwrite that verdict with its old browser note."""
    cid, tid, mid = answered()
    assert client.put(path(cid, tid), headers=H, json={"verdict": "good", "if_absent": True}).json()["verdict"] == "good"    # none yet: stored
    client.put(path(cid, tid), headers=H, json={"verdict": "bad", "reason": "没说日期"})                                       # he changes it since
    kept = client.put(path(cid, tid), headers=H, json={"verdict": "good", "if_absent": True}).json()
    assert (kept["verdict"], kept["reason"]) == ("bad", "没说日期")
    assert feedback.of(OWNER_HASH, [mid])[mid] == {"verdict": "bad", "reason": "没说日期"}
