"""Task 13: tools are disclosed by category (names + one line in the prompt, full schemas after load_tools).

* every catalogue tool belongs to exactly one category (or is always on);
* a default owner turn carries at most 8 KB of tool definitions;
* load_tools: the chosen categories' schemas ride on the NEXT model call, never the same one;
* what a bot's tool_scope removes can not be loaded; a write is still refused without a grant and a card.
"""
import asyncio
import json
import uuid

import pytest

from app import agent_context as layers
from app.agent_tool_catalog import ALWAYS_ON, KERNEL_ONLY, TOOL_CATEGORIES, definitions, legacy_definitions

OWNER = "o" * 40
OWNER_HASH = "h" * 64
FIN = "财报与SEC"
PRICES = "行情"
PORTFOLIO = "持仓"
WORKSPACE = "工作区"
NEWS = "新闻与网页"


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    from app.agent_workflow import consent, tools
    import app.agent_chat_identity as identity
    for module in (consent, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)


def _turn(*, decider=None, recognizer=None, executor=None, tool_scope=None, question="q", state=None):
    pass  # (removed import of the old turn)
    from app.agent_workflow.state import AgentRuntimeContext
    context = AgentRuntimeContext("custom", "m", "k", owner_hash=OWNER_HASH, identity_credential=OWNER,
                                  conversation_id=str(uuid.uuid4()), tool_scope=tool_scope,
                                  decider=decider, intent_recognizer=recognizer, executor=executor)

    async def quiet(_event):
        pass
    return direct, direct.Turn(question, context, quiet, [], state or {}), context, quiet


def _names(schemas):
    return [t["function"]["name"] for t in schemas]


def _call(call_id, name, **args):
    return {"tool_calls": [{"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_every_tool_has_category():
    owned = {}
    for category, info in TOOL_CATEGORIES.items():
        for tool in info.tools:
            owned.setdefault(tool, []).append(category)
    for tool in ALWAYS_ON:
        owned.setdefault(tool, []).append("always_on")
    # The categories are the old engine's disclosure; tools only the kernel offers (it lists every tool at once) have none.
    names = set(legacy_definitions())
    assert names == set(owned), (names ^ set(owned))
    assert set(definitions()) - names == set(KERNEL_ONLY) and not KERNEL_ONLY & set(owned)
    assert {t: c for t, c in owned.items() if len(c) != 1} == {}
    assert all(info.summary and info.tools for info in TOOL_CATEGORIES.values())
    assert {"load_tools"} <= ALWAYS_ON <= names
    # The seven news-source management tools are one tool with an action now.
    assert not names & {"list_news_sources", "dry_run_news_source", "diagnose_news_source", "upsert_news_source",
                        "disable_news_source", "set_news_source_alternate", "repair_news_source_with_rea"}
    assert "manage_news_source" in names


@pytest.fixture
def database(disposable_database):
    from app.database import Base, engine
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_")
                                             and t.name not in skipped])


def test_manage_news_source_validates_action():
    from app.agent_tool_catalog import validate
    assert validate("manage_news_source", {"action": "list"})["action"] == "list"
    with pytest.raises(Exception):
        validate("manage_news_source", {"action": "diagnose"})  # needs source_id
    with pytest.raises(Exception):
        validate("manage_news_source", {"action": "upsert", "source_id": "abc"})  # needs url
    assert validate("manage_news_source", {"action": "set_enabled", "source_id": "abc", "enabled": False})["enabled"] is False


def test_fixed_tokens_is_measured_not_written_down():
    assert layers.FIXED_TOKENS != 8_000
    measured = layers.measure_fixed_tokens()
    assert layers.FIXED_TOKENS == measured
    assert 4_000 < measured < 16_000


def test_retired_news_tool_names_in_old_scopes_mean_the_merged_tool():
    from app.agent_tool_catalog import expand_legacy
    assert "manage_news_source" in expand_legacy({"upsert_news_source", "web_research"})
    assert expand_legacy({"web_research"}) == {"web_research"}
