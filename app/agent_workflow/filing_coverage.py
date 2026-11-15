"""Coverage receipts for saved SEC filing reads, and the filing-rhythm freshness check (SW1 items 1 and 4).

Pure functions, no database: the tools in agent_tools.py gather the filing metadata and rows; this module says
which filings were read, which were left out and why, and whether the saved library is behind the company's own
filing rhythm. Everything here is a deterministic fact about what was read. What the answer says about it is the
model's call (docs/finbot-design-rules.md: deterministic support is code's job, judgement is the model's).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

RECEIPT_LIMIT = 1500          # characters of JSON a receipt may take
LIST_LIMIT = 8                # not_read, filings_read and periods_left_out each hold at most this many
NEAREST_LIMIT = 4
SPAN_RANK = {'quarter': 0, 'annual': 1, 'ytd9': 2, 'ytd6': 3, 'instant': 4, 'other': 5}
# Fields dropped, in this order, when a receipt is over RECEIPT_LIMIT: the table's last field goes first.
DROP_ORDER = ('freshness', 'q4_note', 'nearest_periods', 'library', 'widened', 'periods_left_out',
              'rows_left_out_by_limit', 'not_read', 'filings_read', 'filters')
GRACE_DAYS = 7                # a filing may come this many days after the rhythm says it is due
CADENCE_RANGE = (60, 140)     # every gap between a company's periodic filings must fall in this range
MAX_OVERDUE_DAYS = 120        # past this, the library is stale, not "should have been published"
Q4_NOTE = '该财年第四季度没有单独披露的 3 个月数；可用 FY 全年减前三季度累计推算，结果须标推算。'
NEXT_PERIOD = {'Q1': 'Q2', 'Q2': 'Q3'}


def day(value) -> date | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def order_latest(rows: list[dict]) -> list[dict]:
    """Newest period end first; within one period end: quarter, annual, ytd9, ytd6, instant, other."""
    return sorted(rows, key=lambda r: (-day(r['period_end']).toordinal(), SPAN_RANK.get(r.get('period_span'), 5)))


def filing_key(form, filed_at) -> tuple[str, str]:
    return (str(form or ''), str(filed_at or '')[:10])


def current_period(filing: dict) -> dict | None:
    periods = [p for f in (filing.get('content_financials') or []) if isinstance(f, dict)
               for p in (f.get('periods') or []) if isinstance(p, dict) and p.get('end') and p.get('value') is not None]
    if not periods:
        return None
    end = max(day(p['end']) for p in periods)
    return next(p for p in periods if day(p['end']) == end)


def document_period(filing: dict) -> str | None:
    """The fiscal period a saved filing reports for itself, from its own XBRL: 'FY2026' or 'FY2026 Q3'."""
    current = current_period(filing)
    if current is None or current.get('fiscal_year') is None or not current.get('fiscal_period'):
        return None
    year, period = current['fiscal_year'], current['fiscal_period']
    return f'FY{year}' if period == 'FY' else f'FY{year} {period}'


def next_period(fiscal_year, fiscal_period) -> str | None:
    """The period a company's rhythm names next: FY -> next FY Q1, Q1 -> Q2, Q2 -> Q3, Q3 -> the FY's 10-K."""
    if fiscal_year is None or not fiscal_period:
        return None
    if fiscal_period == 'FY':
        return f'FY{int(fiscal_year) + 1} Q1'
    if fiscal_period == 'Q3':
        return f'FY{fiscal_year}'
    following = NEXT_PERIOD.get(fiscal_period)
    return f'FY{fiscal_year} {following}' if following else None


def fit_receipt(coverage: dict) -> dict:
    """Keep the receipt within RECEIPT_LIMIT characters by dropping whole fields in DROP_ORDER."""
    def size() -> int:
        return len(json.dumps(coverage, ensure_ascii=False, default=str))
    for key in DROP_ORDER:
        if size() <= RECEIPT_LIMIT:
            break
        coverage.pop(key, None)
    return coverage


def library_summary(periodic: list[dict]) -> dict:
    """What the saved library holds for the company, whatever the request filtered. Counts are of the metadata window."""
    if not periodic:
        return {'periodic_filings': 0}
    ordered = sorted(periodic, key=lambda f: day(f['filed_at']))
    def brief(item):
        return {'form': item['form'], 'filed_at': str(item['filed_at'])[:10]}
    return {'periodic_filings': len(ordered), 'newest': brief(ordered[-1]), 'oldest': brief(ordered[0])}


def coverage_receipt(*, filters: dict, filings_read: list[dict], not_read: list[dict], widened: list[dict],
            rows_left_out: int | None = None, periods_left_out: list[str] | None = None,
            library: dict | None = None, nearest_periods: list[str] | None = None,
            q4_note: str | None = None, freshness: dict | None = None) -> dict:
    """One receipt. Financial reads pass rows_left_out and periods_left_out; filing-text reads leave them None."""
    coverage: dict = {'filters': {k: v for k, v in filters.items() if v is not None},
                      'filings_read': filings_read[:LIST_LIMIT],
                      'not_read': not_read[:LIST_LIMIT]}
    if rows_left_out is not None:
        coverage['rows_left_out_by_limit'] = rows_left_out
        coverage['periods_left_out'] = (periods_left_out or [])[:LIST_LIMIT]
    coverage['widened'] = widened
    if library is not None:
        coverage['library'] = library
    if nearest_periods:
        coverage['nearest_periods'] = nearest_periods[:NEAREST_LIMIT]
    if q4_note:
        coverage['q4_note'] = q4_note
    if freshness:
        coverage['freshness'] = freshness
    return fit_receipt(coverage)


def freshness(periodic: list[dict], saved: list[dict], cutoff, *, latest_period: str | None = None,
              latest_end: str | None = None, next_period_label: str | None = None) -> dict | None:
    """Is the saved library behind the company's own filing rhythm? None when the rhythm does not say (SW1 §5.1).

    periodic: the company's 10-K/10-Q/20-F metadata, each {'form', 'filed_at', ...}.
    saved:    the subset this tool can read (fetched, with XBRL for financial reads).
    Returns kind "registered_not_saved" (a newer filing is in the SEC inventory but not readable), "cadence"
    (overdue by the company's own gaps) or "stale" (far past the rhythm: say what is saved, do not say "due").
    """
    cut = day(cutoff)
    ordered = sorted((f for f in periodic if day(f.get('filed_at'))), key=lambda f: day(f['filed_at']))
    if not ordered or cut is None:
        return None
    readable = {filing_key(f['form'], f['filed_at']) for f in saved}
    newest_saved = max((day(f['filed_at']) for f in saved), default=None)
    top = ordered[-1]
    top_day = day(top['filed_at'])
    if filing_key(top['form'], top['filed_at']) not in readable and (newest_saved is None or top_day > newest_saved):
        where = f'库内最新一期是 {latest_period}。' if latest_period else ''
        due = f'下一期（{next_period_label}）应已发布，库里还没有。' if next_period_label else ''
        return {'kind': 'registered_not_saved', 'overdue': True, 'form': top['form'],
                'filed_at': str(top['filed_at'])[:10],
                'note': f"{where}SEC 目录里已有 {str(top['filed_at'])[:10]} 提交的 {top['form']}，正文 / 财务数据还没入库。{due}"}
    window = ordered[-9:]
    gaps = [(day(b['filed_at']) - day(a['filed_at'])).days for a, b in zip(window, window[1:])]
    if len(gaps) < 3 or any(not CADENCE_RANGE[0] <= gap <= CADENCE_RANGE[1] for gap in gaps):
        return None
    last = top_day
    expected = last + timedelta(days=max(gaps) + GRACE_DAYS)
    if cut <= expected:
        return None
    late = (cut - expected).days
    if late > MAX_OVERDUE_DAYS:
        return {'kind': 'stale', 'overdue': False, 'last_filed_at': last.isoformat(),
                'days_since': (cut - last).days,
                'note': f"库内最新一份定期申报提交于 {last.isoformat()}，距今 {(cut - last).days} 天，之后没有入库记录。"}
    basis = f'该公司最近 {len(gaps)} 次定期申报的提交间隔为 {min(gaps)}–{max(gaps)} 天'
    where = f'库内最新一期是 {latest_period}（截至 {latest_end}，{last.isoformat()} 提交）。' if latest_period and latest_end else ''
    due = f'下一期（{next_period_label}）' if next_period_label else '下一期'
    return {'kind': 'cadence', 'overdue': True, 'expected_by': expected.isoformat(), 'basis': basis,
            'note': f'{where}按该公司以往定期申报的提交间隔，{due}应在 {expected.isoformat()} 前后发布，库里还没有。'}
