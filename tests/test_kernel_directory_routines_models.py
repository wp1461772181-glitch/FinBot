"""Stage 3a, task 1: routines with the scheduling the HTTP route has, ``analyze`` with a catalog model and a re-run, ``list_models``.

Card text and refusals come from ``act.prepare``; the press is ``tools._dispatch`` / ``execute_costly`` (the same functions
the card runs).  The routine tests use the disposable Postgres; nothing reaches the network or a model.
"""
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app import agent_tasks as tasks
from app.agent_chat_models import AgentTask
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import OWNER_ONLY, definitions, schemas, validate
from app.agent_workflow import consent, tools
from app.database import Base, SessionLocal, engine
from app.kernel import act, loop, progress, toolrun

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
SOURCE = "11111111-2222-3333-4444-555555555555"


def run(coro):
    return asyncio.run(coro)


def make_run(**extra):
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id="c", bot_id=None, bot_name="",
                              tool_scope=None, default_company=None, watchlist=())
    return SimpleNamespace(context=context, user_text="", question="", turn_id="t", web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], **extra)


@pytest.fixture
def owner(monkeypatch, disposable_database):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_") and t.name not in skipped])
    with SessionLocal() as db:
        db.query(AgentTask).delete()
        db.commit()
    import app.agent_chat_identity as identity
    from app.agent_workflow import direct
    for module in (consent, direct, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)
    import app.kernel.act as kernel_act
    monkeypatch.setattr(kernel_act, "owner_credential_matches", lambda c: c == OWNER)
    return OWNER


def saved(**fields):
    base = {"name": "晨报", "kind": "brief", "schedule_kind": "daily", "schedule_time": "09:00", "instruction": "看新闻"}
    return tasks.create_task(OWNER_HASH, {**base, **fields})


def context():
    return SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id="c", bot_id=None, executor=None)


def press(operation):
    """What the card runs for a reversible operation, minus the consent ledger (the frozen operation is the card's)."""
    args = validate(operation["name"], operation["arguments"])
    if operation["name"] == "create_routine":
        args["_bot_id"] = operation.get("bot_id")
    return asyncio.run(tools._dispatch(operation["name"], args, context(), True, None))


# --- arguments ---------------------------------------------------------------------------------------------------

def test_routine_arguments_take_what_the_route_takes():
    full = validate("create_routine", {"name": "n", "instruction": "i", "schedule_kind": "every", "schedule_time": "08:00",
                                       "every_value": 2, "every_unit": "hours", "max_runs": 5, "skill_id": SOURCE})
    assert (full["every_value"], full["every_unit"], full["max_runs"], full["skill_id"]) == (2, "hours", 5, SOURCE)
    alerts = validate("create_routine", {"name": "n", "kind": "alerts", "schedule_kind": "daily", "channel": "telegram",
                                         "config": {"filings": True, "news": False, "price_lines": [{"symbol": "AAPL", "above": 200}]}})
    assert alerts["kind"] == "alerts" and alerts["instruction"] is None and alerts["channel"] == "telegram"
    # the owner says hour, the route says hours: both are understood, the route's word is what is kept
    assert validate("update_routine", {"routine_id": SOURCE, "every_value": 2, "every_unit": "hour"})["every_unit"] == "hours"
    assert validate("update_routine", {"routine_id": SOURCE, "max_runs": 3})["max_runs"] == 3
    with pytest.raises(Exception):
        validate("update_routine", {"routine_id": SOURCE})
    with pytest.raises(Exception):
        validate("create_routine", {"name": "n", "instruction": "i", "schedule_kind": "every", "every_unit": "months"})


def test_analyze_takes_a_catalog_model_and_a_rerun():
    args = validate("analyze", {"symbol": "AAPL", "source_id": SOURCE, "catalog_model": "glm5.3-flash", "force": True})
    assert args["catalog_model"] == "glm5.3-flash" and args["force"] is True
    plain = validate("analyze", {"symbol": "AAPL", "source_id": SOURCE})
    assert plain["catalog_model"] is None and plain["force"] is False
    for bad in ({"catalog_model": ""}, {"catalog_model": "x" * 41}, {"force": 5}):
        with pytest.raises(Exception):
            validate("analyze", {"symbol": "AAPL", "source_id": SOURCE, **bad})


# --- routines: the card and the refusals ---------------------------------------------------------------------------

def test_update_to_every_two_hours_shows_old_and_new_and_runs_every_two_hours(owner):
    task = saved()
    prepared = run(act.prepare(make_run(), "update_routine", {"routine_id": task["id"], "every_value": 2, "every_unit": "hour", "schedule_kind": "every"}))
    shown = prepared.display["alternative"]
    assert "每天 09:00 → 每 2 小时（从 09:00 起）" in shown and prepared.tier == 2
    assert tasks.get_task(OWNER_HASH, task["id"])["schedule_kind"] == "daily"          # a card writes nothing
    done = press(prepared.operation)
    assert done["ok"] and done["data"][0]["status"] == "updated"
    after = tasks.get_task(OWNER_HASH, task["id"])
    assert (after["schedule_kind"], after["every_value"], after["every_unit"]) == ("every", 2, "hours")
    with SessionLocal() as db:
        row = db.get(AgentTask, after["id"])
        first = row.next_run_at
        tasks.advance(row, first)
        assert (row.next_run_at - first).total_seconds() == 2 * 3600


def test_values_the_route_rejects_are_rejected_with_its_reason_and_no_card(owner):
    task = saved()
    for fields, reason in (({"every_value": 0, "schedule_kind": "every", "every_unit": "hours"}, "invalid_every"),
                           ({"every_value": 721, "schedule_kind": "every", "every_unit": "hours"}, "invalid_every"),
                           ({"schedule_kind": "every", "every_unit": "days"}, "invalid_every"),
                           ({"max_runs": 1001}, "invalid_max_runs"), ({"max_runs": -1}, "invalid_max_runs"),
                           ({"skill_id": "99999999-9999-4999-8999-999999999999"}, "unknown_skill")):
        out = run(act.prepare(make_run(), "update_routine", {"routine_id": task["id"], **fields}))
        assert isinstance(out, dict) and out["error_code"] == reason, fields
        with pytest.raises(tasks.TaskError) as route:           # the route's own validation, same code
            tasks.update_task(OWNER_HASH, task["id"], fields)
        assert str(route.value) == reason
    created = run(act.prepare(make_run(), "create_routine", {"name": "n", "instruction": "i", "schedule_kind": "every", "every_value": 9999, "every_unit": "days"}))
    assert created["error_code"] == "invalid_every"
    blank = run(act.prepare(make_run(), "create_routine", {"name": "n", "schedule_kind": "daily"}))
    assert blank["error_code"] == "invalid_instruction"


def test_create_every_n_with_a_cap_and_alerts_with_telegram(owner):
    prepared = run(act.prepare(make_run(), "create_routine", {"name": "两小时新闻", "instruction": "找新闻", "schedule_kind": "every",
                                                              "schedule_time": "08:00", "every_value": 2, "every_unit": "hours", "max_runs": 3}))
    assert prepared.display["targets"][0]["kind"] == "每 2 小时（从 08:00 起），共 3 次"
    created = press(prepared.operation)
    assert created["ok"]
    (row,) = tasks.list_tasks(OWNER_HASH)
    assert (row["schedule_kind"], row["every_value"], row["every_unit"], row["max_runs"]) == ("every", 2, "hours", 3)
    alerts = run(act.prepare(make_run(), "create_routine", {"name": "盯盘", "kind": "alerts", "schedule_kind": "hourly", "schedule_time": "00:10",
                                                            "channel": "telegram", "config": {"price_lines": [{"symbol": "AAPL", "above": 200}]}}))
    assert "Telegram" in alerts.display["alternative"] and "AAPL" in alerts.display["alternative"]
    assert press(alerts.operation)["ok"]
    kinds = {r["name"]: (r["kind"], r["channel"]) for r in tasks.list_tasks(OWNER_HASH)}
    assert kinds["盯盘"] == ("alerts", "telegram")


def test_a_brief_keeps_its_inbox_and_the_card_says_so(owner):
    task = saved()
    out = run(act.prepare(make_run(), "update_routine", {"routine_id": task["id"], "channel": "telegram", "name": "新名字"}))
    assert "名称：晨报 → 新名字" in out.display["alternative"] and "通知渠道" not in out.display["alternative"]    # a brief's channel stays the inbox


def test_update_card_lists_each_change_old_to_new(owner):
    task = saved(max_runs=4)
    out = run(act.prepare(make_run(), "update_routine", {"routine_id": task["id"], "max_runs": 0, "enabled": False, "symbols": ["AAPL"]}))
    text = out.display["alternative"]
    assert "每天 09:00，共 4 次 → 每天 09:00" in text and "状态：运行中 → 暂停" in text and "范围：研究队列 → AAPL" in text


# --- analyze --------------------------------------------------------------------------------------------------------

def stub_catalog(monkeypatch, *names, keyless=()):
    items = [{"name": n, "display_name": n.upper(), "provider": "openrouter", "model": f"vendor/{n}", "base_url": None,
              "key_source": "env", "key_env": "X_API_KEY", "ciphertext": None, "origin": "server", "is_default": False,
              "migrated_from": None, "context_window": None} for n in names]
    monkeypatch.setattr(catalog, "entries", lambda: (items, names[0] if names else None))
    monkeypatch.setattr(catalog, "_key_for", lambda entry: None if entry["name"] in keyless else "sk-secret-0123456789")


def test_analyze_card_names_the_model_and_a_wrong_name_makes_no_card(monkeypatch):
    stub_catalog(monkeypatch, "glm5.3-flash", "nokey", keyless=("nokey",))
    from app.agent_workflow import direct
    monkeypatch.setattr(direct, "source_display_title", lambda kind, source_id: "Apple 10-K")
    out = run(act.prepare(make_run(), "analyze", {"symbol": "AAPL", "source_id": SOURCE, "catalog_model": "glm5.3-flash", "force": True}))
    assert out.tier == 3 and "GLM5.3-FLASH" in out.display["alternative"] and "vendor/glm5.3-flash" in out.display["alternative"]
    assert "重新" in out.display["alternative"] and "sk-secret" not in json.dumps(out.operation) + json.dumps(out.display)
    assert out.operation["arguments"]["catalog_model"] == "glm5.3-flash" and out.operation["arguments"]["force"] is True
    missing = run(act.prepare(make_run(), "analyze", {"symbol": "AAPL", "source_id": SOURCE, "catalog_model": "nope"}))
    assert isinstance(missing, dict) and missing["error_code"] == "model_not_found"
    nokey = run(act.prepare(make_run(), "analyze", {"symbol": "AAPL", "source_id": SOURCE, "catalog_model": "nokey"}))
    assert nokey["error_code"] == "model_key_missing"
    plain = run(act.prepare(make_run(), "analyze", {"symbol": "AAPL", "source_id": SOURCE}))
    assert "默认" in plain.display["alternative"] and "重新" not in plain.display["alternative"]


def test_analyze_runs_on_the_chosen_model_and_forces(monkeypatch):
    stub_catalog(monkeypatch, "glm5.3-flash")
    from app import material_analysis
    from app.agent_workflow import actions
    seen = {}

    def fake_request(**kwargs):
        seen.update(kwargs)
        return {"job_id": "22222222-2222-4222-8222-222222222222", "status": "queued"}

    monkeypatch.setattr(material_analysis, "request_material_analysis", fake_request)
    monkeypatch.setattr(actions, "owner_credential_matches", lambda c: True)
    # run only the part up to the call: the ledger needs the database, so the action's body is checked through its payload handling
    request = actions.analysis_request({"source_id": SOURCE, "source_type": "official_filing", "catalog_model": "glm5.3-flash", "force": True})
    assert request == {"force": True, "provider": "openrouter", "base_url": None, "model": "vendor/glm5.3-flash", "api_key": "sk-secret-0123456789"}
    assert actions.analysis_request({"source_id": SOURCE}) == {"force": False}
    with pytest.raises(actions.ActionError) as gone:
        actions.analysis_request({"source_id": SOURCE, "catalog_model": "nope"})
    assert gone.value.code == "model_not_found"


# --- list_models ----------------------------------------------------------------------------------------------------

def test_list_models_is_an_owner_only_own_state_read_with_a_phrase():
    assert definitions()["list_models"].level == "read" and "list_models" in OWNER_ONLY
    assert "list_models" in loop.READ_TOOLS and progress.TOOL_PHRASES["list_models"] == "看可用模型"
    assert "list_models" in toolrun._UNNUMBERED and "list_models" in toolrun._OWN_STATE_READS
    assert any(s["function"]["name"] == "list_models" for s in schemas(owner=True))
    assert not any(s["function"]["name"] == "list_models" for s in schemas(owner=False))


def test_a_guest_is_not_offered_list_models(monkeypatch):
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: False)
    guest = [s["function"]["name"] for s in loop._tool_schemas(SimpleNamespace(identity_credential="x", tool_scope=None))]
    assert "list_models" not in guest
    monkeypatch.setattr(loop, "owner_credential_matches", lambda value: True)
    owner_names = [s["function"]["name"] for s in loop._tool_schemas(SimpleNamespace(identity_credential="x", tool_scope=None))]
    assert "list_models" in owner_names


def test_list_models_lists_the_catalog_defaults_and_roles_without_any_key(monkeypatch):
    stub_catalog(monkeypatch, "haiku-5.5", "nokey", keyless=("nokey",))
    monkeypatch.setattr(roles, "all_roles", lambda owner: {"earnings": "haiku-5.5", "forecast": None, "judge": "gone", "fallback": None})
    monkeypatch.setattr(catalog, "exists", lambda name: name in {"haiku-5.5", "nokey"})
    out = asyncio.run(tools._dispatch("list_models", {}, SimpleNamespace(owner_hash=OWNER_HASH), True, None))
    assert out["ok"] is True
    (row,) = out["data"]
    assert row["default_model"] == "haiku-5.5"
    assert [(m["name"], m["key_set"]) for m in row["models"]] == [("haiku-5.5", True), ("nokey", False)]
    assert row["models"][0]["model"] == "vendor/haiku-5.5" and row["models"][0]["is_default"] is True
    assert row["roles"]["earnings"]["model"] == "haiku-5.5" and row["roles"]["forecast"]["model"] is None
    assert row["roles"]["judge"]["in_catalog"] is False
    text = json.dumps(out)
    assert "sk-secret" not in text and "key_hint" not in text and "ciphertext" not in text and "key_env" not in text and "X_API_KEY" not in text
    refused = asyncio.run(tools._dispatch("list_models", {}, SimpleNamespace(owner_hash=OWNER_HASH), False, None))
    assert refused["error_code"] == "owner_login_required"


def test_a_pressed_analysis_reaches_the_service_with_the_model_and_force(disposable_database, monkeypatch):
    """The whole ledger path: what ``request_material_analysis`` is called with (its key never lands in the ledger)."""
    from runpy import run_path
    from uuid import uuid4
    from sqlalchemy import text
    from app import material_analysis
    from app.agent_workflow import actions
    from app.knowledge.models import KnowledgeUploadOwner
    run_path("scripts/migrate_agent_actions.py")["apply"]()
    Base.metadata.create_all(engine, tables=[KnowledgeUploadOwner.__table__])
    upload = uuid4()
    with SessionLocal() as db:
        db.add(KnowledgeUploadOwner(upload_id=upload, owner_hash=OWNER_HASH))
        db.commit()
    stub_catalog(monkeypatch, "glm5.3-flash")
    monkeypatch.setattr(actions, "owner_credential_matches", lambda c: c == OWNER)
    seen = {}
    monkeypatch.setattr(material_analysis, "request_material_analysis",
                        lambda **kwargs: seen.update(kwargs) or {"job_id": str(uuid4()), "status": "succeeded"})
    monkeypatch.setattr(material_analysis, "get_job", lambda db, job_id: {"status": "succeeded"})
    payload = {"source_id": str(upload), "source_type": "uploaded_media", "catalog_model": "glm5.3-flash", "force": True}
    value = actions.execute_action(credential=OWNER, request_key="analyze-1", action="analyze", payload=payload)
    assert value["ok"] and (seen["force"], seen["provider"], seen["model"], seen["api_key"]) == (True, "openrouter", "vendor/glm5.3-flash", "sk-secret-0123456789")
    with SessionLocal() as db:
        ledger = " ".join(str(v) for row in db.execute(text("SELECT * FROM agent_action_requests")).all() for v in row)
    assert "sk-secret" not in ledger
    with pytest.raises(actions.ActionError, match="model_not_found"):
        actions.execute_action(credential=OWNER, request_key="analyze-2", action="analyze", payload={**payload, "catalog_model": "nope"})
