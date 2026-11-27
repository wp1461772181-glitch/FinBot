"""5d-2: the memory change log (``app/memory_events.py``).  Every change to a profile item or a view version writes its event in the same
transaction, with who made it and its basis; consequences carry their cause's ``by``; a deletion takes the item's words out of its earlier
events; a rolled-back change leaves no event; the backfill rebuilds what came before once.  Real PostgreSQL (the test database).
"""
import ast
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text as text_sql

import app
from app import agent_profile as profile, memory_events, memory_settle as settle, owner_views
from app.agent_chat_models import AgentBot, AgentProfileItem, MemoryEvent, OwnerView, ViewReview
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine

OWNER_HASH = owner_hash("memory-events-owner")
OTHER_HASH = owner_hash("memory-events-someone-else")
NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)       # before any real clock this runs on: a change made "now" sorts after it
CID, TID, MID = (str(uuid.uuid4()) for _ in range(3))
RUN = uuid.uuid4()
CHAT = memory_events.chat(CID, TID, MID)


@pytest.fixture(autouse=True)
def world(disposable_database):
    Base.metadata.create_all(engine, tables=[AgentProfileItem.__table__, AgentBot.__table__, OwnerView.__table__, ViewReview.__table__,
                                             MemoryEvent.__table__])
    profile.ensure_bot_column()
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    profile.ensure_template_column()
    owner_views.ensure_archive_column()
    with SessionLocal() as db:
        for model in (MemoryEvent, ViewReview, OwnerView, AgentProfileItem, AgentBot):
            db.query(model).delete()
        db.commit()
    yield


def events(item_id=None, owner=OWNER_HASH):
    """The owner's events (of one item), oldest first."""
    with SessionLocal() as db:
        query = select(MemoryEvent).where(MemoryEvent.owner_hash == owner)
        if item_id is not None:
            query = query.where(MemoryEvent.item_id == uuid.UUID(str(item_id)))
        return [memory_events.as_dict(row) for row in db.scalars(query.order_by(MemoryEvent.at, MemoryEvent.id))]


def actions(item_id):
    return [event["action"] for event in events(item_id)]


def at(event):
    """An event's time as an instant (the database hands it back in its own session's zone)."""
    return datetime.fromisoformat(event["at"])


def explicit(text, *, topic=None, by=CHAT, kind="preference", bot_id=None):
    return profile.add_item(OWNER_HASH, kind=kind, topic=topic, text=text, quote=text, message=text, origin="explicit", source_message_id=MID,
                            bot_id=bot_id, by=by)


def a_bot(name="研究员"):
    with SessionLocal() as db:
        row = AgentBot(owner_hash=OWNER_HASH, name=name, is_default=False)
        db.add(row)
        db.commit()
        return row.id


def stored_item(text, **fields):
    """A profile row written straight to the table, with no event (as every row was before the log)."""
    values = {"owner_hash": OWNER_HASH, "kind": "preference", "text": text, "origin": "explicit", "quote": text, "status": "active",
              "created_at": NOW - timedelta(days=200), "updated_at": NOW - timedelta(days=100), "last_seen_at": NOW - timedelta(days=100), **fields}
    with SessionLocal() as db:
        row = AgentProfileItem(**values)
        db.add(row)
        db.commit()
        return row.id


def stored_view(symbol, text, **fields):
    values = {"owner_hash": OWNER_HASH, "symbol": symbol, "text": text, "quote": text, "status": "active", "created_at": NOW - timedelta(days=50), **fields}
    with SessionLocal() as db:
        row = OwnerView(**values)
        db.add(row)
        db.commit()
        return row.id


# --- profile: each function writes its event ----------------------------------------------------------------------------

def test_an_item_said_in_chat_is_added_by_chat_with_his_quote_and_where_it_came_from():
    added = profile.add_item(OWNER_HASH, kind="preference", text="金额用亿美元", quote="以后金额用亿美元", message="以后金额用亿美元，谢谢",
                             origin="explicit", source_message_id=MID, by=CHAT)
    [event] = events(added["item"]["id"])
    assert (event["target"], event["action"], event["by"], event["text"], event["reconstructed"]) == ("profile", "added", "chat", "金额用亿美元", False)
    assert event["basis"] == {"conversation_id": CID, "turn_id": TID, "message_id": MID, "quote": "以后金额用亿美元"}


def test_a_page_item_is_the_pages_and_its_typed_text_is_not_repeated_as_a_quote():
    item = profile.add_manual_item(OWNER_HASH, kind="instruction", text="先说结论")["item"]
    [event] = events(item["id"])
    assert (event["action"], event["by"], event["text"], event["basis"]) == ("added", "page", "先说结论", {})


def test_no_actor_is_unknown():
    item = profile.add_manual_item(OWNER_HASH, kind="instruction", text="先说结论")["item"]
    profile.confirm_item(OWNER_HASH, item["id"])
    assert [(e["action"], e["by"]) for e in events(item["id"])] == [("added", "page"), ("confirmed", "unknown")]


def test_a_plain_repeat_writes_nothing_and_a_guess_he_then_says_himself_is_confirmed_restated():
    inferred = profile.add_item(OWNER_HASH, kind="preference", text="回答用中文", quote="用中文回答", message="请用中文回答我", origin="inferred",
                                source_message_id=MID, by=memory_events.extract(MID))
    item_id = inferred["item"]["id"]
    assert profile.add_item(OWNER_HASH, kind="preference", text="回答用中文", quote="用中文回答", message="请用中文回答我",
                            origin="inferred", by=memory_events.extract(MID))["status"] == "duplicate"
    assert actions(item_id) == ["added"]
    assert events(item_id)[0]["by"] == "extract"
    profile.add_item(OWNER_HASH, kind="preference", text="回答用中文", quote="回答用中文", message="回答用中文", origin="explicit", by=CHAT)
    confirmed = events(item_id)[1]
    assert (confirmed["action"], confirmed["by"], confirmed["reason"]) == ("confirmed", "chat", "restated")
    explicit("回答用中文")
    assert actions(item_id) == ["added", "confirmed"], "a repeat of his own words is not a change"


def test_a_topic_replaced_carries_the_cause_and_names_the_item_that_replaced_it():
    first = explicit("金额用万元", topic="currency_unit", by=memory_events.PAGE)["item"]["id"]
    second = explicit("金额用亿美元", topic="currency_unit", by=CHAT)["item"]["id"]
    archived = events(first)[-1]
    assert (archived["action"], archived["by"], archived["reason"], archived["text"]) == ("archived", "chat", "replaced", "金额用万元")
    assert archived["basis"]["by_item"] == second and archived["basis"]["conversation_id"] == CID


def test_the_cap_archives_the_oldest_guess_with_the_cause_and_reason_cap():
    first = None
    for index in range(profile.MAX_ACTIVE_ITEMS):
        text = f"偏好第{index}条"
        added = profile.add_item(OWNER_HASH, kind="preference", text=text, quote=text, message=text, origin="inferred", by=memory_events.extract(None))
        first = first or added["item"]["id"]
    explicit("最后一条")
    archived = events(first)[-1]
    assert (archived["action"], archived["by"], archived["reason"]) == ("archived", "chat", "cap")


def test_a_failed_change_rolls_its_event_back_with_it():
    for index in range(profile.MAX_ACTIVE_ITEMS):
        explicit(f"我的规矩{index}")
    with pytest.raises(profile.ProfileError, match="profile_full"):
        explicit("放不下的一条")
    assert len(events()) == profile.MAX_ACTIVE_ITEMS
    assert not any(e["text"] == "放不下的一条" for e in events())


def test_an_edit_rolled_back_by_a_later_refusal_leaves_no_event():
    item = profile.add_manual_item(OWNER_HASH, kind="about_me", text="住在上海")["item"]
    with pytest.raises(profile.ProfileError, match="unknown_bot"):
        profile.update_item(OWNER_HASH, item["id"], {"text": "住在北京", "bot_id": str(uuid.uuid4())}, by=memory_events.PAGE)
    assert actions(item["id"]) == ["added"], "the edit was rolled back, so was its event"
    assert profile.list_items(OWNER_HASH)[0]["text"] == "住在上海"


def test_forget_archives_his_item_and_rejects_a_guess_whose_words_leave_the_log():
    kept = explicit("先看现金流")["item"]["id"]
    profile.archive_item(OWNER_HASH, kept, by=CHAT)
    assert [(e["action"], e["by"]) for e in events(kept)] == [("added", "chat"), ("archived", "chat")]
    guess = profile.add_noticed(OWNER_HASH, kind="preference", text="喜欢短回答", quote="说短一点就行", message_id=MID, by=CHAT)["item"]["id"]
    noticed = events(guess)[0]
    assert (noticed["action"], noticed["by"], noticed["text"], noticed["basis"]["quote"], noticed["basis"]["message_id"]) == ("noticed", "chat", "喜欢短回答", "说短一点就行", MID)
    profile.archive_item(OWNER_HASH, guess, by=CHAT)
    rows = events(guess)
    assert [e["action"] for e in rows] == ["noticed", "rejected"]
    assert all(e["text"] is None and e["before"] is None and "quote" not in e["basis"] and "examples" not in e["basis"] for e in rows)
    assert rows[0]["by"] == "chat" and rows[0]["basis"]["conversation_id"] == CID, "what happened and who did it stay"


def test_a_deletion_scrubs_every_earlier_event_of_that_item_and_only_that_item():
    item = profile.add_manual_item(OWNER_HASH, kind="about_me", text="住在上海")["item"]["id"]
    other = explicit("先看现金流")["item"]["id"]
    profile.update_item(OWNER_HASH, item, {"text": "住在北京"}, by=memory_events.PAGE)
    edited = events(item)[1]
    assert (edited["action"], edited["before"], edited["text"]) == ("edited", "住在上海", "住在北京")
    assert profile.delete_item(OWNER_HASH, item, by=memory_events.PAGE)
    rows = events(item)
    assert [e["action"] for e in rows] == ["added", "edited", "deleted"]
    assert all(e["text"] is None and e["before"] is None for e in rows)
    assert all(e["by"] == "page" for e in rows)
    assert events(other)[0]["text"] == "先看现金流", "another item's words stay"


def test_a_review_proposal_deleted_is_rejected_and_keeps_its_run_but_not_its_examples():
    examples = [{"quote": "我先看现金流再看利润", "message_id": MID, "date": "2026-11-01"}]
    item = profile.add_proposed(OWNER_HASH, kind="preference", text="先看现金流", examples=examples, review_run=RUN, now=NOW,
                                by=memory_events.review(RUN))["id"]
    proposed = events(item)[0]
    assert (proposed["action"], proposed["by"], at(proposed), proposed["basis"]["run"], proposed["basis"]["examples"]) == (
        "proposed", "review", NOW, str(RUN), examples)
    assert profile.delete_item(OWNER_HASH, item, by=memory_events.PAGE)
    rows = events(item)
    assert [e["action"] for e in rows] == ["proposed", "rejected"]
    assert rows[0]["text"] is None and "examples" not in rows[0]["basis"] and rows[0]["basis"]["run"] == str(RUN)


def test_confirm_restore_and_a_layer_move_each_write_their_event():
    examples = [{"quote": "我先看现金流再看利润", "message_id": MID, "date": "2026-11-01"}]
    guess = profile.add_proposed(OWNER_HASH, kind="preference", text="先看现金流", examples=examples, review_run=RUN, now=NOW,
                                 by=memory_events.review(RUN))["id"]
    profile.confirm_item(OWNER_HASH, guess, by=memory_events.PAGE)
    assert [(e["action"], e["by"]) for e in events(guess)] == [("proposed", "review"), ("confirmed", "page")]
    kept = explicit("回答带上来源")["item"]["id"]
    profile.archive_item(OWNER_HASH, kept, by=CHAT)
    profile.restore_item(OWNER_HASH, kept, by=memory_events.PAGE)
    assert [(e["action"], e["by"]) for e in events(kept)] == [("added", "chat"), ("archived", "chat"), ("restored", "page")]
    bot = a_bot()
    profile.update_item(OWNER_HASH, kept, {"bot_id": str(bot)}, by=memory_events.PAGE)
    moved = events(kept)[-1]
    assert (moved["action"], moved["basis"], moved["bot_id"]) == ("moved", {"from_bot": None, "to_bot": str(bot)}, str(bot))
    profile.update_item(OWNER_HASH, kept, {"bot_id": str(bot), "text": "回答带上来源"}, by=memory_events.PAGE)
    assert actions(kept)[-1] == "moved", "nothing changed: nothing written"


def test_the_20_proposal_limit_and_the_60_day_rule_carry_the_reviews_run_and_their_reason():
    examples = [{"quote": "我说过的一句话", "message_id": MID, "date": "2026-11-01"}]
    ids = [profile.add_proposed(OWNER_HASH, kind="preference", text=f"推测第{index}条", examples=examples, review_run=RUN, now=NOW + timedelta(minutes=index),
                                by=memory_events.review(RUN))["id"] for index in range(profile.MAX_PROPOSED + 1)]
    limited = events(ids[0])[-1]
    assert (limited["action"], limited["by"], limited["reason"], limited["basis"]["run"]) == ("archived", "review", "limit", str(RUN))
    later = uuid.uuid4()
    assert profile.archive_stale_proposed(OWNER_HASH, NOW + timedelta(days=90), 60, by=memory_events.review(later)) == profile.MAX_PROPOSED
    stale = events(ids[1])[-1]
    assert (stale["action"], stale["by"], stale["reason"], stale["basis"]["run"]) == ("archived", "review", "stale", str(later))


def test_a_template_names_itself_and_its_label_is_no_change():
    item = profile.add_item(OWNER_HASH, kind="instruction", text="按估值打分", quote="按估值打分", message="按估值打分", origin="manual",
                            by=memory_events.template("value_investor"))["item"]["id"]
    assert (events(item)[0]["by"], events(item)[0]["basis"]) == ("template", {"template": "value_investor"})
    profile.set_template(OWNER_HASH, item, "value_investor")
    assert actions(item) == ["added"], "a template label is not a change"


# --- the settle ---------------------------------------------------------------------------------------------------------

def test_the_settle_promotes_and_expires_by_settle_with_its_reason():
    promoted = stored_item("先看现金流", origin="pattern", confirmed_at=NOW - timedelta(days=90), last_seen_at=NOW - timedelta(days=10))
    expired = stored_item("推断的老习惯", origin="inferred", last_seen_at=NOW - timedelta(days=400))
    with SessionLocal() as db:
        profile._lock(db, OWNER_HASH)
        settle._promote(db, OWNER_HASH, NOW)
        settle._expire(db, OWNER_HASH, NOW, 180)
        db.commit()
    settled = events(promoted)[0]
    assert (settled["action"], settled["by"], at(settled), settled["text"]) == ("settled", "settle", NOW, "先看现金流")
    archived = events(expired)[0]
    assert (archived["action"], archived["by"]) == ("archived", "settle") and archived["reason"].startswith("很久没在你的话里出现")
    view = owner_views.record(OWNER_HASH, "NVDA", "估值太高了", "估值太高了，我觉得", by=memory_events.PAGE)["view"]
    assert settle._archive_views(OWNER_HASH, [view], NOW)
    [last] = [e for e in events(view["id"]) if e["action"] == "archived"]
    assert (last["by"], last["reason"], last["symbol"], at(last)) == ("settle", settle.VIEW_REASON, "NVDA", NOW)


# --- views ----------------------------------------------------------------------------------------------------------------

def test_view_record_supersede_drop_archive_restore_and_delete():
    old = owner_views.record(OWNER_HASH, "NVDA", "估值太高了", "估值太高了，我觉得", by=memory_events.PAGE)["view"]["id"]
    new = owner_views.record(OWNER_HASH, "NVDA", "可以等回调", "我觉得可以等回调再买", MID, CID, TID, by=CHAT)["view"]["id"]
    assert owner_views.record(OWNER_HASH, "NVDA", "可以等回调", "我觉得可以等回调再买", by=CHAT)["status"] == "unchanged"
    recorded = events(new)[0]
    assert (recorded["action"], recorded["by"], recorded["symbol"]) == ("recorded", "chat", "NVDA")
    assert recorded["basis"] == {"conversation_id": CID, "turn_id": TID, "message_id": MID, "quote": "我觉得可以等回调再买"}
    superseded = events(old)[-1]
    assert (superseded["action"], superseded["by"], superseded["basis"]["by_item"]) == ("superseded", "chat", new)
    assert actions(new) == ["recorded"], "the same view again is not a change"
    owner_views.drop(OWNER_HASH, "NVDA", by=CHAT)
    assert actions(new) == ["recorded", "dropped"]
    third = owner_views.record(OWNER_HASH, "AMD", "太贵", "我觉得太贵了", by=memory_events.PAGE)["view"]["id"]
    owner_views.archive(OWNER_HASH, third, "你已不持有", by=memory_events.SETTLE)
    owner_views.restore(OWNER_HASH, third, by=memory_events.PAGE)
    assert [(e["action"], e["by"], e["reason"]) for e in events(third)] == [("recorded", "page", None), ("archived", "settle", "你已不持有"), ("restored", "page", None)]
    assert owner_views.delete_version(OWNER_HASH, old, by=memory_events.PAGE)
    rows = events(old)
    assert [e["action"] for e in rows] == ["recorded", "superseded", "deleted"]
    assert all(e["text"] is None and "quote" not in e["basis"] for e in rows)
    assert events(new)[0]["text"] == "可以等回调", "the version that replaced it keeps its words"


# --- the backfill ---------------------------------------------------------------------------------------------------------

def test_the_backfill_rebuilds_each_kind_once_and_a_second_run_adds_nothing():
    live = explicit("已经有记录的一条")["item"]["id"]
    T = NOW - timedelta(days=30)
    ids = {
        "manual": stored_item("先说结论", origin="manual"),
        "said": stored_item("金额用亿美元", source_message_id=uuid.UUID(MID)),
        "said_unknown": stored_item("回答用中文"),
        "inferred": stored_item("喜欢图表", origin="inferred", source_message_id=uuid.UUID(MID)),
        "proposed": stored_item("先看现金流", origin="pattern", status="proposed", review_run=RUN, examples=[{"quote": "我先看现金流"}]),
        "noticed": stored_item("喜欢短回答", origin="pattern", status="proposed"),
        "template": stored_item("按估值打分", origin="manual", template="value_investor"),
        "settled": stored_item("看自由现金流", origin="pattern", review_run=RUN, confirmed_at=T, settled_at=NOW),
        "expired": stored_item("老习惯", origin="inferred", status="archived", archived_at=NOW, archived_reason="很久没在你的话里出现"),
        "archived": stored_item("旧规矩", status="archived"),
        "rejected": stored_item(profile.fingerprint("不对的推测"), origin="pattern", status="rejected", review_run=RUN, quote=""),
    }
    nvda_at = NOW - timedelta(days=10)
    views = {
        "page": stored_view("AAPL", "护城河很深"),
        "old": stored_view("NVDA", "估值太高了", status="superseded", ended_at=nvda_at),
        "new": stored_view("NVDA", "可以等回调", created_at=nvda_at, conversation_id=uuid.UUID(CID), turn_id=uuid.UUID(TID), source_message_id=uuid.UUID(MID),
                           quote="我觉得可以等回调再买"),
        "dropped": stored_view("TSLA", "太贵", status="dropped", ended_at=nvda_at),
        "archived": stored_view("AMD", "不看了", status="archived", ended_at=NOW, archived_reason="你已不持有"),
    }
    with SessionLocal() as db:
        db.add(AgentProfileItem(owner_hash=OTHER_HASH, kind="preference", text="别人的", origin="manual", quote="别人的", status="active"))
        db.commit()

    assert memory_events.backfill(OWNER_HASH) == 16 + 8
    assert memory_events.backfill(OWNER_HASH) == 0, "idempotent"
    assert actions(live) == ["added"] and events(live)[0]["reconstructed"] is False, "a row the log already knows is never touched"
    assert events(owner=OTHER_HASH) == [], "another owner's rows wait for their own run"

    def shown(key, table=ids):
        return [(e["action"], e["by"]) for e in events(table[key])]
    assert shown("manual") == [("added", "page")]
    assert shown("said") == [("added", "chat")] and events(ids["said"])[0]["basis"] == {"message_id": MID}
    assert shown("said_unknown") == [("added", "unknown")]
    assert shown("inferred") == [("added", "extract")]
    assert shown("proposed") == [("proposed", "review")] and events(ids["proposed"])[0]["basis"] == {"run": str(RUN), "examples": [{"quote": "我先看现金流"}]}
    assert shown("noticed") == [("noticed", "chat")]
    assert shown("template") == [("added", "template")] and events(ids["template"])[0]["basis"] == {"template": "value_investor"}
    assert shown("settled") == [("proposed", "review"), ("confirmed", "page"), ("settled", "settle")]
    assert [at(e) for e in events(ids["settled"])][1:] == [T, NOW]
    assert shown("expired") == [("added", "extract"), ("archived", "settle")] and events(ids["expired"])[1]["reason"] == "很久没在你的话里出现"
    archived = events(ids["archived"])
    assert shown("archived") == [("added", "unknown"), ("archived", "unknown")]
    assert archived[1]["reason"] is None and at(archived[1]) == NOW - timedelta(days=100), "no archive time: when the row last changed"
    rejected = events(ids["rejected"])
    assert shown("rejected") == [("proposed", "review"), ("rejected", "unknown")] and all(e["text"] is None for e in rejected)
    assert shown("page", views) == [("recorded", "page")]
    assert shown("old", views) == [("recorded", "page"), ("superseded", "chat")] and events(views["old"])[1]["basis"]["by_item"] == str(views["new"])
    assert shown("new", views) == [("recorded", "chat")]
    assert events(views["new"])[0]["basis"] == {"conversation_id": CID, "turn_id": TID, "message_id": MID, "quote": "我觉得可以等回调再买"}
    assert shown("dropped", views) == [("recorded", "page"), ("dropped", "unknown")]
    assert shown("archived", views) == [("recorded", "page"), ("archived", "settle")] and events(views["archived"])[1]["reason"] == "你已不持有"
    assert all(e["reconstructed"] for key in ids for e in events(ids[key]))
    assert all(e["reconstructed"] for key in views for e in events(views[key]))


def test_the_backfill_at_startup_never_raises(monkeypatch):
    def broken(owner_hash=None):
        raise RuntimeError("db went away")
    monkeypatch.setattr(memory_events, "backfill", broken)
    memory_events.backfill_at_startup()


# --- reading ----------------------------------------------------------------------------------------------------------------

def test_page_filters_searches_and_pages_newest_first():
    page_item = profile.add_manual_item(OWNER_HASH, kind="instruction", text="先说结论")["item"]["id"]
    first = explicit("金额用万元", topic="currency_unit")["item"]["id"]
    explicit("金额用亿美元", topic="currency_unit")
    owner_views.record(OWNER_HASH, "NVDA", "估值太高了", "估值太高了，我觉得", by=CHAT)
    with SessionLocal() as db:
        memory_events.log(db, OTHER_HASH, target="profile", item_id=uuid.uuid4(), action="added", by="page", text="别人的 50% 仓位")
        db.commit()
    everything, more = memory_events.page(OWNER_HASH)
    assert not more and len(everything) == 5
    assert [e["at"] for e in everything] == sorted((e["at"] for e in everything), reverse=True)
    assert [e["action"] for e in memory_events.page(OWNER_HASH, target="view")[0]] == ["recorded"]
    assert {e["item_id"] for e in memory_events.page(OWNER_HASH, by="page")[0]} == {page_item}
    assert sorted(e["action"] for e in memory_events.page(OWNER_HASH, action=["archived", "recorded"])[0]) == ["archived", "recorded"]
    assert [e["text"] for e in memory_events.page(OWNER_HASH, q="亿美元")[0]] == ["金额用亿美元"]
    assert [e["item_id"] for e in memory_events.page(OWNER_HASH, q="REPLACED")[0]] == [first], "the reason is searched too, case aside"
    assert memory_events.page(OWNER_HASH, q="%")[0] == [], "a wildcard is a character, not a pattern"
    seen, cursor = [], None
    while True:
        items, more = memory_events.page(OWNER_HASH, before=cursor, limit=2)
        seen += [e["id"] for e in items]
        if not more:
            break
        last = items[-1]
        cursor = (datetime.fromisoformat(last["at"]), uuid.UUID(last["id"]))
    assert seen == [e["id"] for e in everything]
    for bad in ({"target": "x"}, {"action": "x"}, {"action": ["added", "x"]}, {"by": "x"}):
        with pytest.raises(ValueError):
            memory_events.page(OWNER_HASH, **bad)


# --- every caller says who it is -----------------------------------------------------------------------------------------------

MUTATORS = {"agent_profile": {"add_item", "add_manual_item", "archive_item", "restore_item", "delete_item", "confirm_item", "update_item",
                              "add_proposed", "add_noticed", "archive_stale_proposed"},
            "owner_views": {"record", "drop", "archive", "restore", "delete_version"},
            "agent_bots": {"delete_bot"}}
WRAPPERS = {"to_thread", "partial"}


def unlogged_calls(source: str, filename: str) -> tuple[int, list[str]]:
    """(how many calls of a memory-changing function this module makes outside its own module, the ones that pass no ``by=``).  A call
    through ``asyncio.to_thread(fn, ...)`` or ``functools.partial(fn, ...)`` counts as a call of ``fn`` with the wrapper's keywords."""
    tree = ast.parse(source)
    modules, functions = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            origin = (node.module or "").rsplit(".", 1)[-1]
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name in MUTATORS and origin in ("", "app"):
                    modules[local] = alias.name
                if origin in MUTATORS and alias.name in MUTATORS[origin]:
                    functions[local] = (origin, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] in MUTATORS:
                    modules[alias.asname or alias.name] = alias.name.rsplit(".", 1)[-1]

    def target(func):
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
            module = modules[func.value.id]
            return (module, func.attr) if func.attr in MUTATORS[module] else None
        if isinstance(func, ast.Name) and func.id in functions:
            return functions[func.id]
        return None

    def wrapper(func):
        return (isinstance(func, ast.Attribute) and func.attr in WRAPPERS) or (isinstance(func, ast.Name) and func.id in WRAPPERS)

    def says_who(call):
        """``by=`` given, and not the literal None (that is unknown by another name)."""
        return any(keyword.arg == "by" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
                   for keyword in call.keywords)

    found, missing, called = 0, [], set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        hit, named = target(node.func), node.func
        if hit is None and node.args and wrapper(node.func):
            hit, named = target(node.args[0]), node.args[0]
        if hit is None:
            continue
        called.add(id(named))
        if Path(filename).name == f"{hit[0]}.py":
            continue
        found += 1
        if not says_who(node):
            missing.append(f"{filename}:{node.lineno} {hit[0]}.{hit[1]}")
    # A mutator handed on as a value (a dict of functions, an alias, run_in_executor) is called where this check cannot see whether it says
    # who it is: wrap it with functools.partial(fn, by=...) instead.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Name)) and id(node) not in called and isinstance(getattr(node, "ctx", None), ast.Load):
            hit = target(node)
            if hit is not None and Path(filename).name != f"{hit[0]}.py":
                found += 1
                missing.append(f"{filename}:{node.lineno} {hit[0]}.{hit[1]} (passed as a value)")
    return found, missing


def test_every_caller_of_a_memory_changing_function_says_who_it_is():
    root = Path(app.__file__).parent
    found, missing = 0, []
    for path in sorted(root.rglob("*.py")):
        count, lacking = unlogged_calls(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
        found += count
        missing += lacking
    assert found >= 20, f"the walk found only {found} calls: it no longer sees them"
    assert not missing, "a call that passes no by= would log 'unknown':\n" + "\n".join(missing)


def test_the_caller_check_catches_a_call_passed_on_as_a_value_or_with_by_none():
    """Fable acceptance of 5d-2: a dict of functions, an alias, run_in_executor and ``by=None`` all slipped past the first check."""
    source = ("import asyncio, functools\nfrom . import agent_profile, owner_views\n"
              "DELETERS = {'memory': agent_profile.delete_item}\n"
              "f = owner_views.drop\n"
              "async def g(loop, owner):\n    await loop.run_in_executor(None, agent_profile.archive_item, owner, 'x')\n"
              "    agent_profile.delete_item(owner, 'x', by=None)\n"
              "    functools.partial(agent_profile.delete_item, by=agent_profile)\n")
    found, missing = unlogged_calls(source, "app/new_module.py")
    assert sorted(missing) == sorted(["app/new_module.py:3 agent_profile.delete_item (passed as a value)", "app/new_module.py:4 owner_views.drop (passed as a value)",
                                      "app/new_module.py:6 agent_profile.archive_item (passed as a value)", "app/new_module.py:7 agent_profile.delete_item"])


MEMORY_MODELS = {"AgentProfileItem", "OwnerView"}
MEMORY_TABLES = re.compile(r"\b(?:UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+(?:agent_profile_items|owner_views)\b", re.I)
# The modules that write those rows themselves and log what is a change (agent_profile's own column backfills, its template label and its
# seen / used stamps are not changes of what it keeps about him).
MEMORY_WRITERS = {"agent_profile.py", "owner_views.py", "memory_events.py", "memory_settle.py"}


def direct_writes(source: str, filename: str) -> list[str]:
    """``query(Model).update/delete``, ``update(Model)``, ``delete(Model)`` or raw SQL writing the memory tables."""
    def queried(node):
        while isinstance(node, (ast.Call, ast.Attribute)):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "query" and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in MEMORY_MODELS:
                    return True
                node = f
            else:
                node = node.value
        return False
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("update", "delete") and queried(f.value):
                found.append(f"{filename}:{node.lineno}")
            if isinstance(f, ast.Name) and f.id in ("update", "delete") and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in MEMORY_MODELS:
                found.append(f"{filename}:{node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and MEMORY_TABLES.search(node.value):
            found.append(f"{filename}:{node.lineno}")
    return found


def test_only_the_memory_modules_write_the_memory_tables_directly():
    """A bulk write elsewhere (``delete_bot`` archived a bot's items with one UPDATE) changes memory without an event: go through agent_profile."""
    root = Path(app.__file__).parent
    stray = [hit for path in sorted(root.rglob("*.py")) if path.name not in MEMORY_WRITERS
             for hit in direct_writes(path.read_text(encoding="utf-8"), str(path.relative_to(root)))]
    assert not stray, "\n".join(stray)
    assert direct_writes("db.query(AgentProfileItem).filter(x).update({'status': 'archived'})\n", "m.py") == ["m.py:1"]


def test_the_caller_check_catches_a_call_without_by():
    source = ("import asyncio\nfrom . import agent_profile as profile\nfrom .owner_views import drop\n"
              "async def f(owner):\n    await asyncio.to_thread(profile.delete_item, owner, 'x')\n    drop(owner, 'NVDA', by=PAGE)\n"
              "    profile.list_items(owner)\n")
    found, missing = unlogged_calls(source, "app/new_module.py")
    assert found == 2 and missing == ["app/new_module.py:5 agent_profile.delete_item"]


# --- Fable acceptance of 5d-2 --------------------------------------------------------------------------------------------

def test_deleting_a_bot_records_each_of_its_items_it_archives():
    from app import agent_bots
    from app.agent_chat_models import AgentConversation, AgentInboxItem, AgentTask
    from app.agent_telegram_bots import AgentTelegramBot
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentInboxItem.__table__, AgentTask.__table__, AgentTelegramBot.__table__])
    b = a_bot()
    own = explicit("研究员只看半导体", bot_id=str(b))["item"]["id"]
    kept = explicit("全局：金额用亿美元")["item"]["id"]
    assert agent_bots.delete_bot(OWNER_HASH, str(b), by=memory_events.PAGE) is True
    last = events(own)[-1]
    assert (last["action"], last["by"], last["reason"], last["text"]) == ("archived", "page", "bot_deleted", "研究员只看半导体")
    assert actions(kept) == ["added"], "a global item is untouched"


def test_a_template_meeting_a_guess_confirms_it_without_saying_he_said_it():
    item = profile.add_item(OWNER_HASH, kind="instruction", text="按估值打分", quote="按估值打分", message="按估值打分", origin="inferred",
                            by=memory_events.extract(MID))["item"]["id"]
    profile.add_item(OWNER_HASH, kind="instruction", text="按估值打分", quote="按估值打分", message="按估值打分", origin="manual",
                     by=memory_events.template("value_investor"))
    confirmed = events(item)[-1]
    assert (confirmed["action"], confirmed["by"], confirmed["reason"]) == ("confirmed", "template", None)


def test_a_second_backfill_while_one_runs_skips_instead_of_waiting():
    stored_item("以后先说结论")
    with SessionLocal() as holder:
        holder.execute(text_sql("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": memory_events.BACKFILL_LOCK})
        assert memory_events.backfill() == 0          # it would hang on pg_advisory_xact_lock
        holder.rollback()
    assert memory_events.backfill() == 1
