"""FP11 step 1, shadow counting (brief-fp11, 方案 §FP11 第一步).

A read refused only because its code is not the one the classifier fixed is counted in ``audit['entity_gate_blocks']``;
a read the same gate lets through is counted in ``audit['entity_gate_passes']``.  Nothing else changes: the refusal, its
code and what the model is told are as before.  The three ID refusals in ``ground_arguments`` share the code
``scope_not_grounded`` with this one; they must not be counted, which is what these tests pin down.
"""
import pytest

from test_agent_scope_phase1 import (AAPL_TURN, AFTER_AAPL, HOLDING_READS, INTC_FORECAST, INTC_HOLDING, _context, _observed,
                                     _portfolio_then_forecast, _rewrite, _run, _step, _turn_about, owner)  # noqa: F401  (fixture)


def test_a_read_refused_for_another_company_is_still_refused_and_counted():
    context, ran, replies, _ = _context(classified={"symbol": "AAPL"},
                                        steps=[_step("query_stock_prices", symbol="MSFT"), {"content": "没有可核验资料。"}])
    result = _run("AAPL 的股价", context)
    assert ran == [] and "scope_not_grounded" in " ".join(replies)
    assert result["audit"]["entity_gate_blocks"] == [{"tool": "query_stock_prices", "asked": "MSFT", "scope_symbol": "AAPL"}]


def test_a_write_aimed_at_another_company_is_still_refused_and_not_counted():
    turn = _turn_about("初始化行情")
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("initialize_prices", {"symbol": "MSFT"})
    assert turn.audit.get("entity_gate_blocks", []) == [] and "entity_gate_passes" not in turn.audit


def test_an_untrusted_source_id_is_refused_by_its_own_check_and_not_counted():
    turn = _turn_about("AAPL 的竞争对手")
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "MSFT"})
    assert len(turn.audit["entity_gate_blocks"]) == 1
    # The same read of MSFT with an ID the turn never saw: refused, and the count does not move.
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "MSFT", "source_id": "SRC-NOT-IN-TEXT"})
    assert len(turn.audit["entity_gate_blocks"]) == 1


def test_a_read_the_gate_lets_through_is_counted_as_a_pass():
    context, ran, replies, _ = _context(steps=_portfolio_then_forecast(), resolver=_rewrite("followup", "我的持仓今天怎么样"),
                                        rows={"query_portfolio": [INTC_HOLDING], "query_latest_forecast": [INTC_FORECAST]})
    result = _run("我的持仓今天怎么样", context, messages=AAPL_TURN, state=AFTER_AAPL)
    assert ran == HOLDING_READS
    assert result["audit"]["entity_gate_passes"] == 1 and "entity_gate_blocks" not in result["audit"]
    # The other pass: the classifier named AAPL, and the owner's holdings show the code that is read.
    turn = _turn_about("AAPL 和我的持仓比怎么样")
    turn.observations.append(_observed("query_portfolio", INTC_HOLDING))
    turn.ground_arguments("query_latest_forecast", {"symbol": "INTC"})
    assert turn.audit["entity_gate_passes"] == 1


def test_the_refusal_list_keeps_the_first_twenty_and_stops_there():
    turn = _turn_about("AAPL 的竞争对手")
    for _ in range(25):
        with pytest.raises(ValueError, match="scope_not_grounded"):
            turn.ground_arguments("query_stock_prices", {"symbol": "MSFT"})
    assert len(turn.audit["entity_gate_blocks"]) == 20
