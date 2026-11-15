"""Saved SEC filings for the SW1 tests (spec §8.1): companies with a known filing rhythm, in the test database.

Each test seeds its own random symbol and removes the rows afterwards. Reads run under a pinned research cutoff
(CUTOFF) so freshness and visibility do not depend on the wall clock.
"""
import copy
import hashlib
import uuid
from datetime import UTC, date, datetime

from app.database import Base, SessionLocal, engine
from app.models import SecFilingInventory

CUTOFF = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
SEEDED_AT = datetime(2026, 11, 1, tzinfo=UTC)   # observed before the cutoff, so the rows are visible under it


def p(start, end, value, fiscal_year, fiscal_period, unit='USD'):
    return {'start': start, 'end': end, 'unit': unit, 'value': value, 'fiscal_year': fiscal_year, 'fiscal_period': fiscal_period}


def figure(metric, label, periods, concept=None):
    return {'metric': metric, 'label': label, 'concept': concept or metric, 'unit': 'USD', 'periods': periods}


def new_symbol():
    """A random four-letter ticker: the symbol check accepts at most five letters, and no test should meet a real one."""
    return ''.join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:4])


def seed(symbol, filings):
    """filings: dicts with form, filed (date), figures (list, for fetched XBRL), status ('fetched' by default).
    Returns the row ids, for drop()."""
    Base.metadata.create_all(engine)
    cik = f'{uuid.uuid4().int % 10**10:010d}'
    ids = []
    with SessionLocal() as db:
        for item in filings:
            form, filed = item['form'], item['filed']
            fetched = item.get('status', 'fetched') == 'fetched'
            body = f'{form} body for {symbol} filed {filed.isoformat()}'
            row = SecFilingInventory(
                symbol=symbol, cik=cik, accession_number=f'{cik}-{filed:%y}-{uuid.uuid4().int % 10**6:06}',
                form=form, filed_at=filed, primary_document=f'{symbol.lower()}-{filed:%Y%m%d}.htm',
                source_url=f'https://www.sec.gov/{symbol}/{form}-{filed:%Y%m%d}.htm', source='sec-edgar',
                review_status='pending_review', observed_at=SEEDED_AT, content_status=item.get('status', 'fetched'),
                content_excerpt=body if fetched else None,
                content_excerpt_sha256=hashlib.sha256(body.encode()).hexdigest() if fetched else None,
                content_observed_at=SEEDED_AT if fetched else None,
                content_financials=copy.deepcopy(item.get('figures')) if fetched else None)
            db.add(row)
            db.commit()
            ids.append(str(row.id))
    return ids


def drop(ids):
    # Other suites walk every saved filing; leftovers would change what they see.
    with SessionLocal() as db:
        for identity in ids:
            row = db.get(SecFilingInventory, uuid.UUID(identity))
            if row:
                db.delete(row)
        db.commit()


def aapl_filings():
    """AAPL-shaped (September year end): 10-K 2026-11-03, 10-Q Q3 2026-08-01, Q2 2026-05-02, Q1 2026-01-31."""
    tenk = [figure('revenue', 'Revenue', [
                p('2025-09-28', '2026-09-26', 478_834_000_000, 2026, 'FY'),
                p('2024-09-29', '2025-09-27', 416_161_000_000, 2026, 'FY'),
                p('2023-10-01', '2024-09-28', 391_035_000_000, 2026, 'FY')]),
            figure('gross_profit', 'Gross profit', [
                p('2025-09-28', '2026-09-26', 233_602_000_000, 2026, 'FY'),
                p('2024-09-29', '2025-09-27', 195_201_000_000, 2026, 'FY'),
                p('2023-10-01', '2024-09-28', 180_683_000_000, 2026, 'FY')])]
    tenq_q3 = [figure('revenue', 'Revenue', [
                   p('2026-03-29', '2026-06-27', 94_000_000_000, 2026, 'Q3'),
                   p('2025-03-30', '2025-06-28', 85_777_000_000, 2026, 'Q3'),
                   p('2025-09-28', '2026-06-27', 364_357_000_000, 2026, 'Q3'),
                   p('2024-09-29', '2025-06-28', 310_000_000_000, 2026, 'Q3')]),
               figure('gross_profit', 'Gross profit', [
                   p('2026-03-29', '2026-06-27', 54_770_000_000, 2026, 'Q3'),
                   p('2025-03-30', '2025-06-28', 46_000_000_000, 2026, 'Q3'),
                   p('2025-09-28', '2026-06-27', 178_782_000_000, 2026, 'Q3'),
                   p('2024-09-29', '2025-06-28', 165_000_000_000, 2026, 'Q3')])]
    tenq_q2 = [figure('revenue', 'Revenue', [
                   p('2025-12-28', '2026-03-28', 111_000_000_000, 2026, 'Q2'),
                   p('2025-09-28', '2026-03-28', 200_000_000_000, 2026, 'Q2')])]
    tenq_q1 = [figure('revenue', 'Revenue', [p('2025-09-28', '2025-12-27', 143_000_000_000, 2026, 'Q1')])]
    return [
        {'form': '10-K', 'filed': date(2026, 11, 3), 'figures': tenk},
        {'form': '10-Q', 'filed': date(2026, 8, 1), 'figures': tenq_q3},
        {'form': '10-Q', 'filed': date(2026, 5, 2), 'figures': tenq_q2},
        {'form': '10-Q', 'filed': date(2026, 1, 31), 'figures': tenq_q1},
    ]


def msft_filings():
    """MSFT-shaped (June year end): 10-K 2026-07-29 (last), 10-Q 2026-04-29, 2026-01-28, 2025-10-29; 10-K 2025-07-30.
    Gaps between the periodic filings are 91 days, so the rhythm predicts the next filing by about 2026-11-06."""
    tenk26 = [figure('revenue', 'Revenue', [p('2025-07-01', '2026-06-30', 331_839_000_000, 2026, 'FY'),
                                            p('2024-07-01', '2025-06-30', 281_724_000_000, 2026, 'FY')])]
    tenq3 = [figure('revenue', 'Revenue', [p('2026-01-01', '2026-03-31', 38_398_000_000, 2026, 'Q3'),
                                           p('2025-07-01', '2026-03-31', 114_634_000_000, 2026, 'Q3')])]
    tenq2 = [figure('revenue', 'Revenue', [p('2025-10-01', '2025-12-31', 76_441_000_000, 2026, 'Q2')])]
    tenq1 = [figure('revenue', 'Revenue', [p('2025-07-01', '2025-09-30', 77_700_000_000, 2026, 'Q1')])]
    tenk25 = [figure('revenue', 'Revenue', [p('2024-07-01', '2025-06-30', 281_724_000_000, 2025, 'FY')])]
    return [
        {'form': '10-K', 'filed': date(2025, 7, 30), 'figures': tenk25},
        {'form': '10-Q', 'filed': date(2025, 10, 29), 'figures': tenq1},
        {'form': '10-Q', 'filed': date(2026, 1, 28), 'figures': tenq2},
        {'form': '10-Q', 'filed': date(2026, 4, 29), 'figures': tenq3},
        {'form': '10-K', 'filed': date(2026, 7, 29), 'figures': tenk26},
    ]


def nvda_filings():
    """NVDA-shaped: four 10-Qs whose gaps are 97, 90 and 91 days. The next one is not due by the cutoff."""
    def quarter(start, end, value, fy, fp):
        return [figure('revenue', 'Revenue', [p(start, end, value, fy, fp)])]
    return [
        {'form': '10-Q', 'filed': date(2025, 11, 21), 'figures': quarter('2025-08-01', '2025-10-26', 57_000_000_000, 2026, 'Q3')},
        {'form': '10-Q', 'filed': date(2026, 2, 26), 'figures': quarter('2025-10-27', '2026-01-25', 68_000_000_000, 2026, 'Q4')},
        {'form': '10-Q', 'filed': date(2026, 5, 27), 'figures': quarter('2026-01-26', '2026-04-26', 44_000_000_000, 2027, 'Q1')},
        {'form': '10-Q', 'filed': date(2026, 8, 26), 'figures': quarter('2026-04-27', '2026-07-26', 46_000_000_000, 2027, 'Q2')},
    ]


def onlyq_filings():
    """A company with 10-Q filings only, the rhythm of a quarter."""
    return [
        {'form': '10-Q', 'filed': date(2026, 2, 10), 'figures': [figure('revenue', 'Revenue', [p('2025-10-01', '2025-12-31', 1_000, 2026, 'Q2')])]},
        {'form': '10-Q', 'filed': date(2026, 5, 10), 'figures': [figure('revenue', 'Revenue', [p('2026-01-01', '2026-03-31', 1_100, 2026, 'Q3')])]},
    ]
