"""Earnings-press-release figures (FINBOT_RELEASE_FIGURES): extraction and its checks, which releases are read, and how
query_financials serves them until the periodic report states the same period.  The model is always a fake."""
import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app import earnings_reader, release_figures
from app.agent_workflow.financials import figure_rows, period_label
from app.database import Base, SessionLocal, engine
from app.knowledge.runtime import research_context
from app.models import SecFilingInventory
from sw1_filings import drop, figure, new_symbol, p, seed

SWITCH = 'FINBOT_RELEASE_FIGURES'
CUTOFF = datetime(2026, 12, 15, 12, 0, tzinfo=UTC)
RELEASE_FILED = date(2026, 11, 17)
FILED_Q2 = date(2026, 8, 26)

RELEASE = """NVIDIA Announces Financial Results for Third Quarter Fiscal 2027
CONDENSED CONSOLIDATED STATEMENTS OF INCOME
(In millions, except per share data)
(Unaudited)
Three Months Ended Nine Months Ended
October 25, October 26, October 25, October 26,
2026 2025 2026 2025
Revenue $ 115,844 $ 57,006 $ 293,681 $ 147,811
Cost of revenue 29,168 15,157 73,705 45,441
Gross profit 86,676 41,849 219,976 102,370
Operating income 80,100 36,010 200,500 88,000
Net income $ 65,287 $ 31,910 $ 160,000 $ 72,000
CONDENSED CONSOLIDATED BALANCE SHEETS
(In millions)
October 25, January 25,
2026 2026
Total assets $ 310,000 $ 206,803
Cash and cash equivalents 21,000 8,589
Total liabilities 70,500 49,510
Total shareholders' equity 239,500 157,293
CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS
Net cash provided by operating activities 48,253 27,414 130,000 64,000
"""
PERSONNEL = "NVIDIA announces the appointment of a new independent director to its board effective November 1, 2026."


def entry(metric, number, value, quote, **kw):
    return {'metric': metric, 'number': number, 'value': value, 'quote': quote, **kw}


def good_reply():
    flow = lambda m, n, v, q, months=3: entry(m, n, v, q, period_end='2026-10-25', months=months)
    point = lambda m, n, v, q: entry(m, n, v, q, as_of='2026-10-25')
    return {'is_earnings_release': True, 'unit': 'millions', 'fiscal_year': 2027, 'fiscal_quarter': 'Q3', 'figures': [
        flow('revenue', '115,844', 115_844_000_000, 'Revenue $ 115,844 $ 57,006 $ 293,681 $ 147,811'),
        flow('revenue', '293,681', 293_681_000_000, 'Revenue $ 115,844 $ 57,006 $ 293,681 $ 147,811', 9),
        flow('cost_of_revenue', '29,168', 29_168_000_000, 'Cost of revenue 29,168 15,157 73,705 45,441'),
        flow('gross_profit', '86,676', 86_676_000_000, 'Gross profit 86,676 41,849 219,976 102,370'),
        flow('operating_income', '80,100', 80_100_000_000, 'Operating income 80,100 36,010 200,500 88,000'),
        flow('net_income', '65,287', 65_287_000_000, 'Net income $ 65,287 $ 31,910 $ 160,000 $ 72,000'),
        flow('operating_cash_flow', '48,253', 48_253_000_000, 'Net cash provided by operating activities 48,253 27,414 130,000 64,000'),
        point('total_assets', '310,000', 310_000_000_000, 'Total assets $ 310,000 $ 206,803'),
        point('cash_and_equivalents', '21,000', 21_000_000_000, 'Cash and cash equivalents 21,000 8,589'),
        point('total_liabilities', '70,500', 70_500_000_000, 'Total liabilities 70,500 49,510'),
        point('stockholders_equity', '239,500', 239_500_000_000, "Total shareholders' equity 239,500 157,293"),
    ]}


def fake_model(monkeypatch, reply):
    calls = []

    async def call(model, system, user):
        calls.append(user)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    monkeypatch.setattr(earnings_reader, '_call_model', call)
    return calls


def extract(reply, text=RELEASE, filed=RELEASE_FILED, monkeypatch=None):
    fake_model(monkeypatch, reply)
    return asyncio.run(release_figures.extract_release_figures(text, {'provider': 'x', 'model': 'y', 'api_key': 'z'}, filed))


def values(figures):
    return {(f['metric'], pe.get('span_months')): pe['value'] for f in figures for pe in f['periods']}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    release_figures._FAILED.clear()


# --- extraction ----------------------------------------------------------------------------------------------

def test_the_release_figures_come_out_in_xbrl_shape(monkeypatch):
    figures = extract(good_reply(), monkeypatch=monkeypatch)
    got = values(figures)
    assert got[('revenue', 3)] == 115_844_000_000 and got[('revenue', 9)] == 293_681_000_000
    assert got[('net_income', 3)] == 65_287_000_000 and got[('operating_cash_flow', 3)] == 48_253_000_000
    assert got[('total_assets', None)] == 310_000_000_000 and len(figures) == 10
    revenue = next(f for f in figures if f['metric'] == 'revenue')
    assert revenue['basis'] == 'press_release_unaudited' and revenue['concept'] == 'press_release' and revenue['unit'] == 'USD'
    quarter = next(pe for pe in revenue['periods'] if pe['span_months'] == 3)
    assert quarter == {'unit': 'USD', 'value': 115_844_000_000, 'start': None, 'end': '2026-10-25', 'fiscal_period': 'Q3',
                       'fiscal_year': 2027, 'basis': 'press_release_unaudited', 'span_months': 3}
    balance = next(f for f in figures if f['metric'] == 'total_assets')['periods'][0]
    assert 'span_months' not in balance and balance['end'] == '2026-10-25'


def test_a_number_that_is_not_in_the_text_is_dropped(monkeypatch):
    reply = good_reply()
    reply['figures'][0] = entry('revenue', '115,999', 115_999_000_000, 'Revenue $ 115,999 $ 57,006', period_end='2026-10-25', months=3)
    got = values(extract(reply, monkeypatch=monkeypatch))
    assert ('revenue', 3) not in got and got[('revenue', 9)] == 293_681_000_000


def test_a_quote_that_is_not_in_the_text_is_dropped(monkeypatch):
    reply = good_reply()
    reply['figures'][5]['quote'] = 'Net income $ 65,287 attributable to the moon'
    assert ('net_income', 3) not in values(extract(reply, monkeypatch=monkeypatch))


def test_a_value_that_does_not_follow_from_the_digits_and_the_scale_is_dropped(monkeypatch):
    reply = good_reply()
    reply['figures'][5]['value'] = 65_287_000          # millions read as thousands
    got = values(extract(reply, monkeypatch=monkeypatch))
    assert ('net_income', 3) not in got and got[('operating_income', 3)] == 80_100_000_000


def test_gross_profit_that_disagrees_with_revenue_less_cost_drops_all_three_for_that_period(monkeypatch):
    reply = good_reply()
    text = RELEASE.replace('Gross profit 86,676', 'Gross profit 86,000')
    reply['figures'][3] = entry('gross_profit', '86,000', 86_000_000_000, 'Gross profit 86,000 41,849 219,976 102,370', period_end='2026-10-25', months=3)
    got = values(extract(reply, text=text, monkeypatch=monkeypatch))
    assert not {('revenue', 3), ('cost_of_revenue', 3), ('gross_profit', 3)} & set(got)
    assert got[('revenue', 9)] == 293_681_000_000 and got[('net_income', 3)] == 65_287_000_000


def test_a_one_unit_rounding_difference_in_the_statement_is_allowed(monkeypatch):
    reply = good_reply()
    text = RELEASE.replace('Gross profit 86,676', 'Gross profit 86,677')
    reply['figures'][3] = entry('gross_profit', '86,677', 86_677_000_000, 'Gross profit 86,677 41,849 219,976 102,370', period_end='2026-10-25', months=3)
    assert values(extract(reply, text=text, monkeypatch=monkeypatch))[('gross_profit', 3)] == 86_677_000_000


def test_a_date_after_the_filing_or_not_a_date_is_dropped(monkeypatch):
    reply = good_reply()
    reply['figures'][0]['period_end'] = '2026-11-18'
    reply['figures'][2]['period_end'] = '2026-02-30'
    got = values(extract(reply, monkeypatch=monkeypatch))
    assert ('revenue', 3) not in got and ('cost_of_revenue', 3) not in got and ('net_income', 3) in got


def test_a_month_count_other_than_3_6_9_12_is_dropped(monkeypatch):
    reply = good_reply()
    reply['figures'][4]['months'] = 4
    reply['figures'][5].pop('months')
    got = values(extract(reply, monkeypatch=monkeypatch))
    assert ('operating_income', 4) not in got and ('net_income', None) not in got and ('operating_income', 3) not in got


def test_negative_numbers_in_parentheses_are_read_as_negative(monkeypatch):
    text = RELEASE.replace('Net income $ 65,287', 'Net income $ (65,287)')
    reply = good_reply()
    reply['figures'][5] = entry('net_income', '(65,287)', -65_287_000_000, 'Net income $ (65,287) $ 31,910', period_end='2026-10-25', months=3)
    assert values(extract(reply, text=text, monkeypatch=monkeypatch))[('net_income', 3)] == -65_287_000_000


def test_a_release_the_model_says_is_not_earnings_gives_nothing(monkeypatch):
    assert extract({'is_earnings_release': False}, text=PERSONNEL, monkeypatch=monkeypatch) == []


def test_a_reply_without_the_fiscal_period_gives_nothing(monkeypatch):
    reply = good_reply()
    reply['fiscal_quarter'] = None
    assert extract(reply, monkeypatch=monkeypatch) == []


def test_a_failed_model_call_or_a_reply_that_is_not_json_raises_instead_of_returning_empty(monkeypatch):
    with pytest.raises(release_figures.ReleaseModelError):
        extract(RuntimeError('timeout'), monkeypatch=monkeypatch)
    with pytest.raises(release_figures.ReleaseModelError):
        extract('sorry, I cannot', monkeypatch=monkeypatch)


# --- which releases, and storing ----------------------------------------------------------------------------

MODEL = {'provider': 'x', 'model': 'y', 'api_key': 'z'}


def seed_release(symbol, filed, *, text=RELEASE, kind='exhibit_99_1', figures=None, status='fetched', form='8-K'):
    Base.metadata.create_all(engine)
    cik = f'{uuid.uuid4().int % 10**10:010d}'
    with SessionLocal() as db:
        row = SecFilingInventory(
            symbol=symbol, cik=cik, accession_number=f'{cik}-{filed:%y}-{uuid.uuid4().int % 10**6:06}', form=form, filed_at=filed,
            primary_document='8k.htm', source_url=f'https://www.sec.gov/{symbol}/8-K-{filed:%Y%m%d}.htm', source='sec-edgar',
            review_status='pending_review', observed_at=datetime(2026, 11, 18, tzinfo=UTC), content_status=status,
            content_observed_at=datetime(2026, 11, 18, tzinfo=UTC), content_text=text, content_kind=kind,
            content_excerpt=text[:200], content_excerpt_sha256=hashlib.sha256(text.encode()).hexdigest(),
            content_source_url=f'https://www.sec.gov/{symbol}/ex991-{filed:%Y%m%d}.htm', content_financials=figures)
        db.add(row)
        db.commit()
        return str(row.id), row.accession_number


def stored(row_id):
    with SessionLocal() as db:
        return db.get(SecFilingInventory, uuid.UUID(row_id)).content_financials


def q2_10q(filed=FILED_Q2):
    return {'form': '10-Q', 'filed': filed, 'figures': [
        figure('revenue', 'Revenue', [p('2026-04-27', '2026-07-26', 46_000_000_000, 2027, 'Q2'), p('2026-01-26', '2026-07-26', 90_000_000_000, 2027, 'Q2')]),
        figure('total_assets', 'Total assets', [{'start': None, 'end': '2026-07-26', 'unit': 'USD', 'value': 250_000_000_000, 'fiscal_year': 2027, 'fiscal_period': 'Q2'}])]}


def test_candidates_are_only_unread_releases_newer_than_the_newest_periodic_report(monkeypatch):
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()]); rows = []
    try:
        newer, _ = seed_release(symbol, RELEASE_FILED)
        older, _ = seed_release(symbol, date(2026, 5, 20))                       # covered by the periodic report
        done, _ = seed_release(symbol, date(2026, 11, 10), figures=[])           # already looked at
        wrong_kind, _ = seed_release(symbol, date(2026, 11, 11), kind='primary_document')
        unfetched, _ = seed_release(symbol, date(2026, 11, 12), status='not_fetched')
        rows = [newer, older, done, wrong_kind, unfetched]
        assert [c['id'] for c in release_figures.find_candidates(symbol)] == [newer]
    finally:
        drop(ids + rows)


def test_a_company_with_no_periodic_report_gets_its_newest_release_only():
    symbol = new_symbol(); newest, _ = seed_release(symbol, RELEASE_FILED); earlier, _ = seed_release(symbol, date(2026, 8, 20))
    try:
        assert [c['id'] for c in release_figures.find_candidates(symbol)] == [newest]
    finally:
        drop([newest, earlier])


def test_run_once_stores_the_checked_figures_and_an_empty_list_for_a_non_release(monkeypatch):
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()])
    release, _ = seed_release(symbol, RELEASE_FILED)
    notice, _ = seed_release(symbol, date(2026, 11, 20), text=PERSONNEL)
    try:
        async def call(model, system, user):
            return json.dumps(good_reply() if 'Financial Results' in user else {'is_earnings_release': False})
        monkeypatch.setattr(earnings_reader, '_call_model', call)
        assert release_figures.run_once(symbol=symbol, model=MODEL) == {'candidates': 2, 'written': 1, 'no_figures': 1, 'failed': 0}
        assert len(stored(release)) == 10 and stored(notice) == []
        assert release_figures.find_candidates(symbol) == []                     # neither is a candidate again
        assert release_figures.run_once(symbol=symbol, model=MODEL)['candidates'] == 0
    finally:
        drop(ids + [release, notice])


def test_a_failed_model_call_stores_nothing_and_is_not_retried_inside_the_backoff(monkeypatch):
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()]); release, accession = seed_release(symbol, RELEASE_FILED)
    now = [1000.0]
    monkeypatch.setattr(release_figures, '_clock', lambda: now[0])
    try:
        calls = fake_model(monkeypatch, RuntimeError('network'))
        assert release_figures.run_once(symbol=symbol, model=MODEL) == {'candidates': 1, 'written': 0, 'no_figures': 0, 'failed': 1}
        assert stored(release) is None and len(calls) == 1
        now[0] += release_figures.BACKOFF_SECONDS - 1
        assert release_figures.run_once(symbol=symbol, model=MODEL)['candidates'] == 0 and len(calls) == 1
        now[0] += 2
        fake_model(monkeypatch, good_reply())
        assert release_figures.run_once(symbol=symbol, model=MODEL)['written'] == 1 and len(stored(release)) == 10
    finally:
        drop(ids + [release])


def test_one_failing_release_does_not_stop_the_others(monkeypatch):
    first, second = new_symbol(), new_symbol()
    a, _ = seed_release(first, RELEASE_FILED, text='alpha ' + RELEASE); b, _ = seed_release(second, RELEASE_FILED, text='beta ' + RELEASE)
    try:
        async def call(model, system, user):
            if user.startswith('alpha'):
                raise RuntimeError('boom')
            return json.dumps(good_reply())
        monkeypatch.setattr(earnings_reader, '_call_model', call)
        stats = release_figures.run_once(symbol=second, model=MODEL)
        assert stats['written'] == 1
        release_figures._FAILED.clear()
        stats = release_figures.run_once(symbol=first, model=MODEL)
        assert stats['failed'] == 1 and stored(a) is None
    finally:
        drop([a, b])


def test_the_switch_off_extracts_nothing(monkeypatch):
    symbol = new_symbol(); release, _ = seed_release(symbol, RELEASE_FILED)
    monkeypatch.setenv(SWITCH, 'off')
    calls = fake_model(monkeypatch, good_reply())
    try:
        assert release_figures.run_once(symbol=symbol, model=MODEL) == {'candidates': 0, 'written': 0, 'no_figures': 0, 'failed': 0}
        assert calls == [] and stored(release) is None
    finally:
        drop([release])


def test_no_owner_or_model_means_nothing_happens(monkeypatch):
    symbol = new_symbol(); release, _ = seed_release(symbol, RELEASE_FILED)
    monkeypatch.setattr(release_figures, '_owner_model', lambda: None)
    calls = fake_model(monkeypatch, good_reply())
    try:
        assert release_figures.run_once(symbol=symbol)['written'] == 0
        assert calls == [] and stored(release) is None
    finally:
        drop([release])


def test_the_background_job_is_a_noop_when_off_and_calls_run_once_when_on(monkeypatch):
    from app import background
    seen = []
    monkeypatch.setattr(release_figures, 'run_once', lambda **k: seen.append(1) or {'candidates': 0, 'written': 0, 'no_figures': 0, 'failed': 0})
    monkeypatch.setenv(SWITCH, 'off')
    background.run_release_figures()
    assert seen == []
    monkeypatch.setenv(SWITCH, 'on')
    background.run_release_figures()
    assert seen == [1]


def test_the_manual_script_lists_candidates_and_writes_nothing_without_apply(monkeypatch, capsys):
    symbol = new_symbol(); release, accession = seed_release(symbol, RELEASE_FILED)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import extract_release_figures as script
    calls = fake_model(monkeypatch, good_reply())
    monkeypatch.setattr(sys, 'argv', ['extract_release_figures.py', '--symbol', symbol])
    try:
        assert script.main() == 0
        out = capsys.readouterr().out
        assert accession in out and '2026-11-17' in out and '1 candidate' in out
        assert calls == [] and stored(release) is None
    finally:
        drop([release])


# --- query_financials ---------------------------------------------------------------------------------------

def release_figures_of(reply=None, text=RELEASE):
    return release_figures.check_figures(reply or good_reply(), text, RELEASE_FILED)


def financials(**args):
    from app.agent_tools import query_financials
    with research_context('release-figures-test', cutoff=CUTOFF):
        return asyncio.run(query_financials.ainvoke(args))


def test_the_newest_period_from_the_release_comes_first_marked_unaudited():
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()]); release, _ = seed_release(symbol, RELEASE_FILED, figures=release_figures_of())
    try:
        result = financials(symbol=symbol, metrics=['revenue'], latest=True)
        rows = result['data']
        first = rows[0]
        assert first['period_end'] == '2026-10-25' and first['basis'] == 'press_release_unaudited' and first['form'] == '8-K'
        assert first['period_start'] is None and first['fiscal_year'] == 2027 and first['fiscal_period'] == 'Q3'
        assert first['period_span'] == 'quarter' and first['value'] == 115_844_000_000
        assert first['period_label'] == 'FY2027 Q3（截至 2026-10-25，3 个月）'
        assert '业绩新闻稿（未经审计）' in first['title'] and '未经审计' in first['excerpt'] and '以季报为准' in first['excerpt']
        assert first['source_url'].endswith('ex991-20261117.htm')
        assert [r['period_span'] for r in rows[:2]] == ['quarter', 'ytd9'] and rows[1]['value'] == 293_681_000_000
        q2 = [r for r in rows if r['form'] == '10-Q']
        assert q2 and all('basis' not in r for r in q2) and q2[0]['period_end'] == '2026-07-26'
        coverage = result['meta']['coverage']
        assert coverage['library']['press_release']['period'] == 'FY2027 Q3'
        assert any(f['form'] == '8-K' and f['period'] == 'FY2027 Q3' for f in coverage['filings_read'])
        assert coverage['freshness']['kind'] == 'press_release_ahead' and '未经审计' in coverage['freshness']['note']
        assert '库内最新一期正式报告是 FY2027 Q2' in coverage['freshness']['note']
    finally:
        drop(ids + [release])


def test_the_periodic_report_for_the_same_period_replaces_the_release_rows():
    symbol = new_symbol()
    q3 = {'form': '10-Q', 'filed': date(2026, 12, 1), 'figures': [
        figure('revenue', 'Revenue', [p('2026-07-27', '2026-10-25', 115_844_000_000, 2027, 'Q3'), p('2026-01-26', '2026-10-25', 293_681_000_000, 2027, 'Q3')])]}
    ids = seed(symbol, [q2_10q(), q3])
    release, _ = seed_release(symbol, RELEASE_FILED, figures=release_figures_of())
    try:
        rows = financials(symbol=symbol, metrics=['revenue'], latest=True)['data']
        assert {r['form'] for r in rows} == {'10-Q'} and rows[0]['period_end'] == '2026-10-25' and rows[0]['period_start'] == '2026-07-27'
        assert not [r for r in rows if r.get('basis')]
        # the balance sheet items the 10-Q fixture does not state are still the release's
        both = financials(symbol=symbol, metrics=['revenue', 'total_assets'], latest=True)
        assert [r['form'] for r in both['data'] if r['metric'] == 'total_assets'][0] == '8-K'
        assert both['meta']['coverage']['freshness']['kind'] != 'cadence'
    finally:
        drop(ids + [release])


def test_an_explicit_form_filter_is_not_mixed_with_the_release_but_the_receipt_names_it():
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()]); release, _ = seed_release(symbol, RELEASE_FILED, figures=release_figures_of())
    try:
        result = financials(symbol=symbol, metrics=['revenue'], form='10-Q', latest=True)
        assert {r['form'] for r in result['data']} == {'10-Q'} and not [r for r in result['data'] if r.get('basis')]
        held = [n for n in result['meta']['coverage']['not_read'] if n['form'] == '8-K']
        assert held == [{'form': '8-K', 'filed_at': '2026-11-17', 'period': 'FY2027 Q3', 'why': 'form_filter'}]
    finally:
        drop(ids + [release])


def test_an_empty_or_unmarked_8k_figures_row_is_never_served():
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()])
    empty, _ = seed_release(symbol, RELEASE_FILED, figures=[])
    other, _ = seed_release(symbol, date(2026, 11, 18), figures=[figure('revenue', 'Revenue', [p('2026-07-27', '2026-10-25', 1, 2027, 'Q3')])])
    try:
        rows = financials(symbol=symbol, metrics=['revenue'], latest=True)['data']
        assert {r['form'] for r in rows} == {'10-Q'}
    finally:
        drop(ids + [empty, other])


def test_with_the_switch_off_query_financials_is_exactly_what_it_was(monkeypatch):
    symbol = new_symbol(); ids = seed(symbol, [q2_10q()])
    try:
        monkeypatch.setenv(SWITCH, 'off')
        before = financials(symbol=symbol, latest=True)
        release, _ = seed_release(symbol, RELEASE_FILED, figures=release_figures_of())
        ids.append(release)
        after = financials(symbol=symbol, latest=True)
        assert json.dumps(after, sort_keys=True, default=str) == json.dumps(before, sort_keys=True, default=str)
        assert not [r for r in after['data'] if r['form'] == '8-K']
    finally:
        drop(ids)


def description(env):
    code = "from app.agent_tools import query_financials; print(query_financials.description)"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
                            env={**os.environ, **env})
    assert result.returncode == 0, result.stderr[-500:]
    return result.stdout.rstrip('\n')


def test_the_tool_description_gets_the_sentence_only_when_the_switch_is_on():
    on = description({SWITCH: 'on'})
    off = description({SWITCH: 'off'})
    assert 'press_release_unaudited' in on and 'press_release_unaudited' not in off
    assert on.startswith(off) and on[len(off):] == release_figures_note()
    assert off.endswith('Prefer it over filing text for these numbers.')


def release_figures_note():
    from app.agent_tools import RELEASE_FIGURES_NOTE
    return RELEASE_FIGURES_NOTE


# --- spans without a start date -----------------------------------------------------------------------------

def test_a_period_with_months_and_no_start_is_labelled_by_its_months_without_a_made_up_start():
    base = dict(document_end=date(2026, 10, 25), dei_fiscal_year=2027, dei_fiscal_period='Q3')
    for months, span, label in ((3, 'quarter', 'FY2027 Q3（截至 2026-10-25，3 个月）'), (6, 'ytd6', 'FY2027 上半年累计（截至 2026-10-25，6 个月）'),
                                (9, 'ytd9', 'FY2027 前三季度累计（截至 2026-10-25，9 个月）'), (12, 'annual', 'FY2027（截至 2026-10-25，12 个月）')):
        got = period_label({'start': None, 'end': '2026-10-25', 'span_months': months}, **base)
        assert (got['span'], got['label'], got['fiscal_year']) == (span, label, 2027)


def test_periods_without_span_months_keep_their_old_labels_and_rows():
    base = dict(document_end=date(2026, 6, 27), dei_fiscal_year=2026, dei_fiscal_period='Q3')
    assert period_label({'start': '2026-03-29', 'end': '2026-06-27'}, **base)['label'] == 'FY2026 Q3（2026-03-29 至 2026-06-27，3 个月）'
    assert period_label({'start': '2025-09-28', 'end': '2026-06-27'}, **base)['label'] == 'FY2026 前三季度累计（2025-09-28 至 2026-06-27，9 个月）'
    assert period_label({'start': None, 'end': '2026-06-27'}, **base)['label'] == '截至 2026-06-27（FY2026 Q3 末，时点数）'
    filing = {'id': 'x', 'symbol': 'ZZZZ', 'form': '10-Q', 'accession_number': 'a', 'filed_at': date(2026, 8, 1), 'source_url': 'u',
              'content_financials': [figure('revenue', 'Revenue', [p('2026-03-29', '2026-06-27', 94_000_000_000, 2026, 'Q3')])]}
    row = figure_rows(filing)[0]
    assert 'basis' not in row and row['period_start'] == '2026-03-29' and row['title'] == 'ZZZZ 10-Q 2026-08-01 · 营业收入 FY2026 Q3'
    assert row['excerpt'].endswith('XBRL 披露值。')
