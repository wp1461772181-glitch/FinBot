"""Kernel ``act``: the operation directory, the lookup and the preparation of a card.  Nothing here touches a database."""
import asyncio
from types import SimpleNamespace

import pytest

from app import agent_profile as profile
from app import agent_tasks, portfolio
from app.agent_tool_catalog import definitions
from app.agent_workflow import direct, sec_sources
from app.kernel import act

NOT_IN_SLICE = {"ingest_web_source", "revise_forecast"}
UUID = "11111111-2222-3333-4444-555555555555"


def make_run(**extra):
    fields = {"identity_credential": "x" * 64, "owner_hash": "o", "conversation_id": "c", "bot_id": None, "bot_name": "", "tool_scope": None}
    fields.update({k: extra.pop(k) for k in ("bot_id", "bot_name") if k in extra})
    return SimpleNamespace(context=SimpleNamespace(**fields), **{"user_text": "", "question": "", "turn_id": "t", **extra})


def run(coro):
    return asyncio.run(coro)


def test_every_operation_is_a_catalogue_write_and_every_write_is_listed():
    policies = definitions()
    for name in act.OPERATIONS:
        assert policies[name].level in {"reversible", "costly"}, name
    writes = {n for n, p in policies.items() if p.level in {"reversible", "costly"}}
    assert writes - set(act.OPERATIONS) == NOT_IN_SLICE


def test_summaries_costs_and_tiers():
    assert all(act.SUMMARIES[name] for name in act.OPERATIONS) and set(act.SUMMARIES) == set(act.OPERATIONS)
    assert set(act.COST_NOTES) == set(act.TIER3)
    assert len(set(act.OPERATIONS)) == len(act.OPERATIONS) == 27
    assert [act.tier_of(n) for n in ("remember", "record_trade", "forecast")] == [1, 2, 3]
    assert act.TIER1[0] == "remember" and act.TIER3[-1] == "save_material_evidence"


def test_act_schema_lists_each_operation_under_its_heading():
    function = act.ACT_SCHEMA["function"]
    assert function["name"] == "act"
    assert function["parameters"]["required"] == ["operation"]
    assert tuple(function["parameters"]["properties"]["operation"]["enum"]) == act.OPERATIONS
    text = function["description"]
    assert text.startswith("所有会改数据的操作都从这里做。只带 operation 调用会返回它的参数格式；带上 arguments 才是真的提出操作。")
    headings = ["直接生效（可撤销）", "需要用户点确认卡", "需要用户点确认卡，并且花钱或不可撤销"]
    sections = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip().rstrip("：:")
        if stripped in headings:
            current = stripped
            sections[current] = []
        elif current and "：" in line:
            sections[current].append(line.split("：", 1)[0].strip())
    assert sections[headings[0]] == list(act.TIER1)
    assert sections[headings[1]] == list(act.TIER2)
    assert sections[headings[2]] == list(act.TIER3)
    for name in act.OPERATIONS:
        assert text.count(f"\n{name}：") == 1


def test_describe_returns_schema_tier_and_cost():
    info = act.describe("record_trade")
    assert info["tier"] == 2 and info["operation"] == "record_trade" and "cost" not in info
    assert info["arguments"] == definitions()["record_trade"].args_schema.model_json_schema()
    assert info["summary"] == act.SUMMARIES["record_trade"]
    assert act.describe("forecast")["cost"] == act.COST_NOTES["forecast"]


def test_invalid_arguments_return_the_schema_and_build_nothing(monkeypatch):
    monkeypatch.setattr(portfolio, "describe_write", lambda *a: pytest.fail("must not be reached"))
    out = run(act.prepare(make_run(), "record_trade", {"kind": "buy"}))
    assert isinstance(out, dict) and out["ok"] is False and out["error_code"] == "invalid_arguments"
    assert out["arguments"] == definitions()["record_trade"].args_schema.model_json_schema()
    out = run(act.prepare(make_run(), "record_trade", "not an object"))
    assert out["error_code"] == "invalid_arguments"
    assert run(act.prepare(make_run(), "delete_everything", {}))["error_code"] == "unknown_operation"


def test_record_trade_freezes_the_operation_and_uses_the_portfolio_card(monkeypatch):
    seen = []
    card = {"title": "记录买入 · AAPL", "targets": [{"symbol": "AAPL", "kind": "买入 1 股"}], "alternative": "可在持仓页删除。"}
    monkeypatch.setattr(portfolio, "describe_write", lambda owner, name, args: seen.append((owner, name, args)) or card)
    out = run(act.prepare(make_run(), "record_trade", {"kind": "buy", "symbol": "AAPL", "quantity": 1, "price": 10}))
    assert isinstance(out, act.Prepared) and out.tier == 2
    assert out.operation["name"] == "record_trade" and out.operation["arguments"]["symbol"] == "AAPL"
    assert set(out.operation) == {"name", "arguments"}
    assert out.display == card and seen[0][:2] == ("o", "record_trade")


def test_portfolio_error_returns_its_reason_and_no_card(monkeypatch):
    def refuse(owner, name, args):
        raise portfolio.PortfolioError("insufficient_shares")
    monkeypatch.setattr(portfolio, "describe_write", refuse)
    out = run(act.prepare(make_run(), "record_trade", {"kind": "sell", "symbol": "AAPL", "quantity": 1, "price": 10}))
    assert isinstance(out, dict) and out["error_code"] == "insufficient_shares"
    assert out["reason"] == portfolio.PortfolioError("insufficient_shares").reason


def test_create_routine_carries_the_bot(monkeypatch):
    args = {"name": "每日", "instruction": "看新闻", "schedule_kind": "daily", "schedule_time": "09:00", "symbols": ["NVDA", "AAPL"]}
    out = run(act.prepare(make_run(bot_id="bot-1"), "create_routine", args))
    assert out.operation["bot_id"] == "bot-1" and out.tier == 2
    assert out.display["title"] == "新建例行任务 · 每日"
    assert out.display["targets"][0]["symbol"] == "NVDA、AAPL"
    assert out.display["alternative"].startswith("每次运行：看新闻")


def test_remember_quotes_the_users_message_and_sets_bot_only_for_bot_scope(monkeypatch):
    monkeypatch.setattr(profile, "user_message_id", lambda conversation, turn: f"msg-{conversation}-{turn}")
    message = "以后回答都用中文，数字用万元"
    args = {"kind": "preference", "text": "用中文", "quote": "用中文", "scope": "global"}
    out = run(act.prepare(make_run(question=message, bot_id="b", bot_name="小助"), "remember", args))
    assert out.tier == 1 and out.operation["bot_id"] is None and out.operation["source_message_id"] == "msg-c-t"
    assert out.operation["arguments"]["quote"] == "用中文"
    assert out.display["title"] == "记住这条偏好" and out.display["targets"][0]["scope"].startswith("全局")
    stray = run(act.prepare(make_run(question=message, bot_id="b", bot_name="小助"), "remember", {**args, "quote": "模型自己编的话", "scope": "bot"}))
    assert stray.operation["arguments"]["quote"] == message and stray.display["targets"][0]["quote"] == message
    assert stray.operation["bot_id"] == "b" and "小助" in stray.display["targets"][0]["scope"]
    long = "字" * 300
    cut = run(act.prepare(make_run(question=long), "remember", {**args, "quote": "没有"}))
    assert cut.operation["arguments"]["quote"] == long[:profile.TEXT_MAX_CHARS]


def test_forecast_alternative_ends_with_the_cost_line():
    out = run(act.prepare(make_run(), "forecast", {"symbol": "AAPL"}))
    assert out.tier == 3 and out.display["title"] == "生成研究预测"
    assert out.display["alternative"].endswith("代价：" + act.COST_NOTES["forecast"])
    assert out.display["targets"] == [{"symbol": "AAPL"}]


def test_forget_with_an_unknown_handle(monkeypatch):
    monkeypatch.setattr(profile, "resolve_handle", lambda *a, **k: None)
    out = run(act.prepare(make_run(), "forget", {"item_id": "#abcdef12"}))
    assert out["error_code"] == "profile_item_not_found"
    monkeypatch.setattr(profile, "resolve_handle", lambda *a, **k: {"text": "用中文"})
    out = run(act.prepare(make_run(), "forget", {"item_id": "#abcdef12"}))
    assert out.tier == 1 and out.display["targets"] == [{"title": "用中文"}]


def test_routine_changes_and_deletes_need_an_existing_routine(monkeypatch):
    monkeypatch.setattr(agent_tasks, "get_task", lambda owner, task_id: None)
    assert run(act.prepare(make_run(), "update_routine", {"routine_id": UUID, "enabled": False}))["error_code"] == "routine_not_found"
    assert run(act.prepare(make_run(), "delete_routine", {"routine_id": UUID}))["error_code"] == "routine_not_found"
    task = {"name": "每日", "schedule_kind": "daily", "schedule_time": "09:00"}
    monkeypatch.setattr(agent_tasks, "get_task", lambda owner, task_id: task)
    out = run(act.prepare(make_run(), "update_routine", {"routine_id": UUID, "enabled": False}))
    assert out.display["title"] == "修改例行任务 · 每日" and out.display["alternative"] == "暂停"
    out = run(act.prepare(make_run(), "delete_routine", {"routine_id": UUID}))
    assert out.display["alternative"] == "删除后不再运行；已生成的简报会保留。"


def test_fetch_sec_uses_the_prepared_filing(monkeypatch):
    prepared = {"name": "fetch_sec", "arguments": {"symbol": "AAPL", "accession_number": "A-1"},
                "discovery": {"form": "10-K", "filed_at": "2026-01-02", "source_url": "https://sec.gov/x"}}
    calls = []
    monkeypatch.setattr(sec_sources, "prepare_filing", lambda name, args, financial_only=False: calls.append(financial_only) or prepared)
    out = run(act.prepare(make_run(), "fetch_sec", {"symbol": "AAPL"}))
    assert out.operation == prepared and calls == [False]
    assert out.display["title"] == "确认登记并拉取 SEC 官方原文"
    assert out.display["targets"][0]["title"] == "AAPL 10-K" and out.display["alternative"].endswith(act.COST_NOTES["fetch_sec"])

    def refuse(name, args, financial_only=False):
        raise ValueError("sec_filing_not_found")
    monkeypatch.setattr(sec_sources, "prepare_filing", refuse)
    assert run(act.prepare(make_run(), "fetch_sec", {"symbol": "AAPL"}))["error_code"] == "sec_filing_not_found"


def test_review_filing_names_the_document(monkeypatch):
    monkeypatch.setattr(direct, "source_display_title", lambda kind, source_id: "Apple 10-K")
    out = run(act.prepare(make_run(), "review_filing", {"source_id": UUID, "decision": "rejected"}))
    assert out.tier == 2
    assert out.display["targets"] == [{"title": "Apple 10-K", "source_type": "SEC 申报", "decision": "标记为不相关"}]
