"""4e Task 1: ``app/memory_overview.py`` (what the 「它眼中的你」 page shows and the export carries) and ``owner_views.all_versions``.
Review Focus 2 (views grouped, every version with its review, counts match the rows), 4 (the export holds every non-rejected item of every
layer, every version, the summaries of an archived conversation, no secret-looking field name), 5 (``seen_block`` is the default bot's block and
reading it changes no ``last_used_at``), 6 (a part that fails is null and named, the rest returns).  Disposable Postgres; no model, no network."""
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import agent_bots, agent_profile as profile, memory_overview as overview, memory_schedule as sched, owner_views
from app.agent_chat_models import (AgentBot, AgentConversation, AgentConversationSummary, AgentMessage, AgentProfileItem, AgentResearchQueue,
                                   AgentTask, MemoryJob, OwnerView, PortfolioPlan, ViewReview)
from app.database import Base, SessionLocal, engine

OWNER = "owner-hash-memory-overview"
OTHER = "other-hash-memory-overview"
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
TABLES = (ViewReview, OwnerView, AgentProfileItem, AgentConversationSummary, AgentMessage, AgentConversation, AgentBot, MemoryJob, AgentTask,
          AgentResearchQueue, PortfolioPlan)


@pytest.fixture(autouse=True)
def world(monkeypatch, disposable_database):
    import app.agent_tasks  # noqa: F401
    import app.main  # noqa: F401
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    owner_views.ensure_archive_column()
    with SessionLocal() as db:
        for model in TABLES:
            db.query(model).delete()
        db.commit()
    for name in ("FINBOT_MEMORY_REVIEW_DAYS", "FINBOT_MEMORY_REVIEW_MIN_MESSAGES", "FINBOT_MEMORY_QUARTER_ANCHORS"):
        monkeypatch.delenv(name, raising=False)


def _days(n):
    return NOW - timedelta(days=n)


def _item(text, *, origin="explicit", status="active", owner=OWNER, bot_id=None, quote=None, examples=None, reason=None, age=10, used=None, kind="preference"):
    with SessionLocal() as db:
        row = AgentProfileItem(owner_hash=owner, kind=kind, topic=None, text=text, origin=origin, quote=quote if quote is not None else "他当时的原话",
                               status=status, bot_id=bot_id, examples=examples, created_at=_days(age), updated_at=_days(age), last_seen_at=_days(age),
                               last_used_at=used, archived_at=_days(2) if status == "archived" else None, archived_reason=reason)
        db.add(row)
        db.commit()
        return str(row.id)


def _view(symbol, text, status="active", *, age=30, owner=OWNER, ended=None, conversation=None, reason=None):
    with SessionLocal() as db:
        row = OwnerView(owner_hash=owner, symbol=symbol, text=text, quote="我当时就是这么想的", status=status, created_at=_days(age), ended_at=ended,
                        conversation_id=conversation, archived_reason=reason)
        db.add(row)
        db.commit()
        return str(row.id)


def _review(view_id, symbol="NVDA", *, verdict="held", text="回头看：成立。", stray=(), age=1, owner=OWNER, snapshot=None):
    with SessionLocal() as db:
        db.add(ViewReview(owner_hash=owner, view_id=uuid.UUID(view_id), symbol=symbol, verdict=verdict, text=text, unmatched_figures=list(stray),
                          input_snapshot=snapshot or {"price": {"then": {"date": "2026-09-25", "close": 100.0}, "now": {"date": "2026-11-24", "close": 150.0}, "change_pct": 50.0}, "quarter": {"label": "FY27Q3"}},
                          created_at=_days(age)))
        db.commit()


def _bot(name, owner=OWNER, default=False):
    with SessionLocal() as db:
        bot = AgentBot(owner_hash=owner, name=name, title="", description="", focus={"companies": [], "theme": None}, avatar="orb:finbot", group_name="",
                       pinned=False, hidden=False, is_default=default, template="blank", daily_notify_cap=5)
        db.add(bot)
        db.commit()
        return str(bot.id)


def _seed_views():
    """NVDA: dropped (oldest), superseded, active (newest) + a review of the active one and an older one of the superseded.  AMD: archived only.
    TSLA: active, older than NVDA's active.  Another owner has an active NVDA view."""
    dropped = _view("NVDA", "先不碰英伟达", "dropped", age=300, ended=_days(200))
    superseded = _view("NVDA", "英伟达估值太高", "superseded", age=120, ended=_days(20))
    active = _view("NVDA", "英伟达还能翻倍", "active", age=20)
    archived = _view("AMD", "AMD 再等等", "archived", age=250, ended=_days(40), reason="很久没提了")
    tsla = _view("TSLA", "特斯拉看交付", "active", age=60)
    _view("NVDA", "别人的看法", "active", owner=OTHER)
    _review(active, text="到目前为止成立。", stray=("37%",))
    _review(superseded, age=40, text="当时说估值高，后来涨了，不成立。", verdict="not_held")
    return {"dropped": dropped, "superseded": superseded, "active": active, "archived": archived, "tsla": tsla}


# ---- Review Focus 2: the views, grouped, with every version and its review --------------------------------------------

def test_all_versions_groups_by_company_current_first_with_each_review():
    ids = _seed_views()
    groups = owner_views.all_versions(OWNER)
    assert [g["symbol"] for g in groups] == ["NVDA", "TSLA", "AMD"]       # current ones first (newest current first), then the rest
    nvda, tsla, amd = groups
    assert nvda["name"] == owner_views.display_name("NVDA") and amd["current"] is None
    assert [v["id"] for v in nvda["versions"]] == [ids["active"], ids["superseded"], ids["dropped"]]       # newest first
    assert nvda["current"]["id"] == ids["active"] and nvda["current"]["review"] == nvda["versions"][0]["review"]
    assert nvda["versions"][0]["review"]["text"] == "到目前为止成立。" and nvda["versions"][0]["review"]["unmatched_figures"] == ["37%"]
    assert nvda["versions"][1]["review"]["verdict"] == "not_held" and nvda["versions"][2]["review"] is None
    assert [v["status"] for v in amd["versions"]] == ["archived"] and amd["versions"][0]["archived_reason"] == "很久没提了" and amd["versions"][0]["review"] is None
    assert tsla["current"]["text"] == "特斯拉看交付"
    assert "别人的看法" not in json.dumps(groups, ensure_ascii=False)
    assert owner_views.all_versions("nobody") == []


def test_all_versions_orders_companies_without_a_current_view_by_their_newest_version():
    _view("AMD", "旧的", "dropped", age=100, ended=_days(90))
    _view("INTC", "新一点的", "superseded", age=50, ended=_days(10))
    _view("MSFT", "当前的", "active", age=200)
    assert [g["symbol"] for g in owner_views.all_versions(OWNER)] == ["MSFT", "INTC", "AMD"]


def test_a_failed_review_read_leaves_the_versions(monkeypatch):
    _seed_views()
    from app import view_review

    def broken(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(view_review, "latest_by_view", broken)
    groups = owner_views.all_versions(OWNER)
    assert [g["symbol"] for g in groups] == ["NVDA", "TSLA", "AMD"] and all(v["review"] is None for g in groups for v in g["versions"])


# ---- counts ---------------------------------------------------------------------------------------------------------

def _seed_profile():
    bot = _bot("研究员")
    _item("用中文回答")
    _item("数字带单位", bot_id=uuid.UUID(bot))
    _item("先说结论", origin="manual")
    _item("喜欢短回答", origin="inferred")
    _item("爱看现金流", origin="pattern", status="active")
    _item("可能偏价值", origin="pattern", status="proposed", examples=[{"quote": "我一般看估值", "message_id": None, "on": "2026-11-01"}], quote="我一般看估值")
    _item("可能不爱追涨", origin="pattern", status="proposed", quote="不追高")
    _item("以前的偏好", origin="explicit", status="archived", reason="两年没提了")
    _item("被否掉的", origin="pattern", status="rejected", quote="")
    _item("别人的偏好", owner=OTHER)
    return bot


def test_counts_come_from_the_rows():
    _seed_profile()
    _seed_views()
    with SessionLocal() as db:
        db.add(PortfolioPlan(owner_hash=OWNER, symbol="NVDA", plan_text="回调再补", add_price=Decimal("100"), stop_price=None, target_price=None))
        db.add(PortfolioPlan(owner_hash=OWNER, symbol="AMD", plan_text="", add_price=None, stop_price=None, target_price=None))      # nothing in it: not counted
        db.add(AgentTask(owner_hash=OWNER, name="盯盘", kind="alerts", schedule_kind="hourly", schedule_time="00:00", timezone="UTC", scope="symbols",
                         symbols=["NVDA"], config={"filings": True, "news": False, "price_lines": []}, enabled=True))
        db.add(AgentTask(owner_hash=OWNER, name="停了的", kind="alerts", schedule_kind="hourly", schedule_time="00:00", timezone="UTC", enabled=False))
        db.add(AgentTask(owner_hash=OWNER, name="早报", kind="brief", schedule_kind="daily", schedule_time="08:00", timezone="UTC", enabled=True))
        db.add(AgentResearchQueue(owner_hash=OWNER, symbols=["NVDA", "AMD", "TSLA"]))
        db.commit()
    counts = overview.collect(OWNER)["counts"]
    assert counts == {"said": 2, "typed": 1, "inferred": 1, "guesses_confirmed": 1, "guesses_waiting": 2, "archived": 1,
                      "views_current": 2, "views_companies": 3, "watch": 1 + 1 + 3}


# ---- the watch, the calendar -----------------------------------------------------------------------------------------

def test_watch_part():
    with SessionLocal() as db:
        db.add(PortfolioPlan(owner_hash=OWNER, symbol="NVDA", plan_text="回调再补", add_price=Decimal("100"), stop_price=Decimal("80.5"), target_price=None))
        db.add(PortfolioPlan(owner_hash=OWNER, symbol="AMD", plan_text="", add_price=None, stop_price=None, target_price=None))
        db.add(PortfolioPlan(owner_hash=OTHER, symbol="TSLA", plan_text="别人的计划", add_price=None, stop_price=None, target_price=None))
        db.add(AgentTask(owner_hash=OWNER, name="盯盘", kind="alerts", schedule_kind="hourly", schedule_time="00:00", timezone="UTC", scope="symbols",
                         symbols=["NVDA"], config={"filings": True, "news": False, "price_lines": [{"symbol": "NVDA", "below": 90.0}]}, enabled=True,
                         next_run_at=_days(-1), channel="telegram"))
        db.add(AgentTask(owner_hash=OWNER, name="早报", kind="brief", schedule_kind="daily", schedule_time="08:00", timezone="UTC"))
        db.add(AgentTask(owner_hash=OTHER, name="别人的盯盘", kind="alerts", schedule_kind="hourly", schedule_time="00:00", timezone="UTC"))
        db.commit()
    watch = overview.collect(OWNER)["watch"]
    assert watch["plans"] == [{"symbol": "NVDA", "plan_text": "回调再补", "add_price": "100.0000", "stop_price": "80.5000", "target_price": None,
                               "updated_at": watch["plans"][0]["updated_at"]}]
    assert len(watch["alert_routines"]) == 1
    routine = watch["alert_routines"][0]
    assert {k: routine[k] for k in ("name", "enabled", "scope", "symbols", "filings", "news", "price_lines")} == {
        "name": "盯盘", "enabled": True, "scope": "symbols", "symbols": ["NVDA"], "filings": True, "news": False, "price_lines": [{"symbol": "NVDA", "below": 90.0}]}
    assert set(routine) == {"id", "name", "enabled", "scope", "symbols", "filings", "news", "price_lines", "next_run_at", "bot_id"}
    assert watch["research_queue"] is None              # never saved
    assert watch["default_rules_note"] == "另外，系统默认对你的持仓和研究队列盯价格异动、新公告（哨兵），这些默认规则现在还不能按你单独调整。"
    with SessionLocal() as db:
        db.add(AgentResearchQueue(owner_hash=OWNER, symbols=["NVDA", "AMD"]))
        db.commit()
    assert overview.collect(OWNER)["watch"]["research_queue"] == ["NVDA", "AMD"]


def test_jobs_part():
    for job in sched.JOBS:
        sched.register(job, OWNER)
    sched.register("monthly_review", OTHER)
    sched.finish("monthly_review", OWNER, "skipped", "没有新内容", _days(5))
    jobs = overview.collect(OWNER)["jobs"]
    assert [j["job"] for j in jobs] == ["monthly_review", "quarterly_settle"]
    monthly, quarterly = jobs
    assert monthly["title"] == sched.JOB_TITLES["monthly_review"] and monthly["last_outcome"] == "skipped" and monthly["last_reason"] == "没有新内容"
    # The same instants, whatever zone the database session writes them in (a test database set to +08:00 gives "17:00+08:00" for "09:00Z").
    assert datetime.fromisoformat(monthly["next_due"]) == _days(5) + sched.period("monthly_review") and datetime.fromisoformat(monthly["last_run_at"]) == _days(5)
    assert monthly["messages_until_early"] == sched.review_min_messages()           # no message of his since
    assert quarterly["next_due"] is not None and quarterly["last_outcome"] is None and "messages_until_early" not in quarterly
    assert overview.collect("nobody")["jobs"] == []


# ---- Review Focus 5: the block the default bot reads ---------------------------------------------------------------

def test_seen_block_is_the_default_bots_block_and_reading_it_changes_nothing():
    default = agent_bots.ensure_default_bot(OWNER)
    other_bot = _bot("研究员")
    stamp = _days(3)
    first = _item("用中文回答", used=stamp)
    _item("研究员专用", bot_id=uuid.UUID(other_bot), used=stamp)
    _item("可能偏价值", origin="pattern", status="proposed", quote="我一般看估值")
    _item("别人的偏好", owner=OTHER)
    expected, _ids = profile.render_block(OWNER, str(default.id), every_bot=True)
    assert expected and "用中文回答" in expected and "研究员专用" in expected and "可能偏价值" in expected and "别人的偏好" not in expected
    assert overview.collect(OWNER)["seen_block"] == expected
    overview.collect(OWNER)
    overview.export(OWNER, "json")
    with SessionLocal() as db:
        assert {r.last_used_at for r in db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER, AgentProfileItem.status == "active")} == {stamp}
        assert db.get(AgentProfileItem, uuid.UUID(first)).updated_at == _days(10)


def test_seen_block_without_a_default_bot_creates_none_and_without_items_is_null():
    assert overview.collect(OWNER)["seen_block"] is None
    _item("用中文回答")
    block = overview.collect(OWNER)["seen_block"]
    assert block and "用中文回答" in block
    with SessionLocal() as db:
        assert db.query(AgentBot).filter(AgentBot.owner_hash == OWNER).count() == 0      # a read made no bot


# ---- Review Focus 6: a part that fails ----------------------------------------------------------------------------

@pytest.mark.parametrize("part,target", [("views", "all_versions"), ("counts", "_counts"), ("watch", "_watch"), ("jobs", "_jobs"), ("seen_block", "_seen_block")])
def test_a_part_that_fails_is_null_and_named_the_rest_returns(monkeypatch, part, target):
    _seed_profile()
    _seed_views()
    sched.register("monthly_review", OWNER)

    def broken(*a, **k):
        raise RuntimeError("secret detail that must not be logged or returned")
    if target == "all_versions":
        monkeypatch.setattr(owner_views, "all_versions", broken)
    else:
        monkeypatch.setattr(overview, target, broken)
    data = overview.collect(OWNER)
    assert data[part] is None and data["errors"] == [part]
    assert set(data) == {"counts", "views", "watch", "jobs", "seen_block", "errors"}
    assert all(data[other] is not None for other in ("counts", "views", "watch", "jobs", "seen_block") if other != part)
    assert "secret detail" not in json.dumps(data)


def test_nothing_failing_means_no_errors():
    assert overview.collect(OWNER)["errors"] == []


# ---- the export ------------------------------------------------------------------------------------------------------

def _seed_summaries(count_each=2):
    default = agent_bots.ensure_default_bot(OWNER)
    with SessionLocal() as db:
        archived = AgentConversation(owner_hash=OWNER, status="active", archived_at=_days(5), bot_id=default.id, created_at=_days(100))
        theirs = AgentConversation(owner_hash=OTHER, status="active", created_at=_days(100))
        db.add_all([archived, theirs])
        db.flush()
        for n in range(count_each):
            db.add(AgentConversationSummary(conversation_id=archived.id, seq=n + 1, from_sequence=n * 10 + 1, upto_sequence=n * 10 + 10,
                                            content=f"归档对话摘要{n + 1}", created_at=_days(90 - n)))
            db.add(AgentConversationSummary(conversation_id=default.conversation_id, seq=n + 1, from_sequence=n * 10 + 1, upto_sequence=n * 10 + 10,
                                            content=f"默认线摘要{n + 1}", created_at=_days(30 - n)))
            db.add(AgentConversationSummary(conversation_id=theirs.id, seq=n + 1, from_sequence=1, upto_sequence=2, content="别人的摘要", created_at=_days(1)))
        db.commit()
        return str(archived.id)


def _keys(value, found=None):
    found = set() if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            _keys(v, found)
    elif isinstance(value, list):
        for v in value:
            _keys(v, found)
    return found


def test_the_json_export_holds_everything_he_has_and_no_secret_field():
    bot = _seed_profile()
    ids = _seed_views()
    archived_conversation = _seed_summaries()
    sched.register("monthly_review", OWNER)
    body, filename, media = overview.export(OWNER, "json", now=NOW)
    assert filename == "finbot-memory-20261125.json" and media == "application/json; charset=utf-8"
    doc = json.loads(body.decode("utf-8"))
    assert body.decode("utf-8") == json.dumps(doc, ensure_ascii=False, indent=2)
    assert set(doc) == {"schema", "exported_at", "counts", "profile_items", "rejected_count", "views", "watch", "jobs", "seen_block", "conversation_summaries", "notes"}
    assert doc["schema"] == "finbot-memory-export/1" and doc["exported_at"] == NOW.isoformat()
    texts = {i["text"] for i in doc["profile_items"]}
    assert texts == {"用中文回答", "数字带单位", "先说结论", "喜欢短回答", "爱看现金流", "可能偏价值", "可能不爱追涨", "以前的偏好"}      # every layer, archived and proposed; no rejected, no other owner
    proposed = next(i for i in doc["profile_items"] if i["text"] == "可能偏价值")
    assert proposed["status"] == "proposed" and proposed["examples"][0]["quote"] == "我一般看估值"
    assert next(i for i in doc["profile_items"] if i["text"] == "数字带单位")["bot_name"] == "研究员" and bot
    assert doc["rejected_count"] == 1
    versions = {v["id"]: v for group in doc["views"] for v in group["versions"]}
    assert set(versions) == set(ids.values()) and versions[ids["active"]]["review"]["text"] == "到目前为止成立。"
    assert doc["views"] == overview.collect(OWNER)["views"]
    summaries = doc["conversation_summaries"]
    assert [s["content"] for s in summaries] == ["归档对话摘要1", "归档对话摘要2", "默认线摘要1", "默认线摘要2"]      # oldest first, his only, archived included
    assert set(summaries[0]) == {"conversation_id", "bot_name", "seq", "created_at", "content"} and summaries[0]["conversation_id"] == archived_conversation
    assert summaries[0]["bot_name"] == agent_bots.ensure_default_bot(OWNER).name
    assert "不含对话原文：原文在每条对话里，也在每夜的数据库备份里。" in doc["notes"] and "被你否掉的推测只留了一个指纹，没有文字，共 1 条。" in doc["notes"]
    assert not any(any(bad in key.lower() for bad in ("owner_hash", "credential", "token", "key", "chat_id")) for key in _keys(doc)), sorted(_keys(doc))
    assert OWNER not in body.decode("utf-8") and OTHER not in body.decode("utf-8") and "别人的" not in body.decode("utf-8")


def test_a_failed_part_is_said_in_the_export(monkeypatch):
    _seed_views()

    def broken(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(owner_views, "all_versions", broken)
    doc = json.loads(overview.export(OWNER, "json", now=NOW)[0])
    assert doc["views"] is None and any("views" in note for note in doc["notes"])


def test_summaries_are_capped_to_the_newest_with_a_note(monkeypatch):
    _seed_summaries(count_each=3)
    monkeypatch.setattr(overview, "SUMMARY_CAP", 2)
    doc = json.loads(overview.export(OWNER, "json", now=NOW)[0])
    assert [s["content"] for s in doc["conversation_summaries"]] == ["默认线摘要2", "默认线摘要3"]       # the newest two, oldest first
    assert "对话摘要只导出了最近 2 段" in doc["notes"]
    monkeypatch.setattr(overview, "SUMMARY_CAP", 2000)
    doc = json.loads(overview.export(OWNER, "json", now=NOW)[0])
    assert len(doc["conversation_summaries"]) == 6 and not any("只导出了最近" in note for note in doc["notes"])


def test_the_format_is_checked():
    with pytest.raises(ValueError, match="invalid_format"):
        overview.export(OWNER, "csv")


def _sections(markdown):
    parts = re.split(r"^## ", markdown, flags=re.M)
    return {part.split("\n", 1)[0].strip(): part for part in parts[1:]}


def test_the_markdown_export_has_each_item_once_in_its_section():
    _seed_profile()
    _seed_views()
    _seed_summaries()
    body, filename, media = overview.export(OWNER, "md", now=NOW)
    assert filename == "finbot-memory-20261125.md" and media == "text/markdown; charset=utf-8"
    markdown = body.decode("utf-8")
    assert markdown.startswith("# 它眼中的你（导出于 2026-11-25）")
    sections = _sections(markdown)
    assert list(sections) == ["概览", "你说过的", "你在记忆页写的", "它推断的", "你确认的推测", "待你确认的推测", "已归档", "你对公司的看法", "盯防", "记忆整理日程",
                              "它每轮读到的画像", "对话摘要", "说明"]
    for heading, texts in {"你说过的": ["用中文回答", "数字带单位"], "你在记忆页写的": ["先说结论"], "它推断的": ["喜欢短回答"], "你确认的推测": ["爱看现金流"],
                           "待你确认的推测": ["可能偏价值", "可能不爱追涨"], "已归档": ["以前的偏好"]}.items():
        for text in texts:
            assert sections[heading].count(text) == 1, (heading, text)
            assert sum(text in section for name, section in sections.items() if name != "它每轮读到的画像") == 1, text
    assert "我一般看估值" in sections["待你确认的推测"] and "两年没提了" in sections["已归档"] and "全局" in sections["你说过的"] and "研究员" in sections["你说过的"]
    assert "被否掉的" not in markdown and "别人的" not in markdown
    views = sections["你对公司的看法"]
    for text in ("英伟达还能翻倍", "英伟达估值太高", "先不碰英伟达", "AMD 再等等", "特斯拉看交付", "到目前为止成立。", "37%"):
        assert views.count(text) == 1, text
    assert "归档对话摘要1" in sections["对话摘要"] and "不含对话原文" in sections["说明"]


# ---- the pure renderer -----------------------------------------------------------------------------------------------

def _empty_doc():
    return {"schema": "finbot-memory-export/1", "exported_at": NOW.isoformat(),
            "counts": {"said": 0, "typed": 0, "inferred": 0, "guesses_confirmed": 0, "guesses_waiting": 0, "archived": 0, "views_current": 0, "views_companies": 0,
                       "watch": 0},
            "profile_items": [], "rejected_count": 0, "views": [],
            "watch": {"plans": [], "alert_routines": [], "research_queue": None, "default_rules_note": "默认规则的说明"},
            "jobs": [], "seen_block": None, "conversation_summaries": [], "notes": ["不含对话原文：原文在每条对话里，也在每夜的数据库备份里。"]}


def test_render_markdown_keeps_every_section_and_says_when_one_is_empty():
    markdown = overview.render_markdown(_empty_doc())
    sections = _sections(markdown)
    assert list(sections) == ["概览", "你说过的", "你在记忆页写的", "它推断的", "你确认的推测", "待你确认的推测", "已归档", "你对公司的看法", "盯防", "记忆整理日程",
                              "它每轮读到的画像", "对话摘要", "说明"]
    for heading in ("你说过的", "你在记忆页写的", "它推断的", "你确认的推测", "待你确认的推测", "已归档", "你对公司的看法", "记忆整理日程", "对话摘要"):
        assert "（没有）" in sections[heading], heading
    assert "（没有）" in sections["它每轮读到的画像"] and "默认规则的说明" in sections["盯防"]
    assert markdown.startswith("# 它眼中的你（导出于 2026-11-25）")


def test_render_markdown_survives_a_missing_part_and_a_fence_in_the_block():
    doc = _empty_doc()
    doc.update({"views": None, "watch": None, "jobs": None, "counts": None, "seen_block": "第一行\n```\n第三行"})
    markdown = overview.render_markdown(doc)
    sections = _sections(markdown)
    assert "没能读出" in sections["你对公司的看法"] and "没能读出" in sections["盯防"] and "没能读出" in sections["记忆整理日程"]
    assert "第三行" in sections["它每轮读到的画像"] and "````" in sections["它每轮读到的画像"]


def test_the_basis_line_reads_the_real_stored_shape_and_never_prints_a_dict():
    real = {"price_then": {"date": "2026-09-25", "close": 100.0}, "price_now": {"date": "2026-11-24", "close": 150.5}, "change_pct": 50.5,
            "quarter_label": "FY2026 Q3"}
    assert overview._basis_text(real) == "股价 100 → 150.5（+50.5%）；最新一季 FY2026 Q3"
    assert overview._basis_text({"price_then": None, "price_now": {"close": 150.0}, "change_pct": None, "quarter_label": None}) == "股价 — → 150"
    assert overview._basis_text({"price_then": 100.0, "price_now": 150.0}) == "股价 100 → 150"      # a bare number is still read
    assert "{" not in overview._basis_text(real) and overview._basis_text({}) == ""
