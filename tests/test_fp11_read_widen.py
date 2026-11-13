"""FP11 step 2, read widening (brief-fp11s2, 方案 §FP11 第二步).

With ``FINBOT_FP11_READ_WIDEN`` on, a read the entity gate would refuse goes ahead and is recorded in
``audit['entity_gate_widened']``, in the same shape as step 1's ``entity_gate_blocks``.  With it off (the default),
step 1's behaviour is unchanged.  Writes and the three ID refusals in ``ground_arguments`` are the same either way.
"""
import pytest

from test_agent_scope_phase1 import _context, _run, _step, _turn_about, owner  # noqa: F401  (fixture)

WIDEN = "FINBOT_FP11_READ_WIDEN"
MSFT_PRICE = {"symbol": "MSFT", "title": "MSFT 收盘价", "excerpt": "MSFT closed at 400 dollars.", "close": 400}


def test_with_the_switch_on_a_read_refused_for_another_company_runs_and_is_recorded(monkeypatch):
    monkeypatch.setenv(WIDEN, "on")
    context, ran, replies, _ = _context(classified={"symbol": "AAPL"},
                                        steps=[_step("query_stock_prices", symbol="MSFT"), {"content": "MSFT 收盘价 400 美元 [1]。"}],
                                        rows={"query_stock_prices": [MSFT_PRICE]})
    result = _run("AAPL 的股价", context)
    assert [name for name, _ in ran] == ["query_stock_prices"] and ran[0][1]["symbol"] == "MSFT"
    assert result["audit"]["entity_gate_widened"] == [{"tool": "query_stock_prices", "asked": "MSFT", "scope_symbol": "AAPL"}]
    assert "entity_gate_blocks" not in result["audit"]
    assert [citation.get("symbol") for citation in result["citations"]] == ["MSFT"]


def test_with_the_switch_on_a_write_aimed_at_another_company_is_still_refused_and_not_widened(monkeypatch):
    monkeypatch.setenv(WIDEN, "on")
    turn = _turn_about("初始化行情")
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("initialize_prices", {"symbol": "MSFT"})
    assert "entity_gate_widened" not in turn.audit and turn.audit.get("entity_gate_blocks", []) == []


def test_with_the_switch_on_an_untrusted_source_id_is_still_refused_and_not_widened(monkeypatch):
    monkeypatch.setenv(WIDEN, "on")
    turn = _turn_about("AAPL 的竞争对手")
    with pytest.raises(ValueError, match="scope_not_grounded"):
        turn.ground_arguments("query_stock_prices", {"symbol": "MSFT", "source_id": "SRC-NOT-IN-TEXT"})
    assert "entity_gate_widened" not in turn.audit and turn.audit.get("entity_gate_blocks", []) == []


@pytest.mark.parametrize("setting", [None, "off"], ids=["unset", "off"])
def test_with_the_switch_off_or_unset_the_read_is_refused_as_in_step_one(monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv(WIDEN, raising=False)
    else:
        monkeypatch.setenv(WIDEN, setting)
    context, ran, replies, _ = _context(classified={"symbol": "AAPL"},
                                        steps=[_step("query_stock_prices", symbol="MSFT"), {"content": "没有可核验资料。"}],
                                        rows={"query_stock_prices": [MSFT_PRICE]})
    result = _run("AAPL 的股价", context)
    assert ran == [] and "scope_not_grounded" in " ".join(replies)
    assert result["audit"]["entity_gate_blocks"] == [{"tool": "query_stock_prices", "asked": "MSFT", "scope_symbol": "AAPL"}]
    assert "entity_gate_widened" not in result["audit"]


def test_with_the_switch_on_the_widened_list_keeps_the_first_twenty_and_stops_there(monkeypatch):
    monkeypatch.setenv(WIDEN, "on")
    turn = _turn_about("AAPL 的竞争对手")
    for _ in range(25):
        turn.ground_arguments("query_stock_prices", {"symbol": "MSFT"})
    assert len(turn.audit["entity_gate_widened"]) == 20
    assert "entity_gate_blocks" not in turn.audit
