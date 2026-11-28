"""Stage 3a, task 2: bots, transactions, skills, model settings and channels through ``act``.

Cards and refusals come from ``act.prepare``; a press goes through the real consent ledger and ``act.execute_handler`` (the
functions a card runs).  What a press does is compared with what the HTTP route does.  Disposable Postgres; no network,
no model.
"""
import asyncio
import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app import agent_bots as bots
from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app import agent_skills as skills
from app import channels, portfolio
from app.agent_chat_models import (AgentBot, AgentChannelPref, AgentConversation, AgentModelEntry, AgentModelRole, AgentSkill,
                                   PortfolioTransaction)
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import OWNER_ONLY, definitions, validate
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.kernel import act

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
OTHER = owner_hash("somebody-else")
NEW = ("create_bot", "update_bot", "delete_transaction", "manage_skill", "set_default_model", "set_model_role", "set_channel_prefs")
SOURCE = "11111111-2222-3333-4444-555555555555"


def run(coro):
    return asyncio.run(coro)


def make_run(bot_id=None, credential=OWNER, **extra):
    context = SimpleNamespace(identity_credential=credential, owner_hash=OWNER_HASH, conversation_id="c", bot_id=bot_id, bot_name="",
                              tool_scope=None, default_company=None, watchlist=(), executor=None)
    return SimpleNamespace(context=context, user_text="", question="", turn_id="t", web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], writes=[], audit={}, read_results=0, **extra)


def wipe():
    with SessionLocal() as db:
        for model in (AgentConsent, PortfolioTransaction, AgentSkill, AgentChannelPref, AgentModelRole, AgentModelEntry, AgentBot, AgentConversation):
            db.query(model).delete()
        db.commit()


@pytest.fixture
def owner(monkeypatch, disposable_database, tmp_path):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_") and t.name not in skipped])
    wipe()
    import app.agent_chat_identity as identity
    import app.agent_chat_stream as stream
    from app.agent_workflow import tools
    for module in (consent, tools, identity, act, stream):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    monkeypatch.setenv("SENTINEL_CONFIG_PATH", str(tmp_path / "sentinel-config.json"))
    refreshed = []
    import app.sentinel_bridge as bridge
    monkeypatch.setattr(bridge, "refresh_sentinel_snapshot", lambda: refreshed.append(1))
    monkeypatch.setattr(bridge, "write_sentinel_snapshot", lambda owner: refreshed.append(owner))
    monkeypatch.setattr(catalog, "_read_file", lambda: ([], None, []))
    KEYLESS.clear()
    real_key = catalog._key_for
    monkeypatch.setattr(catalog, "_key_for", lambda item: None if item["name"] in KEYLESS else real_key(item))
    monkeypatch.setattr("app.model_usage.forget_prices", lambda: None, raising=False)
    yield SimpleNamespace(refreshed=refreshed)
    wipe()          # the database is shared by the whole session: leave no model entry, role, bot or skill behind


KEYLESS = set()


def entry(name, key=True):
    catalog.save_entry(name, provider="openrouter", model=f"vendor/{name}", display_name=name.title(), api_key="sk-secret-0123456789", create=True)
    if not key:
        KEYLESS.add(name)           # an entry whose key is not there (an environment variable that is not set)


def card(prepared, handler_context=None):
    """What the owner sees: the card the turn would mint for this one operation."""
    return prepared.display


def conversation():
    return bots.ensure_default_bot(OWNER_HASH).conversation_id


def press(prepared):
    """The real thing: a consent card for the frozen operation, then the owner's press through the kernel's executor."""
    operation = prepared.operation
    conv = str(conversation())
    proposed = consent.propose(OWNER, conv, [operation], prepared.display)
    token = proposed["choices"][0]["value"].split(":", 1)[1]
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id=conv, bot_id=None, executor=None)
    return consent.execute(OWNER, conv, token, [operation], act.execute_handler(context))


def prepare(name, arguments, **kwargs):
    return run(act.prepare(make_run(**kwargs), name, arguments))


def refused(name, arguments, code, **kwargs):
    out = prepare(name, arguments, **kwargs)
    assert isinstance(out, dict) and out["ok"] is False and out["error_code"] == code, out
    assert out.get("reason") and out.get("hint")       # something the model can act on
    return out


def buy(symbol="INTC", quantity=100, price=80, on="2026-10-01", **extra):
    return portfolio.record_transaction(OWNER_HASH, {"kind": "buy", "symbol": symbol, "quantity": quantity, "price": price, "occurred_on": on, **extra})["id"]


# --- the directory ---------------------------------------------------------------------------------------------

def test_the_seven_operations_are_tier_two_owner_only_cards():
    for name in NEW:
        assert name in act.TIER2 and name in act.OPERATIONS and act.SUMMARIES[name], name
        policy = definitions()[name]
        assert policy.level == "reversible" and name in OWNER_ONLY and policy.confirmation, name
        assert f"\n{name}：" in act.ACT_SCHEMA["function"]["description"]
    assert "delete_bot" not in act.OPERATIONS and not any("delete_bot" in s for s in act.SUMMARIES.values())
    assert act.describe("update_bot")["tier"] == 2


def test_arguments():
    bot = validate("create_bot", {"name": "研究员", "focus_companies": ["AAPL"], "tool_scope": ["query_financials"], "pinned": True})
    assert bot["focus_companies"] == ["AAPL"] and bot["model"] is None
    for bad in ({}, {"name": ""}, {"name": "x" * 41}, {"name": "x", "focus_companies": ["A"] * 21}, {"name": "x", "extra": 1},
                {"name": "x", "tool_scope": ["a"], "all_tools": True}, {"name": "x", "model": "m", "use_default_model": True}):
        with pytest.raises(Exception):
            validate("create_bot", bad)
    assert validate("update_bot", {"bot_id": SOURCE, "all_tools": True})["all_tools"] is True
    with pytest.raises(Exception):
        validate("update_bot", {"bot_id": SOURCE})                     # nothing to change
    for bad in ({"action": "edit", "skill_id": SOURCE}, {"action": "enable", "skill_id": SOURCE, "body": "x"}, {"action": "purge", "skill_id": SOURCE}):
        with pytest.raises(Exception):
            validate("manage_skill", bad)
    assert validate("manage_skill", {"action": "edit", "skill_id": SOURCE, "body": "新步骤"})["body"] == "新步骤"
    assert validate("set_model_role", {"role": "judge"})["model"] is None
    with pytest.raises(Exception):
        validate("set_model_role", {"role": "boss", "model": "x"})
    with pytest.raises(Exception):
        validate("set_channel_prefs", {"mode": "all", "channels": []})
    with pytest.raises(Exception):
        validate("delete_transaction", {"transaction_id": "7"})


# --- bots --------------------------------------------------------------------------------------------------------

def test_create_bot_card_names_everything_and_writes_nothing(owner):
    entry("alpha")
    prepared = prepare("create_bot", {"name": "研究员甲", "title": "盯苹果", "focus_companies": ["aapl", "MSFT"], "focus_theme": "AI 服务器",
                                      "tool_scope": ["query_financials", "web_research"], "model": "alpha", "reasoning_effort": "high", "pinned": True})
    assert prepared.tier == 2 and prepared.display["title"] == "新建 bot · 研究员甲"
    text = prepared.display["alternative"]
    for part in ("名称：研究员甲", "职位：盯苹果", "关注公司：AAPL、MSFT", "关注主题：AI 服务器", "可用工具：query_financials、web_research",
                 "模型：Alpha（vendor/alpha）", "推理强度：high", "置顶：是"):
        assert part in text, part
    assert "删除 bot 要在页面上操作" in text
    assert [b["name"] for b in bots.list_bots(OWNER_HASH)] == ["助理"]           # a card writes nothing (the default bot is the system's own)


def test_create_bot_pressed_equals_the_route(owner):
    from app.agent_bots_api import BotBody, create_bot_endpoint
    entry("alpha")
    prepared = prepare("create_bot", {"name": "研究员甲", "title": "盯苹果", "description": "只看苹果", "focus_companies": ["AAPL"], "focus_theme": "手机",
                                      "tool_scope": ["query_financials"], "model": "alpha", "reasoning_effort": "low", "pinned": True, "hidden": False})
    done = press(prepared)
    assert done["ok"], done
    made = next(b for b in bots.list_bots(OWNER_HASH) if b["name"] == "研究员甲")
    body = BotBody(name="路由版", title="盯苹果", description="只看苹果", focus={"companies": [{"symbol": "AAPL"}], "theme": "手机"},
                   tool_scope=["query_financials"], model="alpha", reasoning_effort="low", pinned=True, hidden=False)
    routed = run(create_bot_endpoint(body, x_chat_session=OWNER))["bot"]
    skip = {"id", "name", "conversation_id", "created_at", "updated_at", "last_message", "last_at"}
    assert {k: v for k, v in made.items() if k not in skip} == {k: v for k, v in routed.items() if k not in skip}
    assert made["conversation_id"] and made["is_default"] is False


def test_create_bot_is_refused_before_a_card_with_the_routes_reason(owner):
    entry("alpha")
    entry("nokey", key=False)
    bots.create_bot(OWNER_HASH, {"name": "重名"})
    for fields, code in (({"model": "ghost"}, "unknown_model"), ({"model": "nokey"}, "model_key_missing"),
                         ({"focus_companies": ["not a ticker"]}, "invalid_focus_symbol"), ({"name": "重名"}, "name_taken"),
                         ({"reasoning_effort": "turbo"}, "invalid_reasoning_effort"), ({"tool_scope": ["no_such_tool"]}, "unknown_tool"),
                         ({"skills": [SOURCE]}, "unknown_skill")):
        refused("create_bot", {"name": "新", **fields}, code)
    for fields, code in (({"focus": {"companies": [{"symbol": "not a ticker"}]}}, "invalid_focus_symbol"), ({"name": "重名"}, "name_taken"),
                         ({"reasoning_effort": "turbo"}, "invalid_reasoning_effort"), ({"tool_scope": ["no_such_tool"]}, "unknown_tool")):
        with pytest.raises(bots.BotError) as route:                 # the route's own service says the same
            bots.create_bot(OWNER_HASH, {"name": "新", **fields})
        assert str(route.value) == code
    assert sorted(b["name"] for b in bots.list_bots(OWNER_HASH)) == ["助理", "重名"]


def test_too_many_bots_refused(owner, monkeypatch):
    monkeypatch.setattr(bots, "MAX_BOTS", 1)
    refused("create_bot", {"name": "多余"}, "too_many_bots")


def test_update_bot_card_lists_each_change_old_to_new_and_the_tools_added_and_removed(owner):
    entry("alpha")
    made = bots.create_bot(OWNER_HASH, {"name": "甲", "tool_scope": ["query_financials", "query_materials"], "focus": {"companies": [{"symbol": "AAPL", "name": "Apple"}], "theme": "手机"}})
    prepared = prepare("update_bot", {"bot_id": made["id"], "name": "乙", "tool_scope": ["query_financials", "web_research"], "model": "alpha",
                                      "reasoning_effort": "high", "pinned": True, "hidden": True})
    text = prepared.display["alternative"]
    assert prepared.display["title"] == "修改 bot · 甲"
    for part in ("名称：甲 → 乙", "新增：web_research", "去掉：query_materials", "模型：默认模型", "→ Alpha（vendor/alpha）", "推理强度：默认 → high",
                 "置顶：否 → 是", "隐藏：否 → 是"):
        assert part in text, part
    assert "query_financials" not in text.split("新增：")[1]          # unchanged tools are not listed as added or removed
    assert bots.get_bot(OWNER_HASH, made["id"])["name"] == "甲"


def test_update_bot_from_all_tools_lists_what_goes_and_back(owner):
    made = bots.create_bot(OWNER_HASH, {"name": "甲"})
    narrowed = prepare("update_bot", {"bot_id": made["id"], "tool_scope": ["query_financials"]})
    text = narrowed.display["alternative"]
    assert "可用工具：全部 → 1 个" in text and "新增：无" in text and "去掉：" in text and "web_research" in text and "基础工具始终保留" in text
    press(narrowed)
    back = prepare("update_bot", {"bot_id": made["id"], "all_tools": True})
    assert "1 个 → 全部" in back.display["alternative"] and "新增：" in back.display["alternative"] and "web_research" in back.display["alternative"]
    press(back)
    assert bots.get_bot(OWNER_HASH, made["id"])["tool_scope"] is None


def test_the_press_applies_what_the_card_showed_not_what_is_said_later(owner):
    made = bots.create_bot(OWNER_HASH, {"name": "甲", "tool_scope": ["query_financials"], "focus": {"companies": [{"symbol": "AAPL", "name": "Apple"}], "theme": "手机"}})
    arguments = {"bot_id": made["id"], "tool_scope": ["query_financials", "web_research"], "focus_theme": "云"}
    prepared = prepare("update_bot", arguments)
    arguments["tool_scope"].append("search_x")                      # the model's later text or arguments: not what was on the card
    arguments["focus_theme"] = "别的"
    assert press(prepared)["ok"]
    after = bots.get_bot(OWNER_HASH, made["id"])
    assert after["tool_scope"] == ["query_financials", "web_research"]
    assert after["focus"] == {"companies": [{"symbol": "AAPL", "name": "Apple"}], "theme": "云"}      # the focus of the card: its companies, with their names


STALE = "卡片发出后这项设置变了，没有执行；请让我重新出一张卡。"
STALE_DELETE = "这笔记录或持仓在卡片发出后变了，没有删除；请让我重新出一张卡。"


def refused_press(prepared, sentence=STALE):
    done = press(prepared)
    results = json.dumps(done, ensure_ascii=False)
    assert "card_stale" in results and sentence in results and '"ok": true' not in results.replace('"ok": true, "data": []', ""), done
    return done


def test_a_bot_that_changed_under_its_card_is_not_written(owner):
    made = bots.create_bot(OWNER_HASH, {"name": "甲", "tool_scope": ["query_financials"], "focus": {"companies": [{"symbol": "AAPL"}], "theme": "手机"}})
    prepared = prepare("update_bot", {"bot_id": made["id"], "focus_companies": ["MSFT"]})
    bots.update_bot(OWNER_HASH, made["id"], {"focus": {"companies": [{"symbol": "AAPL"}], "theme": "中途改的主题"}})
    refused_press(prepared)
    assert bots.get_bot(OWNER_HASH, made["id"])["focus"] == {"companies": [{"symbol": "AAPL", "name": None}], "theme": "中途改的主题"}


def test_a_ledger_that_changed_under_a_delete_card_is_not_written(owner):
    portfolio.record_transaction(OWNER_HASH, {"kind": "deposit", "amount": 11000, "occurred_on": "2026-09-30"})
    mine = buy("AAPL", 10, 10)
    prepared = prepare("delete_transaction", {"transaction_id": mine})
    assert "没有持仓" in prepared.display["alternative"]
    buy("AAPL", 5, 20, on="2026-10-02")                              # the position the card said would be gone is not what it was
    refused_press(prepared, STALE_DELETE)
    with SessionLocal() as db:
        assert db.query(PortfolioTransaction).count() == 3
    again = prepare("delete_transaction", {"transaction_id": mine})  # a new card shows the new figures, and works
    assert "AAPL 持仓：15 股" in again.display["alternative"] and press(again)["ok"]


def test_a_delete_card_whose_entry_is_already_gone_is_not_run_twice(owner):
    mine = buy()
    prepared = prepare("delete_transaction", {"transaction_id": mine})
    portfolio.delete_transaction(OWNER_HASH, mine)
    refused_press(prepared, STALE_DELETE)


def test_every_other_card_with_an_old_value_is_refused_when_that_value_moved(owner):
    entry("alpha")
    entry("beta")
    entry("gamma")
    catalog.set_default("alpha")
    skill = make_skill()
    # a skill edit
    edit = prepare("manage_skill", {"action": "edit", "skill_id": skill["id"], "body": "新步骤"})
    skills.update_skill(OWNER_HASH, skill["id"], {"body": "别人先改了"})
    refused_press(edit)
    assert skills.get_skill(OWNER_HASH, skill["id"])["body"] == "别人先改了"
    # a skill switch and delete
    off = prepare("manage_skill", {"action": "disable", "skill_id": skill["id"]})
    skills.set_enabled(OWNER_HASH, skill["id"], False)
    refused_press(off)
    gone = prepare("manage_skill", {"action": "delete", "skill_id": skill["id"]})
    skills.update_skill(OWNER_HASH, skill["id"], {"description": "又改了"})
    refused_press(gone)
    assert skills.get_skill(OWNER_HASH, skill["id"]) is not None
    # the default model
    default = prepare("set_default_model", {"name": "beta"})
    catalog.set_default("gamma")
    refused_press(default)
    assert catalog.entries()[1] == "gamma"
    # a role
    role = prepare("set_model_role", {"role": "earnings", "model": "beta"})
    roles.set_role(OWNER_HASH, "earnings", "alpha")
    refused_press(role)
    assert roles.get(OWNER_HASH, "earnings") == "alpha"
    # channels
    pref = prepare("set_channel_prefs", {"mode": "all", "channels": ["telegram", "wechat"]})
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    refused_press(pref)
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["wechat"], "mode": "first"}


def test_a_routine_that_changed_under_its_card_is_not_written(owner):
    from app import agent_tasks as tasks
    with SessionLocal() as db:
        from app.agent_chat_models import AgentTask
        db.query(AgentTask).delete()
        db.commit()
    task = tasks.create_task(OWNER_HASH, {"name": "晨报", "kind": "brief", "schedule_kind": "daily", "schedule_time": "09:00", "instruction": "看新闻"})
    assert press(prepare("update_routine", {"routine_id": task["id"], "enabled": False}))["ok"]          # an unchanged routine: the press goes through
    assert tasks.get_task(OWNER_HASH, task["id"])["enabled"] is False
    card = prepare("update_routine", {"routine_id": task["id"], "enabled": True})
    tasks.update_task(OWNER_HASH, task["id"], {"schedule_time": "13:00"})
    refused_press(card)
    assert tasks.get_task(OWNER_HASH, task["id"])["enabled"] is False


def test_a_card_whose_old_value_is_still_true_goes_through(owner):
    entry("alpha")
    entry("beta")
    catalog.set_default("alpha")
    assert press(prepare("set_default_model", {"name": "beta"}))["ok"]


def test_a_keyless_model_is_warned_on_a_role_card_and_the_skill_lookup_counts_as_a_read(owner):
    entry("alpha")
    entry("nokey", key=False)
    assert "还没有配置密钥" in prepare("set_model_role", {"role": "judge", "model": "nokey"}).display["alternative"]
    run_ = make_run()
    run(act.handle(run_, {"operation": "manage_skill"}))
    assert run_.read_results == 1


def test_update_bot_refusals_make_no_card(owner):
    made = bots.create_bot(OWNER_HASH, {"name": "甲"})
    bots.create_bot(OWNER_HASH, {"name": "乙"})
    default = bots.ensure_default_bot(OWNER_HASH)
    foreign = bots.create_bot(OTHER, {"name": "别人的"})
    refused("update_bot", {"bot_id": foreign["id"], "name": "抢"}, "bot_not_found")
    refused("update_bot", {"bot_id": "99999999-9999-4999-8999-999999999999", "name": "抢"}, "bot_not_found")
    refused("update_bot", {"bot_id": made["id"], "name": "乙"}, "name_taken")
    refused("update_bot", {"bot_id": made["id"], "model": "ghost"}, "unknown_model")
    refused("update_bot", {"bot_id": str(default.id), "hidden": True}, "default_bot_not_hidden")
    refused("update_bot", {"bot_id": made["id"], "skills": [SOURCE]}, "unknown_skill")
    assert bots.get_bot(OTHER, foreign["id"])["name"] == "别人的"


def test_update_bot_pressed_equals_the_route(owner):
    from app.agent_bots_api import BotBody, update_bot_endpoint
    one = bots.create_bot(OWNER_HASH, {"name": "甲"})
    two = bots.create_bot(OWNER_HASH, {"name": "乙"})
    press(prepare("update_bot", {"bot_id": one["id"], "title": "新职位", "focus_companies": ["MSFT"], "tool_scope": ["query_financials"], "pinned": True}))
    run(update_bot_endpoint(two["id"], BotBody(title="新职位", focus={"companies": [{"symbol": "MSFT"}]}, tool_scope=["query_financials"], pinned=True), x_chat_session=OWNER))
    skip = {"id", "name", "conversation_id", "created_at", "updated_at"}
    a, b = bots.get_bot(OWNER_HASH, one["id"]), bots.get_bot(OWNER_HASH, two["id"])
    assert {k: v for k, v in a.items() if k not in skip} == {k: v for k, v in b.items() if k not in skip}


def test_a_bot_names_skills_on_its_card(owner):
    skill = skills.create_skill(OWNER_HASH, {"name": "周报", "description": "每周", "body": "先看持仓", "allowed_tools": ["query_portfolio"]})
    made = bots.create_bot(OWNER_HASH, {"name": "甲"})
    prepared = prepare("update_bot", {"bot_id": made["id"], "skills": [skill["id"]]})
    assert "常用技能：无 → 周报" in prepared.display["alternative"]
    press(prepared)
    assert bots.get_bot(OWNER_HASH, made["id"])["skills"] == [skill["id"]]


# --- delete_transaction ------------------------------------------------------------------------------------------

def test_delete_transaction_card_shows_the_trade_and_the_position_and_cash_after(owner):
    portfolio.record_transaction(OWNER_HASH, {"kind": "deposit", "amount": 10000, "occurred_on": "2026-09-30"})
    first = buy(quantity=100, price=80, on="2026-10-01")
    buy(quantity=50, price=90, on="2026-10-02")
    prepared = prepare("delete_transaction", {"transaction_id": first})
    text = prepared.display["alternative"]
    target = prepared.display["targets"][0]
    assert prepared.tier == 2 and prepared.display["title"] == "删除一笔记录 · INTC"
    for part in ("2026-10-01", "买入", "100 股", "INTC", "@ 80"):
        assert part in target["kind"], part
    assert "INTC 持仓：150 股（平均成本 83.33） → 50 股（平均成本 90.00）" in text
    assert "可用资金 -2500.00 → 5500.00" in text
    assert "不能撤销" in text
    with SessionLocal() as db:
        assert db.query(PortfolioTransaction).count() == 3             # a card writes nothing


def test_delete_transaction_that_empties_a_position_says_so(owner):
    only = buy(quantity=10, price=50)
    text = prepare("delete_transaction", {"transaction_id": only}).display["alternative"]
    assert "INTC 持仓：10 股（平均成本 50.00） → 没有持仓" in text


def test_delete_transaction_pressed_equals_the_route(owner):
    from app.portfolio_api import delete_transaction_endpoint
    portfolio.record_transaction(OWNER_HASH, {"kind": "deposit", "amount": 1000, "occurred_on": "2026-09-30"})
    a, b = buy("INTC", 1, 10), buy("AAPL", 1, 10)
    done = press(prepare("delete_transaction", {"transaction_id": a}))
    assert done["ok"], done
    routed = run(delete_transaction_endpoint(b, x_chat_session=OWNER))
    assert routed["status"] == "deleted"
    with SessionLocal() as db:
        assert [r.kind for r in db.query(PortfolioTransaction).all()] == ["deposit"]
    assert owner.refreshed                                                 # the sentinel's copy follows, as for the other portfolio writes


def test_delete_transaction_refusals_make_no_card(owner):
    mine = buy()
    theirs = portfolio.record_transaction(OTHER, {"kind": "buy", "symbol": "AAPL", "quantity": 1, "price": 1, "occurred_on": "2026-10-01"})["id"]
    refused("delete_transaction", {"transaction_id": theirs}, "transaction_not_found")
    refused("delete_transaction", {"transaction_id": str(uuid.uuid4())}, "transaction_not_found")
    portfolio.record_transaction(OWNER_HASH, {"kind": "sell", "symbol": "INTC", "quantity": 100, "price": 90, "occurred_on": "2026-10-03"})
    out = refused("delete_transaction", {"transaction_id": mine}, "would_break_history")      # the sell would have nothing to sell
    assert "后面的卖出" in out["reason"]
    sold = buy("AAPL", 1, 1)
    portfolio.delete_transaction(OWNER_HASH, sold)
    refused("delete_transaction", {"transaction_id": sold}, "transaction_not_found")           # already deleted
    with SessionLocal() as db:
        assert db.query(PortfolioTransaction).filter_by(owner_hash=OTHER).count() == 1


def test_a_delete_needs_its_own_card_and_the_lookup_lists_the_ids(owner):
    mine = buy()
    skill = skills.create_skill(OWNER_HASH, {"name": "周报", "description": "每周", "body": "先看持仓", "allowed_tools": ["query_portfolio"]})
    looked = run(act.handle(make_run(), {"operation": "delete_transaction"}))
    listed = looked["data"][0]["transactions"]
    assert listed[0]["id"] == mine and "INTC" in listed[0]["text"] and "买入" in listed[0]["text"]
    first = make_run()
    assert run(act.handle(first, {"operation": "set_available_funds", "arguments": {"amount": 100}}))["ok"]
    out = run(act.handle(first, {"operation": "delete_transaction", "arguments": {"transaction_id": mine}}))
    assert out["error_code"] == "delete_needs_its_own_card" and len(first.proposals) == 1
    second = make_run()
    assert run(act.handle(second, {"operation": "manage_skill", "arguments": {"action": "delete", "skill_id": skill["id"]}}))["ok"]
    out = run(act.handle(second, {"operation": "set_available_funds", "arguments": {"amount": 100}}))
    assert out["error_code"] == "delete_needs_its_own_card" and len(second.proposals) == 1
    again = run(act.handle(second, {"operation": "manage_skill", "arguments": {"action": "delete", "skill_id": skill["id"]}}))
    assert again["ok"] and len(second.proposals) == 1                  # the same card asked for twice is one card


# --- skills ------------------------------------------------------------------------------------------------------

def make_skill(**fields):
    return skills.create_skill(OWNER_HASH, {"name": "周报", "description": "每周总结", "body": "先看持仓，再看新闻", "allowed_tools": ["query_portfolio"], **fields})


def test_enable_and_disable_cards_and_the_route_effect(owner):
    skill = make_skill()
    prepared = prepare("manage_skill", {"action": "disable", "skill_id": skill["id"]})
    assert prepared.display["title"] == "停用技能 · 周报" and "状态：已启用 → 已停用" in prepared.display["alternative"]
    assert skills.list_skills(OWNER_HASH)[0]["enabled"] is True                                  # a card writes nothing
    assert press(prepared)["ok"]
    routed = skills.set_enabled(OWNER_HASH, skill["id"], False)                                  # the route's call
    assert [s for s in skills.list_skills(OWNER_HASH) if s["name"] == "周报"][0]["enabled"] is False and routed["enabled"] is False
    again = prepare("manage_skill", {"action": "enable", "skill_id": skill["id"]})
    assert "状态：已停用 → 已启用" in again.display["alternative"]
    press(again)
    assert [s for s in skills.list_skills(OWNER_HASH) if s["name"] == "周报"][0]["enabled"] is True
    refused("manage_skill", {"action": "enable", "skill_id": skill["id"]}, "nothing_to_change")    # already so


def test_a_draft_skill_cannot_be_switched_here(owner):
    draft = skills.save(OWNER_HASH, {"name": "草稿", "description": "d", "body": "步骤", "allowed_tools": ["query_portfolio"]}, status="draft")
    refused("manage_skill", {"action": "enable", "skill_id": draft["id"]}, "skill_is_draft")


def test_edit_skill_card_shows_each_change_and_the_press_equals_the_route(owner):
    from app.agent_skills_api import SkillBody, update_skill_endpoint
    a, b = make_skill(name="周报甲"), make_skill(name="周报乙")
    arguments = {"action": "edit", "name": "新周报", "body": "只看新闻", "allowed_tools": ["web_research", "query_portfolio"], "output_template": "三行"}
    prepared = prepare("manage_skill", {**arguments, "skill_id": a["id"]})
    text = prepared.display["alternative"]
    for part in ("名称：周报甲 → 新周报", "步骤：先看持仓，再看新闻 → 只看新闻", "新增：web_research", "输出格式：无 → 三行", "版本 1 → 2"):
        assert part in text, part
    assert "去掉" not in text.split("允许的工具")[1].split("；")[0]
    assert press(prepared)["ok"]
    run(update_skill_endpoint(b["id"], SkillBody(name="新周报乙", body="只看新闻", allowed_tools=["web_research", "query_portfolio"], output_template="三行"), x_chat_session=OWNER))
    skip = {"id", "name", "updated_at"}
    got = {s["id"]: s for s in skills.list_skills(OWNER_HASH)}
    assert {k: v for k, v in got[a["id"]].items() if k not in skip} == {k: v for k, v in got[b["id"]].items() if k not in skip}
    assert got[a["id"]]["version"] == 2


def test_edit_skill_refusals_make_no_card(owner):
    skill = make_skill()
    make_skill(name="另一个")
    skills.seed_builtins()
    builtin = next(s for s in skills.list_skills(OWNER_HASH) if s["builtin"])
    refused("manage_skill", {"action": "edit", "skill_id": skill["id"], "name": "另一个"}, "name_taken")
    refused("manage_skill", {"action": "edit", "skill_id": skill["id"], "allowed_tools": ["no_such_tool"]}, "unknown_tool")
    refused("manage_skill", {"action": "edit", "skill_id": skill["id"], "body": "```python\nimport os\n```"}, "code_not_allowed")
    foreign = skills.create_skill(OTHER, {"name": "别人的", "description": "d", "body": "步骤", "allowed_tools": ["query_portfolio"]})
    for action in ("edit", "disable", "delete"):
        refused("manage_skill", {"action": action, "skill_id": foreign["id"], **({"body": "抢"} if action == "edit" else {})}, "skill_not_found")
    refused("manage_skill", {"action": "delete", "skill_id": "99999999-9999-4999-8999-999999999999"}, "skill_not_found")
    refused("manage_skill", {"action": "edit", "skill_id": builtin["id"], "body": "改"}, "skill_is_builtin")
    refused("manage_skill", {"action": "delete", "skill_id": builtin["id"]}, "skill_is_builtin")
    assert "状态：已启用 → 已停用" in prepare("manage_skill", {"action": "disable", "skill_id": builtin["id"]}).display["alternative"]     # a built-in can be switched


def test_delete_skill_says_it_cannot_be_undone_and_deletes(owner):
    skill = make_skill()
    prepared = prepare("manage_skill", {"action": "delete", "skill_id": skill["id"]})
    assert prepared.display["title"] == "删除技能 · 周报" and "不能撤销" in prepared.display["alternative"] and prepared.tier == 2
    assert len(skills.list_skills(OWNER_HASH)) >= 1 and any(s["id"] == skill["id"] for s in skills.list_skills(OWNER_HASH))
    assert press(prepared)["ok"]
    assert not any(s["id"] == skill["id"] for s in skills.list_skills(OWNER_HASH))
    refused("manage_skill", {"action": "delete", "skill_id": skill["id"]}, "skill_not_found")


def test_the_skill_lookup_lists_ids_and_state(owner):
    skill = make_skill()
    listed = run(act.handle(make_run(), {"operation": "manage_skill"}))["data"][0]["skills"]
    mine = next(s for s in listed if s["id"] == skill["id"])
    assert mine["name"] == "周报" and mine["enabled"] is True and mine["builtin"] is False


# --- default model and roles -----------------------------------------------------------------------------------------

def test_set_default_model_card_press_and_refusals(owner):
    entry("alpha")
    entry("beta")
    catalog.set_default("alpha")
    prepared = prepare("set_default_model", {"name": "beta"})
    text = prepared.display["alternative"]
    assert prepared.display["title"] == "设置默认对话模型 · Beta" and "默认对话模型：Alpha（vendor/alpha） → Beta（vendor/beta）" in text
    assert "没有单独选模型" in text
    assert catalog.entries()[1] == "alpha"
    assert press(prepared)["ok"]
    assert catalog.entries()[1] == "beta"
    refused("set_default_model", {"name": "ghost"}, "model_not_found")
    refused("set_default_model", {"name": "beta"}, "nothing_to_change")
    entry("nokey", key=False)
    assert "还没有配置密钥" in prepare("set_default_model", {"name": "nokey"}).display["alternative"]      # allowed by the route: warned, not hidden


def test_set_default_model_is_refused_when_the_file_decides(owner, monkeypatch):
    entry("alpha")
    monkeypatch.setattr(catalog, "_read_file", lambda: ([], "alpha", []))
    refused("set_default_model", {"name": "alpha"}, "default_from_file")


def test_set_default_model_equals_the_route(owner):
    from app.agent_bots_api import DefaultModelBody, default_model_endpoint
    entry("alpha")
    entry("beta")
    press(prepare("set_default_model", {"name": "beta"}))
    first = catalog.entries()[1]
    run(default_model_endpoint(DefaultModelBody(name="alpha"), x_chat_session=OWNER))
    assert (first, catalog.entries()[1]) == ("beta", "alpha")


def test_set_model_role_card_press_and_clearing(owner):
    entry("alpha")
    entry("beta")
    catalog.set_default("alpha")
    prepared = prepare("set_model_role", {"role": "earnings", "model": "beta"})
    assert prepared.display["title"] == "设置后台模型 · 财报判断"
    assert "财报判断用的模型：服务器默认模型（现为 Alpha） → Beta（vendor/beta）" in prepared.display["alternative"]
    assert roles.get(OWNER_HASH, "earnings") is None
    assert press(prepared)["ok"] and roles.get(OWNER_HASH, "earnings") == "beta"
    cleared = prepare("set_model_role", {"role": "earnings"})
    assert "Beta（vendor/beta） → 服务器默认模型（现为 Alpha）" in cleared.display["alternative"]
    press(cleared)
    assert roles.get(OWNER_HASH, "earnings") is None
    assert "备用模型用的模型：不设备用模型 → Beta（vendor/beta）" in prepare("set_model_role", {"role": "fallback", "model": "beta"}).display["alternative"]
    refused("set_model_role", {"role": "earnings", "model": "ghost"}, "unknown_model")
    refused("set_model_role", {"role": "earnings"}, "nothing_to_change")          # already unset


def test_set_model_role_equals_the_route(owner):
    from app.agent_bots_api import ModelRoleBody, set_model_role_endpoint
    entry("alpha")
    press(prepare("set_model_role", {"role": "judge", "model": "alpha"}))
    assert roles.get(OWNER_HASH, "judge") == "alpha"
    assert run(set_model_role_endpoint("forecast", ModelRoleBody(model="alpha"), x_chat_session=OWNER)) == {"role": "forecast", "model": "alpha"}


def test_the_model_lookups_carry_no_key(owner):
    entry("alpha")
    for name in ("set_default_model", "set_model_role"):
        info = run(act.handle(make_run(), {"operation": name}))["data"][0]
        assert [m["name"] for m in info["models"]] == ["alpha"] and info["models"][0]["key_set"] is True
        assert "sk-secret" not in json.dumps(info)


# --- channels --------------------------------------------------------------------------------------------------------

def test_set_channel_prefs_card_says_where_messages_go_from_now_on(owner, monkeypatch):
    monkeypatch.setattr(channels, "available", lambda db, owner_hash, name, bot: name == "telegram")
    prepared = prepare("set_channel_prefs", {"mode": "all", "channels": ["telegram", "wechat"]})
    text = prepared.display["alternative"]
    assert prepared.display["title"] == "设置主动消息的去向"
    assert "只发 Telegram → 同时发 Telegram 和微信" in text
    assert "盯盘提醒、例行简报、财报通知" in text
    assert "微信现在没有登录" in text and "Telegram 现在可用" in text
    first = prepare("set_channel_prefs", {"mode": "first", "channels": ["wechat", "telegram"]}).display["alternative"]
    assert "先发微信，发不出去再发 Telegram" in first
    only = prepare("set_channel_prefs", {"mode": "first", "channels": ["wechat"]}).display["alternative"]
    assert "只发微信" in only
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["telegram"], "mode": "first"}       # a card writes nothing


def test_set_channel_prefs_press_equals_the_route_and_refusals(owner):
    from app.agent_chat_stream import ChannelPrefsBody, set_channels_endpoint
    refused("set_channel_prefs", {"mode": "all", "channels": ["telegram", "telegram"]}, "invalid_channels")
    prepared = prepare("set_channel_prefs", {"mode": "all", "channels": ["wechat", "telegram"]})
    assert press(prepared)["ok"]
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["wechat", "telegram"], "mode": "all"}
    routed = run(set_channels_endpoint(ChannelPrefsBody(channels=["wechat", "telegram"], mode="all"), x_chat_session=OWNER))
    assert routed == {"channels": ["wechat", "telegram"], "mode": "all"}
    refused("set_channel_prefs", {"mode": "all", "channels": ["wechat", "telegram"]}, "nothing_to_change")


# --- the guest, and the other card paths -------------------------------------------------------------------------------

def test_a_guest_is_refused_everywhere_and_never_offered_the_operations(owner):
    for name in NEW:
        out = run(act.handle(make_run(credential="x" * 64), {"operation": name}))
        assert out["error_code"] == "owner_login_required", name
    from app.kernel import loop
    guest = [s["function"]["name"] for s in loop._tool_schemas(SimpleNamespace(identity_credential="x", tool_scope=None))]
    assert "act" not in guest
    from app.agent_workflow.grants import suggestion_operation
    valid = {"create_bot": {"name": "x"}, "update_bot": {"bot_id": SOURCE, "pinned": True}, "delete_transaction": {"transaction_id": SOURCE},
             "manage_skill": {"action": "delete", "skill_id": SOURCE}, "set_default_model": {"name": "x"}, "set_model_role": {"role": "judge"},
             "set_channel_prefs": {"mode": "all", "channels": ["telegram"]}}
    for name in NEW:
        validate(name, valid[name])
        with pytest.raises(ValueError, match="invalid_action_tool"):
            suggestion_operation(name, valid[name])                    # an agent's own suggestion never changes the owner's settings


def test_old_engine_has_no_way_to_grant_these_on_its_own_words():
    from app.agent_workflow import authorization
    for name in NEW:
        assert authorization.authorized(name, "把默认模型改成 beta，删掉那笔交易，修改机器人") is False


# --- the old engine is as it was before the branch ---------------------------------------------------------------------------

# Hashes taken from a build of 56ad1ad (the commit before 3a) by this same test body run under pytest there (the suite's own environment).
BEFORE_3A = {
    "write_catalogue": "6514c3bd015eff4b", "request_action": "f59753c07da427fec2373e8cf46ce52f", "owner_tools": "7d46be034456c459",
    "guest_tools": "d48a8773a6950809", "classifier_schema": "85e191bec3c40cf8", "categories": "afd78a6f6b43cbbf", "disclosure": "2d299a5460348da9",
    "instruction": "3038930f4b86d970", "write_names": "b65b77ae086295de",
}


