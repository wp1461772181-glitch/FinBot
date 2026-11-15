"""SW1 item 1, read side: latest across every saved filing, the one-rung widening, the coverage receipt (spec §8.2 T01–T16, R01–R02).

Fixtures are seeded per test under random symbols (tests/sw1_filings.py) and read under a pinned cutoff.
"""
import asyncio
import json
from datetime import date

import pytest

from app.agent_workflow import direct
from app.agent_workflow.filing_coverage import RECEIPT_LIMIT, coverage_receipt
from app.agent_workflow.financials import xbrl_metrics_for
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings, drop, figure, new_symbol, nvda_filings, onlyq_filings, p, seed

SWITCH = 'FINBOT_SW1_READ_WIDEN'


@pytest.fixture(autouse=True)
def switch_on(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


def financials(**args):
    from app.agent_tools import query_financials
    with research_context('sw1-read-test', cutoff=CUTOFF):
        return asyncio.run(query_financials.ainvoke(args))


def sec_filings(**args):
    from app.agent_tools import query_sec_filings
    with research_context('sw1-read-test', cutoff=CUTOFF):
        return asyncio.run(query_sec_filings.ainvoke(args))


def test_latest_reads_every_saved_filing_newest_period_first():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        rows = financials(symbol=symbol, metrics=['revenue'], latest=True)['data']
        assert len({r['source_id'] for r in rows}) >= 2 and {r['form'] for r in rows} == {'10-K', '10-Q'}
        ends = [r['period_end'] for r in rows]
        assert ends == sorted(ends, reverse=True)
        assert any(r['fiscal_year'] == 2026 and r['fiscal_period'] == 'Q3' and r['period_span'] == 'quarter' for r in rows)
        keys = [(r['period_start'], r['period_end']) for r in rows]
        assert len(keys) == len(set(keys))
    finally:
        drop(ids)


def test_a_limit_that_cuts_rows_says_which_periods_were_left_out():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = financials(symbol=symbol, metrics=['revenue', 'gross_profit'], latest=True, limit=8)
        coverage = result['meta']['coverage']
        assert len(result['data']) == 8 and coverage['rows_left_out_by_limit'] > 0
        assert any(label.startswith('FY2026 Q1') for label in coverage['periods_left_out'])
    finally:
        drop(ids)


def test_a_form_filter_that_hides_a_newer_filing_brings_the_newer_one_in_marked():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = financials(symbol=symbol, form='10-Q', latest=True)
        rows = result['data']
        widened = [r for r in rows if r.get('widened')]
        assert widened and all(r['widened'] == 'newer_other_form' and r['form'] == '10-K' for r in widened)
        assert any(r['fiscal_year'] == 2026 and r['period_span'] == 'annual' for r in widened)
        assert all(not r.get('widened') for r in rows if r['form'] == '10-Q')
        assert result['meta']['coverage']['widened'][0]['rung'] == 'newer_other_form'
    finally:
        drop(ids)


def test_a_form_filter_with_nothing_newer_is_not_widened():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = financials(symbol=symbol, form='10-K')
        assert result['data'] and all(r['form'] == '10-K' for r in result['data'])
        assert not any(r.get('widened') for r in result['data'])
        assert result['meta']['coverage']['widened'] == []
    finally:
        drop(ids)


def test_a_form_filter_that_hides_every_filing_is_widened_one_rung():
    symbol = new_symbol(); ids = seed(symbol, onlyq_filings())
    try:
        result = financials(symbol=symbol, form='10-K', metrics=['revenue'])
        assert result['data'] and all(r['form'] == '10-Q' and r['widened'] == 'form' for r in result['data'])
        assert result['meta']['coverage']['widened'][0]['rung'] == 'form'
    finally:
        drop(ids)


def test_q4_without_a_three_month_figure_adds_the_annual_and_nine_month_figures():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = financials(symbol=symbol, metrics=['revenue'], fiscal_year=2026, fiscal_period='Q4')
        rows = result['data']
        assert not any(r['period_span'] == 'quarter' for r in rows)
        added = [r for r in rows if r.get('widened') == 'q4_components']
        assert {r['period_span'] for r in added} == {'annual', 'ytd9'} and all(r['fiscal_year'] == 2026 for r in added)
        assert '3 个月' in result['meta']['coverage']['q4_note']
    finally:
        drop(ids)


def test_a_period_nobody_saved_returns_nothing_and_names_only_real_periods():
    symbol = new_symbol(); ids = seed(symbol, nvda_filings())
    try:
        result = financials(symbol=symbol, metrics=['revenue'], fiscal_year=2027, fiscal_period='Q3')
        assert result['data'] == []
        real = {r['period_label'] for r in financials(symbol=symbol, metrics=['revenue'], latest=True)['data']}
        assert set(result['meta']['coverage']['nearest_periods']) <= real
        assert not any(r.get('widened') for r in result['data'])
    finally:
        drop(ids)


def test_a_company_with_no_filings_returns_nothing_and_no_freshness_claim():
    result = financials(symbol=new_symbol(), metrics=['revenue'])
    coverage = result['meta']['coverage']
    assert result['data'] == [] and coverage['library'] == {'periodic_filings': 0}
    assert 'freshness' not in coverage


def test_the_same_period_in_two_filings_keeps_the_newer_filing():
    symbol = new_symbol()
    older = {'form': '10-K', 'filed': date(2025, 10, 31), 'figures': [figure('revenue', 'Revenue', [p('2024-09-29', '2025-09-27', 1, 2025, 'FY')])]}
    newer = {'form': '10-K', 'filed': date(2026, 11, 3), 'figures': [figure('revenue', 'Revenue', [
        p('2024-09-29', '2025-09-27', 2, 2026, 'FY'), p('2025-09-28', '2026-09-26', 3, 2026, 'FY')])]}
    ids = seed(symbol, [older, newer])
    try:
        rows = financials(symbol=symbol, metrics=['revenue'], latest=True)['data']
        kept = [r for r in rows if r['period_start'] == '2024-09-29']
        assert len(kept) == 1 and kept[0]['value'] == 2 and kept[0]['source_id'] == ids[1]
    finally:
        drop(ids)


def test_widened_rows_stay_within_the_cap_and_keep_their_own_filing():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = financials(symbol=symbol, form='10-Q', latest=True, limit=3)
        widened = [r for r in result['data'] if r.get('widened')]
        assert len(widened) <= 12 and len(result['data']) <= 3 + 12
        by_id = {}
        for r in result['data']:
            assert r['source_id'] in ids
            by_id.setdefault(r['source_id'], r['form'])
        assert set(by_id.values()) <= {'10-K', '10-Q'}
    finally:
        drop(ids)


def test_a_filing_search_that_hides_every_filing_is_widened_once():
    symbol = new_symbol()
    ids = seed(symbol, [{'form': '10-K', 'filed': date(2026, 7, 30), 'figures': None}])
    try:
        result = sec_filings(symbol=symbol, form='10-Q')
        assert result['data'] and all(r['form'] == '10-K' and r['widened'] == 'form' for r in result['data'])
        assert result['meta']['coverage']['widened'][0]['rung'] == 'form'
    finally:
        drop(ids)


def test_a_filing_search_holds_back_a_newer_filing_the_form_filter_hid():
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        result = sec_filings(symbol=symbol, form='10-Q', latest=True)
        assert result['data'] and all(r['form'] == '10-Q' for r in result['data'])
        held = result['meta']['coverage']['not_read']
        assert any(n['form'] == '10-K' and n['filed_at'] == '2026-11-03' and n['why'] == 'form_filter' for n in held)
    finally:
        drop(ids)


def test_the_coverage_receipt_is_bounded_and_drops_fields_from_the_end():
    long_label = '（' + 'x' * 180 + '）'
    coverage = coverage_receipt(filters={'latest': True, 'limit': 8},
                       filings_read=[{'form': '10-K', 'filed_at': '2026-11-03', 'period': 'FY2026'}],
                       not_read=[{'form': '10-Q', 'filed_at': f'2026-0{i}-01', 'period': None, 'why': 'form_filter'} for i in range(1, 9)] * 2,
                       widened=[], rows_left_out=40, periods_left_out=[f'FY2025 Q{i % 4 + 1}{long_label}' for i in range(8)],
                       library={'periodic_filings': 9})
    assert len(json.dumps(coverage, ensure_ascii=False)) <= RECEIPT_LIMIT
    assert len(coverage['not_read']) <= 8
    # DROP_ORDER runs from the table's end: library and widened go before periods_left_out, and the filters stay.
    assert 'library' not in coverage and 'periods_left_out' not in coverage and 'filters' in coverage and 'not_read' in coverage


def test_the_receipt_keeps_its_fields_when_they_already_fit():
    coverage = coverage_receipt(filters={'limit': 5}, filings_read=[], not_read=[], widened=[], rows_left_out=0, periods_left_out=[])
    assert set(coverage) == {'filters', 'filings_read', 'not_read', 'rows_left_out_by_limit', 'periods_left_out', 'widened'}


def test_a_widening_switch_off_returns_the_old_single_filing_read(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    try:
        rows = financials(symbol=symbol, metrics=['revenue'], latest=True)['data']
        assert rows and {r['form'] for r in rows} == {'10-K'}
        rows_10q = financials(symbol=symbol, metrics=['revenue'], form='10-Q', latest=True)['data']
        assert rows_10q and all(r['form'] == '10-Q' for r in rows_10q)
        result = financials(symbol=symbol, metrics=['revenue'], latest=True)
        assert 'meta' not in result and set(result) == {'ok', 'data', 'source', 'as_of', 'error_code'}
    finally:
        drop(ids)


def test_the_ratio_words_name_the_figures_a_margin_needs(monkeypatch):
    assert xbrl_metrics_for(['毛利率']) == ['gross_profit', 'revenue']
    assert xbrl_metrics_for(['净利率']) == ['net_income', 'revenue']
    assert xbrl_metrics_for(['营业利润率']) == ['operating_income', 'revenue']
    assert xbrl_metrics_for(['gross margin']) == ['gross_profit', 'revenue']
    assert xbrl_metrics_for(['云业务收入']) == [] and xbrl_metrics_for(['全年营业收入']) == ['revenue']
    monkeypatch.setenv(SWITCH, 'off')
    assert xbrl_metrics_for(['毛利率']) == []


def test_the_read_receipt_reaches_the_model_beside_the_rows(monkeypatch):
    symbol = new_symbol(); ids = seed(symbol, aapl_filings())
    seen = []

    def decide(messages, tools):
        seen.append(messages)
        if len(seen) == 1:
            return {'tool_calls': [{'id': 'call-1', 'function': {'name': 'query_financials',
                    'arguments': json.dumps({'symbol': symbol, 'metrics': ['revenue'], 'latest': True})}}]}
        return {'content': f'{symbol} 已取到财报营收。'}

    async def emit(_):
        pass

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: {'category': 'A', 'mode': 'financials',
                              'symbol': symbol, 'symbols': [symbol], 'days_back': None}, decider=decide)
    try:
        with research_context('sw1-read-test', cutoff=CUTOFF):
            asyncio.run(direct.run_direct_turn(f'{symbol} 最近一期营收', ctx, emit=emit))
        tool_messages = [m for messages in seen for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
        bodies = [json.loads(m['content']) for m in tool_messages if 'coverage' in str(m.get('content'))]
        assert bodies and 'coverage' in bodies[0] and bodies[0]['data']
    finally:
        drop(ids)


def test_a_margin_word_pre_reads_its_figures_without_latest_or_form(monkeypatch):  # T16
    """Route A's XBRL pre-read: a margin is read through its numerator and revenue, with neither latest nor form."""
    async def no_model(provider, model, key, messages, schemas, base_url=None, **_kwargs):
        return {}, {'role': 'assistant', 'content': ''}
    monkeypatch.setattr(direct, 'decision_request', no_model)
    symbol = new_symbol()
    executed = []

    def execute(name, args):
        executed.append((name, args))
        return {'ok': True, 'data': []}

    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              classifier=lambda _: {'category': 'A', 'mode': 'financials', 'symbol': symbol, 'symbols': [symbol],
                                                    'metrics': ['服务收入', '毛利率'], 'days_back': None},
                              decider=lambda messages, tools: {'content': ''}, executor=execute)
    with research_context('sw1-read-test', cutoff=CUTOFF):
        asyncio.run(direct.run_direct_turn(f'{symbol} 的服务收入与毛利率', ctx, emit=emit))
    # The tool layer fills defaults in, so the test reads the values that matter rather than the whole dict.
    assert executed and executed[0][0] == 'query_financials'
    args = executed[0][1]
    assert args['symbol'] == symbol and sorted(args['metrics']) == ['gross_profit', 'revenue']
    assert not args.get('latest') and args.get('form') is None


def test_the_instruction_carries_the_read_sentences_only_while_their_switches_are_on(monkeypatch):  # T39 (S1 part)
    from app.agent_workflow import direct
    text = '\n'.join(direct.INSTRUCTION)
    on = direct.evidence_instruction(text)
    assert direct.EVIDENCE_NEW in on and direct.FRESHNESS_SENTENCE in on and direct.EVIDENCE_OLD not in on
    monkeypatch.setenv('FINBOT_SW1_FRESHNESS', 'off')
    no_fresh = direct.evidence_instruction(text)
    assert direct.EVIDENCE_NEW in no_fresh and direct.FRESHNESS_SENTENCE not in no_fresh
    monkeypatch.setenv('FINBOT_SW1_READ_WIDEN', 'off')
    # S3 (FINBOT_SW1_EXISTENCE_KNOWLEDGE, on by default) adds its own sentence; this check is about S1's sentences alone.
    monkeypatch.setenv('FINBOT_SW1_EXISTENCE_KNOWLEDGE', 'off')
    # SW1B's sample sentence (on by default, its own switch) would also differ from the constant; this check is S1's alone.
    monkeypatch.setenv('FINBOT_SW1B_SAMPLE_AGGREGATE', 'off')
    assert direct.evidence_instruction(text) == text and direct.EVIDENCE_OLD in text   # off: the constant's own text
