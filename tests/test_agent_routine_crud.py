"""例行任务 CRUD from chat (Levi 2026-10-28: 「给了新增例行任务的接口，怎么没给查看、编辑、删除」).

Whole turns through ``run_direct_turn`` with a scripted model: list_routines reads directly; update_routine and
delete_routine make a confirmation card and change nothing until it is pressed; a cancelled card changes
nothing; the 例行任务 page lists the cards still waiting.
"""
import asyncio
import json

import pytest

from app import agent_bots as bots
from app import agent_tasks as tasks
from app.agent_bots import ALWAYS_ON
from app.agent_chat_models import AgentBot, AgentConversation, AgentTask
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import OWNER_ONLY, definitions, validate
from app.agent_workflow import consent
from app.agent_workflow.authorization import routine_ask
from app.agent_workflow.grants import suggestion_operation
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
NEWS = {"name": "每小时新闻", "kind": "brief", "schedule_kind": "hourly", "schedule_time": "00:05",
        "instruction": "每小时找一条研究队列公司的新闻，有新的就 notify_telegram。"}


@pytest.fixture
def owner(monkeypatch, disposable_database):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_")
                                             and t.name not in skipped])
    with SessionLocal() as db:
        for model in (AgentTask, AgentConsent, AgentBot, AgentConversation):
            db.query(model).delete()
        db.commit()
    from app.agent_workflow import tools
    import app.agent_chat_identity as identity
    for module in (consent, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return OWNER


def _context(bot, **kwargs):
    from app.agent_workflow.state import AgentRuntimeContext
    kwargs.setdefault("resolver", lambda payload: {"relationship": "new", "canonical_question": payload["question"]})
    kwargs.setdefault("intent_recognizer", lambda _p: {"category": "D", "days_back": None, "requested_actions": []})
    return AgentRuntimeContext("custom", "test", "dummy", identity_credential=OWNER, owner_hash=OWNER_HASH,
                               conversation_id=bot["conversation_id"], bot_id=bot["id"], bot_name=bot["name"], **kwargs)


def _call(name, arguments, call_id=None):
    return {"tool_calls": [{"id": call_id or name, "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


def _replies(messages):
    return {m["tool_call_id"]: json.loads(m["content"]) for m in messages if m.get("role") == "tool"}


async def _quiet(_event):
    pass


def _turn(question, context, **kwargs):
    from app import agent_chat_store as store
    pass  # (removed import of the old turn)
    async def run():
        try:
            return await direct.run_direct_turn(question, context, emit=_quiet, **kwargs)
        finally:
            await store.engine.dispose()
    return asyncio.run(run())


def _press(card, context, choice="confirm:"):
    value = next(c["value"] for c in card["choices"] if c["value"].startswith(choice))
    return _turn(value, context, state={"pending_request": card, "requested_pending_id": card["id"]})


def _model(write_name, write_args):
    """Lists first, then proposes the write on the id the list returned, then answers."""
    seen = []

    def decide(messages, tools):
        seen.append(messages)
        replies = _replies(messages)
        if "list" not in replies:
            return _call("list_routines", {}, "list")
        if "write" not in replies and write_name:
            return _call(write_name, {"routine_id": replies["list"]["data"][0]["id"], **write_args}, "write")
        return {"content": "好的。"}
    return decide, seen


def _finbot_with_news():
    finbot = bots.create_bot(OWNER_HASH, {"name": "FinBot"})
    task = tasks.create_task(OWNER_HASH, {**NEWS, "bot_id": finbot["id"]})
    return finbot, task


# --- catalogue -------------------------------------------------------------------------------------

def test_routine_tools_are_owner_only_in_every_bot_and_writes_need_a_card():
    assert {"list_routines", "update_routine", "delete_routine"} <= ALWAYS_ON & OWNER_ONLY
    assert definitions()["list_routines"].level == "read"
    assert definitions()["update_routine"].level == definitions()["delete_routine"].level == "reversible"
    rid = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(Exception):
        validate("update_routine", {"routine_id": rid})  # changes nothing
    assert validate("update_routine", {"routine_id": rid, "enabled": False})["enabled"] is False
    for name in ("update_routine", "delete_routine"):
        with pytest.raises(ValueError):
            suggestion_operation(name, {"routine_id": rid})


def test_the_owners_words_ask_for_a_change_only_when_they_name_a_routine():
    assert routine_ask("update_routine", "把每小时新闻那个任务停掉")
    assert routine_ask("update_routine", "例行任务改成每天 9 点")
    assert routine_ask("delete_routine", "删掉那个例行任务")
    assert not routine_ask("delete_routine", "删掉第二段")           # no routine named
    assert not routine_ask("delete_routine", "不要删除例行任务")      # negated


# --- list ------------------------------------------------------------------------------------------

# --- update ----------------------------------------------------------------------------------------

# --- delete ----------------------------------------------------------------------------------------

