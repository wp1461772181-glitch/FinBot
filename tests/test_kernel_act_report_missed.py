"""「这事怎么没告诉我」 (11-28, design 7.3): the kernel's tier-1 ``report_missed`` keeps what he says he was not told, in his words."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app import missed_reports
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import SessionLocal
from app.kernel import act
from tests.test_agent_notify import OWNER, OWNER_HASH, owner  # noqa: F401  (fixture)
from tests.test_kernel_act_rate_answer import conversation, make_run

SAID = "英伟达 11-17 跌了那么多你怎么没告诉我"


@pytest.fixture
def line(owner, monkeypatch):
    import app.agent_chat_identity as identity
    from app.agent_workflow import tools
    for module in (consent, tools, identity, act):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    with SessionLocal() as db:
        db.query(missed_reports.MissedReport).delete()
        db.query(AgentConsent).delete()
        db.commit()
    yield conversation()
    with SessionLocal() as db:
        db.query(missed_reports.MissedReport).delete()
        db.commit()


def report(cid, arguments, **kwargs):
    run_ = make_run(cid, question=SAID, **kwargs)
    return asyncio.run(act.handle(run_, {"operation": "report_missed", "arguments": arguments})), run_


def test_with_no_read_it_is_recorded_at_once_with_where_he_said_it(line):
    turn = uuid.uuid4()
    out, run_ = report(line, {"what": "英伟达 11-17 跌了 6% 没提醒我", "symbol": "nvda"}, turn_id=turn)
    assert out["ok"] and run_.writes == [{"operation": "report_missed", "tier": 1, "outcome": "done"}] and run_.proposals == []
    row = out["data"][0]
    assert row["status"] == "done" and row["title"] == "记下漏报" and row["undo"] == act.UNDO["report_missed"]
    assert row["recorded"] == "已记下：NVDA 英伟达 11-17 跌了 6% 没提醒我"
    [kept] = missed_reports.recent(OWNER_HASH)
    assert kept["symbol"] == "NVDA" and kept["quote"] == SAID and kept["conversation_id"] == str(line) and kept["turn_id"] == str(turn)   # his words, kept by the code


def test_after_an_outside_read_it_goes_on_the_card_and_the_press_records_it(line):
    out, run_ = report(line, {"what": "美光的委托书没告诉我", "symbol": "MU"}, read_results=1)
    assert run_.proposals and run_.proposals[0].operation["name"] == "report_missed" and missed_reports.recent(OWNER_HASH) == []


def test_a_guest_cannot_report(line):
    out, run_ = report(line, {"what": "x"}, credential="g" * 64)
    assert out.get("ok") is False and run_.proposals == [] and missed_reports.recent(OWNER_HASH) == []


def test_the_operation_is_tier_one_kernel_only_owner_only_and_always_on():
    from app import agent_bots
    from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, legacy_definitions, validate
    assert act.tier_of("report_missed") == 1 and "\nreport_missed：" in act.ACT_SCHEMA["function"]["description"]
    assert definitions()["report_missed"].level == "reversible" and "report_missed" in OWNER_ONLY and "report_missed" in KERNEL_ONLY
    assert "report_missed" not in legacy_definitions() and "report_missed" in agent_bots.ALWAYS_ON
    assert validate("report_missed", {"what": "没告诉我"}) == {"what": "没告诉我", "symbol": None}
    for bad in ({}, {"what": ""}, {"what": "字" * 201}, {"what": "x", "verdict": "bad"}, {"what": "x", "quote": "他的原话由代码记，模型不抄"}):
        with pytest.raises(Exception):
            validate("report_missed", bad)


def test_the_list_tool_prints_the_rows(line, monkeypatch, capsys):
    from app import sentinel_bridge
    from scripts import missed_reports as tool
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: OWNER_HASH)
    assert tool.main([]) == 0 and "还没有记下过" in capsys.readouterr().out
    missed_reports.record(OWNER_HASH, "美光的委托书没告诉我", symbol="MU", quote="美光那份委托书你没提醒我")
    assert tool.main([]) == 0 and "MU" in (printed := capsys.readouterr().out) and "美光的委托书没告诉我" in printed
