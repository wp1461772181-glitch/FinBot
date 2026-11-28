"""11-28 三处小修：工具参数出错时写明错在哪；早间简报不重复标题；持仓工具写明币种。"""
import asyncio
from types import SimpleNamespace

import pytest

from app.agent_workflow import tools
from app.kernel import brief


# --- 1. an argument error names the argument and the ones the tool takes ---------------------------------------------------------

def test_an_argument_the_tool_does_not_have_is_named_with_the_ones_it_takes(monkeypatch):
    """11-27 duty turn: ``days_back`` (web_research's) sent to search_configured_news came back as a bare invalid_arguments."""
    context = SimpleNamespace(tool_scope=None, identity_credential="")
    result = asyncio.run(tools.invoke("search_configured_news", {"tickers": ["ANT"], "days_back": 2}, context))
    assert result["ok"] is False and result["error_code"] == "invalid_arguments"
    assert result["problems"] == [{"argument": "days_back", "problem": "这个工具没有这个参数"}]
    assert "tickers" in result["accepted_arguments"] and "since" in result["accepted_arguments"]
    assert "accepted_arguments" in result["hint"]


def test_a_missing_required_argument_is_named_and_marked_required():
    context = SimpleNamespace(tool_scope=None, identity_credential="")
    result = asyncio.run(tools.invoke("query_stock_prices", {}, context))
    assert {"argument": "symbol", "problem": "缺少这个必填参数"} in result["problems"]
    assert "symbol（必填）" in result["accepted_arguments"]


def test_a_kernel_calculation_with_bad_arguments_says_what_was_wrong():
    from app.kernel import toolrun
    checked = toolrun._valid_arguments("calculate", {"expression": "1+1", "nonsense": True})
    assert isinstance(checked, Exception)
    error = tools.argument_error("calculate", checked)
    assert any(p["argument"] == "nonsense" for p in error["problems"])


# --- 2. the brief's own title line --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("written", ["早间简报\n\n先说最要紧的：ANT。", "**早间简报（2026-11-26）**\n先说最要紧的：ANT。",
                                     "# 早间简报\n先说最要紧的：ANT。", "早间简报：\n先说最要紧的：ANT。", "【早间简报】2026-11-28\n先说最要紧的：ANT。"])
def test_a_title_line_the_model_wrote_is_dropped(written):
    assert brief.without_own_title(written) == "先说最要紧的：ANT。"


@pytest.mark.parametrize("written", ["先说最要紧的：早间简报里提到的 ANT。", "早间简报之外还有一件事：ANT 收涨 11%。"])
def test_a_body_that_only_mentions_the_brief_is_left_alone(written):
    assert brief.without_own_title(written) == written


# --- 3. the portfolio tool says its amounts are US dollars ---------------------------------------------------------------------

def test_the_portfolio_rows_say_us_dollars():
    from app import portfolio
    summary = {"available_funds": "8888.00", "positions_value": "35854.00", "total_assets": "44742.00", "floating_pnl": "11290.00",
               "today_pnl": "296.00", "today_pnl_reference_only": False, "realized_pnl": "0.00", "price_date": "2026-11-27", "warnings": [],
               "positions": [{"symbol": "AAPL", "shares": "100", "avg_cost": "245.6400", "diluted_cost": "245.6400", "cost": "24564.00",
                              "price": "358.5400", "price_date": "2026-11-27", "market_value": "35854.00", "floating_pnl": "11290.00",
                              "floating_pnl_pct": "45.96", "today_pnl": "296.00", "today_pnl_reference_only": False, "weight_pct": "80.13",
                              "realized_pnl": "0.00", "plan": {}}]}
    account, aapl = portfolio.evidence_rows(summary)
    assert account["excerpt"].startswith("金额单位：美元") and account["currency"] == "USD"
    assert "（金额单位：美元）" in aapl["excerpt"] and aapl["currency"] == "USD"


def test_the_write_operations_say_the_ledger_is_in_us_dollars():
    from app.agent_tool_catalog import definitions
    funds = definitions()["set_available_funds"].args_schema.model_json_schema()["properties"]["amount"]["description"]
    price = definitions()["record_trade"].args_schema.model_json_schema()["properties"]["price"]["description"]
    assert "US dollars" in funds and "US dollars" in price
