"""Company facts: each company's quarterly and annual figures, margins and growth, by code only, every number with its source."""
import copy
import threading
from datetime import date

import pytest
from sqlalchemy import delete, select

from app import company_facts as cf
from app.database import Base, SessionLocal, engine
from app.models import CompanyFact, CompanyRatio
from tests.sw1_filings import aapl_filings, drop, figure, new_symbol, nvda_filings, p, seed


@pytest.fixture
def world(disposable_database):
    Base.metadata.create_all(engine)
    made = {'ids': [], 'symbols': []}

    def put(filings, symbol=None):
        symbol = symbol or new_symbol()
        made['symbols'].append(symbol)
        made['ids'] += seed(symbol, filings)
        return symbol
    yield put
    drop(made['ids'])
    with SessionLocal() as db:
        for symbol in made['symbols']:
            db.execute(delete(CompanyFact).where(CompanyFact.symbol == symbol))
            db.execute(delete(CompanyRatio).where(CompanyRatio.symbol == symbol))
        db.commit()


def consistent_aapl():
    """aapl_filings() with year-to-date figures that add up (143 + 111 + 94 = 348; 143 + 111 = 254), so a stated quarter agrees with its YTD."""
    filings = copy.deepcopy(aapl_filings())
    for filing in filings:
        for fig in filing['figures'] or []:
            for period in fig['periods']:
                if fig['metric'] == 'revenue' and period['value'] == 364_357_000_000:
                    period['value'] = 348_000_000_000
                if fig['metric'] == 'revenue' and period['value'] == 200_000_000_000:
                    period['value'] = 254_000_000_000
    return filings


def facts(symbol):
    with SessionLocal() as db:
        return {(f.metric, f.period_end.isoformat(), f.span): f for f in db.scalars(select(CompanyFact).where(CompanyFact.symbol == symbol))}


def ratios(symbol):
    with SessionLocal() as db:
        return {(r.name, r.period_end.isoformat(), r.span): r for r in db.scalars(select(CompanyRatio).where(CompanyRatio.symbol == symbol))}


def snapshot(symbol):
    cols = lambda model: [c.name for c in model.__table__.columns]
    with SessionLocal() as db:
        return ([tuple(getattr(r, c) for c in cols(CompanyFact)) for r in db.scalars(select(CompanyFact).where(CompanyFact.symbol == symbol).order_by(CompanyFact.id))],
                [tuple(getattr(r, c) for c in cols(CompanyRatio)) for r in db.scalars(select(CompanyRatio).where(CompanyRatio.symbol == symbol).order_by(CompanyRatio.id))])


def flow(metric, periods, unit='USD'):
    return {'metric': metric, 'label': metric, 'concept': f'us-gaap:{metric}', 'unit': unit, 'periods': periods}


def press(metric, end, value, months, fy, fp, start=None):
    period = {'unit': 'USD', 'value': value, 'start': start, 'end': end, 'fiscal_period': fp, 'fiscal_year': fy,
              'basis': 'press_release_unaudited', 'span_months': months}
    return {'metric': metric, 'label': metric, 'concept': 'press_release', 'unit': 'USD', 'basis': 'press_release_unaudited', 'periods': [period]}


# --- stated figures ---------------------------------------------------------------------------------------------

def test_a_quarter_stated_by_a_10q_carries_its_source(world):
    symbol = world(consistent_aapl())
    cf.refresh(symbol)
    fact = facts(symbol)[('revenue', '2026-06-27', 'quarter')]
    assert int(fact.value) == 94_000_000_000 and fact.kind == 'stated' and fact.basis == 'reported' and fact.unit == 'USD'
    assert (fact.fiscal_year, fact.fiscal_period, fact.form, fact.concept) == (2026, 'Q3', '10-Q', 'revenue')
    assert fact.accession_number and fact.source_url and fact.filed_at == date(2026, 8, 1) and fact.status == 'ok'
    assert fact.formula is None and not fact.parents


def test_margins_of_a_quarter(world):
    symbol = world(consistent_aapl())
    cf.refresh(symbol)
    margin = ratios(symbol)[('gross_margin', '2026-06-27', 'quarter')]
    assert abs(float(margin.value) - 54.77 / 94) < 1e-8 and margin.formula == 'gross_profit / revenue' and margin.basis == 'reported'
    f = facts(symbol)
    assert set(margin.parents) == {str(f[('gross_profit', '2026-06-27', 'quarter')].id), str(f[('revenue', '2026-06-27', 'quarter')].id)}


def test_qoq_and_yoy_name_their_parents(world):
    symbol = world(consistent_aapl())
    cf.refresh(symbol)
    r, f = ratios(symbol), facts(symbol)
    qoq = r[('revenue_qoq', '2026-06-27', 'quarter')]
    yoy = r[('revenue_yoy', '2026-06-27', 'quarter')]
    assert abs(float(qoq.value) - (94 - 111) / 111) < 1e-8 and qoq.formula == '(a - b) / b'
    assert qoq.parents == [str(f[('revenue', '2026-06-27', 'quarter')].id), str(f[('revenue', '2026-03-28', 'quarter')].id)]
    assert abs(float(yoy.value) - (94 - 85.777) / 85.777) < 1e-8
    assert yoy.parents == [str(f[('revenue', '2026-06-27', 'quarter')].id), str(f[('revenue', '2025-06-28', 'quarter')].id)]
    pp = r[('gross_margin_change_yoy_pp', '2026-06-27', 'quarter')]
    assert set(pp.parents) == {str(r[('gross_margin', '2026-06-27', 'quarter')].id), str(r[('gross_margin', '2025-06-28', 'quarter')].id)}


def test_gross_margin_change_in_percentage_points(world):
    symbol = world(consistent_aapl())
    cf.refresh(symbol)
    pp = ratios(symbol)[('gross_margin_change_yoy_pp', '2026-06-27', 'quarter')]
    assert abs(float(pp.value) - (54.77 / 94 - 46 / 85.777) * 100) < 1e-6


# --- derived quarters (review focus 1, 2, 3) --------------------------------------------------------------------

def test_q3_cash_flow_comes_from_ytd9_minus_ytd6_of_the_same_year(world):
    q2 = [flow('operating_cash_flow', [p('2025-10-01', '2026-03-31', 60, 2026, 'Q2')])]
    q3 = [flow('operating_cash_flow', [p('2025-10-01', '2026-06-30', 100, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    f = facts(symbol)
    derived = f[('operating_cash_flow', '2026-06-30', 'quarter')]
    assert int(derived.value) == 40 and derived.kind == 'derived' and derived.formula == 'ytd9 - ytd6'
    assert derived.period_start == date(2026, 4, 1) and (derived.fiscal_year, derived.fiscal_period) == (2026, 'Q3')
    assert set(derived.parents) == {str(f[('operating_cash_flow', '2026-06-30', 'ytd9')].id), str(f[('operating_cash_flow', '2026-03-31', 'ytd6')].id)}


def test_a_missing_ytd6_gives_no_quarter_and_never_shows_ytd9_as_one(world):
    q3 = [flow('operating_cash_flow', [p('2025-10-01', '2026-06-30', 100, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    f = facts(symbol)
    assert ('operating_cash_flow', '2026-06-30', 'ytd9') in f and not [k for k in f if k[2] == 'quarter']


def test_q4_is_the_annual_figure_minus_ytd9(world):
    symbol = world(consistent_aapl())
    cf.refresh(symbol)
    f = facts(symbol)
    q4 = f[('revenue', '2026-09-26', 'quarter')]
    assert int(q4.value) == 478_834_000_000 - 348_000_000_000 and q4.formula == 'annual - ytd9' and q4.kind == 'derived'
    assert (q4.fiscal_year, q4.fiscal_period) == (2026, 'Q4') and q4.period_start == date(2026, 6, 28)
    assert int(f[('gross_profit', '2026-09-26', 'quarter')].value) == 233_602_000_000 - 178_782_000_000 and q4.filed_at == date(2026, 11, 3)
    assert ('gross_margin', '2026-09-26', 'quarter') in ratios(symbol)


def test_no_q4_when_the_year_end_does_not_line_up(world):
    # The annual figure starts a month later than the nine-month figure: a changed fiscal year, not one year's Q4.
    tenq = [flow('revenue', [p('2025-10-01', '2026-06-30', 700, 2026, 'Q3')])]
    tenk = [flow('revenue', [p('2025-11-01', '2026-09-30', 900, 2026, 'FY')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}, {'form': '10-K', 'filed': date(2026, 11, 20), 'figures': tenk}])
    cf.refresh(symbol)
    assert not [k for k in facts(symbol) if k[2] == 'quarter']


def test_no_q4_when_the_fiscal_year_end_moved(world):
    tenq = [flow('revenue', [p('2025-10-01', '2026-06-30', 700, 2026, 'Q3')])]
    tenk = [flow('revenue', [p('2025-10-01', '2026-12-31', 1000, 2026, 'FY')])]   # 15 months: not an annual span at all
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}, {'form': '10-K', 'filed': date(2027, 2, 20), 'figures': tenk}])
    cf.refresh(symbol)
    assert not [k for k in facts(symbol) if k[2] == 'quarter']


def test_a_52_53_week_year_still_gives_its_q4(world):
    tenq = [flow('revenue', [p('2025-09-29', '2026-06-27', 700, 2026, 'Q3')])]
    tenk = [flow('revenue', [p('2025-09-29', '2026-10-03', 1000, 2026, 'FY')])]   # a 53-week year ends a week later
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}, {'form': '10-K', 'filed': date(2026, 11, 20), 'figures': tenk}])
    cf.refresh(symbol)
    assert int(facts(symbol)[('revenue', '2026-10-03', 'quarter')].value) == 300


# --- press releases (review focus 4) -----------------------------------------------------------------------------

def test_a_release_is_kept_while_no_report_covers_its_quarter_then_superseded(world):
    tenq = [flow('revenue', [p('2026-03-29', '2026-06-27', 94, 2026, 'Q3'), p('2025-03-30', '2025-06-28', 80, 2026, 'Q3')])]
    release = [press('revenue', '2026-09-26', 120, 3, 2026, 'Q4'), press('revenue', '2026-06-27', 95, 3, 2026, 'Q3')]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}, {'form': '8-K', 'filed': date(2026, 10, 30), 'figures': release}])
    cf.refresh(symbol)
    f = facts(symbol)
    new = f[('revenue', '2026-09-26', 'quarter')]
    assert int(new.value) == 120 and new.basis == 'press_release_unaudited' and new.form == '8-K' and new.concept == 'press_release'
    assert new.period_start is None and (new.fiscal_year, new.fiscal_period) == (2026, 'Q4')
    # The periodic report beats the release for the same period.
    assert int(f[('revenue', '2026-06-27', 'quarter')].value) == 94 and f[('revenue', '2026-06-27', 'quarter')].basis == 'reported'
    # A ratio resting on the release carries its weaker basis.
    qoq = ratios(symbol)[('revenue_qoq', '2026-09-26', 'quarter')]
    assert qoq.basis == 'press_release_unaudited' and abs(float(qoq.value) - (120 - 94) / 94) < 1e-8
    # The 10-Q for that quarter arrives: the release figure is superseded.
    tenq_q4 = [flow('revenue', [p('2026-06-28', '2026-09-26', 119, 2026, 'Q4')])]
    world([{'form': '10-Q', 'filed': date(2026, 11, 20), 'figures': tenq_q4}], symbol=symbol)
    cf.refresh(symbol)
    superseded = facts(symbol)[('revenue', '2026-09-26', 'quarter')]
    assert int(superseded.value) == 119 and superseded.basis == 'reported' and superseded.form == '10-Q'


def test_a_release_no_newer_than_the_reports_adds_nothing(world):
    tenq = [flow('revenue', [p('2026-03-29', '2026-06-27', 94, 2026, 'Q3')]), flow('total_assets', [p(None, '2026-06-27', 500, 2026, 'Q3')])]
    release = [press('revenue', '2026-06-27', 95, 3, 2026, 'Q3'), press('net_income', '2026-06-27', 9, 3, 2026, 'Q3')]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}, {'form': '8-K', 'filed': date(2026, 7, 30), 'figures': release}])
    cf.refresh(symbol)
    assert {k for k in facts(symbol)} == {('revenue', '2026-06-27', 'quarter'), ('total_assets', '2026-06-27', 'instant')}


# --- checks ------------------------------------------------------------------------------------------------------

def test_a_gross_profit_within_half_a_percent_passes(world):
    tenq = [flow('revenue', [p('2026-04-01', '2026-06-30', 1000, 2026, 'Q3')]), flow('cost_of_revenue', [p('2026-04-01', '2026-06-30', 400, 2026, 'Q3')]),
            flow('gross_profit', [p('2026-04-01', '2026-06-30', 602, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}])
    cf.refresh(symbol)
    assert facts(symbol)[('gross_profit', '2026-06-30', 'quarter')].status == 'ok'


def test_a_negative_derived_revenue_is_marked(world):
    q2 = [flow('revenue', [p('2025-10-01', '2026-03-31', 600, 2026, 'Q2')])]
    q3 = [flow('revenue', [p('2025-10-01', '2026-06-30', 500, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    derived = facts(symbol)[('revenue', '2026-06-30', 'quarter')]
    assert derived.status == 'check_failed' and 'negative' in derived.reason


def test_units_must_match_for_a_ratio(world):
    tenq = [flow('revenue', [p('2026-04-01', '2026-06-30', 1000, 2026, 'Q3')]), flow('net_income', [p('2026-04-01', '2026-06-30', 100, 2026, 'Q3', unit='EUR')], unit='EUR')]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq}])
    cf.refresh(symbol)
    assert ('net_income', '2026-06-30', 'quarter') in facts(symbol) and ('net_margin', '2026-06-30', 'quarter') not in ratios(symbol)


# --- the whole thing ---------------------------------------------------------------------------------------------

def test_refreshing_twice_gives_identical_rows(world):
    symbol = world(consistent_aapl())
    first = cf.refresh(symbol)
    one = snapshot(symbol)
    second = cf.refresh(symbol)
    assert snapshot(symbol) == one and first == second and one[0] and one[1]


def test_a_symbol_without_figures_gets_no_rows_and_no_error(world):
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': None}])
    result = cf.refresh(symbol)
    assert result['facts'] == 0 and result['ratios'] == 0 and not facts(symbol) and cf.latest_quarter(symbol) is None
    assert cf.refresh('ZZZZ')['facts'] == 0


def test_refresh_all_covers_every_symbol_with_figures(world):
    one, two = world(aapl_filings()), world(nvda_filings())
    result = cf.refresh_all()
    assert result['symbols'] >= 2 and facts(one) and facts(two)
    assert cf.refresh_all(limit=1)['symbols'] == 1


def test_latest_quarter_for_an_nvidia_shaped_company(world):
    symbol = world(nvda_filings())
    cf.refresh(symbol)
    latest = cf.latest_quarter(symbol)
    assert latest['symbol'] == symbol and latest['fiscal_label'] == 'FY2027 Q2' and latest['period_end'] == '2026-07-26'
    assert latest['basis'] == 'reported'
    revenue = next(x for x in latest['facts'] if x['metric'] == 'revenue')
    assert revenue['value'] == 46_000_000_000 and revenue['unit'] == 'USD' and revenue['form'] == '10-Q' and revenue['accession_number']
    qoq = next(x for x in latest['ratios'] if x['name'] == 'revenue_qoq')
    assert abs(qoq['value'] - 2 / 44) < 1e-8 and qoq['formula'] == '(a - b) / b' and len(qoq['parents']) == 2
    used = {x['id']: x for x in latest['comparison_facts']}
    assert used[qoq['parents'][1]]['value'] == 44_000_000_000 and used[qoq['parents'][1]]['fiscal_period'] == 'Q1'
    assert not [x for x in latest['ratios'] if x['name'].endswith('_yoy')]


def test_nvidia_fiscal_labels_follow_its_own_year_end_not_the_calendar(world):
    symbol = world(nvda_filings())
    cf.refresh(symbol)
    f = facts(symbol)
    assert (f[('revenue', '2026-01-25', 'quarter')].fiscal_year, f[('revenue', '2026-01-25', 'quarter')].fiscal_period) == (2026, 'Q4')
    assert (f[('revenue', '2026-04-26', 'quarter')].fiscal_year, f[('revenue', '2026-04-26', 'quarter')].fiscal_period) == (2027, 'Q1')


# --- fix round 1 ------------------------------------------------------------------------------------------------

def test_a_restated_year_is_not_subtracted_from_an_unrestated_nine_months(world):
    ytd9 = [flow('revenue', [p('2025-10-01', '2026-06-30', 700, 2026, 'Q3')])]
    fy26 = [flow('revenue', [p('2025-10-01', '2026-09-30', 1000, 2026, 'FY')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': ytd9}, {'form': '10-K', 'filed': date(2026, 11, 20), 'figures': fy26}])
    cf.refresh(symbol)
    assert int(facts(symbol)[('revenue', '2026-09-30', 'quarter')].value) == 300 and facts(symbol)[('revenue', '2026-09-30', 'quarter')].status == 'ok'
    fy27 = [flow('revenue', [p('2026-10-01', '2027-09-30', 1200, 2027, 'FY'), p('2025-10-01', '2026-09-30', 800, 2027, 'FY')])]
    world([{'form': '10-K', 'filed': date(2027, 11, 20), 'figures': fy27}], symbol=symbol)
    cf.refresh(symbol)
    f, r = facts(symbol), ratios(symbol)
    assert int(f[('revenue', '2026-09-30', 'annual')].value) == 800 and f[('revenue', '2026-09-30', 'annual')].status == 'ok'
    q4 = f[('revenue', '2026-09-30', 'quarter')]
    assert q4.status == 'check_failed' and '年度数已重述，九个月累计未同步重述，无法推出第四季' in q4.reason
    assert all(x.value is None for x in r.values() if x.status != 'ok')


def test_a_restated_nine_months_is_not_reduced_by_an_unrestated_half_year(world):
    q2 = [flow('revenue', [p('2025-10-01', '2026-03-31', 600, 2026, 'Q2')])]
    q3 = [flow('revenue', [p('2025-10-01', '2026-06-30', 900, 2026, 'Q3')])]
    later = [flow('revenue', [p('2025-10-01', '2026-06-30', 880, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3},
                    {'form': '10-Q', 'filed': date(2026, 12, 1), 'figures': later}])
    cf.refresh(symbol)
    derived = facts(symbol)[('revenue', '2026-06-30', 'quarter')]
    assert derived.status == 'check_failed' and '九个月累计已重述，上半年累计未同步重述，无法推出第三季' in derived.reason


def test_parents_that_come_from_the_same_restating_filing_are_derived(world):
    q2 = [flow('revenue', [p('2025-10-01', '2026-03-31', 600, 2026, 'Q2')])]
    q3 = [flow('revenue', [p('2025-10-01', '2026-06-30', 900, 2026, 'Q3')])]
    later = [flow('revenue', [p('2025-10-01', '2026-06-30', 880, 2026, 'Q3'), p('2025-10-01', '2026-03-31', 590, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3},
                    {'form': '10-Q', 'filed': date(2026, 12, 1), 'figures': later}])
    cf.refresh(symbol)
    derived = facts(symbol)[('revenue', '2026-06-30', 'quarter')]
    assert derived.status == 'ok' and int(derived.value) == 290 and derived.filed_at == date(2026, 12, 1)


def two_quarters_and_a_half_year(ytd6):
    q1 = [flow('revenue', [p('2025-10-01', '2025-12-31', 100, 2026, 'Q1')])]
    q2 = [flow('revenue', [p('2026-01-01', '2026-03-31', 150, 2026, 'Q2'), p('2025-10-01', '2026-03-31', ytd6, 2026, 'Q2')])]
    return [{'form': '10-Q', 'filed': date(2026, 2, 1), 'figures': q1}, {'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}]


def test_a_stated_quarter_that_disagrees_with_its_ytd_is_marked_and_hidden(world):
    symbol = world(two_quarters_and_a_half_year(400))     # 400 - 100 = 300, not 150
    cf.refresh(symbol)
    stated = facts(symbol)[('revenue', '2026-03-31', 'quarter')]
    assert stated.status == 'check_failed' and stated.kind == 'stated' and '150' in stated.reason and '300' in stated.reason
    assert stated.accession_number in stated.reason and '10-Q' in stated.reason
    assert ratios(symbol)[('revenue_qoq', '2026-03-31', 'quarter')].status == 'check_failed'
    assert cf.latest_quarter(symbol)['period_end'] == '2025-12-31'     # the newest quarter that is trustworthy


def test_a_stated_quarter_that_agrees_with_its_ytd_stays_and_is_not_duplicated(world):
    symbol = world(two_quarters_and_a_half_year(250))
    cf.refresh(symbol)
    stated = facts(symbol)[('revenue', '2026-03-31', 'quarter')]
    assert stated.status == 'ok' and stated.kind == 'stated' and int(stated.value) == 150
    with SessionLocal() as db:
        assert len(db.scalars(select(CompanyFact).where(CompanyFact.symbol == symbol, CompanyFact.span == 'quarter',
                                                         CompanyFact.metric == 'revenue', CompanyFact.period_end == date(2026, 3, 31))).all()) == 1


@pytest.mark.parametrize('before,after,kind', [(10, -5, 'turned_loss'), (-5, 10, 'turned_profit'), (-5, -8, 'loss_widened'),
                                                (-8, -5, 'loss_narrowed'), (0, 7, 'from_zero')])
def test_growth_on_a_zero_or_negative_base_or_a_sign_change_has_no_percentage(world, before, after, kind):
    q2 = [flow('net_income', [p('2026-01-01', '2026-03-31', before, 2026, 'Q2')])]
    q3 = [flow('net_income', [p('2026-04-01', '2026-06-30', after, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    row = ratios(symbol)[('net_income_qoq', '2026-06-30', 'quarter')]
    assert row.value is None and row.status == 'not_meaningful' and row.change_kind == kind
    assert int(row.current_value) == after and int(row.base_value) == before
    assert cf._ratio_dict(row)['change_kind'] == kind and cf._ratio_dict(row)['value'] is None


def test_latest_quarter_carries_a_not_meaningful_change_as_data(world):
    q2 = [flow('revenue', [p('2026-01-01', '2026-03-31', 50, 2026, 'Q2')]), flow('net_income', [p('2026-01-01', '2026-03-31', 10, 2026, 'Q2')])]
    q3 = [flow('revenue', [p('2026-04-01', '2026-06-30', 60, 2026, 'Q3')]), flow('net_income', [p('2026-04-01', '2026-06-30', -5, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    row = next(x for x in cf.latest_quarter(symbol)['ratios'] if x['name'] == 'net_income_qoq')
    assert row['value'] is None and row['change_kind'] == 'turned_loss' and row['current_value'] == -5 and row['base_value'] == 10 and row['status'] == 'not_meaningful'


def test_concurrent_refreshes_of_one_symbol_all_succeed(world):
    symbol = world(consistent_aapl())
    errors = []

    def run():
        try:
            cf.refresh(symbol)
        except Exception as exc:    # noqa: BLE001 - the test reports whatever a refresh raised
            errors.append(repr(exc))
    for _ in range(3):
        threads = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    assert not errors and facts(symbol) and ratios(symbol)


def trio(revenue, cost, gross):
    return [flow('revenue', [p('2026-04-01', '2026-06-30', revenue, 2026, 'Q3')]), flow('cost_of_revenue', [p('2026-04-01', '2026-06-30', cost, 2026, 'Q3')]),
            flow('gross_profit', [p('2026-04-01', '2026-06-30', gross, 2026, 'Q3')])]


def test_when_revenue_cost_and_gross_profit_disagree_all_three_are_marked(world):
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': trio(500, 400, 600)}])
    result = cf.refresh(symbol)
    f = facts(symbol)
    for metric in ('revenue', 'cost_of_revenue', 'gross_profit'):
        assert f[(metric, '2026-06-30', 'quarter')].status == 'check_failed' and 'disagree' in f[(metric, '2026-06-30', 'quarter')].reason
    assert {x['metric'] for x in result['check_failures']} == {'revenue', 'cost_of_revenue', 'gross_profit'}
    margin = ratios(symbol)[('gross_margin', '2026-06-30', 'quarter')]
    assert margin.status == 'check_failed' and margin.value is None
    assert cf.latest_quarter(symbol) is None


def test_a_figure_another_filing_states_again_stays_when_the_trio_disagrees(world):
    later = [flow('revenue', [p('2027-04-01', '2027-06-30', 1300, 2027, 'Q3'), p('2026-04-01', '2026-06-30', 1000, 2027, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': trio(1000, 400, 700)}, {'form': '10-Q', 'filed': date(2027, 8, 1), 'figures': later}])
    cf.refresh(symbol)
    f = facts(symbol)
    assert f[('revenue', '2026-06-30', 'quarter')].status == 'ok'
    assert f[('cost_of_revenue', '2026-06-30', 'quarter')].status == 'check_failed' and f[('gross_profit', '2026-06-30', 'quarter')].status == 'check_failed'


def test_a_10k_outranks_a_10q_filed_the_same_day(world):
    symbol = world([{'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': [flow('revenue', [p('2026-04-01', '2026-06-30', 100, 2026, 'Q3')])]},
                    {'form': '10-K', 'filed': date(2026, 8, 1), 'figures': [flow('revenue', [p('2026-04-01', '2026-06-30', 101, 2026, 'Q3')])]}])
    cf.refresh(symbol)
    assert facts(symbol)[('revenue', '2026-06-30', 'quarter')].form == '10-K'


def test_two_cumulative_figures_under_different_concepts_are_not_subtracted(world):
    q2 = [{**flow('operating_cash_flow', [p('2025-10-01', '2026-03-31', 60, 2026, 'Q2')]), 'concept': 'A'}]
    q3 = [{**flow('operating_cash_flow', [p('2025-10-01', '2026-06-30', 100, 2026, 'Q3')]), 'concept': 'B'}]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    assert facts(symbol)[('operating_cash_flow', '2026-06-30', 'quarter')].status == 'check_failed'


def test_a_negative_derived_cost_of_revenue_is_marked(world):
    q2 = [flow('cost_of_revenue', [p('2025-10-01', '2026-03-31', 600, 2026, 'Q2')])]
    q3 = [flow('cost_of_revenue', [p('2025-10-01', '2026-06-30', 500, 2026, 'Q3')])]
    symbol = world([{'form': '10-Q', 'filed': date(2026, 5, 1), 'figures': q2}, {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': q3}])
    cf.refresh(symbol)
    assert facts(symbol)[('cost_of_revenue', '2026-06-30', 'quarter')].status == 'check_failed'


def test_refresh_all_clears_the_rows_of_a_symbol_whose_figures_are_gone(world):
    symbol = world(nvda_filings())
    cf.refresh(symbol)
    assert facts(symbol)
    with SessionLocal() as db:
        from app.models import SecFilingInventory
        for row in db.scalars(select(SecFilingInventory).where(SecFilingInventory.symbol == symbol)):
            row.content_financials = None
        db.commit()
    cf.refresh_all()
    assert not facts(symbol) and not ratios(symbol)
