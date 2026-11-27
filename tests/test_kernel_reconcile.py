"""5d-1: the figure check after a kernel answer (``app.kernel.reconcile``).

The check is ``evidence.answer_scope``'s ``unmarked_no_holder`` as it is; these tests pin what it flags and what it leaves alone, and the
background job that keeps the result on the stored answer (real PostgreSQL, the test database).
"""
import uuid

import pytest
from sqlalchemy import text

from app.agent_chat_models import AgentConversation, AgentMessage
from app.database import Base, SessionLocal, engine
from app.kernel import reconcile as rc

FILING = {"ordinal": 1, "title": "Apple filing", "source_type": "official_filing", "quote": "营收 4500 美元，成本 1200 美元。",
          "check_text": "营收 4500 美元，成本 1200 美元。"}
NEWS = {"ordinal": 2, "title": "Apple news", "source_type": "web_news", "quote": "毛利 3300 美元。", "check_text": "毛利 3300 美元。"}


def check(answer, citations=(FILING,), user_text="苹果营收多少"):
    return rc.reconcile(answer, list(citations), question="苹果营收多少", user_text=user_text)


def test_a_figure_a_source_holds_is_clean():
    result = check("营收是 4500 美元。")
    assert result == {"version": 1, "figures": 1, "flagged": []}


def test_a_figure_the_user_wrote_is_clean():
    assert check("你的成本是 7700 美元。", user_text="我的成本是 7700 美元")["flagged"] == []
    assert check("你的成本是 7700 美元。", user_text="我的成本是七千七百美元")["flagged"] == [], "Chinese numerals count as his"


def test_a_sum_or_ratio_of_source_figures_is_clean():
    assert check("两项合计 5700 美元。")["flagged"] == []          # 4500 + 1200
    assert check("成本约占营收的 26.67%。")["flagged"] == []      # 1200 / 4500


def test_a_figure_nowhere_is_flagged_with_its_line():
    result = check("营收是 4500 美元。利润是 8888 美元。")
    assert result["figures"] == 2
    assert result["flagged"] == [{"line": "营收是 4500 美元。利润是 8888 美元。", "values": ["8888"]}]      # the line, as the old check reads it


def test_each_line_is_flagged_once_with_its_values_in_order():
    result = check("利润是 8888 美元，现金是 9999 美元。")
    assert result["flagged"] == [{"line": "利润是 8888 美元，现金是 9999 美元。", "values": ["8888", "9999"]}]


def test_a_figure_in_a_source_the_sentence_does_not_cite_is_not_flagged():
    # Held by the news item only: a citation slip, not a fabrication.
    assert check("毛利是 3300 美元。", citations=(FILING, NEWS))["flagged"] == []
    assert check("毛利是 3300 美元 [1]。", citations=(FILING, NEWS))["flagged"] == []


def test_a_figure_from_nowhere_is_flagged_also_in_a_sentence_with_a_marker():
    """answer_scope counts a marked sentence's figures and leaves them out of no_holder: they are the number review's."""
    result = check("利润是 8888 美元 [1]。")
    assert result["flagged"] == [{"line": "利润是 8888 美元 [1]。", "values": ["8888"]}] and result["figures"] == 1      # [1] does not state it


def test_an_exception_is_an_error_and_never_raises(monkeypatch):
    from app.agent_workflow import evidence

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(evidence, "answer_scope", broken)
    assert check("利润是 8888 美元。") == {"version": 1, "error": "RuntimeError"}


def test_a_long_line_is_clipped():
    result = check("利润是 8888 美元，" + "字" * 400 + "。")
    [item] = result["flagged"]
    assert len(item["line"]) == 200 and item["line"].startswith("利润是 8888 美元") and item["values"] == ["8888"]


def test_no_citations_and_a_damaged_list_still_answer():
    assert check("利润是 8888 美元。", citations=())["flagged"] == [{"line": "利润是 8888 美元。", "values": ["8888"]}]
    assert "error" not in check("营收是 4500 美元。", citations=(FILING, "junk", None))


def test_a_value_reads_as_written():
    assert [rc._value_text(v) for v in (8888.0, 12.5, 0.1234, 1e9)] == ["8888", "12.5", "0.1234", "1000000000"]


# --- the stored answer ----------------------------------------------------------------------------------------------

@pytest.fixture
def stored(disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__])
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash="o" * 64)
        db.add(conversation)
        db.commit()
        cid = conversation.id

    def answer(content, record, *, before=(), question="苹果营收多少", status="complete"):
        """The conversation's earlier user rows ``before``, then one turn: its question and its answer.  Returns the answer's id."""
        turn = uuid.uuid4()
        with SessionLocal() as db:
            seq = db.execute(text("select coalesce(max(sequence),0) from agent_messages where conversation_id=:c"), {"c": cid}).scalar()
            rows = [AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=seq + i + 1, role="user", content=said)
                    for i, said in enumerate(before)]
            seq += len(rows)
            rows.append(AgentMessage(conversation_id=cid, turn_id=turn, sequence=seq + 1, role="user", content=question))
            final = AgentMessage(conversation_id=cid, turn_id=turn, sequence=seq + 2, role="assistant", content=content, tool_calls=record, status=status)
            rows.append(final)
            db.add_all(rows)
            db.commit()
            return final.id
    yield answer
    with SessionLocal() as db:
        db.query(AgentMessage).filter(AgentMessage.conversation_id == cid).delete()
        db.query(AgentConversation).filter(AgentConversation.id == cid).delete()
        db.commit()


def record_of(message_id):
    with SessionLocal() as db:
        return db.get(AgentMessage, message_id).tool_calls


def test_the_result_lands_on_the_stored_answer_and_the_other_keys_stay(stored):
    record = {"route": "K", "audit": {"tier": "low"}, "citations": [FILING], "thinking_ms": 900}
    mid = stored("营收是 4500 美元。利润是 8888 美元。", record)
    rc.check_and_store(mid)
    kept = record_of(mid)
    assert {key: kept[key] for key in record} == record
    assert kept["reconciliation"]["flagged"] == [{"line": "营收是 4500 美元。利润是 8888 美元。", "values": ["8888"]}] and kept["reconciliation"]["figures"] == 2


def test_the_job_reads_the_stored_citations_with_their_check_text(stored):
    # The quote shows only part of the source; the figure is in the check text the stored citation keeps.
    citation = {**FILING, "quote": "营收 4500 美元。", "check_text": "营收 4500 美元。……现金 6100 美元。"}
    mid = stored("现金是 6100 美元。", {"route": "K", "citations": [citation]})
    rc.check_and_store(mid)
    assert record_of(mid)["reconciliation"]["flagged"] == []


def test_the_job_holds_figures_the_user_typed_earlier_but_not_a_card_button(stored):
    mid = stored("你说的成本是 7700 美元，存款是 5200 美元。", {"route": "K", "citations": [FILING]},
                 before=["我的成本是 7700 美元", "confirm:" + "Zq9" * 14 + " 5200"])
    with SessionLocal() as db:
        inputs = rc.inputs_of(db, db.get(AgentMessage, mid))
    assert inputs["question"] == "苹果营收多少" and "7700" in inputs["user_text"] and "confirm:" not in inputs["user_text"]
    rc.check_and_store(mid)
    assert record_of(mid)["reconciliation"]["flagged"] == [{"line": "你说的成本是 7700 美元，存款是 5200 美元。", "values": ["5200"]}]


def test_a_failed_check_is_stored_as_its_error(stored, monkeypatch):
    monkeypatch.setattr(rc, "reconcile", lambda *a, **k: {"version": 1, "error": "KeyError"})
    mid = stored("利润是 8888 美元。", {"route": "K", "citations": []})
    rc.check_and_store(mid)
    assert record_of(mid)["reconciliation"] == {"version": 1, "error": "KeyError"}


def test_a_failure_to_read_or_write_is_logged_and_leaves_no_key(stored, monkeypatch, caplog):
    mid = stored("利润是 8888 美元。", {"route": "K", "citations": []})

    def broken(*_a, **_k):
        raise RuntimeError("database gone")
    monkeypatch.setattr(rc, "store", broken)
    rc.check_and_store(mid)                       # never raises
    assert "reconciliation" not in record_of(mid)
    assert "checking answer" in caplog.text
    rc.check_and_store(uuid.uuid4())              # no such row: nothing to write, nothing raised


def test_kernel_answers_are_the_newest_route_k_answers(stored):
    old = stored("旧流程的回答 8888 美元。", {"route": "A"})
    tool_round = stored("", {"calls": [{"id": "c1"}]})
    kernel = stored("新流程的回答 8888 美元。", {"route": "K"})
    with SessionLocal() as db:
        found = [row.id for row in rc.kernel_answers(db, 200)]
    assert kernel in found and old not in found and tool_round not in found
