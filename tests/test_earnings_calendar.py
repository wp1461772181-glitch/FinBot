"""5e-1: the earnings calendar and consensus (``app.earnings_calendar``) and its line in 「系统最新掌握」 (real PostgreSQL)."""
import io
import json
import urllib.error
from datetime import UTC, date, datetime, timedelta

import pytest

from app import earnings_calendar as ec
from app.database import Base, SessionLocal, engine

NOW = datetime(2026, 11, 28, 2, 0, tzinfo=UTC)
PAYLOAD = {"earningsCalendar": [
    {"symbol": "INTC", "date": "2027-01-20", "hour": "amc", "quarter": 4, "year": 2026, "epsEstimate": 0.2541, "epsActual": None,
     "revenueEstimate": 15847129407, "revenueActual": None},
    {"symbol": "INTC", "date": "2026-10-29", "hour": "amc", "quarter": 3, "year": 2026, "epsEstimate": 0.4043, "epsActual": 0.52,
     "revenueEstimate": 16825612051, "revenueActual": 16513000000},
    {"symbol": "", "date": "2027-01-20", "quarter": 1, "year": 2027},
    {"symbol": "MSFT", "date": "not a date", "quarter": 2, "year": 2027},
    {"symbol": "MSFT", "date": "2027-01-26", "hour": "", "quarter": 2, "year": 2027, "epsEstimate": 4.9626, "revenueEstimate": None}]}


@pytest.fixture(autouse=True)
def world(disposable_database, monkeypatch):
    Base.metadata.create_all(engine, tables=[ec.EarningsCalendar.__table__])
    with SessionLocal() as db:
        db.query(ec.EarningsCalendar).delete()
        db.commit()
    monkeypatch.setenv(ec.KEY_ENV, "test-key")
    monkeypatch.setattr(ec, "tracked_symbols", lambda owner: ["INTC", "MSFT", "ANT"])
    yield


def test_parse_keeps_the_rows_that_name_a_company_a_date_and_a_quarter():
    rows = ec.parse(PAYLOAD)
    assert [(r["symbol"], r["report_date"], r["hour"], r["fiscal_quarter"]) for r in rows] == [
        ("INTC", date(2027, 1, 20), "amc", 4), ("INTC", date(2026, 10, 29), "amc", 3), ("MSFT", date(2027, 1, 26), None, 2)]
    assert rows[1]["eps_actual"] == 0.52 and rows[2]["revenue_estimate"] is None
    assert ec.parse({"error": "You don't have access"}) == [] and ec.parse(None) == []


def test_the_fetch_puts_the_key_in_the_query_only():
    seen = {}

    def opener(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return io.BytesIO(json.dumps(PAYLOAD).encode())
    rows = ec.finnhub_fetch("INTC", date(2026, 11, 21), date(2027, 3, 28), "secret-key", opener=opener)
    assert "symbol=INTC" in seen["url"] and "token=secret-key" in seen["url"] and seen["timeout"] == ec.TIMEOUT_SECONDS and len(rows) == 3


def test_refresh_stores_each_quarter_once_and_updates_it_and_one_failure_does_not_stop_the_rest():
    calls = []

    def fetch(symbol, since, until, key):
        calls.append((symbol, since, until, key))
        if symbol == "ANT":
            raise urllib.error.URLError("no data")
        return [row for row in ec.parse(PAYLOAD) if row["symbol"] == symbol] + [{**ec.parse(PAYLOAD)[0], "symbol": "OTHER"}]
    done = ec.refresh("owner", NOW, fetch=fetch, pause=0)
    assert done == {"symbols": 3, "rows": 3, "errors": ["ANT: URLError"], "skipped": None}, "rows of another symbol are dropped"
    assert calls[0][1:] == (date(2026, 11, 21), date(2027, 3, 28), "test-key")
    assert ec.refresh("owner", NOW + timedelta(hours=2), fetch=fetch, pause=0)["skipped"] == "fresh"
    moved = [{**row, "report_date": date(2027, 1, 22)} if row["fiscal_quarter"] == 4 else row for row in ec.parse(PAYLOAD) if row["symbol"] == "INTC"]
    ec.refresh("owner", NOW + timedelta(hours=21), fetch=lambda symbol, *a: moved if symbol == "INTC" else [], pause=0)
    with SessionLocal() as db:
        intc = db.query(ec.EarningsCalendar).filter_by(symbol="INTC").order_by(ec.EarningsCalendar.fiscal_quarter).all()
    assert [(r.fiscal_quarter, r.report_date) for r in intc] == [(3, date(2026, 10, 29)), (4, date(2027, 1, 22))], "a moved date updates the quarter's row"


def test_without_a_key_nothing_is_fetched(monkeypatch):
    monkeypatch.delenv(ec.KEY_ENV)
    assert ec.refresh("owner", NOW, fetch=lambda *a: pytest.fail("no key, no call"), pause=0)["skipped"] == "no_key"


def test_upcoming_is_each_companys_next_report_and_its_line_says_where_the_consensus_came_from():
    ec.store(ec.parse(PAYLOAD), NOW)
    ahead = ec.upcoming(["intc", "MSFT", "ANT"], date(2026, 11, 28))
    assert sorted(ahead) == ["INTC", "MSFT"] and ahead["INTC"]["report_date"] == "2027-01-20"
    text = ec.line(ahead["INTC"])
    assert text == "下次财报：2027-01-20 盘后（FY2026 Q4）；市场预期（Finnhub，调整后口径）每股收益 0.25 美元、营收 158.5 亿美元；11-28 10:00 拉取"
    assert ec.line(ahead["MSFT"]).startswith("下次财报：2027-01-26（FY2027 Q2）；市场预期（Finnhub，调整后口径）每股收益 4.96 美元；")
    assert "没有拿到市场预期" in ec.line({**ahead["MSFT"], "eps_estimate": None})


def test_the_latest_known_block_carries_the_next_report_with_a_citation(monkeypatch, tmp_path):
    import app.models  # noqa: F401  (registers the filings and prices tables)
    from app import latest_known
    Base.metadata.create_all(engine)
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "sentinel.db"))
    ec.store(ec.parse(PAYLOAD), NOW)
    items = latest_known.gather(["INTC"], now=NOW, with_facts=False)
    intc = next(item for item in items if item["symbol"] == "INTC")
    assert intc["earnings"]["report_date"] == "2027-01-20"
    rows = []
    lines = latest_known._section(intc, NOW, rows)
    earnings = [line for line in lines if "下次财报" in line]
    assert len(earnings) == 1 and "财报日历" in earnings[0] and "市场预期（Finnhub，调整后口径）" in earnings[0]
    cited = [row for row in rows if row["id"].startswith("latest-known:INTC:earnings:")]
    assert cited and cited[0]["source_name"] == "Finnhub" and cited[0]["source_type"] == "market_data"
