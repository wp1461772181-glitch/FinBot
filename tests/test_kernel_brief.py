"""5c-2: the morning brief the kernel writes from what its duty kept overnight.

No network: the model is a script, ``tools.invoke`` is replaced; the database is the suite's disposable PostgreSQL."""
import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
from app import agent_task_runner as runner
from app import duty_brief, duty_log, model_usage
from app.agent_chat_models import AgentConversation, AgentMessage, AgentTelegramMessage
from app.database import SessionLocal
from app.kernel import act, brief, loop, prompt, wake
from app.agent_workflow import tools
from tests.test_agent_notify import OWNER, OWNER_HASH, _bind, owner  # noqa: F401  (fixture)
from tests.test_kernel_loop import OK_ROWS, Script, call, step
from tests.test_kernel_wake import INJECTION, MODEL, event, judge

ANSWER = "早上好。NVDA 夜里跌了 6%，原因是出口限制的新闻；它占你仓位两成，今天开盘值得看一眼。"
HELD = "NVDA 盘后跌 6.1%：路透 11-27 报道美国拟收紧对华芯片出口，这是主要原因。"


@pytest.fixture
def env(owner, monkeypatch):
    with SessionLocal() as db:
        db.query(duty_log.DutyLog).delete()
        db.query(duty_brief.DutyBrief).delete()
        db.query(AgentConversation).filter(AgentConversation.owner_hash == OWNER_HASH).delete()
        db.commit()
    for module in (loop, prompt, act):
        monkeypatch.setattr(module, "owner_credential_matches", lambda value: bool(value))
    monkeypatch.setattr(runner, "owner_credential", lambda: OWNER)
    monkeypatch.setattr(runner, "task_model", lambda owner_hash, name: dict(MODEL))
    monkeypatch.setenv("FINBOT_DUTY_MODE", "shadow")
    invoked, tags = [], []

    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        invoked.append((name, args))
        return copy.deepcopy(OK_ROWS)

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    return SimpleNamespace(invoked=invoked, tags=tags, monkeypatch=monkeypatch)


def script(env, steps):
    inner = Script(steps)

    async def recording(*args, **kwargs):
        env.tags.append(dict(model_usage._TAGS.get() or {}))
        return await inner(*args, **kwargs)

    env.monkeypatch.setattr(provider, "stream_decision", recording)
    return inner


def brief_now(days: int = 0) -> datetime:
    """The next Beijing 09:00 after the real now (plus ``days``): a due instant whose default window holds the rows written now."""
    local = datetime.now(brief.BEIJING)
    target = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return (target + timedelta(days=days)).astimezone(UTC)


def run(now=None, **kwargs):
    return asyncio.run(brief.run_once(OWNER_HASH, now or brief_now(), **kwargs))


_IDS = iter(range(1000, 10_000))


def duty(decision, *, delivery=None, message=None, mode="on", symbol="NVDA", text="NVDA 跌 6.1%，现价 120", reason="因为……", outcome="decided"):
    return duty_log.record(OWNER_HASH, next(_IDS), event={"symbol": symbol, "text": text}, mode=mode, outcome=outcome,
                           decision=decision if outcome == "decided" else None, reason=reason, message=message, delivery=delivery)


def held(message=HELD, **kwargs):
    return duty("tell_now", delivery=wake.HELD_NIGHT, message=message, **kwargs)


def outbox(source="brief"):
    with SessionLocal() as db:
        found = db.query(AgentTelegramMessage).filter(AgentTelegramMessage.owner_hash == OWNER_HASH, AgentTelegramMessage.source == source).all()
        for row in found:
            db.expunge(row)
        return found


# --- when it is due ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utc,day", [((0, 4), None), ((0, 5), "2026-11-28"), ((3, 59), "2026-11-28"), ((4, 0), None)])
def test_a_brief_is_due_from_08_05_until_noon_beijing(utc, day):
    assert brief.due_day(datetime(2026, 11, 28, *utc, tzinfo=UTC)) == day


def test_late_in_the_utc_day_is_the_next_beijing_date():
    assert brief.due_day(datetime(2026, 11, 27, 0, 30, tzinfo=UTC)) == "2026-11-27"
    assert brief.due_day(datetime(2026, 11, 27, 23, 30, tzinfo=UTC)) is None      # 07:30 Beijing on the 28th


def test_a_time_outside_the_window_writes_nothing(env):
    duty("record")
    assert run(datetime(2026, 11, 28, 5, 0, tzinfo=UTC)) is None
    with SessionLocal() as db:
        assert db.query(duty_brief.DutyBrief).count() == 0


# --- one brief a day --------------------------------------------------------------------------------------------------------

def test_the_day_is_claimed_once(env):
    first = duty_brief.claim(OWNER_HASH, "2026-11-28", "shadow")
    assert isinstance(first, int) and duty_brief.claim(OWNER_HASH, "2026-11-28", "shadow") is None
    assert duty_brief.claim(OWNER_HASH, "2026-11-29", "shadow") not in (None, first)


def test_a_second_run_the_same_day_does_nothing(env):
    duty("digest")
    fake = script(env, [step(text=ANSWER)])
    first = run()
    assert first["outcome"] == "done" and run() is None and len(fake.calls) == 1


# --- what the brief says --------------------------------------------------------------------------------------------------

def test_nothing_since_the_last_brief_is_skipped_without_a_model_call(env):
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    _bind()
    fake = script(env, [])
    row = run()
    assert row["outcome"] == "skipped" and row["reason"] == brief.NOTHING and row["message"] is None
    assert fake.calls == [] and outbox() == []


def test_only_filtered_rows_are_the_code_written_line_alone(env):
    duty("record")
    duty("record")
    duty("ignore")
    fake = script(env, [])
    row = run()
    assert fake.calls == [] and row["outcome"] == "done" and row["turn_id"] is None and row["model_calls"] == 0
    assert row["message"] == "【早间简报】从昨天到现在，另有 3 条提醒我看过，判断不用打扰你（2 条只记下，1 条不理会），在后台「值班」里能看到。"
    assert row["counts"] == {"digest": 0, "held": 0, "record": 2, "ignore": 1, "told": 0, "failed": 0}


def test_a_zero_part_of_the_filtered_line_is_left_out():
    assert brief.filtered_line({"record": 3, "ignore": 0}) == "从昨天到现在，另有 3 条提醒我看过，判断不用打扰你（3 条只记下），在后台「值班」里能看到。"
    assert "（1 条不理会）" in brief.filtered_line({"ignore": 1})
    assert brief.filtered_line({"record": 0, "ignore": 0, "digest": 4}) == ""


def test_kept_and_held_items_go_to_one_model_turn_without_decide_act_or_ask(env):
    duty("digest", reason="不急，留到早上说。")
    held()
    duty("record")
    duty("tell_now", delivery="queued", message="白天已经发出的话")
    duty(None, outcome="failed")
    fake = script(env, [step(text=ANSWER)])
    row = run()
    assert len(fake.calls) == 1
    system, user = fake.calls[0]["messages"][0]["content"], fake.calls[0]["messages"][1]["content"]
    assert system.startswith(prompt.brief_system_text()) and user == prompt.BRIEF_INSTRUCTION
    assert system.index("【攒进简报的】") < system.index("不急，留到早上说。") < system.index("【夜里压住的跟进】") < system.index(HELD)
    assert "白天已经发出的话" not in system
    offered = fake.calls[0]["tools"]
    assert "query_financials" in offered and not {"decide", "act", "ask", "use_skill", "search_x"} & set(offered)
    line = brief.filtered_line(row["counts"])
    assert row["message"] == f"{brief.HEAD}{ANSWER}\n\n{line}" and "1 条只记下" in line
    assert row["counts"] == {"digest": 1, "held": 1, "record": 1, "ignore": 0, "told": 1, "failed": 1}
    assert row["outcome"] == "done" and row["reason"] is None and row["model_calls"] == 1 and row["turn_id"]


def test_the_brief_is_booked_as_duty_and_stored_in_the_hidden_duty_conversation(env):
    from app.agent_recall import TASK_POST_HEAD
    duty("digest")
    script(env, [step(calls=[call("c1", "query_financials", {"symbol": "NVDA"})]), step(text=ANSWER)])
    now = brief_now()
    row = run(now)
    day = brief.due_day(now)
    assert [t["purpose"] for t in env.tags] == ["duty", "duty"] and {t["job"] for t in env.tags} == {f"brief:{day}"}
    assert all(t["turn_id"] == row["turn_id"] for t in env.tags)
    with SessionLocal() as db:
        stored = db.query(AgentMessage).filter(AgentMessage.turn_id == uuid.UUID(row["turn_id"])).order_by(AgentMessage.sequence).all()
        assert [m.role for m in stored] == ["user", "assistant", "tool", "assistant"]
        assert stored[0].content == f"{TASK_POST_HEAD}早间简报 {day}" and stored[-1].content == ANSWER
        conversation = db.get(AgentConversation, stored[0].conversation_id)
        assert conversation.archived_at is not None


def test_an_instruction_in_a_kept_alert_is_only_data(env):
    duty("digest", text=INJECTION)
    fake = script(env, [step(text=ANSWER)])
    run()
    system, user = fake.calls[0]["messages"][0]["content"], fake.calls[0]["messages"][1]["content"]
    assert INJECTION not in user and system.count(INJECTION) == 1 and system.index("【攒进简报的】") < system.index(INJECTION)
    assert env.invoked == []


def test_a_failing_model_still_sends_every_kept_item_and_held_message(env):
    duty("digest", text="AAPL 跌 3%\n第二行不进列表", symbol="AAPL")
    duty("digest", text="TSLA 涨 5%", symbol="TSLA")
    held()
    held("INTC 夜里的跟进：财报指引下调。", symbol="INTC")
    script(env, [RuntimeError("boom")])
    row = run()
    assert row["outcome"] == "done" and "RuntimeError" in row["reason"]
    assert row["message"].startswith(brief.HEAD + brief.FALLBACK_HEAD)
    for line in ("· AAPL 跌 3%", "· TSLA 涨 5%", f"· {HELD}", "· INTC 夜里的跟进：财报指引下调。"):
        assert line in row["message"]
    assert "第二行不进列表" not in row["message"]


def test_an_empty_answer_falls_back_to_the_plain_list(env):
    duty("digest", text="AAPL 跌 3%")
    script(env, [step(text=""), step(text="")])
    row = run()
    assert row["outcome"] == "done" and "· AAPL 跌 3%" in row["message"] and "没有写出" in row["reason"]


def test_a_turn_past_the_wall_clock_falls_back(env):
    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    duty("digest", text="AAPL 跌 3%")
    env.monkeypatch.setattr(provider, "stream_decision", slow)
    env.monkeypatch.setattr(brief, "WALL_SECONDS", 0.05)
    row = run()
    assert row["outcome"] == "done" and "超过" in row["reason"] and "· AAPL 跌 3%" in row["message"]


def test_a_failure_after_the_claim_finishes_the_row_as_failed(env):
    def broken(owner_hash, since):
        raise ValueError("x")

    env.monkeypatch.setattr(brief, "gather", broken)
    row = run()
    assert row["outcome"] == "failed" and "ValueError" in row["reason"]


# --- the modes --------------------------------------------------------------------------------------------------------------

def test_on_sends_one_brief_past_a_full_day_of_duty_messages_and_marks_held_rows_briefed(env):
    from app import agent_bots as bots
    from app import agent_telegram as tg
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    _bind()
    bot = bots.ensure_default_bot(OWNER_HASH)
    with SessionLocal() as db:
        for _ in range(wake.daily_cap()):
            tg.enqueue(db, OWNER_HASH, bot.id, "m", source="duty")
        db.commit()
    kept_row, held_row = duty("digest"), held()
    script(env, [step(text=ANSWER)])
    row = run()
    (sent,) = outbox()
    assert row["outcome"] == "done" and row["mode"] == "on" and row["delivery"] == "queued" and row["delivery_group"] == str(sent.group_id)
    assert ANSWER in sent.text and brief.HEAD in sent.text and sent.status == "pending"
    assert duty_log.get(OWNER_HASH, held_row["alert_id"])["delivery"] == "briefed"
    assert duty_log.get(OWNER_HASH, kept_row["alert_id"])["delivery"] is None
    # The wake's told list now carries the follow-up the brief delivered.
    fake = script(env, [step(calls=[call("d1", "decide", {"decision": "record", "reason": "已经说过。"})])])
    judge(event(77))
    assert HELD in fake.calls[0]["messages"][0]["content"]


def test_a_full_notify_cap_of_the_bot_does_not_stop_the_brief(env):
    from app import agent_bots as bots
    from app import agent_telegram as tg
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    _bind()
    bot = bots.ensure_default_bot(OWNER_HASH)
    with SessionLocal() as db:
        for _ in range(bot.daily_notify_cap):
            tg.enqueue(db, OWNER_HASH, bot.id, "m", source="notify")
        db.commit()
    duty("record")
    row = run()
    assert row["delivery"] == "queued" and len(outbox()) == 1


def test_on_without_a_bound_channel_marks_nothing(env):
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    held_row = held()
    script(env, [step(text=ANSWER)])
    row = run()
    assert row["outcome"] == "done" and row["delivery"] == "telegram_not_bound" and row["delivery_group"] is None
    assert duty_log.get(OWNER_HASH, held_row["alert_id"])["delivery"] == wake.HELD_NIGHT


def test_shadow_writes_the_brief_and_sends_nothing(env):
    _bind()
    held_row = held()
    script(env, [step(text=ANSWER)])
    row = run()
    assert row["outcome"] == "done" and row["mode"] == "shadow" and row["delivery"] is None and row["message"].startswith(brief.HEAD + ANSWER)
    assert outbox() == [] and duty_log.get(OWNER_HASH, held_row["alert_id"])["delivery"] == wake.HELD_NIGHT


def test_off_writes_no_brief_and_calls_no_model(env):
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "off")
    duty("digest")
    fake = script(env, [])
    row = run()
    assert row["outcome"] == "skipped_off" and row["mode"] == "off" and row["message"] is None and fake.calls == []


# --- the window -------------------------------------------------------------------------------------------------------------

def test_rows_before_the_last_brief_that_ran_are_not_counted(env):
    duty("record")
    first = run(brief_now())
    assert first["outcome"] == "done" and first["counts"]["record"] == 1
    duty("ignore")
    second = run(brief_now(1))
    assert second["outcome"] == "done" and second["counts"]["record"] == 0 and second["counts"]["ignore"] == 1


def test_a_skipped_day_does_not_move_the_window(env):
    assert run(brief_now())["outcome"] == "skipped"
    assert duty_brief.last_done(OWNER_HASH) is None


# --- the background loop ----------------------------------------------------------------------------------------------------

def test_the_loop_runs_the_brief_for_the_owner_and_does_nothing_without_one(monkeypatch):
    from app import background, sentinel_bridge
    seen = []

    async def fake_run_once(owner_hash, now):
        seen.append((owner_hash, now.tzinfo is not None))
        return {"day": "2026-11-28", "outcome": "done"}

    monkeypatch.setattr(brief, "run_once", fake_run_once)
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: None)
    background.run_morning_brief()
    assert seen == []
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: OWNER_HASH)
    background.run_morning_brief()
    assert seen == [(OWNER_HASH, True)]
    assert {n: i for n, i, _ in background.LOOPS}["morning-brief"] == background.BRIEF_SECONDS == 60
