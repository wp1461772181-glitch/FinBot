"""4c Task 2: the quarterly settle.  Review Focus 1 (confirmed guess seen again -> 长期; one unseen for 200 days -> archived with the date; an
explicit item untouched for two years stays), 2 (a sold company's view archived, the same company in the queue kept), 3 (the box down over
05-15: one run on 05-20, next due 08-15), 5 (restore); the note; nothing changed -> no message.  Disposable Postgres, no model."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import agent_bots, agent_profile as profile, memory_schedule as sched, memory_settle as settle, owner_views
from app.agent_chat_models import (AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentResearchQueue, AgentTelegramMessage,
                                   MemoryJob, OwnerView)
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
JOB = "quarterly_settle"


@pytest.fixture(autouse=True)
def world(monkeypatch, disposable_database):
    import app.agent_tasks  # noqa: F401
    import app.main  # noqa: F401
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    owner_views.ensure_archive_column()
    with SessionLocal() as db:
        for model in (AgentProfileItem, AgentMessage, AgentConversation, AgentTelegramMessage, AgentBot, MemoryJob, OwnerView, AgentResearchQueue):
            db.query(model).delete()
        from app.agent_chat_models import PortfolioTransaction
        db.query(PortfolioTransaction).delete()
        db.commit()
    for name in ("FINBOT_MEMORY_STALE_DAYS", "FINBOT_MEMORY_QUARTER_ANCHORS"):
        monkeypatch.delenv(name, raising=False)
    import app.channels as channels
    monkeypatch.setattr(channels, "available", lambda db, owner, channel, bot: channel == "telegram")
    import app.agent_chat_identity as identity
    import app.agent_chat_stream as stream
    for module in (identity, stream):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)


def _days(n):
    return NOW - timedelta(days=n)


def _item(text, *, origin="pattern", status="active", seen=None, confirmed=None, settled=None, owner=OWNER_HASH, topic=None, archived_at=None, edited=None):
    """``confirmed``: when he confirmed a guess (``confirmed_at``); ``edited`` is ``updated_at`` (defaults to the confirmation time)."""
    with SessionLocal() as db:
        row = AgentProfileItem(owner_hash=owner, kind="preference", topic=topic, text=text, origin=origin, quote=text, status=status,
                               created_at=_days(400), updated_at=edited or confirmed or _days(400), last_seen_at=seen or _days(400), settled_at=settled,
                               confirmed_at=confirmed if origin == "pattern" else None, archived_at=archived_at)
        db.add(row)
        db.commit()
        return str(row.id)


def _row(item_id):
    with SessionLocal() as db:
        row = db.get(AgentProfileItem, uuid.UUID(item_id))
        db.expunge(row)
        return row


def _view(symbol="NVDA", text="估值太高了"):
    return owner_views.record(OWNER_HASH, symbol, text, text + "，我觉得", at=_days(300))["view"]["id"]


def _say(text, when):
    with SessionLocal() as db:
        cid = agent_bots.ensure_default_bot(OWNER_HASH).conversation_id
        count = db.query(AgentMessage).filter_by(conversation_id=cid).count()
        db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=count + 1, role="user", content=text, status="complete", created_at=when))
        db.commit()


def _posted():
    with SessionLocal() as db:
        return [m.content for m in db.query(AgentMessage).filter(AgentMessage.role == "assistant").all()]


def _notices():
    with SessionLocal() as db:
        return db.query(AgentTelegramMessage).filter_by(source="memory").count()


def _buy(symbol, quantity, on):
    from app import portfolio
    portfolio.record_transaction(OWNER_HASH, {"kind": "deposit", "amount": 1000000, "occurred_on": "2025-01-02"}) if not _has_cash() else None
    portfolio.record_transaction(OWNER_HASH, {"kind": "buy" if quantity > 0 else "sell", "symbol": symbol, "quantity": abs(quantity), "price": 100, "occurred_on": on})


def _has_cash():
    from app.agent_chat_models import PortfolioTransaction
    with SessionLocal() as db:
        return db.query(PortfolioTransaction).count() > 0


# ---- Review Focus 1 --------------------------------------------------------------------------------------------------

def test_a_guess_confirmed_three_months_ago_and_seen_last_month_becomes_long_term_and_the_block_says_so():
    guess = _item("先要结论再看细节", confirmed=_days(95), seen=_days(30))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["outcome"] == "done" and result["promoted"] == 1 and result["archived"] == 0
    row = _row(guess)
    assert row.settled_at == NOW and row.status == "active" and row.updated_at == _days(95)
    block, _ids = profile.render_block(OWNER_HASH)
    assert "·长期" in block and "先要结论再看细节" in block
    assert profile.serialize(row)["settled_label"] == "长期"


def test_a_guess_confirmed_too_recently_or_not_seen_lately_is_not_settled():
    recent = _item("刚确认的", confirmed=_days(20), seen=_days(5))
    unseen = _item("很久没提的", confirmed=_days(150), seen=_days(130))
    proposed = _item("还没确认的", status="proposed", confirmed=_days(150), seen=_days(5))
    settle.run(OWNER_HASH, NOW, None)
    assert _row(recent).settled_at is None and _row(unseen).settled_at is None and _row(proposed).settled_at is None


def test_a_guess_not_seen_for_200_days_is_archived_with_the_date_and_an_explicit_item_untouched_for_two_years_is_not():
    old = _item("三季度关心苹果", seen=datetime(2026, 4, 28, 8, 0, tzinfo=UTC))
    inferred = _item("推断的老习惯", origin="inferred", seen=_days(200))
    explicit = _item("回答用中文", origin="explicit", seen=_days(730))
    manual = _item("手写的老条目", origin="manual", seen=_days(730))
    fresh = _item("最近的推断", origin="inferred", seen=_days(10))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["archived"] == 2 and result["promoted"] == 0
    row = _row(old)
    assert row.status == "archived" and row.archived_at == NOW and row.archived_reason == "很久没在你的话里出现（最后一次 4月28日）"
    assert len(row.archived_reason) <= 80
    assert _row(inferred).status == "archived"
    assert all(_row(i).status == "active" and _row(i).archived_at is None for i in (explicit, manual, fresh))


def test_a_settled_item_is_archived_only_after_twice_the_period():
    kept = _item("长期的一", settled=_days(100), confirmed=_days(300), seen=_days(250))
    gone = _item("长期的二", settled=_days(100), confirmed=_days(500), seen=_days(370))
    settle.run(OWNER_HASH, NOW, None)
    assert _row(kept).status == "active" and _row(gone).status == "archived"


def test_the_days_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("FINBOT_MEMORY_STALE_DAYS", "30")
    stale = _item("四十天没提", origin="inferred", seen=_days(40))
    settle.run(OWNER_HASH, NOW, None)
    assert _row(stale).status == "archived"


# ---- Review Focus 2 --------------------------------------------------------------------------------------------------

def test_a_view_on_a_company_he_sold_is_archived_and_the_same_company_in_the_queue_is_kept():
    _buy("NVDA", 10, "2025-06-01")
    _buy("NVDA", -10, "2026-08-20")        # sold last quarter
    _buy("AMD", 5, "2025-06-01")           # still held
    sold, queued, held, talked = _view("NVDA"), _view("TSLA", "太贵"), _view("AMD", "不错"), _view("AAPL", "一般")
    with SessionLocal() as db:
        db.add(AgentResearchQueue(owner_hash=OWNER_HASH, symbols=["TSLA"]))
        db.commit()
    _say("苹果这周发布会你怎么看", _days(20))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["views_archived"] == 1
    with SessionLocal() as db:
        statuses = {v.symbol: (v.status, v.archived_reason, v.ended_at) for v in db.query(OwnerView).all()}
    assert statuses["NVDA"] == ("archived", "你已不持有、不在关注列表，也很久没提", NOW)
    assert statuses["TSLA"][0] == statuses["AMD"][0] == statuses["AAPL"][0] == "active"


def test_a_bots_focus_company_or_a_recent_mention_by_name_keeps_the_view():
    _view("NVDA"), _view("AAPL"), _view("MSFT")
    with SessionLocal() as db:
        bot = agent_bots.ensure_default_bot(OWNER_HASH)
        db.query(AgentBot).filter_by(id=bot.id).update({"focus": {"companies": [{"symbol": "MSFT", "name": None}], "theme": None}})
        db.commit()
    _say("英伟达最近怎么样", _days(30))
    _say("这条是很久以前提到苹果的", _days(400))      # outside the window
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["views_archived"] == 1
    assert owner_views.current(OWNER_HASH, ["NVDA", "AAPL", "MSFT"]).keys() == {"NVDA", "MSFT"}


def test_a_system_posted_row_is_not_his_mention():
    _view("NVDA")
    from app import work
    with SessionLocal() as db:
        line = db.get(AgentConversation, agent_bots.ensure_default_bot(OWNER_HASH).conversation_id)
        work.post_system_message(db, line, "任务", "英伟达财报出了", {})
        db.commit()
    assert settle.run(OWNER_HASH, NOW, None)["views_archived"] == 1


def test_an_unreadable_ledger_leaves_the_views_alone(monkeypatch):
    _view("NVDA")
    monkeypatch.setattr(settle, "_held", lambda owner: (_ for _ in ()).throw(RuntimeError("boom")))
    assert settle.run(OWNER_HASH, NOW, None)["views_archived"] == 0


# ---- the note --------------------------------------------------------------------------------------------------------

def test_one_system_posted_note_lists_both_kinds_and_one_notice_goes_out():
    _item("先要结论再看细节", confirmed=_days(95), seen=_days(30))
    _item("推断的老习惯", origin="inferred", seen=_days(200))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["posted"] is True
    [note] = _posted()
    assert note.startswith("这一季的记忆整理：") and "转为长期 1 条" in note and "- 先要结论再看细节" in note
    assert "归档 1 条" in note and "推断的老习惯（很久没在你的话里出现" in note and note.endswith("归档的都还在记忆页，可以恢复。")
    assert _notices() == 1
    with SessionLocal() as db:
        marked = db.query(AgentMessage).filter(AgentMessage.role == "assistant").one()
        assert marked.tool_calls.get("memory_settle") is True


def test_nothing_changed_posts_nothing():
    _item("回答用中文", origin="explicit", seen=_days(700))
    _item("最近的推断", origin="inferred", seen=_days(5))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["outcome"] == "done" and (result["promoted"], result["archived"], result["posted"]) == (0, 0, False)
    assert _posted() == [] and _notices() == 0


def test_another_owners_items_are_never_touched():
    other = _item("别人的推断", origin="inferred", seen=_days(300), owner="somebody-else")
    settle.run(OWNER_HASH, NOW, None)
    assert _row(other).status == "active"


# ---- Review Focus 3: the calendar ------------------------------------------------------------------------------------

def _registered(created):
    sched.register(JOB, OWNER_HASH)
    with SessionLocal() as db:
        db.query(MemoryJob).filter_by(job=JOB).update({"created_at": created})
        db.commit()


def test_the_job_is_registered_and_listed_with_its_title():
    assert sched.JOBS[JOB] == "app.memory_settle:run" and sched.JOB_TITLES[JOB] == "每季整理记忆"
    from app import work
    sched.register(JOB, OWNER_HASH)
    assert any(i["title"] == "每季整理记忆" for i in work._memory_items(OWNER_HASH, NOW))


def test_first_run_is_the_first_anchor_after_registration_and_then_one_catch_up_run():
    _registered(datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    assert sched.due(datetime(2027, 2, 14, 23, 0, tzinfo=UTC)) == []
    assert sched.due(datetime(2027, 2, 15, 0, 0, tzinfo=UTC)) == [(JOB, OWNER_HASH)]
    assert sched.next_due(JOB, OWNER_HASH) == datetime(2027, 2, 15, tzinfo=UTC)
    # the box was down over 05-15 and comes back 05-20: one run, then next due 08-15
    with SessionLocal() as db:
        db.query(MemoryJob).filter_by(job=JOB).update({"last_run_at": datetime(2027, 2, 15, 0, 5, tzinfo=UTC)})
        db.commit()
    back = datetime(2027, 5, 20, 8, 0, tzinfo=UTC)
    ran = []
    assert sched.tick(back, runner=lambda job, owner, now, last: ran.append(job) or {"outcome": "done", "reason": "ok"}) == 1
    assert ran == [JOB]
    assert sched.tick(back + timedelta(minutes=10), runner=lambda *a: ran.append("again") or {"outcome": "done"}) == 0
    assert sched.next_due(JOB, OWNER_HASH) == datetime(2027, 8, 15, tzinfo=UTC)


def test_a_bad_anchor_entry_is_skipped_and_the_year_rolls_over(monkeypatch):
    monkeypatch.setenv("FINBOT_MEMORY_QUARTER_ANCHORS", "13-40, 03-01 ,nonsense")
    assert sched.next_anchor(datetime(2026, 12, 1, tzinfo=UTC)) == datetime(2027, 3, 1, tzinfo=UTC)
    monkeypatch.delenv("FINBOT_MEMORY_QUARTER_ANCHORS")
    assert sched.next_anchor(datetime(2026, 11, 15, tzinfo=UTC)) == datetime(2027, 2, 15, tzinfo=UTC)   # strictly after


def test_the_monthly_review_keeps_its_own_rule():
    sched.register("monthly_review", OWNER_HASH)
    with SessionLocal() as db:
        db.query(MemoryJob).filter_by(job="monthly_review").update({"created_at": NOW - timedelta(days=31)})
        db.commit()
    assert ("monthly_review", OWNER_HASH) in sched.due(NOW)


# ---- Review Focus 5: restore -----------------------------------------------------------------------------------------

def test_restoring_an_archived_item_puts_it_back_active_seen_now_with_the_archive_fields_cleared():
    old = _item("推断的老习惯", origin="inferred", seen=_days(200))
    settle.run(OWNER_HASH, NOW, None)
    assert _row(old).status == "archived"
    restored = profile.restore_item(OWNER_HASH, old, now=NOW + timedelta(days=1))
    assert restored["status"] == "active" and restored["archived_at"] is None and restored["archived_reason"] is None
    row = _row(old)
    assert row.last_seen_at == NOW + timedelta(days=1) and row.status == "active"
    assert profile.restore_item(OWNER_HASH, old) is None                     # no longer archived
    assert profile.restore_item("somebody-else", old) is None


def test_restore_routes_are_owner_only_and_a_view_with_a_current_one_is_refused(client):
    old = _item("推断的老习惯", origin="inferred", seen=_days(200))
    first = _view("NVDA", "估值太高了")
    settle.run(OWNER_HASH, NOW, None)
    guest, owner = {"X-Chat-Session": "g" * 64}, {"X-Chat-Session": OWNER}
    assert client.post(f"/agent-chat/profile/{old}/restore", headers=guest).status_code == 403
    assert client.post(f"/agent-chat/views/{first}/restore", headers=guest).status_code == 403
    answer = client.post(f"/agent-chat/profile/{old}/restore", headers=owner)
    assert answer.status_code == 200 and answer.json()["item"]["status"] == "active"
    assert client.post(f"/agent-chat/profile/{old}/restore", headers=owner).status_code == 404
    # a newer current view of the same company blocks the restore
    owner_views.record(OWNER_HASH, "NVDA", "现在看好", "现在看好了，真的")
    blocked = client.post(f"/agent-chat/views/{first}/restore", headers=owner)
    assert blocked.status_code == 409 and blocked.json()["detail"] == "这家公司已有一条当前看法，先撤回它再恢复"
    owner_views.drop(OWNER_HASH, "NVDA")
    ok = client.post(f"/agent-chat/views/{first}/restore", headers=owner)
    assert ok.status_code == 200 and ok.json()["view"]["status"] == "active" and ok.json()["view"]["archived_reason"] is None
    assert client.post(f"/agent-chat/views/{uuid.uuid4()}/restore", headers=owner).status_code == 404


def test_the_registry_exempts_both_restores():
    from app.kernel.operation_registry import OPERATION_REGISTRY
    for path in ("/agent-chat/profile/{item_id}/restore", "/agent-chat/views/{view_id}/restore"):
        assert OPERATION_REGISTRY[("POST", path)] == {"exempt": "本人在页面上恢复"}


# ---- fix round 1 ------------------------------------------------------------------------------------------------------

def test_restore_never_archives_a_newer_item_on_the_same_topic():
    old = _item("金额用万美元", origin="inferred", status="archived", topic="currency_unit", seen=_days(200))
    explicit = _item("金额用亿美元", origin="explicit", topic="currency_unit", seen=_days(5))
    with pytest.raises(profile.ProfileError, match="已有一条同类的记忆在用，先忘掉它再恢复"):
        profile.restore_item(OWNER_HASH, old)
    assert _row(old).status == "archived" and _row(explicit).status == "active"


def test_restore_refuses_a_duplicate_text_and_changes_nothing():
    old = _item("先要结论", origin="inferred", status="archived", seen=_days(200))
    same = _item("  先要结论 ", origin="explicit", seen=_days(5))
    with pytest.raises(profile.ProfileError, match="已有一条同类的记忆在用"):
        profile.restore_item(OWNER_HASH, old)
    assert _row(old).status == "archived" and _row(old).last_seen_at == _days(200) and _row(same).status == "active"


def test_restore_never_evicts_to_make_room(monkeypatch):
    monkeypatch.setattr(profile, "MAX_ACTIVE_ITEMS", 2)
    old = _item("老推断", origin="inferred", status="archived", seen=_days(200))
    first, second = _item("一", origin="inferred", seen=_days(5)), _item("二", origin="explicit", seen=_days(5))
    with pytest.raises(profile.ProfileError, match="profile_full"):
        profile.restore_item(OWNER_HASH, old)
    assert _row(first).status == "active" and _row(old).status == "archived"


def test_the_restore_route_says_why_in_chinese(client):
    old = _item("金额用万美元", origin="inferred", status="archived", topic="currency_unit", seen=_days(200))
    _item("金额用亿美元", origin="explicit", topic="currency_unit")
    answer = client.post(f"/agent-chat/profile/{old}/restore", headers={"X-Chat-Session": OWNER})
    assert answer.status_code == 409 and answer.json()["detail"] == "已有一条同类的记忆在用，先忘掉它再恢复"


def test_confirming_a_guess_records_when_and_promotion_counts_from_it_not_from_edits():
    with SessionLocal() as db:
        row = AgentProfileItem(owner_hash=OWNER_HASH, kind="preference", text="先要结论", origin="pattern", quote="先要结论", status="proposed",
                               created_at=_days(100), updated_at=_days(100), last_seen_at=_days(100))
        db.add(row)
        db.commit()
        guess = str(row.id)
    done = profile.confirm_item(OWNER_HASH, guess)
    assert done["confirmed_at"] is not None and _row(guess).confirmed_at is not None
    # an old confirmation edited yesterday still counts from the confirmation
    settled = _item("早就确认的", confirmed=_days(95), edited=_days(1), seen=_days(10))
    fresh = _item("刚确认的", confirmed=_days(10), edited=_days(95), seen=_days(10))
    legacy = _item("没有确认时间的", confirmed=None, edited=_days(95), seen=_days(10))
    with SessionLocal() as db:
        db.query(AgentProfileItem).filter_by(id=uuid.UUID(legacy)).update({"confirmed_at": None})
        db.commit()
    settle.run(OWNER_HASH, NOW, None)
    assert _row(settled).settled_at == NOW and _row(fresh).settled_at is None and _row(legacy).settled_at is None


def test_startup_backfill_gives_confirmed_guesses_a_confirmed_at_once():
    a = _item("已确认的", confirmed=_days(95))
    with SessionLocal() as db:
        db.query(AgentProfileItem).filter_by(id=uuid.UUID(a)).update({"confirmed_at": None, "updated_at": _days(90)})
        db.commit()
    profile.ensure_seen_columns()
    assert _row(a).confirmed_at == _days(90)
    with SessionLocal() as db:
        db.query(AgentProfileItem).filter_by(id=uuid.UUID(a)).update({"updated_at": _days(1)})
        db.commit()
    profile.ensure_seen_columns()
    assert _row(a).confirmed_at == _days(90)


def test_a_confirmed_guess_comes_back_active_even_if_a_replacement_archived_it_and_an_unconfirmed_one_comes_back_proposed():
    confirmed = _item("确认过的", status="archived", confirmed=_days(100), seen=_days(50))      # no archived_at: not the settle's doing
    unconfirmed = _item("没确认过的", status="archived", seen=_days(50))
    with SessionLocal() as db:
        db.query(AgentProfileItem).filter_by(id=uuid.UUID(unconfirmed)).update({"confirmed_at": None})
        db.commit()
    assert profile.restore_item(OWNER_HASH, confirmed)["status"] == "active"
    assert profile.restore_item(OWNER_HASH, unconfirmed)["status"] == "proposed"


def test_a_failure_reading_the_views_inputs_does_not_lose_the_note_for_what_was_written(monkeypatch):
    _item("推断的老习惯", origin="inferred", seen=_days(200))
    _view("NVDA")
    monkeypatch.setattr(settle, "_queued", lambda db, owner: (_ for _ in ()).throw(RuntimeError("boom")))
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["archived"] == 1 and result["views_archived"] == 0 and result["posted"] is True
    assert "推断的老习惯" in _posted()[0]
    assert owner_views.current(OWNER_HASH, ["NVDA"]).keys() == {"NVDA"}


def test_a_failure_while_archiving_a_view_still_reports_what_was_written(monkeypatch):
    _item("推断的老习惯", origin="inferred", seen=_days(200))
    first, second = _view("NVDA"), _view("TSLA", "太贵")
    real = owner_views.archive
    def flaky(owner, view_id, reason, **kw):
        if view_id == second:
            raise RuntimeError("db went away")
        return real(owner, view_id, reason, **kw)
    monkeypatch.setattr(owner_views, "archive", flaky)
    result = settle.run(OWNER_HASH, NOW, None)
    assert result["archived"] == 1 and result["posted"] is True
    note = _posted()[0]
    assert "推断的老习惯" in note and "归档 " in note
    assert ("看法" in note) == (result["views_archived"] > 0)
