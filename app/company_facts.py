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

from sqlalchemy import delete, func, select, text

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
_WINDOW_DAYS = 400      # how far back from the newest quarter its comparison periods and derivation parents can lie
_GP_TOLERANCE = Decimal('0.005')
_CORROBORATION = Decimal('0.001')
_DERIVATIONS = (('ytd6', 'quarter', 'ytd6 - q1', 'Q2'), ('ytd9', 'ytd6', 'ytd9 - ytd6', 'Q3'), ('annual', 'ytd9', 'annual - ytd9', 'Q4'))
_PREVIOUS_PERIOD = {'Q1': 'Q4', 'Q2': 'Q1', 'Q3': 'Q2', 'Q4': 'Q3'}
_NAMESPACE = uuid.UUID('6f1c1d5e-3b53-4e0e-9a0e-2b7a0c0f6c11')
_FACT_COLUMNS = ('id', 'symbol', 'metric', 'period_start', 'period_end', 'span', 'fiscal_year', 'fiscal_period', 'value', 'unit', 'kind', 'basis',
                 'accession_number', 'form', 'filed_at', 'source_url', 'concept', 'formula', 'parents', 'status', 'reason')
_RATIO_COLUMNS = ('id', 'symbol', 'name', 'period_end', 'span', 'fiscal_year', 'fiscal_period', 'value', 'formula', 'parents', 'basis', 'status', 'reason', 'change_kind', 'current_value', 'base_value')


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
        SecFilingInventory.content_status == 'fetched', SecFilingInventory.content_financials.is_not(None))).all()
    # Newest first.  On one day an annual report outranks a quarterly one (it is the later word), then the accession number breaks the tie.
    found = sorted(found, key=lambda r: (r.filed_at, r.form in ('10-K', '20-F'), r.accession_number), reverse=True)
    return [{'id': r.id, 'symbol': r.symbol, 'form': r.form, 'accession_number': r.accession_number, 'filed_at': r.filed_at,
             'source_url': r.source_url, 'content_source_url': r.content_source_url, 'content_financials': r.content_financials}
            for r in found if r.content_financials]


def _stated(symbol, filings):
    """Stated facts keyed (metric, period_end, span): the newest periodic filing's figure, then an earnings release that is ahead.
    Also returns every filing's value for each key (``history``, newest first), which restatement and corroboration checks read.
    A fact keeps its id when restated (the id is the period's), so an id quoted earlier names the period, not a frozen value."""
    periodic = [f for f in filings if f['form'] in PERIODIC_FORMS]
    picked, history, latest_report = {}, {}, ''
    for filing in periodic:                       # newest first: a restatement beats the figure it restates
        for row in figure_rows(filing):
            latest_report = max(latest_report, row['period_end'][:10])
            if row['period_span'] != 'other':
                key = (row['metric'], row['period_end'][:10], row['period_span'])
                picked.setdefault(key, row)
                history.setdefault(key, []).append({'accession': row['accession_number'], 'filed_at': row['filed_at'], 'value': Decimal(row['value']),
                                                    'basis': REPORTED, 'form': row['form']})
    for filing in filings:
        if filing['form'] != '8-K':
            continue
        rows = [r for r in figure_rows(filing) if r.get('basis') == PRESS_RELEASE_BASIS and r['period_span'] != 'other']
        for row in rows:                          # a release always counts as a second statement of a figure, ahead or not
            history.setdefault((row['metric'], row['period_end'][:10], row['period_span']), []).append(
                {'accession': row['accession_number'], 'filed_at': row['filed_at'], 'value': Decimal(row['value']), 'basis': PRESS_RELEASE_BASIS, 'form': row['form']})
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
    return facts, history


# --- checks and derivation -------------------------------------------------------------------------------------

def _corroborated(fact, history):
    """An independent source states the same value for the same period and span (within 0.1 %): a press release against a periodic report,
    or the reverse.  A later report repeating a comparative is not independent (a mapping error repeats in every filing)."""
    for entry in history.get((fact['metric'], fact['period_end'].isoformat(), fact['span']), []):
        if entry['basis'] != fact['basis'] and entry['accession'] != fact['accession_number'] and abs(entry['value'] - fact['value']) <= _CORROBORATION * abs(fact['value']):
            return True
    return False


def _check_gross_profit(facts, history):
    """Revenue, cost of revenue and gross profit must agree where all three are known.  The code cannot tell which is wrong, so all
    three are marked, except a figure another filing independently states with the same value."""
    for key, gross in sorted(facts.items()):
        metric, end, span = key
        if metric != 'gross_profit' or gross['status'] != 'ok':
            continue
        revenue, cost = facts.get(('revenue', end, span)), facts.get(('cost_of_revenue', end, span))
        if not revenue or not cost or revenue['status'] != 'ok' or cost['status'] != 'ok' or not (revenue['unit'] == cost['unit'] == gross['unit']):
            continue
        expected = revenue['value'] - cost['value']
        if abs(gross['value'] - expected) <= _GP_TOLERANCE * abs(gross['value']):
            continue
        reason = (f"revenue {int(revenue['value'])} - cost_of_revenue {int(cost['value'])} = {int(expected)} "
                  f"!= gross_profit {int(gross['value'])}: the three disagree")
        for fact in (revenue, cost, gross):
            if not _corroborated(fact, history):
                fact['status'], fact['reason'] = 'check_failed', reason


def _check_bounds(facts):
    """Limits no true figure breaks, whatever else is known: a negative cost of revenue, a gross profit above revenue."""
    for key, fact in sorted(facts.items()):
        if fact['status'] != 'ok':
            continue
        if fact['metric'] == 'cost_of_revenue' and fact['value'] < 0:
            fact['status'], fact['reason'] = 'check_failed', 'cost_of_revenue is negative'
        elif fact['metric'] == 'gross_profit':
            revenue = facts.get(('revenue', key[1], key[2]))
            if revenue and revenue['unit'] == fact['unit'] and fact['value'] > revenue['value']:
                fact['status'], fact['reason'] = 'check_failed', f"gross_profit {int(fact['value'])} exceeds revenue {int(revenue['value'])}"


def _vintage(fact, history):
    """(restated, date) for a stated periodic figure: whether older filings gave another value, and the date of the oldest filing
    that already gives the current one."""
    entries = [e for e in history.get((fact['metric'], fact['period_end'].isoformat(), fact['span']), []) if e['basis'] == REPORTED]
    if fact['basis'] != REPORTED or not entries:
        return False, None
    current, since = entries[0]['value'], entries[0]['filed_at']
    run = True
    restated = False
    for entry in entries:
        if entry['value'] == current and run:
            since = entry['filed_at']
        else:
            run = False
            if entry['value'] != current:
                restated = True
    return restated, since


_PART_NAMES = {'annual': '年度数', 'ytd9': '九个月累计', 'ytd6': '上半年累计', 'quarter': '第一季度数'}
_QUARTER_NAMES = {'Q2': '第二季', 'Q3': '第三季', 'Q4': '第四季'}


def _mixed_vintage(big, small, history, fiscal_period):
    """Exactly one parent restated in a later filing while the other still comes from an older one: the pair is not one set of books.
    Both restated (each in its own filing) or neither is not flagged here."""
    (big_restated, big_since), (small_restated, small_since) = _vintage(big, history), _vintage(small, history)
    if big_restated == small_restated:
        return None
    changed, other, since = (big, small, big_since) if big_restated else (small, big, small_since)
    if other['filed_at'] < date.fromisoformat(str(since)[:10]):
        return f"{_PART_NAMES[changed['span']]}已重述，{_PART_NAMES[other['span']]}未同步重述，无法推出{_QUARTER_NAMES[fiscal_period]}"
    return None


def _derive(symbol, facts, history):
    """A quarter from two stated figures of the same fiscal year whose periods fit exactly.  Where a quarter is also stated, the two
    must agree (within 0.5 %); a stated quarter that does not is marked and not shown."""
    added = {}
    for metric in FLOW_METRICS:
        for big_span, small_span, formula, fiscal_period in _DERIVATIONS:
            for big in [f for k, f in sorted(facts.items()) if k[0] == metric and k[2] == big_span and f['status'] == 'ok']:
                key = (metric, big['period_end'].isoformat(), 'quarter')
                if key in added:
                    continue
                for small in [f for k, f in sorted(facts.items()) if k[0] == metric and k[2] == small_span and f['status'] == 'ok']:
                    if small_span == 'quarter' and small['fiscal_period'] != 'Q1':
                        continue
                    if small['fiscal_year'] != big['fiscal_year'] or small['unit'] != big['unit'] or not _within(_gap(big['period_end'], small['period_end']), _QUARTER_GAP):
                        continue
                    if big['period_start'] and small['period_start'] and abs(_gap(big['period_start'], small['period_start'])) > _START_SLACK:
                        continue
                    value = big['value'] - small['value']
                    problem = _mixed_vintage(big, small, history, fiscal_period)
                    if not problem and big['basis'] == REPORTED == small['basis'] and big['concept'] != small['concept']:
                        problem = f"两个累计数的会计科目不同（{small['concept']} 与 {big['concept']}），无法相减"
                    stated = facts.get(key)
                    if stated is not None:
                        if stated['status'] == 'ok' and problem:
                            stated['reason'] = f'not compared with the year-to-date figures: {problem}'
                        if stated['status'] == 'ok' and not problem and abs(stated['value'] - value) > _GP_TOLERANCE * abs(stated['value']):
                            stated['status'] = 'check_failed'
                            stated['reason'] = (f"stated quarter {int(stated['value'])} ({stated['form']} {stated['accession_number']}) != {formula} = {int(value)} "
                                                f"({big['form']} {big['accession_number']} and {small['form']} {small['accession_number']})")
                        break
                    if not problem and value < 0 and metric in ('revenue', 'cost_of_revenue'):
                        problem = f'derived {metric} is negative'
                    later = big if big['filed_at'] >= small['filed_at'] else small
                    added[key] = {
                        'id': _id(symbol, *key), 'symbol': symbol, 'metric': metric, 'period_start': small['period_end'] + timedelta(days=1),
                        'period_end': big['period_end'], 'span': 'quarter', 'fiscal_year': big['fiscal_year'], 'fiscal_period': fiscal_period,
                        'value': value, 'unit': big['unit'], 'kind': 'derived', 'basis': _weakest(big['basis'], small['basis']),
                        'accession_number': later['accession_number'], 'form': later['form'], 'filed_at': later['filed_at'], 'source_url': later['source_url'],
                        'concept': None, 'formula': formula, 'parents': [str(big['id']), str(small['id'])],
                        'status': 'check_failed' if problem else 'ok', 'reason': problem}
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
        if (key[0], key[2]) == (metric, span) and (fact['fiscal_year'], fact['fiscal_period']) == (year, period) \
                and fact['unit'] == current['unit'] and _within(_gap(current['period_end'], fact['period_end']), bounds):
            return fact
    return None


def _change_kind(current, base):
    """What a change from ``base`` to ``current`` is, in words, when a percentage would mislead (zero or negative base, or a sign change)."""
    if base == 0:
        return 'from_zero'
    if base > 0:
        return 'turned_loss'
    if current > 0:
        return 'turned_profit'
    return 'loss_narrowed' if current > base else 'loss_widened' if current < base else 'loss_unchanged'


def _worst(parents):
    """A ratio is only as good as its parents: a parent that failed a check fails it; one that has no meaningful value leaves it without."""
    for wanted in ('check_failed', 'not_meaningful'):
        for parent in parents:
            if parent['status'] == wanted:
                label = parent.get('metric') or parent.get('name')
                return wanted, f"parent {label} {parent['period_end'].isoformat()} {wanted}"
    return 'ok', None


def _ratio(symbol, name, current, formula, parents, basis, value=None, status='ok', reason=None, kind=None, now=None, base=None):
    return {'id': _id(symbol, name, current['period_end'].isoformat(), current['span']), 'symbol': symbol, 'name': name,
            'period_end': current['period_end'], 'span': current['span'], 'fiscal_year': current['fiscal_year'], 'fiscal_period': current['fiscal_period'],
            'value': value if status == 'ok' else None, 'formula': formula, 'parents': [str(p['id']) for p in parents], 'basis': basis,
            'status': status, 'reason': reason, 'change_kind': kind, 'current_value': now, 'base_value': base}


def _ratios(symbol, facts):
    out = {}
    for (metric, end, span), revenue in sorted(facts.items()):
        if metric != 'revenue' or span not in FLOW_SPANS:
            continue
        for name, numerator in MARGINS:
            top = facts.get((numerator, end, span))
            if not top or top['unit'] != revenue['unit']:
                continue
            status, reason = _worst([top, revenue])
            if status == 'ok' and revenue['value'] == 0:
                status, reason = 'not_meaningful', 'revenue is zero'
            elif status == 'ok' and abs(top['value']) > abs(revenue['value']):
                status, reason = 'check_failed', f'{name} outside -100%..100%'
            out[(name, end, span)] = _ratio(symbol, name, revenue, f'{numerator} / revenue', [top, revenue], _weakest(top['basis'], revenue['basis']),
                                            _ratio_value(top['value'], revenue['value']) if status == 'ok' else None, status, reason)
    for (metric, end, span), current in sorted(facts.items()):
        for name, source in GROWTH_METRICS:
            if metric != source:
                continue
            for how in ('qoq', 'yoy'):
                before = _prior(facts, current, how)
                if not before:
                    continue
                status, reason = _worst([current, before])
                kind = None
                if status == 'ok' and (before['value'] <= 0 or current['value'] < 0):
                    status, kind = 'not_meaningful', _change_kind(current['value'], before['value'])
                    reason = f'no percentage on a {"zero or negative base" if before["value"] <= 0 else "sign change"}: {kind}'
                out[(f'{name}_{how}', end, span)] = _ratio(
                    symbol, f'{name}_{how}', current, '(a - b) / b', [current, before], _weakest(current['basis'], before['basis']),
                    _ratio_value(current['value'] - before['value'], before['value']) if status == 'ok' else None, status, reason, kind,
                    current['value'] if status != 'check_failed' else None, before['value'] if status != 'check_failed' else None)
        if metric == 'revenue':
            now = out.get(('gross_margin', end, span))
            for how in ('qoq', 'yoy'):
                before = _prior(facts, current, how)
                then = out.get(('gross_margin', before['period_end'].isoformat(), span)) if before else None
                if now and then:
                    status, reason = _worst([now, then])
                    out[(f'gross_margin_change_{how}_pp', end, span)] = _ratio(
                        symbol, f'gross_margin_change_{how}_pp', current, 'gross_margin(a) - gross_margin(b), percentage points', [now, then],
                        _weakest(now['basis'], then['basis']),
                        ((now['value'] - then['value']) * 100).quantize(Decimal('0.00000001')) if status == 'ok' else None, status, reason)
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
    # Refreshes of one symbol run one at a time, and the one that gets the lock reads the filings after it: the last one in sees the newest.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:space), hashtext(:symbol))'), {'space': 'company_facts', 'symbol': symbol})
    facts, history = _stated(symbol, _filings(db, symbol))
    _check_gross_profit(facts, history)
    _check_bounds(facts)
    _derive(symbol, facts, history)
    _check_gross_profit(facts, history)
    _check_bounds(facts)
    ratios = _ratios(symbol, facts)
    _store(db, CompanyFact, _FACT_COLUMNS, list(facts.values()), symbol, now)
    _store(db, CompanyRatio, _RATIO_COLUMNS, list(ratios.values()), symbol, now)
    failures = [{'metric': k[0], 'period_end': k[1], 'span': k[2], 'reason': f['reason']} for k, f in sorted(facts.items()) if f['status'] == 'check_failed']
    return {'symbol': symbol, 'facts': len(facts), 'stated': sum(f['kind'] == 'stated' for f in facts.values()),
            'derived': sum(f['kind'] == 'derived' for f in facts.values()), 'ratios': len(ratios), 'check_failures': failures}


def refresh(symbol: str, *, db=None) -> dict:
    """Rebuild one symbol's facts and ratios in one transaction.  With ``db`` the caller commits; without it this commits (and rolls back on error).
    The transaction holds a per-symbol lock until it ends: refresh one symbol per transaction (or symbols in sorted order), and never keep
    the transaction open across a network fetch, or every other refresh of that symbol waits."""
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


def refresh_quietly(symbol: str) -> None:
    """The hook the stores call after their own commit: a refresh in its own session, whose failure is logged (one line) and never reaches the caller."""
    try:
        refresh(symbol)
    except Exception as exc:  # noqa: BLE001 - a refresh problem must never fail the fetch or the store that triggered it
        log.warning('company facts refresh of %s failed (%s: %s)', symbol, type(exc).__name__, str(exc)[:200])


def refresh_all(*, limit: int | None = None) -> dict:
    """Refresh every symbol that has saved figures; one symbol failing is logged and does not stop the rest."""
    with SessionLocal() as db:
        symbols = set(db.scalars(select(SecFilingInventory.symbol).where(
            SecFilingInventory.content_status == 'fetched', SecFilingInventory.content_financials.is_not(None),
            SecFilingInventory.form.in_(PERIODIC_FORMS + ('8-K',))).distinct()))
        symbols |= set(db.scalars(select(CompanyFact.symbol).distinct()))      # a symbol whose figures are gone gets its stale rows cleared
        symbols = sorted(symbols)
    if limit is not None:
        symbols = symbols[:max(0, int(limit))]
    total = {'symbols': 0, 'facts': 0, 'ratios': 0, 'check_failures': [], 'errors': {}}
    for symbol in symbols:
        try:
            one = refresh(symbol)
        except Exception as exc:
            log.warning('company facts refresh failed for %s (%s: %s)', symbol, type(exc).__name__, str(exc)[:200])
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
            'basis': f.basis, 'status': f.status, 'accession_number': f.accession_number, 'form': f.form, 'filed_at': f.filed_at.isoformat() if f.filed_at else None,
            'source_url': f.source_url, 'concept': f.concept, 'formula': f.formula, 'parents': list(f.parents or [])}


def _ratio_dict(r):
    return {'id': str(r.id), 'name': r.name, 'value': None if r.value is None else float(r.value), 'status': r.status, 'reason': r.reason,
            'change_kind': r.change_kind, 'current_value': None if r.current_value is None else _number(r.current_value),
            'base_value': None if r.base_value is None else _number(r.base_value), 'period_end': r.period_end.isoformat(), 'span': r.span, 'fiscal_year': r.fiscal_year,
            'fiscal_period': r.fiscal_period, 'formula': r.formula, 'parents': list(r.parents or []), 'basis': r.basis}


def latest_quarter(symbol: str, *, db=None) -> dict | None:
    """The newest quarter that has at least revenue, with its facts, ratios and the comparison periods those ratios used.
    Two reads in all: the symbol's usable facts and its usable ratios from a year and a bit before the newest quarter on (the comparison
    periods and the parents of a derived figure all lie inside that window); the rest is picking in memory."""
    symbol = (symbol or '').strip().upper()
    session = db or SessionLocal()
    try:
        newest = select(func.max(CompanyFact.period_end) - _WINDOW_DAYS).where(
            CompanyFact.symbol == symbol, CompanyFact.metric == 'revenue', CompanyFact.span == 'quarter', CompanyFact.status == 'ok').scalar_subquery()
        facts = {str(f.id): f for f in session.scalars(select(CompanyFact).where(
            CompanyFact.symbol == symbol, CompanyFact.status == 'ok', CompanyFact.period_end >= newest))}
        tops = [f for f in facts.values() if f.metric == 'revenue' and f.span == 'quarter']
        if not tops:
            return None
        top = max(tops, key=lambda f: f.period_end)
        ratios = {str(r.id): r for r in session.scalars(select(CompanyRatio).where(
            CompanyRatio.symbol == symbol, CompanyRatio.status.in_(('ok', 'not_meaningful')), CompanyRatio.period_end >= newest))}
        quarter = sorted((f for f in facts.values() if f.period_end == top.period_end and f.span in ('quarter', 'instant')), key=lambda f: f.metric)
        own_ratios = sorted((r for r in ratios.values() if r.period_end == top.period_end and r.span == 'quarter'), key=lambda r: r.name)
        known = {str(f.id) for f in quarter} | {str(r.id) for r in own_ratios}
        comparison_facts, comparison_ratios = {}, {}
        wanted = [p for r in own_ratios for p in r.parents] + [p for f in quarter for p in (f.parents or [])]
        while wanted:
            identity = wanted.pop()
            if identity in known:
                continue
            known.add(identity)
            if identity in facts:
                comparison_facts[identity] = facts[identity]
                wanted += list(facts[identity].parents or [])      # a derived figure's own parents, so every figure shown can be traced to a stated one
            elif identity in ratios:
                comparison_ratios[identity] = ratios[identity]
                wanted += list(ratios[identity].parents or [])
        return {'symbol': symbol, 'fiscal_label': f'FY{top.fiscal_year} {top.fiscal_period}', 'fiscal_year': top.fiscal_year,
                'fiscal_period': top.fiscal_period, 'period_end': top.period_end.isoformat(), 'basis': top.basis,
                'basis_note': '新闻稿，未经审计' if top.basis == PRESS_RELEASE_BASIS else None,
                'facts': [_fact_dict(f) for f in quarter], 'ratios': [_ratio_dict(r) for r in own_ratios],
                'comparison_facts': [_fact_dict(f) for _, f in sorted(comparison_facts.items(), key=lambda kv: (kv[1].period_end, kv[1].metric))],
                'comparison_ratios': [_ratio_dict(r) for _, r in sorted(comparison_ratios.items(), key=lambda kv: (kv[1].period_end, kv[1].name))]}
    finally:
        if db is None:
            session.close()
