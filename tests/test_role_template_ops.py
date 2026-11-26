"""4f task 3: ``apply_role_template`` and ``undo_role_template`` through ``act`` (Review Focus 6 and 7, the cards, the refusals, the guest).

The cards come from ``act.prepare``; a press goes through the real consent ledger and ``act.execute_handler``.  Disposable Postgres; no
network, no model.  The fixtures and helpers are the sibling module's (the same ones the other directory operations are tested with).
"""
import pytest
from test_kernel_directory_settings import (OWNER, OWNER_HASH, SOURCE, make_run, owner, prepare, press, refused, run)  # noqa: F401

from app import agent_bots as bots
from app import agent_profile, agent_skills, agent_tasks
from app import role_templates as rt
from app.agent_chat_models import AgentProfileItem, AgentSkill, AgentTask, RoleTemplateApplication
from app.agent_tool_catalog import OWNER_ONLY, definitions, validate
from app.database import SessionLocal
from app.kernel import act

NAMES = ("apply_role_template", "undo_role_template")


@pytest.fixture(autouse=True)
def clean(owner):          # noqa: F811 - the sibling's fixture, so the tables exist and its monkeypatches are in place
    agent_profile.ensure_template_column()
    agent_skills.ensure_columns()
    agent_skills.seed_builtins()

    def wipe():
        with SessionLocal() as db:
            for model in (RoleTemplateApplication, AgentTask, AgentProfileItem):
                db.query(model).delete()
            db.query(AgentSkill).filter(AgentSkill.owner_hash != "builtin").delete()
            db.commit()
    wipe()
    yield
    wipe()


def counts():
    with SessionLocal() as db:
        return {"items": db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH).count(),
                "tasks": db.query(AgentTask).filter(AgentTask.owner_hash == OWNER_HASH).count(),
                "skills": db.query(AgentSkill).filter(AgentSkill.owner_hash == OWNER_HASH).count(),
                "applications": db.query(RoleTemplateApplication).filter(RoleTemplateApplication.owner_hash == OWNER_HASH).count()}


def kinds(prepared):
    return [row["kind"] for row in prepared.display["targets"]]


def test_the_two_operations_are_tier_two_owner_only_cards_with_a_summary():
    for name in NAMES:
        assert name in act.TIER2 and name in act.OPERATIONS and act.SUMMARIES[name], name
        policy = definitions()[name]
        assert policy.level == "reversible" and name in OWNER_ONLY, name
        assert f"\n{name}：" in act.ACT_SCHEMA["function"]["description"]
        assert act.describe(name)["tier"] == 2


def test_the_card_lists_every_item_says_what_is_reused_and_says_what_it_does_not_reach():
    """Review Focus 6: 「我是做定投的，按定投帮我设一下，简报不要」 is one card without the brief."""
    before = counts()
    prepared = prepare("apply_role_template", {"template": "定投", "leave_out": ["dca_monthly"]})
    assert counts() == before                                           # a card writes nothing
    assert prepared.display["title"] == "用模板起步 · 定投"
    shown = kinds(prepared)
    assert [k for k in shown if k.startswith("记忆")] == [f"记忆 · {m['text']}" for m in rt.TEMPLATES["dca"]["memory"]]
    assert "技能 · 定投复盘" in shown and "常用技能 · 定投复盘" in shown and "常用技能 · 财报速读" in shown
    assert not [k for k in shown if k.startswith("简报")]
    text = prepared.display["alternative"]
    assert rt.NOTE_SENTINEL in text and rt.NOTE_DUTY_RECORDS in text and rt.NOTE_BRIEF_COST in text and "全局记忆" in text
    assert prepared.operation["name"] == "apply_role_template"


def test_the_card_names_the_brief_with_its_schedule_when_it_is_ticked():
    shown = kinds(prepare("apply_role_template", {"template": "短线"}))
    assert "简报 · 盘前速览（工作日 09:00（美东时间））" in shown


def test_the_press_writes_what_the_card_listed_and_nothing_else():
    prepared = prepare("apply_role_template", {"template": "dca", "leave_out": ["dca_monthly"]})
    out = press(prepared)
    assert out["ok"], out
    assert counts() == {"items": 4, "tasks": 0, "skills": 1, "applications": 1}
    with SessionLocal() as db:
        record = db.query(RoleTemplateApplication).one()
        assert record.template == "dca" and len(record.created["profile_item_ids"]) == 4


def test_the_press_after_the_card_went_stale_reuses_instead_of_duplicating():
    first = prepare("apply_role_template", {"template": "dca"})
    stale = prepare("apply_role_template", {"template": "dca"})
    assert press(first)["ok"]
    after_first = counts()
    assert press(stale)["ok"]                 # a second press of an older card: duplicates are reused, nothing is written twice
    assert counts() == after_first


def test_a_full_layer_card_says_what_does_not_fit_and_nothing_is_evicted():
    for number in range(27):
        text = f"我自己的第 {number} 条偏好"
        agent_profile.add_item(OWNER_HASH, kind="preference", text=text, quote=text, message=text, origin="explicit")
    prepared = prepare("apply_role_template", {"template": "dca", "leave_out": ["dca_monthly"]})
    assert not [k for k in kinds(prepared) if k.startswith("记忆")]
    assert "这一层记忆已有 27 条" in prepared.display["alternative"]
    assert press(prepared)["ok"]
    assert counts()["items"] == 27


def test_refusals_say_what_to_do_next():
    refused("apply_role_template", {"template": "swing"}, "unknown_template")
    refused("apply_role_template", {"template": "定投", "bot": "没有这个 bot"}, "bot_not_found")
    refused("apply_role_template", {"template": "定投", "leave_out": ["nope"]}, "unknown_leave_out")
    assert press(prepare("apply_role_template", {"template": "短线"}))["ok"]
    refused("apply_role_template", {"template": "短线"}, "nothing_to_change")          # everything is there already
    refused("undo_role_template", {"application_id": SOURCE}, "application_not_found")


def test_a_bot_is_named_by_its_name_or_its_id():
    bot = bots.create_bot(OWNER_HASH, {"name": "短线机器人"})
    by_name = prepare("apply_role_template", {"template": "短线", "bot": "短线机器人"})
    by_id = prepare("apply_role_template", {"template": "短线", "bot": bot["id"]})
    assert kinds(by_name) == kinds(by_id) and "短线机器人的记忆" in by_name.display["alternative"]
    assert press(by_name)["ok"]
    with SessionLocal() as db:
        assert {str(r.bot_id) for r in db.query(AgentProfileItem).filter(AgentProfileItem.owner_hash == OWNER_HASH)} == {bot["id"]}


def test_the_lookup_lists_the_templates_with_their_keys_and_his_bots():
    bots.create_bot(OWNER_HASH, {"name": "我的 bot"})
    found = run(act.handle(make_run(), {"operation": "apply_role_template"}))
    text = str(found)
    assert "dca_monthly" in text and "定投" in text and "我的 bot" in text
    assert "token" not in text.lower() and OWNER_HASH not in text


def test_undo_takes_back_the_newest_application_and_shows_each_item():
    assert press(prepare("apply_role_template", {"template": "定投"}))["ok"]
    after_apply = counts()
    assert after_apply["items"] == 4 and after_apply["tasks"] == 1
    card = prepare("undo_role_template", {})
    assert card.display["title"] == "撤掉模板 · 定投" and len(card.display["targets"]) == 4 + 1 + 1 + 1       # memory, brief, skill, usual 财报速读
    assert counts() == after_apply                                   # a card writes nothing
    assert press(card)["ok"]
    assert counts() == {"items": 0, "tasks": 0, "skills": 0, "applications": 1}
    refused("undo_role_template", {}, "application_not_found")             # nothing left to take back
    with SessionLocal() as db:
        application = str(db.query(RoleTemplateApplication).one().id)
    refused("undo_role_template", {"application_id": application}, "already_undone")


def test_undo_with_leave_out_keeps_those_and_says_so():
    assert press(prepare("apply_role_template", {"template": "定投"}))["ok"]
    keep = next(i for i in rt.list_applications(OWNER_HASH)[0]["items"] if i["part"] == "memory")
    card = prepare("undo_role_template", {"leave_out": [keep["id"]]})
    assert len(card.display["targets"]) == 3 + 1 + 1 + 1 and f"留下：{keep['label']}" in card.display["alternative"]
    assert press(card)["ok"]
    assert counts()["items"] == 1
    refused("undo_role_template", {"leave_out": ["nope"]}, "application_not_found")      # nothing left, and a made-up id is not a way round it


def test_a_guest_is_refused_and_an_agents_own_suggestion_never_applies_a_template():
    for name in NAMES:
        out = run(act.handle(make_run(credential="x" * 64), {"operation": name}))
        assert out["error_code"] == "owner_login_required", name
    from app.agent_workflow.grants import suggestion_operation
    for name, arguments in (("apply_role_template", {"template": "定投"}), ("undo_role_template", {})):
        validate(name, arguments)
        with pytest.raises(ValueError, match="invalid_action_tool"):
            suggestion_operation(name, arguments)


def test_the_duty_sentence_follows_the_live_mode(monkeypatch):
    monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    assert rt.NOTE_DUTY_RECORDS not in prepare("apply_role_template", {"template": "定投"}).display["alternative"]
    monkeypatch.setenv("FINBOT_DUTY_MODE", "shadow")
    assert rt.NOTE_DUTY_RECORDS in prepare("apply_role_template", {"template": "定投"}).display["alternative"]
