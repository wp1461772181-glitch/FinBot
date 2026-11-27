"""5d-3c: the weekly self-check (``app.quality_review``): his 不好 answers of the week, sorted by the judge model (real PostgreSQL)."""
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import quality_review as qr
from app.agent_chat_models import AgentConversation, AgentMessage
from app.answer_feedback import AnswerFeedback
from app.database import Base, SessionLocal, engine

OWNER, OTHER = "q" * 64, "x" * 64
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def world(disposable_database, monkeypatch):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, AnswerFeedback.__table__, qr.QualityReport.__table__])
    with SessionLocal() as db:
        for model in (qr.QualityReport, AnswerFeedback, AgentMessage, AgentConversation):
            db.query(model).delete()
        db.commit()
    monkeypatch.delenv("FINBOT_QUALITY_DAYS", raising=False)
    yield


def answered(question, answer, *, owner=OWNER, tools=(), failed=(), verdict=None, reason=None, rated=None):
    """One turn: his question, a tool round (``tools``; ``failed`` of them answer ok false), the answer; and his verdict on it."""
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=owner)
        db.add(conversation)
        db.flush()
        turn = uuid.uuid4()
        rows = [AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=1, role="user", content=question, created_at=NOW)]
        calls = [{"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": "{}"}} for i, name in enumerate(tools)]
        if calls:
            rows.append(AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=2, role="assistant", content="", tool_calls={"calls": calls}, created_at=NOW))
            for i, name in enumerate(tools):
                result = {"ok": False, "data": [], "error_code": "invalid_arguments"} if name in failed else {"ok": True, "data": []}
                rows.append(AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=3 + i, role="tool", tool_call_id=f"c{i}",
                                         content=json.dumps(result), created_at=NOW))
        final = AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=20, role="assistant", content=answer, created_at=NOW)
        rows.append(final)
        db.add_all(rows)
        db.flush()
        if verdict:
            at = rated or NOW - timedelta(days=1)
            db.add(AnswerFeedback(owner_hash=owner, message_id=final.id, conversation_id=conversation.id, turn_id=turn, verdict=verdict, reason=reason,
                                  channel="web", created_at=at, updated_at=at))
        db.commit()
        return str(final.id)


def reports():
    with SessionLocal() as db:
        return db.scalars(select(qr.QualityReport).order_by(qr.QualityReport.created_at)).all()


def test_a_week_with_no_bad_answer_writes_an_empty_report_and_asks_no_model(monkeypatch):
    answered("苹果股价", "355 美元", verdict="good")
    monkeypatch.setattr(qr, "_complete", lambda *a: pytest.fail("no model is asked for an empty week"))
    assert qr.run(OWNER, NOW, None)["outcome"] == "done"
    [report] = reports()
    assert (report.status, report.good, report.bad, report.items) == ("empty", 1, 0, None)


def test_the_model_sorts_each_bad_answer_and_says_what_to_fix_first(monkeypatch):
    first = answered("英伟达营收", "1,158 亿美元", tools=("query_financials", "act"), failed=("act",), verdict="bad", reason="没说环比",
                     rated=NOW - timedelta(hours=2))
    second = answered("特斯拉股价", "380 美元", verdict="bad", rated=NOW - timedelta(hours=5))
    third = answered("苹果市值", "5 万亿", verdict="bad", reason="单位不对", rated=NOW - timedelta(hours=8))
    answered("微软", "好", verdict="good")
    seen = {}

    def model(owner, system, user):
        seen["user"] = user
        return json.dumps({"items": [{"id": 1, "category": "想得太浅", "why": "漏了环比"}, {"id": 2, "category": "不存在的类", "why": "x"}],
                           "next": "先补环比对比。"}), "judge-model"
    monkeypatch.setattr(qr, "_complete", model)
    assert qr.run(OWNER, NOW, None) == {"outcome": "done", "reason": "归类了 3 条"}
    [report] = reports()
    assert (report.status, report.good, report.bad, report.model, report.next_step) == ("done", 1, 3, "judge-model", "先补环比对比。")
    assert [(i["message_id"], i["category"], i["why"]) for i in report.items] == [(first, "想得太浅", "漏了环比"), (second, "其他", "x"), (third, "没归类", None)]
    assert report.categories == {"想得太浅": 1, "其他": 1, "没归类": 1}
    assert "【1】" in seen["user"] and "他的原因：没说环比" in seen["user"] and "用过的工具：query_financials、act" in seen["user"]
    assert "出错的工具：invalid_arguments" in seen["user"] and "他的原因：（没写）" in seen["user"]


def test_an_answer_that_is_not_json_fails_the_run_and_stores_nothing(monkeypatch):
    answered("英伟达营收", "1,158 亿美元", verdict="bad")
    monkeypatch.setattr(qr, "_complete", lambda *a: ("我觉得都挺好", "m"))
    assert qr.run(OWNER, NOW, None)["outcome"] == "failed"
    assert reports() == []
    assert qr._json_object("```json\n{\"items\": [], \"next\": \"x\"}\n```") == {"items": [], "next": "x"}


def test_only_his_verdicts_of_the_period_count(monkeypatch):
    answered("别人的", "x", owner=OTHER, verdict="bad")
    answered("上上周的", "x", verdict="bad", rated=NOW - timedelta(days=10))
    answered("上次自检之前的", "x", verdict="bad", rated=NOW - timedelta(days=3))
    monkeypatch.setattr(qr, "_complete", lambda *a: pytest.fail("nothing of his in the period"))
    qr.run(OWNER, NOW, NOW - timedelta(days=2))
    [report] = reports()
    assert (report.status, report.bad) == ("empty", 0)
    assert report.period_start == NOW - timedelta(days=2)


def test_recent_reports_newest_first(monkeypatch):
    monkeypatch.setattr(qr, "_complete", lambda *a: pytest.fail("no model"))
    qr.run(OWNER, NOW - timedelta(days=7), None)
    qr.run(OWNER, NOW, NOW - timedelta(days=7))
    found = qr.recent(OWNER)
    assert len(found) == 2 and found[0]["created_at"] >= found[1]["created_at"] and found[0]["status"] == "empty"
    assert qr.recent(OTHER) == []
