"""Kernel ``act``: the operation directory, the lookup and the preparation of a card.  Nothing here touches a database."""
import asyncio
from types import SimpleNamespace

import pytest

from app import agent_profile as profile
from app import agent_tasks, portfolio
from app.agent_tool_catalog import definitions
from app.agent_workflow import direct, sec_sources, workspace_tools
from app.kernel import act

NOT_IN_SLICE = set()      # every catalogue write is in the directory now
UUID = "11111111-2222-3333-4444-555555555555"


def make_run(**extra):
    fields = {"identity_credential": "x" * 64, "owner_hash": "o", "conversation_id": "c", "bot_id": None, "bot_name": "", "tool_scope": None,
              "default_company": None, "watchlist": ()}
    fields.update({k: extra.pop(k) for k in ("bot_id", "bot_name", "default_company", "watchlist") if k in extra})
    return SimpleNamespace(context=SimpleNamespace(**fields), **{"user_text": "", "question": "", "turn_id": "t", "web_rows": {}, "citations": [],
                                                                  "proposals": [], "question_card": None, "carried_sets": [], **extra})


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
    assert len(set(act.OPERATIONS)) == len(act.OPERATIONS) == 29
    assert [act.tier_of(n) for n in ("remember", "record_trade", "forecast", "ingest_web_source", "revise_forecast")] == [1, 2, 3, 3, 3]
    assert act.TIER1[0] == "remember" and act.TIER3[-2:] == ("ingest_web_source", "revise_forecast")
    assert act.SUMMARIES["ingest_web_source"] == "把这一轮搜到的一个网页存进资料库"
    assert act.SUMMARIES["revise_forecast"] == "用新材料修订一份已存的预测（材料由用户在卡片上勾选）"
    assert act.COST_NOTES["ingest_web_source"] == "会把这个网页存入资料库和知识库。"
    assert act.COST_NOTES["revise_forecast"] == "会调用付费模型重新计算这份预测，生成新版本，旧版本保留。"


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


# --- the fix round: card targets, the contract with the handlers, error detail ---------------------------------

from app.agent_tool_catalog import validate

U = "aaaaaaaa-1111-2222-3333-444444444444"
PAGE_URL = "https://news.example.com/aapl-q1"
PAGE = {"url": PAGE_URL, "title": "苹果一季度财报解读", "excerpt": "Revenue grew 8 percent.", "published_at": "2026-01-05T00:00:00+00:00",
        "fetched_at": "2026-01-06T00:00:00+00:00", "body_provenance": "page", "truncated": False}
VERSION = "99999999-2222-3333-4444-555555555555"
MINIMAL = {
    "remember": {"kind": "preference", "text": "用中文", "quote": "用中文"},
    "forget": {"item_id": "#abcdef12"},
    "add_to_research_queue": {"symbol": "AAPL"}, "remove_from_research_queue": {"symbol": "AAPL"},
    "record_trade": {"kind": "buy", "symbol": "AAPL", "quantity": 1, "price": 10},
    "set_available_funds": {"amount": 100},
    "set_position_plan": {"symbol": "AAPL", "plan_text": "持有"},
    "create_routine": {"name": "每日", "instruction": "看新闻", "schedule_kind": "daily"},
    "update_routine": {"routine_id": UUID, "enabled": False}, "delete_routine": {"routine_id": UUID},
    "save_skill": {"name": "s", "description": "d", "body": "b", "allowed_tools": ["calculate"]},
    "review_filing": {"source_id": UUID, "decision": "accepted"},
    "forecast": {"symbol": "AAPL"}, "analyze": {"symbol": "AAPL", "source_id": UUID},
    "translate_content": {"kind": "analysis", "record_id": UUID},
    "start_historical_replay": None,
    "fetch_sec": {"symbol": "AAPL"}, "refresh_sec": {"symbol": "AAPL"}, "scan_official": {"symbol": "AAPL"},
    "initialize_prices": None, "import": {"symbol": "AAPL", "source_id": UUID},
    "import_sources": {"source_type": "faq", "source_ids": [UUID, U]}, "index": {},
    "retry_document_index": {"document_id": UUID},
    "review_knowledge_candidate": {"candidate_id": UUID, "approved": True},
    "withdraw_knowledge_document": {"document_id": UUID},
    "save_material_evidence": {"symbol": "AAPL", "title": "t", "source_url": "https://x.com/a", "published_at": "2026-01-01", "content": "c"},
    "ingest_web_source": {"url": PAGE_URL, "symbol": "AAPL"}, "revise_forecast": {"symbol": "AAPL"},
}


def _minimal(name):
    """Minimal valid arguments, found from the catalogue's own schema for the few that need dates or counts."""
    given = MINIMAL[name]
    if given is not None:
        return given
    required = definitions()[name].args_schema.model_json_schema().get("required", [])
    fill = {"symbol": "AAPL", "decision_date": "2026-01-02", "days": 30}
    return {key: fill[key] for key in required}


def ready_plan(count=5):
    return {"status": "ready", "symbol": "AAPL", "version_id": VERSION, "version_no": 2, "decision_at": "2026-01-02T15:00:00+00:00",
            "window_start": "2025-12-03T15:00:00+00:00", "window_end": "2026-01-09T15:00:00+00:00", "target_end_date": "2026-02-01",
            "candidates": [{"source_type": "uploaded_media", "source_id": f"{i:08d}-2222-3333-4444-555555555555", "title": f"材料{i}", "kind": "上传材料",
                            "published_at": f"2026-01-0{i}T00:00:00+00:00", "category": "after", "badge": "预测后发布"} for i in range(1, count + 1)],
            "excluded": [], "mentioned": []}


@pytest.fixture
def faked(monkeypatch):
    monkeypatch.setattr(act, "_already_saved", lambda *a: None)
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: ready_plan())
    monkeypatch.setattr(profile, "user_message_id", lambda *a: "m1")
    monkeypatch.setattr(profile, "resolve_handle", lambda *a, **k: {"text": "用中文"})
    monkeypatch.setattr(agent_tasks, "get_task", lambda *a: {"name": "每日", "schedule_kind": "daily", "schedule_time": "09:00"})
    monkeypatch.setattr(direct, "source_display_title", lambda *a: "某材料")
    monkeypatch.setattr(portfolio, "describe_write", lambda *a: {"title": "t", "targets": [{"symbol": "AAPL"}], "alternative": "a"})
    monkeypatch.setattr(sec_sources, "prepare_filing", lambda name, args, financial_only=False: {
        "name": name, "arguments": {**args, "accession_number": "0000320193-26-000001"},
        "discovery": {"form": "10-K", "filed_at": "2026-01-02", "source_url": "https://sec.gov/x"}})


@pytest.mark.parametrize("name", act.OPERATIONS)
def test_every_prepared_operation_still_passes_its_handler_validation(name, faked):
    out = run(act.prepare(make_run(question="用中文回答", web_rows={PAGE_URL: PAGE}), name, _minimal(name)))
    assert isinstance(out, act.Prepared), out
    assert validate(name, out.operation["arguments"])
    assert all(any(row.values()) for row in out.display["targets"]), "an empty target row"


def test_the_fallback_quote_is_a_valid_remember_quote(faked):
    from app.agent_tool_catalog import RememberArgs
    message = "字" * 300
    out = run(act.prepare(make_run(question=message), "remember", {**MINIMAL["remember"], "quote": "不在其中"}))
    quote = out.operation["arguments"]["quote"]
    RememberArgs.model_validate(out.operation["arguments"])
    assert profile.quote_in_message(quote, message)


def test_fetch_sec_keeps_the_discovery_for_the_handler(faked):
    out = run(act.prepare(make_run(), "fetch_sec", {"symbol": "AAPL"}))
    assert out.operation["discovery"]["form"] == "10-K"


@pytest.mark.parametrize("name,args,words", [
    ("withdraw_knowledge_document", {"document_id": UUID}, ["知识文档 11111111"]),
    ("retry_document_index", {"document_id": UUID}, ["知识文档 11111111"]),
    ("translate_content", {"kind": "forecast", "record_id": UUID}, ["预测简报 11111111"]),
    ("review_knowledge_candidate", {"candidate_id": UUID, "approved": False}, ["知识候选 11111111", "拒绝"]),
    ("review_knowledge_candidate", {"candidate_id": UUID, "approved": True}, ["通过"]),
    ("import_sources", {"source_type": "sec", "source_ids": [UUID, U, U]}, ["3 份SEC 申报"]),
])
def test_record_operations_name_their_target(name, args, words, faked):
    row = run(act.prepare(make_run(), name, args)).display["targets"][0]
    shown = " ".join(str(v) for v in row.values())
    assert all(word in shown for word in words), row
    assert "symbol" not in row


def test_an_operation_with_nothing_to_show_has_no_target_rows(faked):
    out = run(act.prepare(make_run(), "set_available_funds", {"amount": 1}))   # describe_write replaces the rows; check the base path below
    assert out.display["targets"]
    assert asyncio.run(act._targets("start_historical_replay", {})) == []


def test_unknown_operation_hint_and_invalid_argument_problems():
    out = run(act.prepare(make_run(), "nope", {}))
    assert "目录" in out["hint"]
    out = run(act.prepare(make_run(), "record_trade", {"kind": "buy", "symbol": "SECRET-VALUE-123456"}))
    assert out["error_code"] == "invalid_arguments" and out["arguments"]
    assert any(line.startswith("symbol") for line in out["problems"])
    assert "SECRET-VALUE" not in " ".join(out["problems"])
    assert run(act.prepare(make_run(), "record_trade", "x"))["problems"]


# --- ingest_web_source ------------------------------------------------------------------------------------------

@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(act, "_already_saved", lambda *a: None)


def ingest(run_, **args):
    return run(act.prepare(run_, "ingest_web_source", {"url": PAGE_URL, **args}))


def test_ingest_of_a_page_no_read_returned_is_refused_and_makes_no_card(web):
    out = ingest(make_run(web_rows={"https://other.example.com/x": PAGE}), symbol="AAPL")
    assert isinstance(out, dict) and out["error_code"] == "web_source_not_returned"
    assert ingest(make_run(), symbol="AAPL")["error_code"] == "web_source_not_returned"


def test_ingest_card_shows_title_url_date_destination_and_cost(web):
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}), symbol="AAPL", company="Apple")
    assert isinstance(out, act.Prepared) and out.tier == 3 and out.options is None
    shown = out.display
    assert shown["title"] == "保存网页" and shown["url"] == PAGE_URL and shown["web_date"] == PAGE["published_at"]
    assert shown["targets"][0]["title"] == PAGE["title"]
    assert shown["alternative"] == "存入 资料库 · AAPL ＋ 知识库检索。也可抓取最新 SEC 官方文件。\n代价：会把这个网页存入资料库和知识库。"
    operation = out.operation
    assert operation["name"] == "ingest_web_source" and operation["arguments"]["symbol"] == "AAPL" and operation["arguments"]["company"] == "Apple"
    assert operation["snapshot"]["content_hash"] and operation["snapshot"]["url"] == PAGE_URL
    assert operation["published_at"] == PAGE["published_at"] and operation["entity_aliases"] == []


def test_ingest_knowledge_only_says_so_and_needs_no_symbol(web):
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}), knowledge_only=True)
    assert out.display["alternative"].startswith("只存知识库检索，不进资料库。也可抓取最新 SEC 官方文件。")


def test_ingest_symbol_comes_from_the_argument_then_the_bots_company(web):
    run_ = make_run(web_rows={PAGE_URL: PAGE}, default_company={"symbol": "MSFT", "company": "Microsoft"})
    out = ingest(run_)
    assert out.operation["arguments"]["symbol"] == "MSFT" and out.operation["arguments"]["company"] == "Microsoft"
    assert "资料库 · MSFT" in out.display["alternative"]
    assert ingest(run_, symbol="NVDA").operation["arguments"]["symbol"] == "NVDA"


def test_ingest_with_no_symbol_gets_the_old_refusal_with_candidates(web):
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}, watchlist=("AAPL", "NVDA", "AAPL")))
    assert out["error_code"] == "library_symbol_required" and out["candidates"] == ["AAPL", "NVDA"]
    assert out["question"] == "存到哪只股票的资料库？" and "knowledge_only=true" in out["hint"] and "ask_user" not in out["hint"]
    assert ingest(make_run(web_rows={PAGE_URL: PAGE}))["candidates"] == []


def test_ingest_of_an_already_saved_page_makes_no_card(monkeypatch):
    seen = []
    monkeypatch.setattr(act, "_already_saved", lambda owner, url, content_hash, knowledge_only: seen.append((owner, url, knowledge_only)) or "src-1")
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}), symbol="AAPL")
    assert out == {"ok": True, "data": [{"status": "already_exists", "source_id": "src-1"}]} and seen == [("o", PAGE_URL, False)]


def test_ingest_newer_than_compares_with_the_kernels_citations(web):
    citations = [{"ordinal": 1, "source_type": "official_filing", "published_at": "2026-01-01T00:00:00+00:00"},
                 {"ordinal": 2, "source_type": "web", "published_at": "2025-01-01T00:00:00+00:00"}]
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}, citations=citations), symbol="AAPL", newer_than=1)
    assert out.operation["condition"] == {"kind": "newer_than_saved", "saved_date": "2026-01-01T00:00:00+00:00"}
    assert out.display["saved_date"] == "2026-01-01T00:00:00+00:00"
    older = [{**citations[0], "published_at": "2026-02-01T00:00:00+00:00"}]
    out = ingest(make_run(web_rows={PAGE_URL: PAGE}, citations=older), symbol="AAPL", newer_than=1)
    assert out["data"][0]["status"] == "not_newer"
    assert ingest(make_run(web_rows={PAGE_URL: PAGE}, citations=citations), symbol="AAPL", newer_than=2)["error_code"] == "comparison_date_unavailable"
    undated = {**PAGE, "published_at": None}
    assert ingest(make_run(web_rows={PAGE_URL: undated}, citations=citations), symbol="AAPL", newer_than=1)["error_code"] == "comparison_date_unavailable"


def test_ingest_of_a_page_that_cannot_be_frozen_is_a_refusal(web):
    out = ingest(make_run(web_rows={PAGE_URL: {**PAGE, "excerpt": ""}}), symbol="AAPL")
    assert out["error_code"] == "web_snapshot_unavailable"


# --- revise_forecast --------------------------------------------------------------------------------------------

def revise(run_=None, **args):
    return run(act.prepare(run_ or make_run(), "revise_forecast", args))


def test_a_ready_revision_is_a_proposal_with_options_and_the_frozen_candidates(monkeypatch):
    seen = []
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: seen.append(a) or ready_plan(12))
    run_ = make_run()
    out = revise(run_, symbol="AAPL", mentioned_sources=[{"source_type": "uploaded_media", "source_id": U}])
    assert seen[0][0] == "AAPL" and seen[0][1] is None and seen[0][2] is run_.context and seen[0][3] == [{"source_type": "uploaded_media", "source_id": U}]
    assert out.tier == 3 and len(out.options) == direct.REVISION_CARD_LIMIT == 10
    assert out.options[0] == {"value": "1", "label": "材料1", "detail": "上传材料 · 2026-01-01 发布 · 预测后发布"}
    assert [o["value"] for o in out.options] == [str(i) for i in range(1, 11)]
    operation = out.operation
    assert set(operation) == {"name", "arguments", "revision", "candidates"} and operation["name"] == "revise_forecast"
    assert operation["arguments"] == {"symbol": "AAPL", "version_id": VERSION}
    assert operation["revision"] == {"version_no": 2, "decision_at": "2026-01-02T15:00:00+00:00",
                                     "window_start": "2025-12-03T15:00:00+00:00", "window_end": "2026-01-09T15:00:00+00:00"}
    assert len(operation["candidates"]) == 10 and set(operation["candidates"][0]) == {"source_type", "source_id", "title", "kind", "published_at", "category"}
    assert out.display["title"] == "修正 AAPL 的预测（v2，2026-01-02 作出）"
    assert "共 12 份，这里列出最新的 10 份" in out.display["alternative"]


def test_a_revision_that_is_not_ready_says_why_and_makes_no_card(monkeypatch):
    plan = {"status": "target_expired", "symbol": "AAPL", "version_no": 2, "decision_at": "2026-01-02T15:00:00+00:00", "target_end_date": "2026-01-20"}
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: plan)
    out = revise(symbol="AAPL")
    assert isinstance(out, dict) and out["ok"] is False and out["error_code"] == "target_expired"
    assert out["reason"] == direct.revision_notice(plan) and "不能再修订" in out["reason"]


def test_a_revision_names_its_symbol_and_the_model_cannot_name_materials(monkeypatch):
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: pytest.fail("no plan is made for invalid arguments"))
    assert revise(make_run())["error_code"] == "invalid_arguments"
    assert revise(make_run(), symbol="AAPL", source_refs=[{"source_type": "uploaded_media", "source_id": U}])["error_code"] == "invalid_arguments"


def test_a_revision_never_shares_a_card(monkeypatch):
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: pytest.fail("no plan is made for a call that cannot have a card"))
    sharing = make_run(proposals=[act.Prepared({"name": "forecast", "arguments": {}}, {"title": "t"}, 3)])
    assert revise(sharing, symbol="AAPL")["error_code"] == "revision_needs_its_own_card"
    asked = make_run(question_card={"id": "q"})
    assert revise(asked, symbol="AAPL")["error_code"] == "one_card_per_turn"


def test_a_proposal_after_a_revision_is_refused(monkeypatch):
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: ready_plan())
    run_ = make_run()
    first = act._collect(run_, revise(run_, symbol="AAPL"))
    assert first[1] == "proposed"
    result, outcome = act._collect(run_, run(act.prepare(run_, "forecast", {"symbol": "NVDA"})))
    assert result["error_code"] == "revision_needs_its_own_card" and outcome == "refused:revision_needs_its_own_card"
    assert len(run_.proposals) == 1


# --- the fix wave ------------------------------------------------------------------------------------------------------------

def test_a_page_an_earlier_turns_read_returned_can_be_saved(web):
    earlier = [{"id": "a", "tool": "web_research", "rows": [{**PAGE, "title": "旧的"}]}, {"id": "b", "tool": "search_configured_news", "rows": [PAGE]},
               {"id": "c", "tool": "search_x", "rows": [{**PAGE, "url": "https://x.com/u/1"}]}]
    out = ingest(make_run(carried_sets=earlier), symbol="AAPL")
    assert isinstance(out, act.Prepared) and out.display["targets"][0]["title"] == PAGE["title"]       # the newest set wins
    assert ingest(make_run(carried_sets=earlier), symbol="AAPL", url="https://x.com/u/1")["error_code"] == "web_source_not_returned"
    this_turn = {**PAGE, "excerpt": "This turn's text."}
    out = ingest(make_run(web_rows={PAGE_URL: this_turn}, carried_sets=earlier), symbol="AAPL")
    assert out.operation["snapshot"]["excerpt"] == "This turn's text."


def test_an_unreturned_page_is_refused_before_the_symbol_is_asked_for(web):
    assert ingest(make_run())["error_code"] == "web_source_not_returned"


def test_the_card_headline_is_fixed_and_the_page_title_is_one_capped_line(web):
    nasty = {**PAGE, "title": "第一行\n第二行\t" + "长" * 300}
    out = ingest(make_run(web_rows={PAGE_URL: nasty}), symbol="AAPL")
    assert out.display["title"] == "保存网页"
    shown = out.display["targets"][0]["title"]
    assert "\n" not in shown and "\t" not in shown and shown.startswith("第一行 第二行 长") and len(shown) <= 100
    assert out.operation["snapshot"]["title"] == nasty["title"]            # what is saved is the stored row, untouched
    untitled = ingest(make_run(web_rows={PAGE_URL: {**PAGE, "title": None}}), symbol="AAPL")
    assert untitled.display["targets"][0]["title"] == PAGE_URL


def test_a_repeated_revision_call_gets_the_first_calls_answer(monkeypatch):
    monkeypatch.setattr(workspace_tools, "revision_plan", lambda *a: ready_plan())
    run_ = make_run()
    first = run(act.prepare(run_, "revise_forecast", {"symbol": "AAPL"}))
    assert act._collect(run_, first)[1] == "proposed"
    again = run(act.prepare(run_, "revise_forecast", {"symbol": "AAPL"}))
    assert again == {"ok": True, "data": [{"status": "awaiting_selection", "candidates": 5, "note": act.REVISION_NOTE}]}
    assert run(act.prepare(run_, "revise_forecast", {"symbol": "NVDA"}))["error_code"] == "revision_needs_its_own_card"
