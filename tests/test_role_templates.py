"""Stage 4f: the three role templates as data (task 1), and what applying them writes (task 2).

A template is text: memory lines, routine briefs and recipes.  Nothing in ``app/`` outside ``app/role_templates.py`` may know a template id.
Disposable Postgres; no network, no model.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import agent_skills, agent_tasks
from app import role_templates as rt
from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentSkill, AgentTask, RoleTemplateApplication
from app.agent_tool_catalog import definitions
from app.agent_profile import KINDS, TEXT_MAX_CHARS
from app.database import Base, SessionLocal, engine

APP = Path(__file__).resolve().parent.parent / "app"
IDS = ("short_term", "dca", "fund_manager")


TABLES = [AgentProfileItem.__table__, AgentBot.__table__, AgentConversation.__table__, AgentMessage.__table__, AgentSkill.__table__,
          AgentTask.__table__, RoleTemplateApplication.__table__]


@pytest.fixture
def tables(disposable_database):
    Base.metadata.create_all(engine, tables=TABLES)
    with SessionLocal() as db:
        for table in (RoleTemplateApplication, AgentTask, AgentSkill, AgentProfileItem, AgentBot):
            db.query(table).delete()
        db.commit()
    return None


# --- task 1: the data ----------------------------------------------------------------------------------------------------

def test_three_templates_with_the_planned_ids_and_labels():
    assert tuple(rt.TEMPLATES) == IDS
    assert [rt.TEMPLATES[i]["label"] for i in IDS] == ["短线", "定投", "基金经理"]
    for template in rt.TEMPLATES.values():
        assert template["blurb"].endswith("。") and set(template) == {"label", "blurb", "memory", "briefs", "skills", "usual"}


def test_the_appendix_counts():
    counts = {i: (len(t["memory"]), len(t["briefs"]), len(t["skills"]), len(t["usual"])) for i, t in rt.TEMPLATES.items()}
    assert counts == {"short_term": (5, 1, 2, 3), "dca": (4, 1, 1, 2), "fund_manager": (5, 2, 1, 3)}


def test_the_appendix_texts_verbatim_for_a_few_known_lines():
    short = rt.TEMPLATES["short_term"]
    assert [m["key"] for m in short["memory"]] == ["st_about", "st_conclusion_first", "st_fast_moves", "st_why_moving", "st_news_impact"]
    assert short["memory"][1] == {"key": "st_conclusion_first", "kind": "instruction", "text": "回答先给结论和关键价位，再讲原因；提到价格都写明是几点的数据。"}
    brief = short["briefs"][0]
    assert (brief["key"], brief["name"], brief["schedule_kind"], brief["schedule_time"], brief["timezone"], brief["skill_key"]) == (
        "st_premarket", "盘前速览", "weekdays", "09:00", "America/New_York", "st_skill_premarket")
    dca = rt.TEMPLATES["dca"]["briefs"][0]
    assert (dca["schedule_kind"], dca["every_value"], dca["every_unit"], dca["schedule_time"], dca["timezone"]) == ("every", 30, "days", "10:00", "Asia/Shanghai")
    fund = rt.TEMPLATES["fund_manager"]
    assert fund["briefs"][0]["schedule_time"] == "16:30" and fund["briefs"][0]["timezone"] == "America/New_York" and fund["briefs"][0].get("skill_key") is None
    assert (fund["briefs"][1]["every_value"], fund["briefs"][1]["every_unit"]) == (7, "days")
    assert fund["usual"] == ["fm_skill_check", "同行对比", "财报速读"] and short["usual"] == ["st_skill_premarket", "st_skill_why", "新闻摘要"]
    assert "25%" in fund["memory"][1]["text"] and "3%" in fund["memory"][1]["text"]


def test_every_key_is_stable_ascii_and_unique():
    keys = []
    for template in rt.TEMPLATES.values():
        for part in ("memory", "briefs", "skills"):
            keys += [item["key"] for item in template[part]]
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in keys)
    assert len(keys) == len(set(keys))


def test_memory_lines_fit_the_profile_rules():
    for template in rt.TEMPLATES.values():
        for item in template["memory"]:
            assert item["kind"] in KINDS and 0 < len(item["text"]) <= TEXT_MAX_CHARS


def test_every_skill_passes_the_skill_validator_and_names_only_catalog_tools():
    catalog = set(definitions())
    for template in rt.TEMPLATES.values():
        for skill in template["skills"]:
            assert set(skill["allowed_tools"]) <= catalog, skill["key"]
            checked = agent_skills._validate({k: skill[k] for k in ("name", "description", "body", "output_template", "allowed_tools")})
            assert checked["name"] == skill["name"]


def test_every_brief_is_accepted_by_the_task_validator(tables):
    for template in rt.TEMPLATES.values():
        for brief in template["briefs"]:
            assert len(brief["instruction"]) <= agent_tasks.INSTRUCTION_MAX_CHARS
            fields = rt.brief_fields(brief)
            shown = agent_tasks.preview_task("nobody-hash", fields)
            assert shown["name"] == brief["name"] and shown["kind"] == "brief" and shown["next_run_at"]


def test_usual_entries_are_the_templates_own_skills_or_builtin_names():
    builtin = {spec["name"] for spec in agent_skills.BUILTINS}
    for template in rt.TEMPLATES.values():
        own = {skill["key"] for skill in template["skills"]}
        assert all(ref in own or ref in builtin for ref in template["usual"])
        assert all(brief.get("skill_key") in own | {None} for brief in template["briefs"])
        assert len(set(template["usual"])) == len(template["usual"])


def test_no_skill_name_clashes_with_a_builtin():
    builtin = {spec["name"] for spec in agent_skills.BUILTINS}
    names = [skill["name"] for template in rt.TEMPLATES.values() for skill in template["skills"]]
    assert not set(names) & builtin and len(names) == len(set(names))


def test_templates_lists_copies_with_the_fixed_notes_and_nothing_else_leaks():
    listed = rt.templates()
    assert [t["id"] for t in listed] == list(IDS)
    listed[0]["memory"][0]["text"] = "changed"
    assert rt.TEMPLATES["short_term"]["memory"][0]["text"] != "changed"


# --- Review Focus 5: the kernel never learns what a 「短线用户」 is -------------------------------------------------------

def test_no_code_outside_role_templates_names_a_template_id():
    pattern = re.compile(r"short_term|fund_manager|[\"']dca[\"']")
    hits = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "role_templates.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(APP)}:{number}: {line.strip()}")
    assert not hits, hits


# --- task 2: preview, apply, undo ------------------------------------------------------------------------------------------

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app import agent_bots, agent_profile
from app.agent_chat_store import owner_hash

OWNER = "r" * 40
OWNER_HASH = owner_hash(OWNER)
H = {"X-Chat-Session": OWNER}
OTHER = "s" * 40
OTHER_HASH = owner_hash(OTHER)


@pytest.fixture
def owner(monkeypatch, disposable_database):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_") and t.name not in skipped])
    agent_skills.ensure_columns()
    agent_profile.ensure_template_column()
    with SessionLocal() as db:
        for model in (RoleTemplateApplication, AgentTask, AgentSkill, AgentProfileItem, AgentBot):
            db.query(model).delete()
        db.commit()
    agent_skills.seed_builtins()
    from app.agent_workflow import consent, direct, tools
    import app.agent_chat_identity as identity
    for module in (consent, direct, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c in {OWNER, OTHER})
    monkeypatch.delenv("FINBOT_DUTY_MODE", raising=False)
    return OWNER_HASH


def counts(owner_hash_value=OWNER_HASH) -> dict:
    with SessionLocal() as db:
        return {"items": db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == owner_hash_value).count(),
                "tasks": db.query(AgentTask).filter(AgentTask.owner_hash == owner_hash_value).count(),
                "skills": db.query(AgentSkill).filter(AgentSkill.owner_hash == owner_hash_value).count(),
                "bots": db.query(AgentBot).filter(AgentBot.owner_hash == owner_hash_value).count(),
                "applications": db.query(RoleTemplateApplication).filter(RoleTemplateApplication.owner_hash == owner_hash_value).count()}


def put_item(text, *, origin="explicit", kind="preference", bot_id=None):
    return agent_profile.add_item(OWNER_HASH, kind=kind, text=text, quote=text, message=text, origin=origin, bot_id=bot_id)["item"]


def default_bot():
    return agent_bots.ensure_default_bot(OWNER_HASH)


def keys(entries):
    return [e["key"] for e in entries]


APPENDIX_MEMORY = [m["key"] for m in rt.TEMPLATES["short_term"]["memory"]]


def test_preview_says_what_would_be_written_and_writes_nothing(owner):
    before = counts()
    shown = rt.preview(OWNER_HASH, "short_term")
    assert counts() == before        # not even the default bot: a preview is read-only
    assert shown["template"] == "short_term" and shown["label"] == "短线" and shown["skip"] == [] and shown["reuse"] == []
    assert shown["target"] == {"bot_id": None, "bot_name": "助理", "scope": "global"}
    created = shown["will_create"]
    assert [(e["part"], e["key"]) for e in created] == (
        [("skill", "st_skill_premarket"), ("skill", "st_skill_why")] + [("memory", k) for k in APPENDIX_MEMORY]
        + [("brief", "st_premarket")] + [("usual", "st_skill_premarket"), ("usual", "st_skill_why"), ("usual", "新闻摘要")])
    brief = next(e for e in created if e["part"] == "brief")
    assert brief["name"] == "盘前速览" and brief["when"] == "工作日 09:00（美东时间）" and brief["skill_name"] == "盘前速览"
    assert brief["instruction"] == rt.TEMPLATES["short_term"]["briefs"][0]["instruction"] and brief["next_run_at"]
    assert shown["notes"] == list(rt.NOTES) and shown["duty_mode"] == "shadow"


def test_applying_short_term_on_an_empty_owner_writes_exactly_the_appendix(owner):
    """Review Focus 1."""
    done = rt.apply(OWNER_HASH, "short_term")
    assert done["skipped"] == [] and done["reused"] == []
    with SessionLocal() as db:
        rows = db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH).all()
        assert sorted(r.text for r in rows) == sorted(m["text"] for m in rt.TEMPLATES["short_term"]["memory"])
        assert {r.origin for r in rows} == {"manual"} and {r.template for r in rows} == {"short_term"} and {r.bot_id for r in rows} == {None}
        assert {r.status for r in rows} == {"active"}
        tasks = db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).all()
        assert len(tasks) == 1
        task = tasks[0]
        bot = default_bot()
        assert (task.name, task.kind, task.schedule_kind, task.schedule_time, task.timezone, task.enabled, task.bot_id) == (
            "盘前速览", "brief", "weekdays", "09:00", "America/New_York", True, bot.id)
        mine = {s.name: s for s in db.query(AgentSkill).filter(AgentSkill.owner_hash == OWNER_HASH)}
        assert set(mine) == {"盘前速览", "异动归因"} and {s.origin for s in mine.values()} == {"mine"}
        assert task.skill_id == mine["盘前速览"].id
        builtin_news = next(s for s in agent_skills.list_skills(OWNER_HASH) if s["name"] == "新闻摘要")
        assert default_bot().skills == [str(mine["盘前速览"].id), str(mine["异动归因"].id), builtin_news["id"]]
        record = db.query(RoleTemplateApplication).one()
        assert record.template == "short_term" and record.bot_id is None and record.undone_at is None and record.skipped == []
        assert sorted(record.created["profile_item_ids"]) == sorted(str(r.id) for r in rows)
        assert record.created["task_ids"] == [str(task.id)]
        assert sorted(record.created["skill_ids"]) == sorted(str(s.id) for s in mine.values())
        assert record.created["usual_added"] == default_bot().skills
    assert done["application"]["id"] == str(record.id) and done["application"]["template"] == "short_term"
    assert len(done["created"]) == 5 + 1 + 2 + 3


def test_the_first_brief_runs_at_nine_in_new_york_whatever_the_server_clock(owner):
    rt.apply(OWNER_HASH, "short_term")
    with SessionLocal() as db:
        task = db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).one()
        local = task.next_run_at.astimezone(ZoneInfo("America/New_York"))
        assert (local.hour, local.minute) == (9, 0) and local.weekday() < 5


def test_template_items_render_with_their_tag_and_the_template_column_is_only_a_label(owner):
    rt.apply(OWNER_HASH, "dca")
    block, _ = agent_profile.render_block(OWNER_HASH)
    assert "·模板「定投」" in block and rt.TEMPLATES["dca"]["memory"][1]["text"] in block


def test_a_full_memory_layer_refuses_the_memory_part_as_a_whole_and_evicts_nothing(owner):
    """Review Focus 2."""
    for number in range(20):
        put_item(f"我自己写的第 {number} 条", origin="explicit")
    for number in range(7):
        put_item(f"推断出的第 {number} 条", origin="inferred")
    shown = rt.preview(OWNER_HASH, "short_term")
    refused = [e for e in shown["skip"] if e["part"] == "memory"]
    assert keys(refused) == APPENDIX_MEMORY and {e["code"] for e in refused} == {"memory_full"}
    assert refused[0]["reason"] == "这一层记忆已有 27 条，再加 5 条会超过 30 条；先删几条或少勾几条"
    assert not [e for e in shown["will_create"] if e["part"] == "memory"]
    done = rt.apply(OWNER_HASH, "short_term")
    assert {e["code"] for e in done["skipped"] if e["part"] == "memory"} == {"memory_full"}
    with SessionLocal() as db:
        rows = db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH).all()
        assert len(rows) == 27 and {r.status for r in rows} == {"active"} and not [r for r in rows if r.template]
        assert db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).count() == 1                    # the brief still applied
        assert db.query(AgentSkill).filter(AgentSkill.owner_hash == OWNER_HASH).count() == 2                  # and the skills
        record = db.query(RoleTemplateApplication).one()
    assert record.created["profile_item_ids"] == [] and {e["code"] for e in record.skipped} == {"memory_full"}


def test_exactly_thirty_is_allowed_and_a_proposal_does_not_count(owner):
    for number in range(26):
        put_item(f"条目 {number}", origin="explicit")
    done = rt.apply(OWNER_HASH, "dca")                      # 26 + 4 = 30
    assert not [e for e in done["skipped"] if e["part"] == "memory"]
    assert counts()["items"] == 30


def test_duplicates_are_reused_and_reported_and_nothing_of_his_is_touched(owner):
    """Review Focus 3, first half."""
    mine = put_item("回答先给结论和关键价位，再讲原因；提到价格都写明是几点的数据。", origin="inferred", kind="instruction")
    own_skill = agent_skills.create_skill(OWNER_HASH, {"name": "盘前速览", "description": "我自己的", "body": "1. 看盘前。",
                                                      "allowed_tools": ["query_portfolio"]})
    default = default_bot()
    own_task = agent_tasks.create_task(OWNER_HASH, {"kind": "brief", "name": "盘前速览", "schedule_kind": "daily", "schedule_time": "08:00",
                                                    "instruction": "我自己的简报", "bot_id": str(default.id)})
    snapshot_before = (dict(agent_skills.get_skill(OWNER_HASH, own_skill["id"])), dict(agent_tasks.get_task(OWNER_HASH, own_task["id"])))
    shown = rt.preview(OWNER_HASH, "short_term")
    assert [(e["part"], e["key"], e["reason"]) for e in shown["reuse"]] == [
        ("skill", "st_skill_premarket", "已有同名技能，沿用你的"), ("memory", "st_conclusion_first", "已有，沿用")]
    assert [(e["part"], e["key"], e["code"], e["reason"]) for e in shown["skip"]] == [("brief", "st_premarket", "name_taken", "已有同名任务")]
    done = rt.apply(OWNER_HASH, "short_term")
    assert keys(done["reused"]) == ["st_skill_premarket", "st_conclusion_first"] and keys(done["skipped"]) == ["st_premarket"]
    assert snapshot_before == (agent_skills.get_skill(OWNER_HASH, own_skill["id"]), agent_tasks.get_task(OWNER_HASH, own_task["id"]))
    with SessionLocal() as db:
        item = db.get(AgentProfileItem, uuid.UUID(mine["id"]))
        assert (item.origin, item.template, item.updated_at.isoformat()) == ("inferred", None, mine["updated_at"])      # not even promoted to manual
        record = db.query(RoleTemplateApplication).one()
    assert mine["id"] not in record.created["profile_item_ids"] and own_skill["id"] not in record.created["skill_ids"]
    assert record.created["task_ids"] == []
    assert own_skill["id"] in record.created["usual_added"]          # reused for the usual skills: it is his skill, and added to the list


def test_applying_the_same_template_twice_creates_nothing_the_second_time(owner):
    """Review Focus 3, second half."""
    first = rt.apply(OWNER_HASH, "fund_manager")
    after_first = counts()
    second = rt.apply(OWNER_HASH, "fund_manager")
    assert second["created"] == [] and second["application"] is None
    assert counts() == after_first
    assert {e["part"] for e in second["reused"]} == {"skill", "memory", "usual"} and {e["code"] for e in second["skipped"]} == {"name_taken"}
    assert len(first["created"]) == 5 + 2 + 1 + 3


def test_leave_out_keeps_unticked_parts_out_and_a_brief_without_its_skill_has_none(owner):
    done = rt.apply(OWNER_HASH, "dca", leave_out=["dca_monthly", "dca_skill_review"])
    assert {e["part"] for e in done["created"]} == {"memory", "usual"} and keys([e for e in done["created"] if e["part"] == "usual"]) == ["财报速读"]
    assert counts()["tasks"] == 0 and counts()["skills"] == 0
    rt.undo(OWNER_HASH, done["application"]["id"])
    done = rt.apply(OWNER_HASH, "dca", leave_out=["dca_skill_review"])
    with SessionLocal() as db:
        task = db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).one()
        assert task.name == "每月定投复盘" and task.skill_id is None


def test_a_leave_out_key_the_template_does_not_have_is_refused_not_ignored(owner):
    with pytest.raises(rt.RoleTemplateError) as failure:
        rt.preview(OWNER_HASH, "dca", leave_out=["nope"])
    assert failure.value.code == "unknown_leave_out"
    with pytest.raises(rt.RoleTemplateError) as failure:
        rt.apply(OWNER_HASH, "dca", leave_out=["st_about"])        # another template's key
    assert failure.value.code == "unknown_leave_out" and counts()["items"] == 0


def test_unknown_template_and_unknown_bot_have_their_codes(owner):
    for call in (rt.preview, rt.apply):
        with pytest.raises(rt.RoleTemplateError) as failure:
            call(OWNER_HASH, "swing")
        assert failure.value.code == "unknown_template"
        with pytest.raises(rt.RoleTemplateError) as failure:
            call(OWNER_HASH, "dca", bot_id=str(uuid.uuid4()))
        assert failure.value.code == "unknown_bot"
        with pytest.raises(rt.RoleTemplateError) as failure:
            call(OWNER_HASH, "dca", bot_id="not-a-uuid")
        assert failure.value.code == "unknown_bot"
    assert counts()["items"] == 0 and counts()["tasks"] == 0


def test_a_bot_of_his_gets_its_own_layer_its_own_task_and_its_own_usual_skills(owner):
    bot = agent_bots.create_bot(OWNER_HASH, {"name": "短线机器人"})
    done = rt.apply(OWNER_HASH, "short_term", bot_id=bot["id"])
    assert done["application"]["bot_id"] == bot["id"] and done["application"]["scope"] == "bot" and done["application"]["bot_name"] == "短线机器人"
    with SessionLocal() as db:
        assert {str(r.bot_id) for r in db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH)} == {bot["id"]}
        assert [str(t.bot_id) for t in db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH)] == [bot["id"]]
    assert len(agent_bots.get_bot(OWNER_HASH, bot["id"])["skills"]) == 3
    assert default_bot().skills in (None, [])
    # the global layer was empty, so a second application there is not a duplicate of the bot's layer
    again = rt.apply(OWNER_HASH, "short_term")
    assert len([e for e in again["created"] if e["part"] == "memory"]) == 5


def test_the_usual_skills_are_appended_to_his_list_without_duplicates_and_capped_at_twenty(owner):
    ids = [agent_skills.create_skill(OWNER_HASH, {"name": f"技能{n}", "description": "d", "body": "1. x", "allowed_tools": ["calculate"]})["id"]
           for n in range(18)]
    agent_bots.update_bot(OWNER_HASH, str(default_bot().id), {"skills": ids})
    done = rt.apply(OWNER_HASH, "short_term")
    usual = agent_bots.get_bot(OWNER_HASH, str(default_bot().id))["skills"]
    assert usual[:18] == ids and len(usual) == 20
    skipped = [e for e in done["skipped"] if e["part"] == "usual"]
    assert [e["code"] for e in skipped] == ["usual_full"] and "20" in skipped[0]["reason"]
    with SessionLocal() as db:
        record = db.query(RoleTemplateApplication).one()
    assert record.created["usual_added"] == usual[18:]


def test_too_many_tasks_and_too_many_skills_skip_only_what_does_not_fit(owner):
    default = str(default_bot().id)
    for number in range(agent_tasks.MAX_TASKS):
        agent_tasks.create_task(OWNER_HASH, {"kind": "brief", "name": f"任务{number}", "schedule_kind": "daily", "schedule_time": "07:00",
                                             "instruction": "x", "bot_id": default})
    done = rt.apply(OWNER_HASH, "dca")
    assert [(e["part"], e["code"]) for e in done["skipped"]] == [("brief", "too_many_tasks")]
    assert counts()["tasks"] == agent_tasks.MAX_TASKS and counts()["items"] == 4 and counts()["skills"] == 1


def test_a_skill_that_cannot_be_created_is_skipped_and_the_brief_goes_without_it(owner):
    with SessionLocal() as db:
        for number in range(agent_skills.MAX_SKILLS):
            db.add(AgentSkill(owner_hash=OWNER_HASH, name=f"s{number}", description="d", body="b", allowed_tools=["calculate"],
                              origin="mine", status="active", enabled=True, version=1))
        db.commit()
    done = rt.apply(OWNER_HASH, "dca")
    assert [(e["part"], e["code"]) for e in done["skipped"] if e["part"] == "skill"] == [("skill", "too_many_skills")]
    with SessionLocal() as db:
        assert db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).one().skill_id is None


def test_a_same_named_draft_is_not_reused_as_a_skill(owner):
    agent_skills.create_skill(OWNER_HASH, {"name": "定投复盘", "description": "d", "body": "1. x", "allowed_tools": ["calculate"]}, status="draft")
    done = rt.apply(OWNER_HASH, "dca")
    assert [(e["part"], e["code"]) for e in done["skipped"]] == [("skill", "name_taken")]


def test_the_notes_are_fixed_sentences_and_the_duty_sentence_follows_the_live_mode(owner, monkeypatch):
    """Review Focus 7."""
    duty = "值班现在只记录、不主动发消息（要打开请告诉我），所以这几条暂时只影响回答。"
    for mode in (None, "shadow", "off", "bogus"):
        if mode is None:
            monkeypatch.delenv("FINBOT_DUTY_MODE", raising=False)
        else:
            monkeypatch.setenv("FINBOT_DUTY_MODE", mode)
        shown = rt.preview(OWNER_HASH, "dca")
        assert duty in shown["notes"] and shown["duty_mode"] in {"shadow", "off"}
    monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    shown = rt.preview(OWNER_HASH, "dca")
    assert duty not in shown["notes"] and shown["duty_mode"] == "on" and len(shown["notes"]) == len(rt.NOTES) - 1
    assert "价格异动的默认提醒（哨兵）这一版不随模板改变。" in shown["notes"]
    assert "每条简报每次运行会调用一次模型，记在用量里；不想要可以不勾，或之后在例行任务里暂停。" in shown["notes"]
    import os
    assert os.environ["FINBOT_DUTY_MODE"] == "on"         # read only: nothing here writes the environment


def test_an_exception_midway_still_records_what_was_written_so_undo_finds_it(owner, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database went away")
    monkeypatch.setattr(agent_tasks, "create_task", boom)
    with pytest.raises(RuntimeError):
        rt.apply(OWNER_HASH, "short_term")
    with SessionLocal() as db:
        record = db.query(RoleTemplateApplication).one()
    assert len(record.created["skill_ids"]) == 2 and len(record.created["profile_item_ids"]) == 5 and record.created["task_ids"] == []
    undone = rt.undo(OWNER_HASH, str(record.id))
    assert len(undone["removed"]) == 7 and counts()["items"] == 0 and counts()["skills"] == 0


def test_undo_removes_only_what_the_application_recorded(owner):
    """Review Focus 4."""
    own_item = put_item("我自己的偏好", origin="explicit")
    own_skill = agent_skills.create_skill(OWNER_HASH, {"name": "我的技能", "description": "d", "body": "1. x", "allowed_tools": ["calculate"]})
    default = default_bot()
    own_task = agent_tasks.create_task(OWNER_HASH, {"kind": "brief", "name": "我的简报", "schedule_kind": "daily", "schedule_time": "08:00",
                                                    "instruction": "x", "bot_id": str(default.id)})
    agent_bots.update_bot(OWNER_HASH, str(default.id), {"skills": [own_skill["id"]]})
    done = rt.apply(OWNER_HASH, "short_term")
    record_id = done["application"]["id"]
    with SessionLocal() as db:
        record = db.get(RoleTemplateApplication, uuid.UUID(record_id))
        created = dict(record.created)
    edited_id = created["profile_item_ids"][0]
    agent_profile.update_item(OWNER_HASH, edited_id, {"text": "我改过这一条的字"})
    task_id = created["task_ids"][0]
    assert agent_tasks.delete_task(OWNER_HASH, task_id)                 # he deleted the brief himself
    listed = rt.list_applications(OWNER_HASH)[0]
    assert next(i for i in listed["items"] if i["id"] == edited_id)["label"] == "我改过这一条的字"     # the undo list shows the current text
    assert next(i for i in listed["items"] if i["id"] == task_id) == {"part": "brief", "id": task_id, "label": "盘前速览", "there": False, "note": ""}
    assert listed["still_there"] == {"memory": 5, "brief": 0, "skill": 2, "usual": 1}
    undone = rt.undo(OWNER_HASH, record_id)
    assert [(g["part"], g["id"], g["reason"]) for g in undone["gone"]] == [("brief", task_id, "已经不在了")] and undone["gone"][0]["label"] == "盘前速览"
    assert len(undone["removed"]) == 5 + 2 + 1 and not undone["kept"]
    with SessionLocal() as db:
        assert [r.text for r in db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH)] == ["我自己的偏好"]
        assert [s.name for s in db.query(AgentSkill).filter(AgentSkill.owner_hash == OWNER_HASH)] == ["我的技能"]
        assert [t.name for t in db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH)] == ["我的简报"]
        assert db.query(AgentSkill).filter(AgentSkill.owner_hash == "builtin").count() == 3                       # built-ins never deleted
        assert db.get(RoleTemplateApplication, uuid.UUID(record_id)).undone_at is not None
    assert agent_bots.get_bot(OWNER_HASH, str(default.id))["skills"] == [own_skill["id"]]                        # his usual skill stays, the template's go
    assert agent_profile.list_items(OWNER_HASH)[0]["id"] == own_item["id"]
    assert agent_tasks.get_task(OWNER_HASH, own_task["id"])


def test_undo_leave_out_keeps_the_ticked_off_items_and_their_usual_entry(owner):
    done = rt.apply(OWNER_HASH, "short_term")
    listed = rt.list_applications(OWNER_HASH)[0]
    keep_skill = next(i for i in listed["items"] if i["part"] == "skill" and i["label"] == "异动归因")
    keep_item = next(i for i in listed["items"] if i["part"] == "memory")
    undone = rt.undo(OWNER_HASH, done["application"]["id"], leave_out=[keep_skill["id"], keep_item["id"]])
    assert sorted(k["id"] for k in undone["kept"]) == sorted([keep_skill["id"], keep_item["id"]])
    assert counts()["items"] == 1 and counts()["skills"] == 1 and counts()["tasks"] == 0
    assert agent_bots.get_bot(OWNER_HASH, str(default_bot().id))["skills"] == [keep_skill["id"]]
    with pytest.raises(rt.RoleTemplateError) as failure:
        rt.undo(OWNER_HASH, done["application"]["id"])
    assert failure.value.code == "already_undone"


def test_undo_leave_out_with_an_id_the_application_does_not_have_is_refused(owner):
    done = rt.apply(OWNER_HASH, "dca")
    with pytest.raises(rt.RoleTemplateError) as failure:
        rt.undo(OWNER_HASH, done["application"]["id"], leave_out=[str(uuid.uuid4())])
    assert failure.value.code == "unknown_leave_out" and counts()["items"] == 4


def test_undo_of_another_owners_application_or_a_bad_id_is_not_found(owner):
    done = rt.apply(OWNER_HASH, "dca")
    for who, application in ((OTHER_HASH, done["application"]["id"]), (OWNER_HASH, str(uuid.uuid4())), (OWNER_HASH, "nope")):
        with pytest.raises(rt.RoleTemplateError) as failure:
            rt.undo(who, application)
        assert failure.value.code == "application_not_found"
    assert counts()["items"] == 4


def test_undo_warns_when_another_task_still_uses_a_skill_it_is_about_to_delete(owner):
    done = rt.apply(OWNER_HASH, "dca")
    skill_id = done["application"]["items"][-1]["id"] if False else next(e["id"] for e in done["created"] if e["part"] == "skill")
    agent_tasks.create_task(OWNER_HASH, {"kind": "brief", "name": "我也用它", "schedule_kind": "daily", "schedule_time": "08:00",
                                         "instruction": "x", "skill_id": skill_id})
    listed = rt.list_applications(OWNER_HASH)[0]
    note = next(i for i in listed["items"] if i["id"] == skill_id)["note"]
    assert note == "还有 1 个别的例行任务在用它"
    rt.undo(OWNER_HASH, listed["id"])
    assert agent_skills.get_skill(OWNER_HASH, skill_id) is None                       # still deleted, as asked
    with SessionLocal() as db:
        assert db.query(AgentTask).filter(AgentTask.name == "我也用它").one().skill_id is not None   # existing delete behaviour: the id is left dangling


def test_list_applications_newest_first_with_counts_and_bot_names(owner):
    first = rt.apply(OWNER_HASH, "dca")
    second = rt.apply(OWNER_HASH, "fund_manager")
    listed = rt.list_applications(OWNER_HASH)
    assert [a["id"] for a in listed] == [second["application"]["id"], first["application"]["id"]]
    top = listed[0]
    assert (top["template"], top["label"], top["bot_name"], top["scope"], top["undone_at"]) == ("fund_manager", "基金经理", "助理", "global", None)
    # usual: only what this application itself added and that is not also a skill it made.  「财报速读」 was already on the list from the 定投
    # application, so this one did not add it (and its undo must not take it away): that leaves 「同行对比」.
    assert top["still_there"] == {"memory": 5, "brief": 2, "skill": 1, "usual": 1}
    assert rt.list_applications(OTHER_HASH) == []


def test_another_owners_rows_are_never_touched(owner):
    with SessionLocal() as db:
        db.add(AgentProfileItem(owner_hash=OTHER_HASH, kind="preference", text="他人的", origin="explicit", quote="他人的", status="active"))
        db.commit()
    done = rt.apply(OWNER_HASH, "dca")
    rt.undo(OWNER_HASH, done["application"]["id"])
    assert counts(OTHER_HASH)["items"] == 1


# --- the routes --------------------------------------------------------------------------------------------------------------

def test_the_routes_are_owner_only(owner, client):
    guest = {"X-Chat-Session": "g" * 40}
    assert client.get("/agent-chat/role-templates", headers=guest).status_code == 403
    assert client.get("/agent-chat/role-templates").status_code == 403
    for path in ("/agent-chat/role-templates/dca/preview", "/agent-chat/role-templates/dca/apply",
                 f"/agent-chat/role-templates/applications/{uuid.uuid4()}/undo"):
        assert client.post(path, headers=guest, json={}).status_code == 403


def test_get_lists_the_templates_the_applications_and_the_duty_mode(owner, client):
    body = client.get("/agent-chat/role-templates", headers=H).json()
    assert set(body) == {"templates", "applications", "duty_mode"} and body["applications"] == [] and body["duty_mode"] == "shadow"
    assert [t["id"] for t in body["templates"]] == list(IDS)
    first = body["templates"][0]
    assert set(first) == {"id", "label", "blurb", "memory", "briefs", "skills", "usual", "notes"} and first["notes"] == list(rt.NOTES)
    assert first["memory"][0] == {"key": "st_about", "kind": "about_me", "text": "我主要做短线，关注日内和几天内的走势，持有时间短。"}


def test_preview_apply_undo_over_http(owner, client):
    before = counts()
    preview = client.post("/agent-chat/role-templates/dca/preview", headers=H, json={"bot_id": None, "leave_out": ["dca_monthly"]})
    assert preview.status_code == 200 and counts() == before
    shown = preview.json()
    assert set(shown) == {"template", "label", "target", "will_create", "reuse", "skip", "notes", "duty_mode"}
    assert not [e for e in shown["will_create"] if e["part"] == "brief"]
    applied = client.post("/agent-chat/role-templates/dca/apply", headers=H, json={"leave_out": ["dca_monthly"]})
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert set(body) == {"application", "created", "reused", "skipped"} and body["skipped"] == [] and body["reused"] == []
    application = body["application"]
    assert application["template"] == "dca" and application["label"] == "定投" and application["scope"] == "global"
    listed = client.get("/agent-chat/role-templates", headers=H).json()["applications"]
    assert [a["id"] for a in listed] == [application["id"]]
    undo = client.post(f"/agent-chat/role-templates/applications/{application['id']}/undo", headers=H, json={})
    assert undo.status_code == 200 and set(undo.json()) == {"removed", "gone", "kept"} and len(undo.json()["removed"]) == 4 + 1 + 1
    assert counts()["items"] == 0 and counts()["skills"] == 0
    again = client.post(f"/agent-chat/role-templates/applications/{application['id']}/undo", headers=H, json={})
    assert again.status_code == 409 and again.json()["detail"] == "already_undone"


def test_route_errors(owner, client):
    assert client.post("/agent-chat/role-templates/swing/preview", headers=H, json={}).json()["detail"] == "unknown_template"
    assert client.post("/agent-chat/role-templates/swing/apply", headers=H, json={}).status_code == 404
    bad = client.post("/agent-chat/role-templates/dca/apply", headers=H, json={"bot_id": str(uuid.uuid4())})
    assert bad.status_code == 422 and bad.json()["detail"] == "unknown_bot"
    bad = client.post("/agent-chat/role-templates/dca/preview", headers=H, json={"leave_out": ["nope"]})
    assert bad.status_code == 422 and bad.json()["detail"] == "unknown_leave_out"
    mine = client.post("/agent-chat/role-templates/dca/apply", headers=H, json={}).json()["application"]["id"]
    other = client.post(f"/agent-chat/role-templates/applications/{mine}/undo", headers={"X-Chat-Session": OTHER}, json={})
    assert other.status_code == 404 and other.json()["detail"] == "application_not_found"
    assert client.post(f"/agent-chat/role-templates/applications/{uuid.uuid4()}/undo", headers=H, json={}).status_code == 404
    assert counts()["items"] == 4


# --- from the independent review: a usual-skills list that holds an entry which no longer validates ------------------------------------

def _poison_usual():
    """A skill he put on 「助理」's usual list and then deleted: the list now holds an id no check accepts, so no write of the list goes through."""
    default = default_bot()
    ghost = agent_skills.create_skill(OWNER_HASH, {"name": "很快删掉", "description": "d", "body": "1. x", "allowed_tools": ["calculate"]})
    with SessionLocal() as db:
        row = db.get(AgentBot, default.id)
        row.skills = list(row.skills or []) + [ghost["id"]]       # written straight: the service would refuse it, which is the point
        db.commit()
    agent_skills.delete_skill(OWNER_HASH, ghost["id"])
    return ghost["id"]


def test_apply_says_why_the_usual_skills_were_not_added_when_his_list_holds_a_dead_entry(owner):
    _poison_usual()
    done = rt.apply(OWNER_HASH, "dca")
    stuck = [e for e in done["skipped"] if e["part"] == "usual"]
    assert {e["key"] for e in stuck} == {"dca_skill_review", "财报速读"} and {e["code"] for e in stuck} == {"unknown_skill"}
    assert all("已经失效" in e["reason"] for e in stuck)
    assert counts()["items"] == 4 and counts()["skills"] == 1            # the rest of the template still went in


def test_undo_does_not_claim_to_remove_usual_skills_it_could_not_take_off_a_list_it_could_not_change(owner):
    done = rt.apply(OWNER_HASH, "dca")
    ghost = _poison_usual()
    undone = rt.undo(OWNER_HASH, done["application"]["id"])
    assert [(k["part"], k["label"]) for k in undone["kept"]] == [("usual", "财报速读")] and "已经失效" in undone["kept"][0]["reason"]
    assert "财报速读" not in [r["label"] for r in undone["removed"] if r["part"] == "usual"]
    assert {r["part"] for r in undone["removed"]} == {"memory", "brief", "skill"}          # everything else was taken back, the skill too
    assert ghost in (default_bot().skills or [])                                              # his list is exactly as it was: nothing guessed


# --- from the independent review: what the preview promises is what the apply writes ---------------------------------------------------

def _leave_outs(template_id):
    template = rt.TEMPLATES[template_id]
    return [[], [template["memory"][0]["key"]], [template["briefs"][0]["key"]], [s["key"] for s in template["skills"]],
            [template["memory"][0]["key"], template["briefs"][-1]["key"], template["usual"][-1]]]


@pytest.mark.parametrize("template_id,leave", [(t, lo) for t in IDS for lo in _leave_outs(t)])
def test_the_preview_lists_exactly_what_the_apply_then_creates(owner, template_id, leave):
    shown = rt.preview(OWNER_HASH, template_id, leave_out=leave)
    done = rt.apply(OWNER_HASH, template_id, leave_out=leave)
    promised = sorted((e["part"], e["key"]) for e in shown["will_create"])
    written = sorted((e["part"], e["key"]) for e in done["created"])
    assert promised == written and (done["application"] is None) == (not written)
    assert done["skipped"] == [] and shown["skip"] == [] and not [e for e in shown["will_create"] if e["key"] in leave]

