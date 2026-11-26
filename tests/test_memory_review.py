"""4b Task 2: the monthly memory review.  Review Focus 2 (a quote not in the cited message, another owner's or an out-of-window message),
4 (a confirmed proposal leaves the 推测 section and is not proposed again), 5 (fewer than 10 messages: skipped, no model call, no message);
the light-use block, the message and its counts, the channel notice, the 60-day archive, system-posted rows."""
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import agent_bots, agent_profile as profile, memory_review as review, memory_schedule as sched
from app.agent_chat_models import (AgentBot, AgentChannelPref, AgentConversation, AgentMessage, AgentModelRole,
                                   AgentProfileItem, AgentTelegramMessage, MemoryJob)
from app.database import Base, SessionLocal, engine

OWNER = "owner-hash-memory-review"
OTHER = "other-hash-memory-review"
NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=30)
HEADING = "我的推测（未经你确认）：只影响回答的详略和先后，不影响结论和数字"


@pytest.fixture(autouse=True)
def world(monkeypatch):
    import app.agent_tasks  # noqa: F401
    from app import work
    import app.main  # noqa: F401  (every table's model)
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    with SessionLocal() as db:
        for model in (AgentProfileItem, AgentMessage, AgentConversation, AgentTelegramMessage, AgentBot, MemoryJob):
            db.query(model).delete()
        db.commit()
    import app.channels as channels
    monkeypatch.setattr(channels, "available", lambda db, owner, channel, bot: channel == "telegram")
    for name in ("FINBOT_MEMORY_REVIEW_FLOOR",):
        monkeypatch.delenv(name, raising=False)
    review_calls.clear()


review_calls: list = []


def _model(monkeypatch, answer):
    def fake(owner, system, user):
        review_calls.append({"owner": owner, "system": system, "user": user})
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    monkeypatch.setattr(review, "_complete", fake)


def _line(owner=OWNER):
    return agent_bots.ensure_default_bot(owner).conversation_id


def _say(texts, *, owner=OWNER, when=None, role="user", conversation=None):
    """Store owner messages; returns their ids in order."""
    ids = []
    with SessionLocal() as db:
        cid = conversation or _line(owner)
        base = db.query(AgentMessage).filter_by(conversation_id=cid).count()
        for i, text in enumerate(texts):
            row = AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=base + i + 1, role=role, content=text, status="complete",
                               created_at=when or (NOW - timedelta(days=3, minutes=i)))
            db.add(row)
            db.flush()
            ids.append(str(row.id))
        db.commit()
    return ids


def _twelve():
    return _say([f"帮我看看第{i}家公司的现金流，先说结论 {i}" for i in range(12)])


def _proposal(ids, text="提问时总是先要结论", quotes=("先说结论 0", "先说结论 1"), kind="habit"):
    examples = [{"message_id": ids[i], "quote": q} for i, q in enumerate(quotes)]
    return {"text": text, "type": kind, "examples": examples}


def _items(**filters):
    with SessionLocal() as db:
        return db.query(AgentProfileItem).filter_by(owner_hash=OWNER, **filters).all()


def _memory_notices():
    with SessionLocal() as db:
        return db.query(AgentTelegramMessage).filter_by(source="memory").all()


def _posted():
    with SessionLocal() as db:
        return [r.content for r in db.query(AgentMessage).filter(AgentMessage.role == "assistant", AgentMessage.content.contains("对吗")).all()]


def test_fewer_than_ten_owner_messages_is_skipped_with_no_model_call_and_no_message(monkeypatch):
    _model(monkeypatch, {"items": []})
    _say([f"问题{i}" for i in range(9)])
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "skipped" and result["reason"] and review_calls == []
    assert _posted() == [] and _memory_notices() == [] and _items() == []


def test_system_posted_rows_are_neither_counted_nor_shown_to_the_model(monkeypatch):
    from app.agent_tasks import POST_NOTE
    _say([f"问题{i}" for i in range(9)])
    _say([f"【例行任务结果】「晨报」2026-12-01 08:00{POST_NOTE}", f"【任务结果】「预测」{POST_NOTE}", f"随便一句{POST_NOTE}"])
    assert sched.owner_messages_since(OWNER, SINCE) == 9
    assert review.run(OWNER, NOW, SINCE)["reason"] and review_calls == []
    ids = _say(["第十条真话先说结论"])
    _model(monkeypatch, {"items": [_proposal(ids * 2, quotes=("先说结论", "先说结论"))]})
    review.run(OWNER, NOW, SINCE)
    sent = review_calls[0]["user"]
    assert "晨报" not in sent and "随便一句" not in sent and "第十条真话" in sent


def test_a_good_proposal_is_stored_proposed_with_examples_and_the_bad_ones_are_dropped(monkeypatch):
    ids = _twelve()
    other = _say(["别人的话 先说结论"], owner=OTHER)
    old = _say(["很久以前 先说结论"], when=SINCE - timedelta(days=5))
    good = _proposal(ids)
    fabricated = _proposal(ids, "编造的习惯", quotes=("先说结论 0", "这句话他从没说过"))
    foreign = _proposal(ids, "别人的", quotes=("先说结论 0", "别人的话 先说结论"))
    foreign["examples"][1]["message_id"] = other[0]
    outside = _proposal(ids, "窗口外的", quotes=("先说结论 0", "很久以前 先说结论"))
    outside["examples"][1]["message_id"] = old[0]
    single = _proposal(ids, "只有一条", quotes=("先说结论 0", "先说结论 0"))
    single["examples"][1]["message_id"] = ids[0]
    toolong = _proposal(ids, "长" * 81, quotes=("先说结论 2", "先说结论 3"))
    _model(monkeypatch, {"items": [good, fabricated, foreign, outside, single, toolong]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "done" and result["proposed"] == 1 and result["dropped"] == 5
    [row] = _items()
    assert (row.origin, row.status, row.kind, row.text) == ("pattern", "proposed", "preference", "提问时总是先要结论")
    assert [e["message_id"] for e in row.examples] == ids[:2] and row.examples[0]["quote"] == "先说结论 0" and row.examples[0]["date"]
    assert row.review_run is not None


def test_interest_becomes_about_me_and_a_duplicate_of_an_active_item_is_dropped(monkeypatch):
    ids = _twelve()
    profile.add_manual_item(OWNER, kind="preference", text="提问时总是先要结论")
    _model(monkeypatch, {"items": [_proposal(ids), _proposal(ids, "最近在看现金流", quotes=("公司的现金流", "公司的现金流"), kind="interest")]})
    # the second needs two distinct messages
    second = _proposal(ids, "最近在看现金流", quotes=("公司的现金流", "公司的现金流"), kind="interest")
    second["examples"][1]["message_id"] = ids[1]
    _model(monkeypatch, {"items": [_proposal(ids), second]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 1 and result["dropped"] == 1
    [row] = _items(status="proposed")
    assert row.kind == "about_me"


def test_no_proposals_posts_nothing_and_a_model_failure_is_a_failed_run(monkeypatch):
    _twelve()
    _model(monkeypatch, {"items": []})
    result = review.run(OWNER, NOW, SINCE)
    assert result["outcome"] == "done" and result["proposed"] == 0 and _posted() == [] and _memory_notices() == []
    _model(monkeypatch, RuntimeError("boom"))
    assert review.run(OWNER, NOW, SINCE)["outcome"] == "failed"
    _model(monkeypatch, "not json at all")
    failed = review.run(OWNER, NOW, SINCE)
    assert failed["outcome"] == "failed" and failed["reason"]


def test_the_message_is_posted_system_marked_in_the_default_conversation_with_one_notice(monkeypatch):
    from app.agent_tasks import POST_NOTE
    ids = _twelve()
    _model(monkeypatch, {"items": [_proposal(ids)]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 1
    cid = _line()
    with SessionLocal() as db:
        rows = db.query(AgentMessage).filter_by(conversation_id=cid).order_by(AgentMessage.sequence.desc()).limit(2).all()
    answer, head = rows
    assert head.role == "user" and head.content.startswith("【任务结果】") and POST_NOTE in head.content
    assert answer.role == "assistant"
    text = answer.content
    assert text.startswith("这个月我对你的了解多了这几条，对吗？") and "1. 提问时总是先要结论" in text and "先说结论 0" in text
    assert "在记忆页确认或删掉；也可以直接告诉我哪条不对。" in text and "新记 1 条推测、确认了 0 条、删掉 0 条" in text
    [notice] = _memory_notices()
    assert notice.owner_hash == OWNER and "记忆" in notice.text
    # the same day a second run still posts its message but sends no second notice (daily cap 1)
    _model(monkeypatch, {"items": [_proposal(ids, "另一条习惯", quotes=("先说结论 4", "先说结论 5"))]})
    # (quotes point at messages 0 and 1; fix ids)
    second = _proposal(ids, "另一条习惯", quotes=("先说结论 4", "先说结论 5"))
    second["examples"][0]["message_id"], second["examples"][1]["message_id"] = ids[4], ids[5]
    _model(monkeypatch, {"items": [second]})
    review.run(OWNER, NOW, SINCE)
    assert len(_memory_notices()) == 1


def test_the_block_has_a_light_section_for_proposals_and_confirming_moves_it_to_his_items(monkeypatch):
    ids = _twelve()
    profile.add_manual_item(OWNER, kind="preference", text="用人民币")
    _model(monkeypatch, {"items": [_proposal(ids)]})
    review.run(OWNER, NOW, SINCE)
    block, shown = profile.render_block(OWNER)
    lines = block.splitlines()
    assert HEADING in lines
    mine, section = lines.index(next(l for l in lines if "用人民币" in l)), lines.index(HEADING)
    assert mine < section and "提问时总是先要结论" in "\n".join(lines[section + 1:])
    assert "提问时总是先要结论" not in "\n".join(lines[:section])
    [row] = _items(status="proposed")
    confirmed = profile.confirm_item(OWNER, str(row.id))
    assert confirmed["status"] == "active" and confirmed["origin"] == "pattern"
    block, _ = profile.render_block(OWNER)
    assert HEADING not in block and "提问时总是先要结论" in block and "用人民币" in block
    # the next run does not propose it again
    _model(monkeypatch, {"items": [_proposal(ids)]})
    again = review.run(OWNER, NOW + timedelta(days=30), SINCE)
    assert again["proposed"] == 0 and len(_items(origin="pattern")) == 1


def test_the_section_shows_at_most_eight_lines_and_only_proposals_make_a_block(monkeypatch):
    with SessionLocal() as db:
        for i in range(12):
            db.add(AgentProfileItem(owner_hash=OWNER, kind="preference", text=f"推测{i}", origin="pattern", quote=f"q{i}", status="proposed",
                                    examples=[]))
        db.commit()
    block, shown = profile.render_block(OWNER)
    section = block.split(HEADING)[1].strip().splitlines()
    assert len(section) == 8 and len(shown) == 8


def test_the_change_note_counts_only_what_he_confirmed_or_rejected_himself(monkeypatch):
    ids = _twelve()
    with SessionLocal() as db:
        def pattern(text, status, age_days=1, updated=NOW - timedelta(days=2)):
            row = AgentProfileItem(owner_hash=OWNER, kind="preference", text=text, origin="pattern", quote="q", status=status, examples=[],
                                   created_at=NOW - timedelta(days=age_days), updated_at=updated)
            db.add(row)
        pattern("确认的", "active")
        pattern("他删掉的", "proposed")
        pattern("他忘掉的", "proposed")
        pattern("被上限挤掉的", "archived")
        pattern("太久没回的", "proposed", age_days=61, updated=NOW - timedelta(days=61))
        pattern("还在等的", "proposed", age_days=10, updated=NOW - timedelta(days=10))
        db.commit()
    by_text = {r.text: r for r in _items()}
    assert profile.delete_item(OWNER, str(by_text["他删掉的"].id))
    assert profile.archive_item(OWNER, profile.handle(by_text["他忘掉的"].id))
    _model(monkeypatch, {"items": [_proposal(ids)]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["archived"] == 1
    text = _posted()[0]
    assert "新记 1 条推测、确认了 1 条、删掉 2 条" in text and "1 条超过 60 天没回应，已自动归档" in text
    now_rows = {r.text: r for r in _items()}
    assert (now_rows["太久没回的"].status, now_rows["还在等的"].status) == ("archived", "proposed")


def test_a_deleted_proposal_keeps_none_of_his_words_only_a_fingerprint(monkeypatch):
    ids = _twelve()
    _model(monkeypatch, {"items": [_proposal(ids)]})
    review.run(OWNER, NOW, SINCE)
    [row] = _items(status="proposed")
    assert profile.delete_item(OWNER, str(row.id)) is True
    [gone] = _items()
    assert gone.status == "rejected" and gone.quote == "" and not gone.examples and gone.source_message_id is None
    assert "先说结论" not in gone.text and "结论" not in gone.text and gone.text.startswith(profile.FINGERPRINT_PREFIX)
    assert "结论" not in "".join(profile.review_texts(OWNER))
    _model(monkeypatch, {"items": [_proposal(ids)]})
    again = review.run(OWNER, NOW + timedelta(days=30), SINCE)
    assert again["proposed"] == 0 and again["dropped"] == 1
    assert "提问时总是先要结论" not in review_calls[-1]["user"]


def test_one_bad_example_is_dropped_on_its_own_and_the_proposal_kept_when_two_messages_still_back_it(monkeypatch):
    ids = _twelve()
    three = _proposal(ids, "三条里一条是编的", quotes=("先说结论 0", "先说结论 1", "这句话他从没说过"))
    three["examples"][2]["message_id"] = ids[2]
    _model(monkeypatch, {"items": [three]})
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 1
    [row] = _items()
    assert [e["quote"] for e in row.examples] == ["先说结论 0", "先说结论 1"]


def test_a_two_character_quote_is_not_an_example(monkeypatch):
    ids = _say([f"的话我们{i} 先说结论 {i}" for i in range(12)])
    short = _proposal(ids, "只靠两个字", quotes=("的话", "的话"))
    short["examples"][1]["message_id"] = ids[1]
    _model(monkeypatch, {"items": [short]})
    assert review.run(OWNER, NOW, SINCE)["proposed"] == 0


def test_a_run_whose_window_is_smaller_than_the_floor_is_skipped(monkeypatch):
    _say([f"问题{i}" for i in range(9)])
    _say([f"confirm:{i}" for i in range(5)])
    _model(monkeypatch, {"items": []})
    assert review.run(OWNER, NOW, SINCE)["outcome"] == "skipped" and review_calls == []


def test_forget_and_deleting_work_on_proposed_items(monkeypatch):
    ids = _twelve()
    _model(monkeypatch, {"items": [_proposal(ids)]})
    review.run(OWNER, NOW, SINCE)
    [row] = _items(status="proposed")
    assert profile.resolve_handle(OWNER, profile.handle(row.id), every_bot=True)["id"] == str(row.id)
    assert profile.archive_item(OWNER, profile.handle(row.id))["status"] == "rejected"
    assert profile.render_block(OWNER)[0] is None
    assert profile.delete_item(OWNER, str(row.id)) is True
    # a deleted proposal is not proposed again
    _model(monkeypatch, {"items": [_proposal(ids)]})
    assert review.run(OWNER, NOW + timedelta(days=30), SINCE)["proposed"] == 0


def test_at_most_twenty_proposed_at_once_oldest_first_and_eight_per_run(monkeypatch):
    ids = _twelve()
    with SessionLocal() as db:
        for i in range(19):
            db.add(AgentProfileItem(owner_hash=OWNER, kind="preference", text=f"旧推测{i}", origin="pattern", quote="q", status="proposed",
                                    examples=[], created_at=NOW - timedelta(days=20 - i % 20, minutes=i), updated_at=NOW - timedelta(days=5)))
        db.commit()
    items = []
    for n in range(10):
        p = _proposal(ids, f"新习惯{n}", quotes=("先说结论 0", "先说结论 1"))
        items.append(p)
    _model(monkeypatch, {"items": items})
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 8
    assert len(_items(status="proposed")) == 20


def test_the_memory_role_exists_and_resolves_to_the_server_default_when_unset(monkeypatch):
    from app import agent_model_roles as roles
    assert "memory" in roles.ROLES and roles.all_roles(OWNER)["memory"] is None
    asked = {}
    monkeypatch.setattr(roles, "resolve", lambda owner, role: asked.update(owner=owner, role=role) or {"name": "x"})
    assert review._model_for(OWNER) == {"name": "x"} and asked == {"owner": OWNER, "role": "memory"}


# --- the guesses the model wrote during a chat (kernel memory writes, slice A5) -----------------------------------------------------------

def _guess(text, when=None, quote="先说结论 3"):
    return profile.add_noticed(OWNER, kind="preference", text=text, quote=quote, now=when or NOW - timedelta(days=2))


def test_the_message_lists_the_waiting_in_chat_guesses_after_its_own_proposals_and_does_not_propose_them_again(monkeypatch):
    ids = _twelve()
    _guess("总是先要结论")
    _guess("上个月就记下的猜测", when=SINCE - timedelta(days=5))       # older than the last run: he has seen it in that month's message
    _model(monkeypatch, {"items": [_proposal(ids), _proposal(ids, text="总是先要结论")]})        # the second repeats the in-chat guess
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 1 and result["dropped"] == 1
    sent = json.loads(review_calls[0]["user"])
    assert "总是先要结论" in sent["known"] and "上个月就记下的猜测" in sent["known"]
    text = _posted()[0]
    assert "1. 提问时总是先要结论（我的推测）" in text and "2. 总是先要结论（我的推测）\n   例：「先说结论 3」" in text and "上个月就记下的猜测" not in text
    assert "新记 1 条推测" in text
    assert len(_items(status="proposed")) == 3


def test_waiting_guesses_alone_still_get_a_message_and_a_confirmed_or_reviewed_one_is_not_listed(monkeypatch):
    _twelve()
    _guess("总是先要结论")
    _guess("别的习惯")
    with SessionLocal() as db:
        db.query(AgentProfileItem).filter_by(text="别的习惯").update({"review_run": uuid.uuid4()})      # a review's own proposal: its message already listed it
        db.commit()
    _model(monkeypatch, {"items": []})
    result = review.run(OWNER, NOW, SINCE)
    assert result["proposed"] == 0 and result["posted"] is True
    text = _posted()[0]
    assert "1. 总是先要结论（我的推测）" in text and "别的习惯" not in text


def test_flag_off_the_message_is_the_earlier_one(monkeypatch):
    monkeypatch.setenv("FINBOT_KERNEL_MEMORY_WRITES", "off")
    ids = _twelve()
    _guess("总是先要结论")
    _model(monkeypatch, {"items": []})
    assert review.run(OWNER, NOW, SINCE)["posted"] is False and _posted() == []
    _model(monkeypatch, {"items": [_proposal(ids)]})
    review.run(OWNER, NOW, SINCE)
    assert "2. " not in _posted()[0] and "例：「先说结论 3」" not in _posted()[0]
