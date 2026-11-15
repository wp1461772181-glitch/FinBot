"""SW1 item 4: is the saved library behind the company's own filing rhythm (spec §8.2 T22–T29, R02–R03).

The rule is checked on metadata lists (pure), and once end to end through the financial tool on seeded filings.
"""
import asyncio
from datetime import date

from app.agent_workflow.filing_coverage import freshness
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, drop, msft_filings, new_symbol, nvda_filings, seed

FRESH_SWITCH = 'FINBOT_SW1_FRESHNESS'


def meta(form, filed, status='fetched'):
    return {'form': form, 'filed_at': filed, 'content_status': status}


def msft_meta():
    return [meta(f['form'], f['filed']) for f in msft_filings()]


def test_msft_rhythm_is_overdue_and_names_the_next_period():  # T22
    periodic = msft_meta()
    note = freshness(periodic, periodic, CUTOFF, latest_period='FY2026', latest_end='2026-06-30', next_period_label='FY2027 Q1')
    assert note['kind'] == 'cadence' and note['overdue'] is True
    assert date(2026, 11, 3) <= date.fromisoformat(note['expected_by']) <= date(2026, 11, 8)
    assert 'FY2027 Q1' in note['note'] and '库里还没有' in note['note']
    assert '91' in note['basis']


def test_nvda_is_not_yet_due_at_the_cutoff():  # T23, R03
    periodic = [meta(f['form'], f['filed']) for f in nvda_filings()]
    assert freshness(periodic, periodic, CUTOFF) is None


def test_two_intervals_are_too_few_to_read_a_rhythm():  # T24
    periodic = [meta('10-Q', date(2026, 2, 10)), meta('10-Q', date(2026, 5, 10)), meta('10-Q', date(2026, 8, 10))]
    assert freshness(periodic, periodic, CUTOFF) is None


def test_annual_reports_alone_give_no_rhythm():  # T25
    periodic = [meta('10-K', date(2023, 8, 1)), meta('10-K', date(2024, 8, 1)), meta('10-K', date(2025, 8, 1))]
    assert freshness(periodic, periodic, CUTOFF) is None


def test_a_rhythm_long_past_is_stale_and_never_says_due():  # T26
    periodic = [meta('10-Q', date(2022, 2, 1)), meta('10-Q', date(2022, 5, 2)), meta('10-Q', date(2022, 8, 1)),
                meta('10-Q', date(2022, 10, 31))]
    note = freshness(periodic, periodic, CUTOFF)
    assert note['kind'] == 'stale' and note['overdue'] is False
    assert '应已发布' not in note['note'] and '2022-10-31' in note['note']


def test_a_newer_filing_registered_but_not_saved_is_named_first():  # T27
    periodic = msft_meta() + [meta('10-Q', date(2026, 10, 30), status='not_fetched')]
    saved = [m for m in periodic if m['content_status'] == 'fetched']
    note = freshness(periodic, saved, CUTOFF)
    assert note['kind'] == 'registered_not_saved' and note['overdue'] is True
    assert '2026-10-30' in note['note'] and '还没入库' in note['note']


def test_the_cutoff_decides_not_the_wall_clock():  # T28
    periodic = msft_meta()
    assert freshness(periodic, periodic, date(2026, 10, 1)) is None
    assert freshness(periodic, periodic, date(2026, 11, 15)) is not None


def test_a_company_with_no_filings_has_no_rhythm():  # R02 (pure half)
    assert freshness([], [], CUTOFF) is None


def financials(**args):
    from app.agent_tools import query_financials
    with research_context('sw1-fresh-test', cutoff=CUTOFF):
        return asyncio.run(query_financials.ainvoke(args))


def test_the_financial_tool_says_when_the_library_is_behind_its_rhythm(monkeypatch):  # T29
    monkeypatch.delenv(FRESH_SWITCH, raising=False)
    symbol = new_symbol(); ids = seed(symbol, msft_filings())
    try:
        coverage = financials(symbol=symbol, metrics=['revenue'])['meta']['coverage']
        assert coverage['freshness']['overdue'] is True
        assert 'FY2027 Q1' in coverage['freshness']['note']
    finally:
        drop(ids)


def test_the_freshness_switch_off_drops_the_claim(monkeypatch):  # T29 switch half
    monkeypatch.setenv(FRESH_SWITCH, 'off')
    symbol = new_symbol(); ids = seed(symbol, msft_filings())
    try:
        coverage = financials(symbol=symbol, metrics=['revenue'])['meta']['coverage']
        assert 'freshness' not in coverage
    finally:
        drop(ids)
