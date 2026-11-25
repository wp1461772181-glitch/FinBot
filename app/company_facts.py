"""Company facts: each company's latest quarterly and annual figures, margins and growth, kept by code, every number with its source.

Nothing here calls a model or looks anything up.  The only input is what the stored filings already say
(``SecFilingInventory.content_financials``: periodic XBRL figures, and the figures of an 8-K earnings press release).

* A figure exists only if a stored filing states it (``kind='stated'``), or both parents of a subtraction exist and their periods
  fit exactly (``kind='derived'``: ``ytd6 - q1``, ``ytd9 - ytd6``, ``annual - ytd9``; same fiscal year, adjacent spans).
* A ratio exists only if numerator and denominator share period, span and unit.
* Where the data allows a consistency check (gross profit = revenue - cost of revenue within 0.5 %; a derived revenue is not
  negative) a failed check marks the row ``check_failed`` with a reason.  The row is kept for inspection and never offered as a fact.
* A periodic report beats an earnings release for the same ``(metric, period_end, span)``; a release counts only while it is ahead of
  every periodic report (the rule ``query_financials`` follows), and the newest periodic filing wins when a figure is restated.
* A refresh of the same inputs gives the same rows: ids are derived from the row's key, and ``built_at`` is kept for a row that did
  not change.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import delete, select

from .agent_workflow.financials import PRESS_RELEASE_BASIS, figure_rows
from .database import SessionLocal
from .models import CompanyFact, CompanyRatio, SecFilingInventory

log = logging.getLogger(__name__)

PERIODIC_FORMS = ('10-K', '10-Q', '20-F')
FLOW_METRICS = ('revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 'net_income', 'operating_cash_flow')
FLOW_SPANS = ('quarter', 'ytd6', 'ytd9', 'annual')
MARGINS = (('gross_margin', 'gross_profit'), ('operating_margin', 'operating_income'), ('net_margin', 'net_income'))
GROWTH_METRICS = (('revenue', 'revenue'), ('net_income', 'net_income'))
REPORTED = 'reported'
_BASIS_RANK = {REPORTED: 0, PRESS_RELEASE_BASIS: 1}
# One quarter is 91 days give or take a week; one year 364 or 371 days (52/53 weeks) give or take a week.
_QUARTER_GAP = (84, 98)
_YEAR_GAP = (357, 372)
_START_SLACK = 7
_GP_TOLERANCE = Decimal('0.005')
_DERIVATIONS = (('ytd6', 'quarter', 'ytd6 - q1', 'Q2'), ('ytd9', 'ytd6', 'ytd9 - ytd6', 'Q3'), ('annual', 'ytd9', 'annual - ytd9', 'Q4'))
_PREVIOUS_PERIOD = {'Q1': 'Q4', 'Q2': 'Q1', 'Q3': 'Q2', 'Q4': 'Q3'}
_NAMESPACE = uuid.UUID('6f1c1d5e-3b53-4e0e-9a0e-2b7a0c0f6c11')
_FACT_COLUMNS = ('id', 'symbol', 'metric', 'period_start', 'period_end', 'span', 'fiscal_year', 'fiscal_period', 'value', 'unit', 'kind', 'basis',
                 'accession_number', 'form', 'filed_at', 'source_url', 'concept', 'formula', 'parents', 'status', 'reason')
_RATIO_COLUMNS = ('id', 'symbol', 'name', 'period_end', 'span', 'fiscal_year', 'fiscal_period', 'value', 'formula', 'parents', 'basis', 'status', 'reason')


def _weakest(*bases):
    return max(bases, key=lambda b: _BASIS_RANK.get(b, 1))


def _id(*parts):
    return uuid.uuid5(_NAMESPACE, '|'.join(str(x) for x in parts))


def _gap(later, earlier):
    return (later - earlier).days


def _within(days, bounds):
    return bounds[0] <= days <= bounds[1]


def _ratio_value(numerator, denominator):
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal('0.00000001'), rounding=ROUND_HALF_EVEN)


# --- reading the stored filings --------------------------------------------------------------------------------

def _filings(db, symbol):
    found = db.scalars(select(SecFilingInventory).where(
        SecFilingInventory.symbol == symbol, SecFilingInventory.form.in_(PERIODIC_FORMS + ('8-K',)),
        SecFilingInventory.content_status == 'fetched', SecFilingInventory.content_financials.is_not(None))
        .order_by(SecFilingInventory.filed_at.desc(), SecFilingInventory.accession_number.desc())).all()
    return [{'id': r.id, 'symbol': r.symbol, 'form': r.form, 'accession_number': r.accession_number, 'filed_at': r.filed_at,
             'source_url': r.source_url, 'content_source_url': r.content_source_url, 'content_financials': r.content_financials}
            for r in found if r.content_financials]


def _stated(symbol, filings):
    """Stated facts keyed (metric, period_end, span): the newest periodic filing's figure, then an earnings release that is ahead."""
    periodic = [f for f in filings if f['form'] in PERIODIC_FORMS]
    picked, latest_report = {}, ''
    for filing in periodic:                       # newest first: a restatement beats the figure it restates
        for row in figure_rows(filing):
            latest_report = max(latest_report, row['period_end'][:10])
            if row['period_span'] != 'other':
                picked.setdefault((row['metric'], row['period_end'][:10], row['period_span']), row)
    for filing in filings:
        if filing['form'] != '8-K':
            continue
        rows = [r for r in figure_rows(filing) if r.get('basis') == PRESS_RELEASE_BASIS and r['period_span'] != 'other']
        if not rows or max(r['period_end'][:10] for r in rows) <= latest_report:
            continue                              # the periodic reports have caught up with this release
        for row in rows:
            picked.setdefault((row['metric'], row['period_end'][:10], row['period_span']), row)
    facts = {}
    for (metric, end, span), row in picked.items():
        start = row['period_start']
        facts[(metric, end, span)] = {
            'id': _id(symbol, metric, end, span), 'symbol': symbol, 'metric': metric,
            'period_start': date.fromisoformat(str(start)[:10]) if start else None, 'period_end': date.fromisoformat(end), 'span': span,
            'fiscal_year': row['fiscal_year'], 'fiscal_period': row['fiscal_period'], 'value': Decimal(row['value']), 'unit': row['unit'],
            'kind': 'stated', 'basis': row.get('basis') or REPORTED, 'accession_number': row['accession_number'], 'form': row['form'],
            'filed_at': date.fromisoformat(row['filed_at']), 'source_url': row['source_url'], 'concept': row['concept'],
            'formula': None, 'parents': None, 'status': 'ok', 'reason': None}
    return facts


# --- checks and derivation -------------------------------------------------------------------------------------

def _check_gross_profit(facts):
    """Gross profit must equal revenue - cost of revenue where all three are known: only the gross profit row is marked."""
    for key, gross in sorted(facts.items()):
        metric, end, span = key
        if metric != 'gross_profit' or gross['status'] != 'ok':
            continue
        revenue, cost = facts.get(('revenue', end, span)), facts.get(('cost_of_revenue', end, span))
        if not revenue or not cost or revenue['status'] != 'ok' or cost['status'] != 'ok' or not (revenue['unit'] == cost['unit'] == gross['unit']):
            continue
        expected = revenue['value'] - cost['value']
        if abs(gross['value'] - expected) > _GP_TOLERANCE * abs(gross['value']):
            gross['status'] = 'check_failed'
            gross['reason'] = f"gross_profit {int(gross['value'])} != revenue {int(revenue['value'])} - cost_of_revenue {int(cost['value'])} = {int(expected)}"


def _derive(symbol, facts):
    """A quarter from two stated figures of the same fiscal year whose periods fit exactly."""
    added = {}
    for metric in FLOW_METRICS:
        for big_span, small_span, formula, fiscal_period in _DERIVATIONS:
            for big in [f for k, f in sorted(facts.items()) if k[0] == metric and k[2] == big_span and f['status'] == 'ok']:
                key = (metric, big['period_end'].isoformat(), 'quarter')
                if key in facts or key in added:
                    continue
                for small in [f for k, f in sorted(facts.items()) if k[0] == metric and k[2] == small_span and f['status'] == 'ok']:
                    if small_span == 'quarter' and small['fiscal_period'] != 'Q1':
                        continue
                    if small['fiscal_year'] != big['fiscal_year'] or small['unit'] != big['unit'] or not _within(_gap(big['period_end'], small['period_end']), _QUARTER_GAP):
                        continue
                    if big['period_start'] and small['period_start'] and abs(_gap(big['period_start'], small['period_start'])) > _START_SLACK:
                        continue
                    value = big['value'] - small['value']
                    negative = metric == 'revenue' and value < 0
                    added[key] = {
                        'id': _id(symbol, *key), 'symbol': symbol, 'metric': metric, 'period_start': small['period_end'] + timedelta(days=1),
                        'period_end': big['period_end'], 'span': 'quarter', 'fiscal_year': big['fiscal_year'], 'fiscal_period': fiscal_period,
                        'value': value, 'unit': big['unit'], 'kind': 'derived', 'basis': _weakest(big['basis'], small['basis']),
                        'accession_number': big['accession_number'], 'form': big['form'], 'filed_at': big['filed_at'], 'source_url': big['source_url'],
                        'concept': None, 'formula': formula, 'parents': [str(big['id']), str(small['id'])],
                        'status': 'check_failed' if negative else 'ok', 'reason': 'derived revenue is negative' if negative else None}
                    break
    facts.update(added)


# --- ratios ----------------------------------------------------------------------------------------------------

def _prior(facts, current, how):
    """The fact of the same metric one quarter before (``qoq``) or one year before (``yoy``), if it exists and fits."""
    metric, span = current['metric'], current['span']
    if how == 'qoq':
        if span != 'quarter' or current['fiscal_period'] not in _PREVIOUS_PERIOD:
            return None
        year = current['fiscal_year'] - (1 if current['fiscal_period'] == 'Q1' else 0)
        period, bounds = _PREVIOUS_PERIOD[current['fiscal_period']], _QUARTER_GAP
    else:
        if span not in ('quarter', 'annual'):
            return None
        year, period, bounds = current['fiscal_year'] - 1, current['fiscal_period'], _YEAR_GAP
    for key, fact in sorted(facts.items()):
        if (key[0], key[2]) == (metric, span) and fact['status'] == 'ok' and (fact['fiscal_year'], fact['fiscal_period']) == (year, period) \
                and fact['unit'] == current['unit'] and _within(_gap(current['period_end'], fact['period_end']), bounds):
            return fact
    return None


def _ratio(symbol, name, current, value, formula, parents, basis):
    return {'id': _id(symbol, name, current['period_end'].isoformat(), current['span']), 'symbol': symbol, 'name': name,
            'period_end': current['period_end'], 'span': current['span'], 'fiscal_year': current['fiscal_year'], 'fiscal_period': current['fiscal_period'],
            'value': value, 'formula': formula, 'parents': [str(p) for p in parents], 'basis': basis, 'status': 'ok', 'reason': None}


def _ratios(symbol, facts):
    good = {k: f for k, f in facts.items() if f['status'] == 'ok'}
    out = {}
    for (metric, end, span), revenue in sorted(good.items()):
        if metric != 'revenue' or span not in FLOW_SPANS or revenue['value'] == 0:
            continue
        for name, numerator in MARGINS:
            top = good.get((numerator, end, span))
            if top and top['unit'] == revenue['unit']:
                out[(name, end, span)] = _ratio(symbol, name, revenue, _ratio_value(top['value'], revenue['value']), f'{numerator} / revenue',
                                                [top['id'], revenue['id']], _weakest(top['basis'], revenue['basis']))
    for (metric, end, span), current in sorted(good.items()):
        for name, source in GROWTH_METRICS:
            if metric != source:
                continue
            for how in ('qoq', 'yoy'):
                before = _prior(good, current, how)
                if before and before['value'] > 0:
                    out[(f'{name}_{how}', end, span)] = _ratio(symbol, f'{name}_{how}', current, _ratio_value(current['value'] - before['value'], before['value']),
                                                               '(a - b) / b', [current['id'], before['id']], _weakest(current['basis'], before['basis']))
        if metric == 'revenue':
            now = out.get(('gross_margin', end, span))
            for how in ('qoq', 'yoy'):
                before = _prior(good, current, how)
                then = out.get(('gross_margin', before['period_end'].isoformat(), span)) if before else None
                if now and then:
                    out[(f'gross_margin_change_{how}_pp', end, span)] = _ratio(
                        symbol, f'gross_margin_change_{how}_pp', current, ((now['value'] - then['value']) * 100).quantize(Decimal('0.00000001')),
                        'gross_margin(a) - gross_margin(b), percentage points', [now['id'], then['id']], _weakest(now['basis'], then['basis']))
    return out


# --- storing ---------------------------------------------------------------------------------------------------

def _store(db, model, columns, rows, symbol, now):
    """Replace the symbol's rows; a row identical to the one it replaces keeps that row's ``built_at``."""
    old = {r.id: (tuple(getattr(r, c) for c in columns), r.built_at) for r in db.scalars(select(model).where(model.symbol == symbol))}
    db.execute(delete(model).where(model.symbol == symbol))
    db.flush()
    for row in sorted(rows, key=lambda r: str(r['id'])):
        same = old.get(row['id'])
        stamp = same[1] if same and same[0] == tuple(row[c] for c in columns) else now
        db.add(model(**row, built_at=stamp))
    db.flush()


def _rebuild(db, symbol):
    now = datetime.now(UTC)
    facts = _stated(symbol, _filings(db, symbol))
    _check_gross_profit(facts)
    _derive(symbol, facts)
    _check_gross_profit(facts)
    ratios = _ratios(symbol, facts)
    _store(db, CompanyFact, _FACT_COLUMNS, list(facts.values()), symbol, now)
    _store(db, CompanyRatio, _RATIO_COLUMNS, list(ratios.values()), symbol, now)
    failures = [{'metric': k[0], 'period_end': k[1], 'span': k[2], 'reason': f['reason']} for k, f in sorted(facts.items()) if f['status'] == 'check_failed']
    return {'symbol': symbol, 'facts': len(facts), 'stated': sum(f['kind'] == 'stated' for f in facts.values()),
            'derived': sum(f['kind'] == 'derived' for f in facts.values()), 'ratios': len(ratios), 'check_failures': failures}


def refresh(symbol: str, *, db=None) -> dict:
    """Rebuild one symbol's facts and ratios in one transaction.  With ``db`` the caller commits; without it this commits (and rolls back on error)."""
    symbol = (symbol or '').strip().upper()
    session = db or SessionLocal()
    try:
        result = _rebuild(session, symbol)
        if db is None:
            session.commit()
        return result
    except Exception:
        if db is None:
            session.rollback()
        raise
    finally:
        if db is None:
            session.close()


def refresh_all(*, limit: int | None = None) -> dict:
    """Refresh every symbol that has saved figures; one symbol failing is logged and does not stop the rest."""
    with SessionLocal() as db:
        symbols = list(db.scalars(select(SecFilingInventory.symbol).where(
            SecFilingInventory.content_status == 'fetched', SecFilingInventory.content_financials.is_not(None),
            SecFilingInventory.form.in_(PERIODIC_FORMS + ('8-K',))).distinct().order_by(SecFilingInventory.symbol)))
    if limit is not None:
        symbols = symbols[:max(0, int(limit))]
    total = {'symbols': 0, 'facts': 0, 'ratios': 0, 'check_failures': [], 'errors': {}}
    for symbol in symbols:
        try:
            one = refresh(symbol)
        except Exception as exc:
            log.exception('company facts refresh failed for %s', symbol)
            total['errors'][symbol] = f'{type(exc).__name__}: {exc}'[:200]
            continue
        total['symbols'] += 1
        total['facts'] += one['facts']
        total['ratios'] += one['ratios']
        total['check_failures'] += [{'symbol': symbol, **f} for f in one['check_failures']]
    return total


# --- reading ---------------------------------------------------------------------------------------------------

def _number(value):
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def _fact_dict(f):
    return {'id': str(f.id), 'metric': f.metric, 'value': _number(f.value), 'unit': f.unit, 'period_start': f.period_start.isoformat() if f.period_start else None,
            'period_end': f.period_end.isoformat(), 'span': f.span, 'fiscal_year': f.fiscal_year, 'fiscal_period': f.fiscal_period, 'kind': f.kind,
            'basis': f.basis, 'accession_number': f.accession_number, 'form': f.form, 'filed_at': f.filed_at.isoformat() if f.filed_at else None,
            'source_url': f.source_url, 'concept': f.concept, 'formula': f.formula, 'parents': list(f.parents or [])}


def _ratio_dict(r):
    return {'id': str(r.id), 'name': r.name, 'value': float(r.value), 'period_end': r.period_end.isoformat(), 'span': r.span, 'fiscal_year': r.fiscal_year,
            'fiscal_period': r.fiscal_period, 'formula': r.formula, 'parents': list(r.parents or []), 'basis': r.basis}


def latest_quarter(symbol: str, *, db=None) -> dict | None:
    """The newest quarter that has at least revenue, with its facts, ratios and the comparison periods those ratios used."""
    symbol = (symbol or '').strip().upper()
    session = db or SessionLocal()
    try:
        top = session.scalars(select(CompanyFact).where(CompanyFact.symbol == symbol, CompanyFact.metric == 'revenue', CompanyFact.span == 'quarter',
                                                        CompanyFact.status == 'ok').order_by(CompanyFact.period_end.desc())).first()
        if top is None:
            return None
        quarter = [f for f in session.scalars(select(CompanyFact).where(
            CompanyFact.symbol == symbol, CompanyFact.period_end == top.period_end, CompanyFact.span.in_(('quarter', 'instant')),
            CompanyFact.status == 'ok').order_by(CompanyFact.metric))]
        own_ratios = list(session.scalars(select(CompanyRatio).where(
            CompanyRatio.symbol == symbol, CompanyRatio.period_end == top.period_end, CompanyRatio.span == 'quarter',
            CompanyRatio.status == 'ok').order_by(CompanyRatio.name)))
        known = {str(f.id) for f in quarter} | {str(r.id) for r in own_ratios}
        comparison_facts, comparison_ratios, wanted = {}, {}, [p for r in own_ratios for p in r.parents]
        while wanted:
            identity = wanted.pop()
            if identity in known:
                continue
            known.add(identity)
            fact = session.get(CompanyFact, uuid.UUID(identity))
            ratio = None if fact else session.get(CompanyRatio, uuid.UUID(identity))
            if fact:
                comparison_facts[identity] = fact
            elif ratio:
                comparison_ratios[identity] = ratio
                wanted += list(ratio.parents or [])
        return {'symbol': symbol, 'fiscal_label': f'FY{top.fiscal_year} {top.fiscal_period}', 'fiscal_year': top.fiscal_year,
                'fiscal_period': top.fiscal_period, 'period_end': top.period_end.isoformat(), 'basis': top.basis,
                'basis_note': '新闻稿，未经审计' if top.basis == PRESS_RELEASE_BASIS else None,
                'facts': [_fact_dict(f) for f in quarter], 'ratios': [_ratio_dict(r) for r in own_ratios],
                'comparison_facts': [_fact_dict(f) for _, f in sorted(comparison_facts.items(), key=lambda kv: (kv[1].period_end, kv[1].metric))],
                'comparison_ratios': [_ratio_dict(r) for _, r in sorted(comparison_ratios.items(), key=lambda kv: (kv[1].period_end, kv[1].name))]}
    finally:
        if db is None:
            session.close()
