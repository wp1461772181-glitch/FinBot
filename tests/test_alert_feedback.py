"""5c-3b: the 「有用／没用」 store (app/alert_feedback.py).

Every callback format of the plan's table, and the bad ones; the upsert (the last verdict wins, the same twice is a no-op); what a target
was about (a scripted sentinel ``alerts`` table, a duty and a brief outbox group); the readers.  Real PostgreSQL (the test database)."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import alert_feedback as feedback
from app.agent_chat_models import AgentTelegramMessage
from app.database import Base, SessionLocal, engine
from app.duty_brief import DutyBrief
from app.duty_log import DutyLog
from sentinel.store import Store

OWNER = "a" * 64
OTHER = "b" * 64
GROUP = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def world(disposable_database):
    Base.metadata.create_all(engine, tables=[feedback.AlertFeedback.__table__, AgentTelegramMessage.__table__, DutyLog.__table__,
                                             DutyBrief.__table__])
    with SessionLocal() as db:
        for model in (feedback.AlertFeedback, DutyBrief, DutyLog):
            db.query(model).delete()
        db.query(AgentTelegramMessage).filter(AgentTelegramMessage.owner_hash.in_([OWNER, OTHER])).delete()
        db.commit()


# --- the callback formats ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("data,parsed", [
    ("fu:s:7", ("sentinel", "7", "useful")),
    ("fn:s:7", ("sentinel", "7", "not_useful")),
    (f"fu:o:{GROUP}", ("outbox", GROUP, "useful")),
    (f"fn:o:{GROUP}", ("outbox", GROUP, "not_useful")),
])
def test_every_callback_format_of_the_table_parses(data, parsed):
    assert feedback.parse_callback(data) == parsed


def test_the_longest_callback_fits_telegram():
    assert len(f"fu:o:{GROUP}".encode()) == 41 <= feedback.CALLBACK_MAX


@pytest.mark.parametrize("data", [
    "ack:7", "ok:7", "zz:s:7", "fx:s:1",                    # wrong prefix
    "fu:x:7", "fu:7", "fu:s:", "fu:s:7:8", "fu::7",         # wrong shape
    "fu:s:abc", "fu:s:-1", "fu:s:0", "fu:s:007", "fu:s:1.5", "fu:s:١", "fu:s:" + "9" * 19,
    "fu:o:not-a-uuid", f"fu:o:{GROUP.upper()}", f"fu:o:{GROUP.replace('-', '')}", f"fu:o:{{{GROUP}}}", "fu:o:7",
    "fu:o:" + "a" * 100,                                    # too long
    "", None, 7,
])
def test_anything_else_is_not_a_feedback_button(data):
    assert feedback.parse_callback(data) is None


# --- the upsert ---------------------------------------------------------------------------------------------------------------

def _rows():
    with SessionLocal() as db:
        return db.query(feedback.AlertFeedback).count()


def test_record_keeps_one_row_per_target_and_the_last_verdict_wins():
    first = feedback.record(OWNER, "sentinel", "7", "useful", "telegram", symbol="INTC", kind="short", text="INTC 急跌\n第二行")
    assert (first["verdict"], first["channel"], first["symbol"], first["kind"], first["text"]) == ("useful", "telegram", "INTC", "short", "INTC 急跌")
    changed = feedback.record(OWNER, "sentinel", "7", "not_useful", "web")
    assert changed["id"] == first["id"] and changed["verdict"] == "not_useful" and changed["channel"] == "web"
    assert changed["symbol"] == "INTC" and datetime.fromisoformat(changed["updated_at"]) > datetime.fromisoformat(first["updated_at"])
    assert _rows() == 1


def test_the_same_verdict_twice_changes_nothing():
    first = feedback.record(OWNER, "outbox", GROUP, "useful", "telegram")
    again = feedback.record(OWNER, "outbox", GROUP, "useful", "web")
    assert again == first and _rows() == 1


def test_owners_and_targets_are_kept_apart():
    feedback.record(OWNER, "sentinel", "7", "useful", "telegram")
    feedback.record(OTHER, "sentinel", "7", "not_useful", "telegram")
    feedback.record(OWNER, "sentinel", "8", "not_useful", "telegram")
    assert _rows() == 3
    assert [r["target_id"] for r in feedback.recent(OWNER)] == ["8", "7"]


@pytest.mark.parametrize("args", [("sentinel", "abc", "useful", "telegram"), ("outbox", "x", "useful", "telegram"),
                                  ("other", "7", "useful", "telegram"), ("sentinel", "7", "great", "telegram"), ("sentinel", "7", "useful", "sms")])
def test_record_refuses_what_is_not_a_verdict(args):
    with pytest.raises(ValueError, match="invalid_feedback"):
        feedback.record(OWNER, *args)
    assert _rows() == 0


# --- what the target was about ----------------------------------------------------------------------------------------------

def test_describe_a_sentinel_alert_from_the_alerts_table(tmp_path, monkeypatch):
    path = tmp_path / "sentinel.db"
    store = Store(path)
    alert_id = store.add_alert("NVDA", "short", "NVDA 15 分钟内跌 3.2%\n现价 120", True, 1_700_000_000)
    monkeypatch.setenv("SENTINEL_DB_PATH", str(path))
    assert feedback.describe(OWNER, "sentinel", str(alert_id)) == {"symbol": "NVDA", "kind": "short", "text": "NVDA 15 分钟内跌 3.2%"}
    assert feedback.describe(OWNER, "sentinel", "999") == {"symbol": None, "kind": None, "text": None}
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "missing.db"))
    assert feedback.describe(OWNER, "sentinel", str(alert_id)) == {"symbol": None, "kind": None, "text": None}


def _outbox(source, text, group=None):
    with SessionLocal() as db:
        row = AgentTelegramMessage(owner_hash=OWNER, source=source, text=text, status="sent", channel="telegram", group_id=group,
                                   created_at=datetime.now(UTC))
        db.add(row)
        db.commit()
        return row.id


def test_describe_a_duty_group_from_its_duty_log_row():
    group = uuid.uuid4()
    _outbox("duty", "【助理】\nNVDA 今天跌了 6%，占你仓位 20%。\n要不要复盘？", group)
    with SessionLocal() as db:
        db.add(DutyLog(owner_hash=OWNER, alert_id=11, event={"symbol": "NVDA"}, mode="on", outcome="decided", decision="tell_now",
                       message="NVDA 今天跌了 6%，占你仓位 20%。\n要不要复盘？", delivery="queued", delivery_group=group))
        db.commit()
    assert feedback.describe(OWNER, "outbox", str(group)) == {"symbol": "NVDA", "kind": "duty", "text": "NVDA 今天跌了 6%，占你仓位 20%。"}
    assert feedback.describe(OTHER, "outbox", str(group)) == {"symbol": None, "kind": None, "text": None}


def test_describe_a_brief_group_from_its_brief_row():
    group = uuid.uuid4()
    _outbox("brief", "【助理】\n早上好。昨夜 3 件事。", group)
    with SessionLocal() as db:
        db.add(DutyBrief(owner_hash=OWNER, day="2026-11-27", mode="on", outcome="done", message="早上好。昨夜 3 件事。\n一、……",
                         delivery="queued", delivery_group=group, counts={}))
        db.commit()
    assert feedback.describe(OWNER, "outbox", str(group)) == {"symbol": None, "kind": "brief", "text": "早上好。昨夜 3 件事。"}


def test_describe_a_row_without_a_group_by_its_own_id_and_without_a_log_row_by_its_text():
    row_id = _outbox("duty", "【助理】\n只有发件箱里的这句话。")
    assert feedback.describe(OWNER, "outbox", str(row_id)) == {"symbol": None, "kind": "duty", "text": "只有发件箱里的这句话。"}
    assert feedback.describe(OWNER, "outbox", "not-a-uuid") == {"symbol": None, "kind": None, "text": None}


# --- the readers --------------------------------------------------------------------------------------------------------------

def test_recent_is_newest_first_and_counts_go_by_when_the_verdict_was_given():
    before = datetime.now(UTC) - timedelta(seconds=1)
    feedback.record(OWNER, "sentinel", "1", "useful", "telegram")
    feedback.record(OWNER, "sentinel", "2", "not_useful", "telegram")
    feedback.record(OWNER, "outbox", GROUP, "not_useful", "web")
    feedback.record(OWNER, "sentinel", "1", "not_useful", "telegram")     # changed: it is now the newest
    assert [(r["target_id"], r["verdict"]) for r in feedback.recent(OWNER)] == [("1", "not_useful"), (GROUP, "not_useful"), ("2", "not_useful")]
    assert [r["target_id"] for r in feedback.recent(OWNER, 2)] == ["1", GROUP]
    assert feedback.counts(OWNER, before) == {"useful": 0, "not_useful": 3}
    assert feedback.counts(OWNER, datetime.now(UTC) + timedelta(minutes=1)) == {"useful": 0, "not_useful": 0}
    assert feedback.counts(OTHER, before) == {"useful": 0, "not_useful": 0} and feedback.recent(OTHER) == []
    assert feedback.verdicts(OWNER, "outbox", [GROUP, str(uuid.uuid4())]) == {GROUP: "not_useful"}
