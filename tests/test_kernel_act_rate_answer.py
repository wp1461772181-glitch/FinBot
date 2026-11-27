"""5d-3a: 「好／不好」 said in a conversation, the kernel's tier-1 ``rate_answer``.  Code finds the answer he means (the newest of this
conversation before this turn) and the result names it; with nothing from outside read this turn it runs at once (channel chat), else it
goes on the card.  Telegram and WeChat have no button under an answer: the sentence goes to the bot unchanged and the kernel records it
without a card (WeChat cannot press one).  Disposable Postgres; no network, no model."""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import agent_telegram as tg
from app import answer_feedback as feedback
from app.agent_chat_models import AgentConversation, AgentMessage
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import SessionLocal
from app.kernel import act
from tests.test_agent_notify import OWNER, OWNER_HASH, owner  # noqa: F401  (fixture)

SAID = "刚才那个回答不好，数据太旧了"
NOW = datetime.now(UTC).replace(microsecond=0)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def line(owner, monkeypatch):
    """One conversation of his with one answered turn; returns (conversation id, its turn id, the answer's id, when it was written)."""
    import app.agent_chat_identity as identity
    from app.agent_workflow import direct, tools
    for module in (consent, direct, tools, identity, act):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    with SessionLocal() as db:
        db.query(feedback.AnswerFeedback).delete()
        db.query(AgentConsent).delete()
        db.commit()
    cid = conversation()
    tid, mid, at = answered(cid, "英特尔上季营收 128 亿美元。\n毛利率 41%。", minutes_ago=5)
    yield SimpleNamespace(cid=cid, tid=tid, mid=mid, at=at)
    with SessionLocal() as db:
        db.query(feedback.AnswerFeedback).delete()
        db.commit()


def conversation():
    with SessionLocal() as db:
        row = AgentConversation(owner_hash=OWNER_HASH)
        db.add(row)
        db.commit()
        return row.id


def answered(cid, text, *, minutes_ago):
    turn_id, at = uuid.uuid4(), NOW - timedelta(minutes=minutes_ago)
    with SessionLocal() as db:
        seq = db.query(AgentMessage).filter(AgentMessage.conversation_id == cid).count() + 1
        final = AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 1, role="assistant", content=text,
                             tool_calls={"route": "K", "audit": {"terminal_status": "succeeded"}}, created_at=at)
        db.add_all([AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq, role="user", content="英特尔营收多少", created_at=at), final])
        db.commit()
        return turn_id, final.id, at


def make_run(cid, question=SAID, credential=OWNER, read_results=0, turn_id=None):
    context = SimpleNamespace(identity_credential=credential, owner_hash=OWNER_HASH, conversation_id=str(cid), bot_id=None, bot_name="",
                              tool_scope=None, default_company=None, watchlist=(), executor=None)
    return SimpleNamespace(context=context, user_text="", question=question, turn_id=str(turn_id or uuid.uuid4()), web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], writes=[], audit={}, read_results=read_results, inbox=None)


def rate(cid, arguments, **kwargs):
    run_ = make_run(cid, **kwargs)
    return run(act.handle(run_, {"operation": "rate_answer", "arguments": arguments})), run_


def _beijing(at: datetime) -> str:
    return at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")


def test_with_no_read_it_runs_at_once_on_the_previous_answer_and_names_it(line):
    out, run_ = rate(line.cid, {"verdict": "bad", "reason": "数据太旧了"})
    assert out["ok"] and run_.writes == [{"operation": "rate_answer", "tier": 1, "outcome": "done"}] and run_.proposals == []
    row = out["data"][0]
    assert row["status"] == "done" and row["title"] == "记下回答反馈" and row["undo"] == act.UNDO["rate_answer"]
    assert row["recorded"] == f"{_beijing(line.at)}「英特尔上季营收 128 亿美元。」——不好（原因：数据太旧了）"
    assert row["message_id"] == str(line.mid)
    assert feedback.of(OWNER_HASH, [line.mid]) == {str(line.mid): {"verdict": "bad", "reason": "数据太旧了"}}
    with SessionLocal() as db:
        assert db.query(feedback.AnswerFeedback).one().channel == "chat"


def test_saying_it_again_changes_it_and_good_has_no_reason(line):
    rate(line.cid, {"verdict": "bad", "reason": "数据太旧了"})
    out, _ = rate(line.cid, {"verdict": "good", "reason": "其实挺好"}, question="那条改成好的")
    assert out["ok"] and out["data"][0]["recorded"].endswith("——好")
    assert feedback.of(OWNER_HASH, [line.mid]) == {str(line.mid): {"verdict": "good", "reason": None}}


def test_it_is_the_answer_before_this_turn_never_the_one_being_written(line):
    newer_turn, newer_mid, _ = answered(line.cid, "第二个回答", minutes_ago=1)
    current = uuid.uuid4()
    with SessionLocal() as db:       # the turn being written already has a row of text (a cancelled draft, a card's line)
        db.add(AgentMessage(conversation_id=line.cid, turn_id=current, sequence=99, role="assistant", content="正在写", created_at=NOW))
        db.commit()
    out, _ = rate(line.cid, {"verdict": "good"}, question="上一条答得不错", turn_id=current)
    assert out["data"][0]["message_id"] == str(newer_mid) and "「第二个回答」" in out["data"][0]["recorded"]
    assert newer_turn


def test_after_an_outside_read_it_goes_on_the_card_and_the_press_rates_the_one_named(line):
    out, run_ = rate(line.cid, {"verdict": "bad"}, read_results=1)
    assert out["data"][0]["status"] == "awaiting_confirmation" and run_.writes == [{"operation": "rate_answer", "tier": 1, "outcome": "proposed"}]
    assert feedback.of(OWNER_HASH, [line.mid]) == {}
    prepared = run_.proposals[0]
    assert prepared.display == {"title": "记下回答反馈", "targets": [{"title": f"{_beijing(line.at)}「英特尔上季营收 128 亿美元。」", "decision": "不好"}],
                                "alternative": act.UNDO["rate_answer"]}
    answered(line.cid, "后来又来了一条", minutes_ago=0)          # a newer answer arrives before he presses
    proposed = consent.propose(OWNER, str(line.cid), [prepared.operation], prepared.display)
    token = proposed["choices"][0]["value"].split(":", 1)[1]
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id=str(line.cid), bot_id=None, executor=None)
    pressed = consent.execute(OWNER, str(line.cid), token, [prepared.operation], act.execute_handler(context))
    assert pressed["ok"] and list(feedback.of(OWNER_HASH, [line.mid])) == [str(line.mid)]


def test_with_no_earlier_answer_it_is_refused_with_the_sentence(owner, monkeypatch):
    for module in (act,):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)
    cid = conversation()
    out, run_ = rate(cid, {"verdict": "bad"})
    assert out["ok"] is False and out["error_code"] == "answer_not_found"
    assert out["reason"] == out["hint"] == "这段对话里还没有之前的回答可以评价。"
    assert run_.writes == [{"operation": "rate_answer", "tier": 1, "outcome": "refused:answer_not_found"}]


def test_a_guest_cannot_rate(line):
    out, _ = rate(line.cid, {"verdict": "good"}, credential="g" * 64)
    assert out["error_code"] == "owner_login_required" and feedback.of(OWNER_HASH, [line.mid]) == {}


@pytest.mark.parametrize("channel", ["telegram", "wechat"])
def test_on_telegram_and_wechat_the_sentence_reaches_the_bot_unchanged_and_is_recorded_without_a_card(line, channel):
    # Both bridges route an owner's message with agent_telegram.route (the WeChat bridge is built with route=agent_telegram.route) and post its
    # text to the stream: there is no button and no special parsing; the kernel's tier-1 act records it at once, so no card waits to be pressed.
    target = tg.route(OWNER_HASH, SAID)
    assert target["text"] == SAID and target["via"] == "default"
    out, run_ = rate(line.cid, {"verdict": "bad", "reason": "数据太旧了"}, question=target["text"])
    assert out["ok"] and run_.proposals == [] and out["data"][0]["status"] == "done"
    assert feedback.of(OWNER_HASH, [line.mid])[str(line.mid)]["verdict"] == "bad"


def test_the_operation_is_tier_one_kernel_only_owner_only_and_always_on():
    from app import agent_bots
    from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, legacy_definitions, validate
    assert act.tier_of("rate_answer") == 1 and "\nrate_answer：" in act.ACT_SCHEMA["function"]["description"]
    assert act.SUMMARIES["rate_answer"].startswith("记下用户对这段对话里上一条回答的『好／不好』")
    assert definitions()["rate_answer"].level == "reversible" and "rate_answer" in OWNER_ONLY and "rate_answer" in KERNEL_ONLY
    assert "rate_answer" not in legacy_definitions() and "rate_answer" in agent_bots.ALWAYS_ON       # the old pipeline's bots do not get it
    assert validate("rate_answer", {"verdict": "bad", "reason": "太旧"}) == {"verdict": "bad", "reason": "太旧"}
    assert validate("rate_answer", {"verdict": "good", "reason": "挺好"}) == {"verdict": "good", "reason": None}      # a reason goes with 不好 only
    for bad in ({"verdict": "useful"}, {"verdict": "bad", "reason": ""}, {"verdict": "bad", "reason": "字" * 201}, {"verdict": "bad", "quote": "x"}, {}):
        with pytest.raises(Exception):
            validate("rate_answer", bad)


def test_each_tier_one_line_names_its_arguments_from_the_schema():
    """The shadow run of 5d-3a: the model guessed rate_answer's argument (rating), the retry came after a lookup in the same step and went on a
    card.  The operations that run in the turn name their arguments in the directory, read from their schemas."""
    lines = {line.split("：", 1)[0]: line for line in act.ACT_SCHEMA["function"]["description"].splitlines()}
    assert lines["rate_answer"].endswith("参数：verdict（good/bad）、reason（可省）")
    assert "参数：verdict（useful/not_useful）、about（alert/brief，可省）、symbol（可省）、quote" in lines["rate_alert"]
    for name in act.TIER1:
        assert "参数：" in lines[name], name
        for key in act._schema(name).get("properties", {}):
            if not key.startswith("_") and key != "say":
                assert key in lines[name].split("参数：")[1], (name, key)
    assert all("参数：" not in lines[name] for name in act.TIER2 if name in lines), "the card operations keep the lookup"
