"""5c-3c: 「有用／没用」 said in a conversation, the kernel's tier-1 ``rate_alert``.  Code finds the message he means and the result names it;
it runs at once (channel chat), also after a read; a sentinel alert is acknowledged too, but only when nothing was read this turn.
Disposable Postgres and a scripted sentinel database; no network, no model."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import alert_feedback as feedback
from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage, AgentTelegramMessage
from app.agent_chat_store import owner_hash
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.duty_brief import DutyBrief
from app.duty_log import DutyLog
from app.kernel import act
from sentinel.store import Store

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
CONVERSATION = "aaaaaaaa-1111-2222-3333-444444444444"
TURN = "bbbbbbbb-1111-2222-3333-444444444444"
SAID = "刚才英特尔那条提醒没用"


def run(coro):
    return asyncio.run(coro)


def make_run(question=SAID, credential=OWNER, read_results=0):
    context = SimpleNamespace(identity_credential=credential, owner_hash=OWNER_HASH, conversation_id=CONVERSATION, bot_id=None, bot_name="",
                              tool_scope=None, default_company=None, watchlist=(), executor=None)
    return SimpleNamespace(context=context, user_text="", question=question, turn_id=TURN, web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], writes=[], audit={}, read_results=read_results, inbox=None)


def wipe():
    with SessionLocal() as db:
        for model in (feedback.AlertFeedback, AgentConsent, DutyLog, DutyBrief):
            db.query(model).delete()
        db.commit()


@pytest.fixture
def owner(monkeypatch, disposable_database, tmp_path):
    Base.metadata.create_all(engine, tables=[feedback.AlertFeedback.__table__, AgentConsent.__table__, AgentBot.__table__,
                                             AgentConversation.__table__, AgentMessage.__table__,
                                             AgentTelegramMessage.__table__, DutyLog.__table__, DutyBrief.__table__])
    wipe()
    import app.agent_chat_identity as identity
    from app.agent_workflow import direct, tools
    for module in (consent, direct, tools, identity, act):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    path = tmp_path / "sentinel.db"
    monkeypatch.setenv("SENTINEL_DB_PATH", str(path))
    yield Store(path)
    wipe()


def rate(arguments, **kwargs):
    run_ = make_run(**kwargs)
    return run(act.handle(run_, {"operation": "rate_alert", "arguments": {"quote": run_.question, **arguments}})), run_


def _beijing(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")


def _ago(hours: float) -> float:
    return (datetime.now(UTC) - timedelta(hours=hours)).timestamp()


def test_with_no_read_it_runs_at_once_records_with_channel_chat_and_acknowledges_the_alert(owner):
    created = _ago(1)
    alert_id = owner.add_alert("INTC", "short", "INTC 15 分钟内跌 3.2%\n现价 20", True, created)
    out, run_ = rate({"verdict": "not_useful", "symbol": "INTC"})
    assert out["ok"] and run_.writes == [{"operation": "rate_alert", "tier": 1, "outcome": "done"}] and run_.proposals == []
    row = out["data"][0]
    assert row["status"] == "done" and row["title"] == "记下提醒反馈" and row["undo"] == "说错了就说『那条改成有用／没用』。"
    assert row["recorded"] == f"INTC {_beijing(created)}「INTC 15 分钟内跌 3.2%」——没用"
    assert (row["target"], row["target_id"]) == ("sentinel", str(alert_id))
    (saved,) = feedback.recent(OWNER_HASH)
    assert (saved["target"], saved["target_id"], saved["verdict"], saved["channel"], saved["symbol"], saved["kind"], saved["text"]) == (
        "sentinel", str(alert_id), "not_useful", "chat", "INTC", "short", "INTC 15 分钟内跌 3.2%")
    assert owner.alert(alert_id)["acked_at"] is not None            # 「收到」 as well: the sentinel stops escalating


def test_after_a_read_it_still_runs_at_once_but_does_not_acknowledge(owner):
    # He usually asks which alert first (query_alerts); a card would leave WeChat stuck.  A page read this turn could ask for a
    # verdict, so the verdict is kept but the alert is not acknowledged: nothing read can silence an urgent alert.
    created = _ago(2)
    alert_id = owner.add_alert("INTC", "short", "INTC 急跌", True, created)
    out, run_ = rate({"verdict": "useful", "symbol": "INTC"}, read_results=1)
    assert out["ok"] and out["data"][0]["status"] == "done" and run_.writes == [{"operation": "rate_alert", "tier": 1, "outcome": "done"}]
    assert [r["target_id"] for r in feedback.recent(OWNER_HASH)] == [str(alert_id)]
    assert owner.alert(alert_id)["acked_at"] is None


def test_a_card_rates_the_message_it_named_even_if_a_newer_one_arrives(owner):
    created = _ago(2)
    alert_id = owner.add_alert("INTC", "short", "INTC 急跌", True, created)
    prepared = run(act.prepare(make_run(), "rate_alert", {"verdict": "useful", "symbol": "INTC", "quote": "英特尔那条有用"}))
    assert prepared.display == {"title": "记下提醒反馈", "targets": [{"symbol": "INTC", "title": f"{_beijing(created)}「INTC 急跌」", "decision": "有用"}],
                                "alternative": "说错了就说『那条改成有用／没用』。"}
    assert prepared.operation["match"]["target_id"] == str(alert_id)
    owner.add_alert("INTC", "short", "INTC 又跌", True, _ago(0.1))
    proposed = consent.propose(OWNER, CONVERSATION, [prepared.operation], prepared.display)
    token = proposed["choices"][0]["value"].split(":", 1)[1]
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id=CONVERSATION, bot_id=None, executor=None)
    pressed = consent.execute(OWNER, CONVERSATION, token, [prepared.operation], act.execute_handler(context))
    assert pressed["ok"] and [r["target_id"] for r in feedback.recent(OWNER_HASH)] == [str(alert_id)]


def test_nothing_found_is_refused_with_the_sentence(owner):
    out, run_ = rate({"verdict": "not_useful", "symbol": "INTC"})
    assert out["ok"] is False and out["error_code"] == "feedback_target_not_found"
    assert out["reason"] == out["hint"] == "最近 48 小时里没找到INTC的提醒。"
    assert run_.writes == [{"operation": "rate_alert", "tier": 1, "outcome": "refused:feedback_target_not_found"}]
    out, _ = rate({"verdict": "useful"})
    assert out["reason"] == "最近 48 小时里没找到的提醒。"
    out, _ = rate({"verdict": "useful", "about": "brief"}, question="今天的简报挺有用")
    assert out["reason"] == "最近 48 小时里没找到的早间简报。"
    assert feedback.recent(OWNER_HASH) == []


def test_the_newest_is_meant_and_naming_the_stock_picks_another(owner):
    intc = owner.add_alert("INTC", "short", "INTC 急跌", True, _ago(3))
    tsla = owner.add_alert("TSLA", "short", "TSLA 急涨", False, _ago(1))
    out, _ = rate({"verdict": "not_useful"})
    assert out["data"][0]["target_id"] == str(tsla) and out["data"][0]["recorded"].startswith("TSLA ")
    out, _ = rate({"verdict": "not_useful", "symbol": "intc"}, question="不对，是英特尔那条")
    assert out["data"][0]["target_id"] == str(intc)
    assert {r["target_id"] for r in feedback.recent(OWNER_HASH)} == {str(intc), str(tsla)}


def test_the_brief_is_rated_by_its_group_and_nothing_is_acknowledged(owner, monkeypatch):
    group = uuid.uuid4()
    with SessionLocal() as db:
        db.add(DutyBrief(owner_hash=OWNER_HASH, day="2026-11-27", mode="on", outcome="done", message="【助理】\n早上好。昨夜 3 件事。",
                         delivery="queued", delivery_group=group, counts={}, created_at=datetime.now(UTC) - timedelta(hours=5)))
        db.commit()
    monkeypatch.setattr(Store, "ack_alert", lambda self, alert_id, now=None: pytest.fail("a brief is not an alert"))
    out, _ = rate({"verdict": "useful", "about": "brief"}, question="今天的简报挺有用")
    row = out["data"][0]
    assert out["ok"] and (row["target"], row["target_id"]) == ("outbox", str(group))
    assert row["recorded"].endswith("「早上好。昨夜 3 件事。」——有用") and not row["recorded"].startswith(" ")
    assert feedback.recent(OWNER_HASH)[0]["kind"] == "brief"


def test_a_failed_acknowledgement_does_not_fail_the_verdict(owner, monkeypatch):
    alert_id = owner.add_alert("INTC", "short", "INTC 急跌", True, _ago(1))

    def broken(self, alert_id, now=None):
        raise OSError("disk is gone")
    monkeypatch.setattr(Store, "ack_alert", broken)
    out, _ = rate({"verdict": "not_useful", "symbol": "INTC"})
    assert out["ok"] and out["data"][0]["target_id"] == str(alert_id)
    assert feedback.recent(OWNER_HASH)[0]["verdict"] == "not_useful"


def test_a_guest_cannot_rate(owner):
    owner.add_alert("INTC", "short", "INTC 急跌", True, _ago(1))
    out, _ = rate({"verdict": "useful"}, credential="g" * 64)
    assert out["error_code"] == "owner_login_required" and feedback.recent(OWNER_HASH) == []


def test_the_operation_is_tier_one_kernel_only_owner_only_and_always_on():
    from app import agent_bots
    from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, legacy_definitions, validate
    assert act.tier_of("rate_alert") == 1 and "\nrate_alert：" in act.ACT_SCHEMA["function"]["description"]
    assert act.SUMMARIES["rate_alert"].startswith("记下用户对某条提醒、值班消息或早间简报的『有用／没用』") and "不用先查提醒列表" in act.SUMMARIES["rate_alert"]
    assert definitions()["rate_alert"].level == "reversible" and "rate_alert" in OWNER_ONLY and "rate_alert" in KERNEL_ONLY
    assert "rate_alert" not in legacy_definitions() and "rate_alert" in agent_bots.ALWAYS_ON
    assert validate("rate_alert", {"verdict": "useful", "symbol": " brk.b ", "quote": "有用"}) == {"verdict": "useful", "about": "alert", "symbol": "BRK.B", "quote": "有用"}
    for bad in ({"verdict": "great", "quote": "x"}, {"verdict": "useful", "symbol": "英特尔", "quote": "x"}, {"verdict": "useful", "symbol": "A" * 13, "quote": "x"},
                {"verdict": "useful", "quote": ""}, {"verdict": "useful", "quote": "字" * 201}, {"verdict": "useful", "about": "duty", "quote": "x"}):
        with pytest.raises(Exception):
            validate("rate_alert", bad)
