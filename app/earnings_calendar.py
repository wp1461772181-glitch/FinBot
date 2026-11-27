"""The earnings calendar and the market's consensus (5e-1, design §7.4): when each company the owner holds or follows reports next, and
what analysts expect (EPS and revenue).

The data comes from a provider (Finnhub's ``/calendar/earnings`` on its free plan; ``FINNHUB_API_KEY`` on the box, placed by the owner) and
is kept in ``earnings_calendar``, one row per company and fiscal quarter, with where it came from and when it was fetched.  A background loop
refreshes it once a day; nothing else calls the provider.  Without a key nothing is fetched and nothing breaks.

The provider is one function (``finnhub_fetch``): another provider is another function returning the same rows.  Its EPS is the adjusted
(non-GAAP) figure analysts forecast; whoever shows it says so.  The free plan has holes in past quarters (a report it missed), so the
calendar says when a company reports and what is expected; whether a report has come out is still the SEC monitor's word.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

log = logging.getLogger(__name__)

SOURCE = "finnhub"
SOURCE_NAME = "Finnhub"
KEY_ENV = "FINNHUB_API_KEY"
URL = "https://finnhub.io/api/v1/calendar/earnings"
TIMEOUT_SECONDS = 15
PAUSE_SECONDS = 1.1            # the free plan allows 60 calls a minute
BACK_DAYS = 7
AHEAD_DAYS = 120
STALE_AFTER = timedelta(hours=20)
HOURS = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}
WEEKDAYS = "一二三四五六日"


class EarningsCalendar(Base):
    """One company's report for one fiscal quarter as the provider gives it: the date (and before / after the market), the consensus EPS and
    revenue, and once reported the actual ones.  ``fetched_at`` is when this row was last read from the provider."""
    __tablename__ = "earnings_calendar"
    __table_args__ = (UniqueConstraint("symbol", "fiscal_year", "fiscal_quarter", "source", name="uq_earnings_calendar_quarter"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hour: Mapped[str | None] = mapped_column(String(4), nullable=True)               # bmo | amc | dmh | None (not said)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    eps_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=SOURCE)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None          # NaN is no number


def parse(payload) -> list[dict]:
    """The provider's rows as ours; a row without a symbol, a date or its quarter is left out."""
    rows = payload.get("earningsCalendar") if isinstance(payload, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            reported = date.fromisoformat(str(row.get("date")))
            year, quarter = int(row.get("year")), int(row.get("quarter"))
        except (TypeError, ValueError):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol or not 1 <= quarter <= 4:
            continue
        hour = str(row.get("hour") or "").strip().lower()
        out.append({"symbol": symbol, "report_date": reported, "hour": hour if hour in HOURS else None, "fiscal_year": year, "fiscal_quarter": quarter,
                    "eps_estimate": _number(row.get("epsEstimate")), "revenue_estimate": _number(row.get("revenueEstimate")),
                    "eps_actual": _number(row.get("epsActual")), "revenue_actual": _number(row.get("revenueActual"))})
    return out


def finnhub_fetch(symbol: str, since: date, until: date, key: str, opener=urllib.request.urlopen) -> list[dict]:
    """One company's calendar rows between two dates from Finnhub.  The key goes in the query and is never logged; a failure raises."""
    query = urllib.parse.urlencode({"symbol": symbol, "from": since.isoformat(), "to": until.isoformat(), "token": key})
    with opener(URL + "?" + query, timeout=TIMEOUT_SECONDS) as response:
        return parse(json.loads(response.read()))


def tracked_symbols(owner_hash: str) -> list[str]:
    """What the owner holds, queues for research and has his bots focus on (the same set the quarterly settle keeps views for)."""
    from .memory_settle import _focused, _held, _queued
    with SessionLocal() as db:
        found = _queued(db, owner_hash) | _focused(db, owner_hash)
    return sorted(found | _held(owner_hash))


def store(rows: list[dict], now: datetime) -> int:
    """Insert or update each (symbol, fiscal quarter) row; returns how many were written."""
    written = 0
    with SessionLocal() as db:
        for row in rows:
            found = db.scalar(select(EarningsCalendar).where(EarningsCalendar.symbol == row["symbol"], EarningsCalendar.fiscal_year == row["fiscal_year"],
                                                              EarningsCalendar.fiscal_quarter == row["fiscal_quarter"], EarningsCalendar.source == SOURCE))
            if found is None:
                db.add(EarningsCalendar(**row, source=SOURCE, fetched_at=now))
            else:
                for field, value in row.items():
                    setattr(found, field, value)
                found.fetched_at = now
            written += 1
        db.commit()
    return written


def last_fetched() -> datetime | None:
    with SessionLocal() as db:
        return db.scalar(select(EarningsCalendar.fetched_at).order_by(EarningsCalendar.fetched_at.desc()).limit(1))


def refresh(owner_hash: str, now: datetime | None = None, *, fetch=finnhub_fetch, pause: float = PAUSE_SECONDS, force: bool = False) -> dict:
    """Fetch the tracked companies' calendars when the last fetch is older than ``STALE_AFTER`` (or ``force``).  One company failing does
    not stop the others.  ``{"symbols", "rows", "errors", "skipped"}``; no key: ``skipped`` says so and nothing is fetched."""
    now = now or datetime.now(UTC)
    key = os.getenv(KEY_ENV, "").strip()
    if not key:
        return {"symbols": 0, "rows": 0, "errors": [], "skipped": "no_key"}
    latest = last_fetched()
    if not force and latest is not None and now - latest < STALE_AFTER:
        return {"symbols": 0, "rows": 0, "errors": [], "skipped": "fresh"}
    symbols = tracked_symbols(owner_hash)
    since, until = (now - timedelta(days=BACK_DAYS)).date(), (now + timedelta(days=AHEAD_DAYS)).date()
    rows, errors = [], []
    for index, symbol in enumerate(symbols):
        if index and pause:
            time.sleep(pause)
        try:
            rows += [row for row in fetch(symbol, since, until, key) if row["symbol"] == symbol]
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{symbol}: {type(exc).__name__}")
    written = store(rows, now) if rows else 0
    return {"symbols": len(symbols), "rows": written, "errors": errors, "skipped": None}


def upcoming(symbols, today: date) -> dict[str, dict]:
    """For each symbol its next report on or after ``today`` (the earliest), as stored: ``{symbol: row dict}``; a symbol with none is absent."""
    wanted = sorted({str(s).upper() for s in symbols or [] if s})
    if not wanted:
        return {}
    with SessionLocal() as db:
        rows = db.scalars(select(EarningsCalendar).where(EarningsCalendar.symbol.in_(wanted), EarningsCalendar.report_date >= today)
                          .order_by(EarningsCalendar.symbol, EarningsCalendar.report_date)).all()
    found: dict[str, dict] = {}
    for row in rows:
        found.setdefault(row.symbol, as_dict(row))
    return found


def as_dict(row: EarningsCalendar) -> dict:
    return {"symbol": row.symbol, "report_date": row.report_date.isoformat(), "hour": row.hour, "fiscal_year": row.fiscal_year,
            "fiscal_quarter": row.fiscal_quarter, "eps_estimate": row.eps_estimate, "revenue_estimate": row.revenue_estimate,
            "eps_actual": row.eps_actual, "revenue_actual": row.revenue_actual, "source": row.source,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None}


def _amount(value: float) -> str:
    """Dollars as people read them: 亿美元 from 100 million up, 万美元 below."""
    if abs(value) >= 1e8:
        return f"{value / 1e8:,.1f} 亿美元"
    return f"{value / 1e4:,.0f} 万美元"


def line(row: dict) -> str:
    """One line for a company's next report: its date and hour, and the consensus with where it came from and when it was read."""
    when = row["report_date"]
    weekday = f"（周{WEEKDAYS[date.fromisoformat(when).weekday()]}）"      # written by code: a model counting days from a date gets it wrong
    hour = HOURS.get(row.get("hour") or "")
    expected = []
    if row.get("eps_estimate") is not None:
        expected.append(f"每股收益 {row['eps_estimate']:.2f} 美元")
    if row.get("revenue_estimate") is not None:
        expected.append(f"营收 {_amount(row['revenue_estimate'])}")
    fetched = datetime.fromisoformat(row["fetched_at"]).astimezone(UTC) + timedelta(hours=8) if row.get("fetched_at") else None
    told = f"市场预期（{SOURCE_NAME}，调整后口径）" + "、".join(expected) if expected else "没有拿到市场预期"
    stamp = f"；{fetched:%m-%d %H:%M} 拉取" if fetched else ""
    return f"下次财报：{when}{weekday}{(' ' + hour) if hour else ''}（财年 FY{row['fiscal_year']} Q{row['fiscal_quarter']}）；{told}{stamp}"
