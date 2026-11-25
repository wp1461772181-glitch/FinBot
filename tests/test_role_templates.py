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
