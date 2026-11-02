"""财报阅读器（计划 Task 8）：涨跌口径、σ、compare 的 Intel 数字、extract 的逐字核对、judge 的 quote 核对。"""
import asyncio
import json
from datetime import date, timedelta

import pytest

from app import earnings_reader as er

INTC_RELEASE = """Intel Reports Third-Quarter 2026 Financial Results
Third-quarter revenue was $16.5 billion, up 21% year-over-year (YoY).
Gross margin 43.0% 38.2% up 4.8 ppts 44.1% 40.0% up 4.1 ppts
Earnings per share attributable to Intel—diluted $0.60 $0.90 down 33% $0.52 $0.23 up 126%
Q4 2026 GAAP Non-GAAP
Revenue ($B) $15.0 - $16.0
Gross margin 37.1% 38.0%
Earnings (Loss) Per Share Attributable to Intel—Diluted $0.10 $0.25
"we see the PC slowdown continuing at least through the first half of next year"
"""


def run(coro):
    return asyncio.run(coro)


# --- label_reaction / daily_sigma -------------------------------------------------------------------------

@pytest.mark.parametrize("r,sigma,expected", [(-0.170, 0.0385, "down"), (0.236, 0.0401, "up"),
                                              (-0.079, 0.0494, "flat"), (-0.286, 0.0490, "down")])
def test_label_reaction_intc_four_quarters(r, sigma, expected):
    assert er.label_reaction(r, sigma) == expected


def test_label_reaction_three_percent_floor():
    assert er.label_reaction(-0.025, 0.005) == "flat"
    assert er.label_reaction(-0.031, 0.005) == "down"
    assert er.label_reaction(0.031, 0.005) == "up"


def _closes(n, start=date(2026, 1, 1)):
    out, price = [], 100.0
    for i in range(n):
        price *= 1.01 if i % 2 else 0.99
        out.append((start + timedelta(days=i), price))
    return out


def _series(returns, start=date(2026, 1, 1)):
    out, price = [(start, 100.0)], 100.0
    for i, r in enumerate(returns, 1):
        price *= 1 + r
        out.append((start + timedelta(days=i), price))
    return out


def test_daily_sigma_excludes_reaction_days():
    returns = [0.01 if i % 2 else -0.01 for i in range(60)]
    returns[30] = 0.30                                   # an earnings jump
    closes = _series(returns)
    jump_day = closes[31][0]
    with_jump = er.daily_sigma(closes, exclude_dates=set())
    without = er.daily_sigma(closes, exclude_dates={jump_day})
    assert with_jump > 0.03 and without == pytest.approx(0.01, abs=0.001)


def test_daily_sigma_needs_twenty_days():
    assert er.daily_sigma(_closes(19), set()) is None
    assert er.daily_sigma(_closes(21), set()) is not None


def test_daily_sigma_uses_last_n_days():
    closes = _closes(300)
    for i in range(0, 100):   # an old, violent stretch outside the 126-day window
        closes[i] = (closes[i][0], 100.0 * (1.2 if i % 2 else 0.8))
    assert er.daily_sigma(closes, set(), n=126) < 0.03


# --- compare: Intel's real numbers ------------------------------------------------------------------------

def _intel():
    facts = er.ReleaseFacts(revenue=16.5, gross_margin=44.1, eps=0.52, eps_gaap=0.60,
                            guidance=er.Guidance(revenue_low=15.0, revenue_high=16.0, gross_margin=38.0, eps=0.25))
    prior = er.Guidance(revenue_low=15.8, revenue_high=16.8, gross_margin=42.0, eps=0.38)
    return facts, prior


def test_compare_intel_five_percentages():
    facts, prior = _intel()
    c = er.compare(facts, prior, history=[], prices=[])
    assert c.revenue_vs_guidance_pct == pytest.approx(1.2, abs=0.05)
    assert c.eps_vs_guidance_pct == pytest.approx(36.8, abs=0.05)
    assert c.new_revenue_vs_actual_pct == pytest.approx(-6.1, abs=0.05)
    assert c.new_eps_vs_actual_pct == pytest.approx(-51.9, abs=0.05)
    assert c.new_gross_margin_vs_actual_pp == pytest.approx(-6.1, abs=0.05)


def test_compare_subtracts_habitual_beat_and_year_ago():
    facts, prior = _intel()
    history = [er.HistoryQuarter(period=f"q{i}", revenue=10.0, eps=0.20, gross_margin=40.0,
                                 guided=er.Guidance(revenue_low=9.5, revenue_high=10.5, gross_margin=39.0, eps=0.10),
                                 same_quarter_last_year=(i == 4)) for i in range(1, 5)]
    c = er.compare(facts, prior, history=history, prices=[])
    assert c.habitual_eps_beat_pct == pytest.approx(100.0)       # 0.20 vs 0.10 every time
    assert c.eps_beat_excess_pct == pytest.approx(36.8 - 100.0, abs=0.1)
    assert c.new_eps_vs_year_ago_pct == pytest.approx((0.25 / 0.20 - 1) * 100, abs=0.1)
    assert c.new_revenue_vs_year_ago_pct == pytest.approx((15.5 / 10.0 - 1) * 100, abs=0.1)


def test_compare_pre_release_run_and_quality_and_missing():
    facts, prior = _intel()
    prices = [(date(2026, 1, 1) + timedelta(days=i), 100.0 + i) for i in range(30)]
    c = er.compare(facts, prior, history=[], prices=prices)
    assert c.pre_release_return_20d_pct == pytest.approx((129.0 / 109.0 - 1) * 100, abs=0.01)
    assert c.eps_gaap_minus_nongaap == pytest.approx(0.08)
    empty = er.compare(er.ReleaseFacts(), None, history=[], prices=[])
    assert empty.revenue_vs_guidance_pct is None and empty.new_eps_vs_actual_pct is None


# --- extract_release: every number must be found verbatim -------------------------------------------------

def _fake(monkeypatch, payload):
    async def call(model, system, user):
        return payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(er, "_call_model", call)


def test_extract_release_blanks_numbers_not_in_text(monkeypatch):
    _fake(monkeypatch, {
        "revenue": {"quote": "Third-quarter revenue was $16.5 billion", "number": "16.5", "unit": "B"},
        "gross_margin": {"quote": "Gross margin 43.0% 38.2% up 4.8 ppts 44.1%", "number": "44.1"},
        "eps": {"quote": "non-GAAP EPS was $0.77", "number": "0.77"},                      # made up
        "eps_gaap": {"quote": "Earnings per share attributable to Intel—diluted $0.60", "number": "0.65"},  # number not in quote
        "guidance_revenue": {"quote": "Revenue ($B) $15.0 - $16.0", "low": "15.0", "high": "16.0", "unit": "B"},
        "guidance_gross_margin": {"quote": "Gross margin 37.1% 38.0%", "number": "38.0"},
        "guidance_eps": {"quote": "Diluted EPS of $0.25", "number": "0.25"},               # quote not verbatim
    })
    facts = run(er.extract_release(INTC_RELEASE, {"name": "x"}))
    assert facts.revenue == 16.5 and facts.gross_margin == 44.1
    assert facts.eps is None and facts.eps_gaap is None and facts.guidance.eps is None
    assert (facts.guidance.revenue_low, facts.guidance.revenue_high) == (15.0, 16.0)
    assert facts.guidance.gross_margin == 38.0


def test_extract_release_converts_millions_and_survives_garbage(monkeypatch):
    text = "Revenue was $16,500 million for the quarter."
    _fake(monkeypatch, {"revenue": {"quote": "Revenue was $16,500 million", "number": "16,500", "unit": "M"}})
    assert run(er.extract_release(text, {})).revenue == 16.5
    _fake(monkeypatch, "not json at all")
    assert run(er.extract_release(text, {})).revenue is None


# --- judge ------------------------------------------------------------------------------------------------

def test_judge_keeps_only_quotes_found_in_the_source(monkeypatch):
    facts, prior = _intel()
    facts.source_text = INTC_RELEASE
    comparison = er.compare(facts, prior, [], [])
    _fake(monkeypatch, {"direction": "down", "confidence": "high",
                        "reasons": [{"text": "PC 放缓", "quote": "we see the PC slowdown continuing at least through the first half of next year"},
                                    {"text": "新指引 EPS 腰斩", "quote": "Diluted $0.10 $0.25"},
                                    {"text": "编造", "quote": "management said demand is collapsing"}],
                        "counter_argument": "数据中心增长 78%"})
    j = run(er.judge(facts, comparison, "", None, {}))
    assert j.direction == "down" and j.confidence == "high"
    assert [r["quote"] for r in j.reasons] == ["we see the PC slowdown continuing at least through the first half of next year",
                                               "Diluted $0.10 $0.25"]
    assert j.counter_argument == "数据中心增长 78%"


def test_judge_downgrades_high_without_grounded_reasons_and_rejects_bad_enums(monkeypatch):
    facts, prior = _intel()
    comparison = er.compare(facts, prior, [], [])
    _fake(monkeypatch, {"direction": "down", "confidence": "high",
                        "reasons": [{"text": "x", "quote": "not in any source"}], "counter_argument": ""})
    j = run(er.judge(facts, comparison, "", None, {}))
    assert j.confidence != "high" and j.reasons == []
    _fake(monkeypatch, {"direction": "sideways", "confidence": "certain", "reasons": []})
    j = run(er.judge(facts, comparison, "", None, {}))
    assert (j.direction, j.confidence) == ("unclear", "low")
    _fake(monkeypatch, "oops")
    assert run(er.judge(facts, comparison, "", None, {})).direction == "unclear"


def test_judge_prompt_carries_the_calibration_logic_not_a_threshold():
    p = er.JUDGE_PROMPT
    assert "指引" in p and "惯常" in p and "不要" in p
    assert "超预期" in p          # explicitly says a plain beat percentage is not the criterion
