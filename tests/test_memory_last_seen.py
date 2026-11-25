"""4c Task 1: every profile item records when the owner's own words last bore it out (``last_seen_at``).
Review Focus 4 (the monthly review's ``still_seen``: a fabricated quote does not bump, a real one bumps to that message's date), the bump when
he repeats an item through ``add_item``, the startup backfill being idempotent, ``bump_seen`` never moving backwards."""
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text as sql

from app import agent_bots, agent_profile as profile, memory_review as review
from app.agent_chat_models import (AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentTelegramMessage, MemoryJob)
from app.database import Base, SessionLocal, engine

OWNER = "owner-hash-last-seen"
NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=30)
OLD = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
calls: list = []


@pytest.fixture(autouse=True)
def world(monkeypatch):
    import app.agent_tasks  # noqa: F401
    import app.main  # noqa: F401
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    with SessionLocal() as db:
        for model in (AgentProfileItem, AgentMessage, AgentConversation, AgentTelegramMessage, AgentBot, MemoryJob):
            db.query(model).delete()
        db.commit()
    monkeypatch.delenv("FINBOT_MEMORY_REVIEW_FLOOR", raising=False)
    calls.clear()


def _model(monkeypatch, answer):
    def fake(owner, system, user):
        calls.append({"system": system, "user": user})
        return json.dumps(answer, ensure_ascii=False)
    monkeypatch.setattr(review, "_complete", fake)


def _say(texts, *, when=None):
    ids = []
    with SessionLocal() as db:
        cid = agent_bots.ensure_default_bot(OWNER).conversation_id
        base = db.query(AgentMessage).filter_by(conversation_id=cid).count()
        for i, text in enumerate(texts):
            row = AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=base + i + 1, role="user", content=text, status="complete",
                               created_at=when or (NOW - timedelta(days=3, minutes=i)))
            db.add(row)
            db.flush()
            ids.append(str(row.id))
        db.commit()
    return ids


def _item(text="回答用中文", *, origin="explicit", status="active", kind="preference", topic=None, seen=OLD):
    with SessionLocal() as db:
        row = AgentProfileItem(owner_hash=OWNER, kind=kind, topic=topic, text=text, origin=origin, quote=text, status=status,
                               created_at=OLD, updated_at=OLD, last_seen_at=seen)
        db.add(row)
        db.commit()
        return str(row.id)


def _row(item_id):
    with SessionLocal() as db:
        row = db.get(AgentProfileItem, uuid.UUID(item_id))
        db.expunge(row)
        return row


def _twelve():
    return _say([f"帮我看看第{i}家公司的现金流，先说结论 {i}" for i in range(12)])


def test_the_item_has_the_four_new_fields_and_serialize_shows_them():
    item_id = _item()
    row = _row(item_id)
    assert row.last_seen_at == OLD and row.archived_at is None and row.archived_reason is None and row.settled_at is None
    data = profile.serialize(row)
    assert data["last_seen_at"] == OLD.isoformat() and data["archived_at"] is None
    assert data["archived_reason"] is None and data["settled_at"] is None


def test_the_startup_backfill_sets_last_seen_from_created_at_once_and_is_idempotent():
    item_id = _item(seen=None)
    profile.ensure_seen_columns()
    assert _row(item_id).last_seen_at == OLD
    later = NOW
    profile.bump_seen(OWNER, item_id, later)
    profile.ensure_seen_columns()
    assert _row(item_id).last_seen_at == later          # a second startup does not overwrite what was learned since


def test_bump_seen_moves_forward_only_and_leaves_use_and_edit_times_alone():
    item_id = _item()
    assert profile.bump_seen(OWNER, item_id, NOW) is True
    assert profile.bump_seen(OWNER, item_id, NOW - timedelta(days=40)) is False
    row = _row(item_id)
    assert row.last_seen_at == NOW and row.last_used_at is None and row.updated_at == OLD
    assert profile.bump_seen("someone-else", item_id, NOW + timedelta(days=1)) is False
    assert profile.bump_seen(OWNER, "not-an-id", NOW) is False


def test_he_repeats_an_existing_item_in_the_same_words_and_it_is_seen_now():
    first = profile.add_manual_item(OWNER, kind="preference", text="回答用中文")["item"]
    with SessionLocal() as db:
        db.query(AgentProfileItem).update({"last_seen_at": OLD})
        db.commit()
    again = profile.add_manual_item(OWNER, kind="preference", text="回答用中文")
    assert again["status"] == "duplicate" and again["item"]["id"] == first["id"]
    assert _row(first["id"]).last_seen_at > datetime.now(UTC) - timedelta(minutes=5)


def test_a_new_explicit_item_on_the_same_topic_is_seen_now_and_the_replaced_one_is_archived():
    old = _item("用美元", topic="currency_unit")
    out = profile.add_item(OWNER, kind="preference", text="用人民币", quote="用人民币", message="请用人民币", origin="explicit", topic="currency_unit")
    assert out["status"] == "added"
    assert _row(old).status == "archived" and _row(old).last_seen_at == OLD     # the replaced row is not "seen" again
    assert _row(out["item"]["id"]).last_seen_at is not None and _row(out["item"]["id"]).last_seen_at > OLD


def test_a_proposal_starts_seen_at_its_creation():
    ids = _twelve()
    stored = profile.add_proposed(OWNER, kind="preference", text="先要结论", review_run=uuid.uuid4(), now=NOW,
                                  examples=[{"message_id": ids[0], "quote": "先说结论 0", "date": "2026-12-17"}])
    assert _row(stored["id"]).last_seen_at == NOW


def test_still_seen_with_a_real_quote_bumps_to_that_messages_date_and_a_fabricated_one_does_not(monkeypatch):
    ids = _twelve()
    real, fake_quote, unknown = _item("喜欢先看结论"), _item("关心现金流"), _item("无关的旧习惯")
    handle = profile.handle
    _model(monkeypatch, {"items": [], "still_seen": [
        {"handle": handle(real), "examples": [{"message_id": ids[2], "quote": "先说结论 2"}, {"message_id": ids[0], "quote": "先说结论 0"}]},
        {"handle": handle(fake_quote), "examples": [{"message_id": ids[1], "quote": "这句话他从没说过"}]},
        {"handle": "#deadbeef", "examples": [{"message_id": ids[1], "quote": "先说结论 1"}]},
        {"handle": handle(unknown), "examples": []}]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "done" and result["seen"] == 1 and result["seen_unverified"] == 3
    newest = (NOW - timedelta(days=3)).date()
    assert _row(real).last_seen_at.date() == newest and _row(real).last_seen_at > OLD
    assert _row(fake_quote).last_seen_at == OLD and _row(unknown).last_seen_at == OLD
    sent = json.loads(calls[0]["user"])
    assert {"handle": handle(real), "text": "喜欢先看结论"} in sent["active"]
    assert "still_seen" in calls[0]["system"]


def test_still_seen_cannot_bump_an_archived_or_proposed_item_or_another_owners(monkeypatch):
    ids = _twelve()
    archived, proposed = _item("归档的", status="archived"), _item("待确认的", origin="pattern", status="proposed")
    _model(monkeypatch, {"items": [], "still_seen": [
        {"handle": profile.handle(archived), "examples": [{"message_id": ids[0], "quote": "先说结论 0"}]},
        {"handle": profile.handle(proposed), "examples": [{"message_id": ids[0], "quote": "先说结论 0"}]}]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["seen"] == 0 and result["seen_unverified"] == 2
    assert _row(archived).last_seen_at == OLD and _row(proposed).last_seen_at == OLD


def test_the_example_check_is_one_function_shared_by_proposals_and_still_seen():
    by_id = {"m1": {"id": "m1", "content": "先说结论吧", "date": "2026-12-01"}}
    kept = review._valid_examples([{"message_id": "m1", "quote": "先说结论"}, {"message_id": "m1", "quote": "编造的话一句"},
                                   {"message_id": "m1", "quote": "先"}], by_id, 3)
    assert [e["quote"] for e in kept] == ["先说结论"]


def test_a_reply_without_still_seen_is_still_a_normal_review(monkeypatch):
    _twelve()
    _model(monkeypatch, {"items": []})
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "done" and result["seen"] == 0 and result["seen_unverified"] == 0


def test_a_reply_with_only_still_seen_is_a_normal_run_with_no_proposals_and_still_bumps(monkeypatch):
    ids = _twelve()
    real = _item("喜欢先看结论")
    _model(monkeypatch, {"still_seen": [{"handle": profile.handle(real), "examples": [{"message_id": ids[2], "quote": "先说结论 2"}]}]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "done" and result["proposed"] == 0 and result["seen"] == 1
    assert _row(real).last_seen_at > OLD


def test_a_json_reply_with_neither_items_nor_still_seen_is_a_failed_run_but_either_key_even_empty_is_normal(monkeypatch):
    _twelve()
    _model(monkeypatch, {"error": "rate limited"})
    failed = review.run(OWNER, NOW, SINCE)
    assert failed["outcome"] == "failed" and failed["reason"] == "模型回复里没有可用的内容"
    for reply in ({"items": []}, {"still_seen": []}):
        _model(monkeypatch, reply)
        assert review.run(OWNER, NOW, SINCE)["outcome"] == "done"


def test_the_per_turn_extractor_re_inferring_his_own_item_bumps_its_last_seen_and_keeps_his_origin():
    first = profile.add_item(OWNER, kind="preference", text="喜欢先看结论", quote="先说结论", message="请先说结论", origin="explicit")["item"]
    with SessionLocal() as db:
        db.query(AgentProfileItem).update({"last_seen_at": OLD})
        db.commit()
    again = profile.add_item(OWNER, kind="preference", text="喜欢先看结论", quote="先说结论", message="还是先说结论", origin="inferred")
    assert again["status"] == "duplicate" and again["item"]["id"] == first["id"]
    assert _row(first["id"]).last_seen_at > datetime.now(UTC) - timedelta(minutes=5)
    assert _row(first["id"]).origin == "explicit"
