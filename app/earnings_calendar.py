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
    """Insert or update each (symbol, fiscal quarter) row; returns how many were written.  A quarter given twice in one batch keeps the
    later row (the session does not flush between rows, so a second insert of the same key would fail the whole batch)."""
    unique = {(row["symbol"], row["fiscal_year"], row["fiscal_quarter"]): row for row in rows}
    written = 0
    with SessionLocal() as db:
        for row in unique.values():
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


def fetched_by_symbol(symbols) -> dict[str, datetime]:
    """When each symbol's calendar was last read (its newest row's ``fetched_at``); a symbol never read is absent."""
    from sqlalchemy import func
    wanted = sorted({str(s).upper() for s in symbols or [] if s})
    if not wanted:
        return {}
    with SessionLocal() as db:
        rows = db.execute(select(EarningsCalendar.symbol, func.max(EarningsCalendar.fetched_at)).where(EarningsCalendar.symbol.in_(wanted))
                          .group_by(EarningsCalendar.symbol)).all()
    return {symbol: at for symbol, at in rows}


def refresh(owner_hash: str, now: datetime | None = None, *, fetch=finnhub_fetch, pause: float = PAUSE_SECONDS, force: bool = False) -> dict:
    """Fetch each tracked company whose own last fetch is older than ``STALE_AFTER`` (or that was never fetched, or failed: it has no new
    row; or all with ``force``).  Each company is its own try: one failing does not stop the others, and the error kept names only the
    company and the kind of error (never the request, which carries the key).  ``{"symbols", "rows", "errors", "skipped"}``; no key:
    ``skipped`` says so and nothing is fetched."""
    now = now or datetime.now(UTC)
    key = os.getenv(KEY_ENV, "").strip()
    if not key:
        return {"symbols": 0, "rows": 0, "errors": [], "skipped": "no_key"}
    tracked = tracked_symbols(owner_hash)
    seen = fetched_by_symbol(tracked)
    symbols = [s for s in tracked if force or s not in seen or now - seen[s] >= STALE_AFTER]
    if not symbols:
        return {"symbols": 0, "rows": 0, "errors": [], "skipped": "fresh"}
    since, until = (now - timedelta(days=BACK_DAYS)).date(), (now + timedelta(days=AHEAD_DAYS)).date()
    rows, errors = [], []
    for index, symbol in enumerate(symbols):
        if index and pause:
            time.sleep(pause)
        try:
            rows += [row for row in fetch(symbol, since, until, key) if row["symbol"] == symbol]
        except Exception as exc:  # noqa: BLE001 - any failure is this company's; the others still go
            errors.append(f"{symbol}: {type(exc).__name__}")
    written = store(rows, now) if rows else 0
    return {"symbols": len(symbols), "rows": written, "errors": errors, "skipped": None}


def upcoming(symbols, today: date, session=None) -> dict[str, dict]:
    """For each symbol its next report on or after ``today`` (US Eastern date) that has not come out yet (no actual EPS), the earliest, as
    stored: ``{symbol: row dict}``; a symbol with none is absent.  ``session``: read in the caller's (its timeouts hold)."""
    from sqlalchemy import and_, or_
    wanted = sorted({str(s).upper() for s in symbols or [] if s})
    if not wanted:
        return {}
    query = (select(EarningsCalendar).where(EarningsCalendar.symbol.in_(wanted), EarningsCalendar.report_date >= today,
                                            or_(EarningsCalendar.eps_actual.is_(None), EarningsCalendar.report_date > today))
             .order_by(EarningsCalendar.symbol, EarningsCalendar.report_date))
    if session is not None:
        rows = session.scalars(query).all()
    else:
        with SessionLocal() as db:
            rows = db.scalars(query).all()
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
    weekday = f"（周{WEEKDAYS[date.fromisoformat(when).weekday()]}，美东）"      # written by code: a model counting days from a date gets it wrong
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


# --- the week's calendar in the Monday brief (5e-2a) ---------------------------------------------------------------------------

WEEK_HEAD = "本周财报（Finnhub 日历；日期为美东，是数据商的预估，以公司公告为准；市场预期为调整后口径）："


def _company(symbol: str) -> str:
    from .owner_views import display_name
    name = display_name(symbol)
    return f"{name}（{symbol}）" if name and name != symbol else symbol


def _expected(row: dict) -> str:
    parts = []
    if row.get("eps_estimate") is not None:
        parts.append(f"每股收益 {row['eps_estimate']:.2f} 美元")
    if row.get("revenue_estimate") is not None:
        parts.append(f"营收 {_amount(row['revenue_estimate'])}")
    return "预期" + "、".join(parts) if parts else "没有拿到市场预期"


def _when(row: dict) -> str:
    reported = date.fromisoformat(row["report_date"])
    hour = HOURS.get(row.get("hour") or "")
    return f"{reported:%m-%d}（周{WEEKDAYS[reported.weekday()]}）" + (f"{hour}" if hour else "")


def week_block(symbols, monday: date) -> tuple[str, bool]:
    """The Monday brief's code-written block: the tracked companies reporting in the US week starting ``monday`` (a Beijing Monday morning is
    the US Sunday night before it), earliest first.  A week with none says so and names the next report, if any is known; nothing known at
    all is an empty string.  The second value says whether any company reports this week (the brief sends for that alone)."""
    wanted = sorted({str(s).upper() for s in symbols or [] if s})
    if not wanted:
        return "", False
    with SessionLocal() as db:
        rows = [as_dict(row) for row in db.scalars(select(EarningsCalendar).where(
            EarningsCalendar.symbol.in_(wanted), EarningsCalendar.report_date >= monday, EarningsCalendar.eps_actual.is_(None))
            .order_by(EarningsCalendar.report_date, EarningsCalendar.symbol)).all()]
    if not rows:
        return "", False
    end = monday + timedelta(days=6)
    week = [row for row in rows if date.fromisoformat(row["report_date"]) <= end]
    if not week:
        nxt = rows[0]
        return f"本周你持有和关注的公司没有财报；最近的一家是 {_when(nxt)} {_company(nxt['symbol'])}（美东日期）。", False
    return WEEK_HEAD + "".join(f"\n· {_when(row)}　{_company(row['symbol'])}　{_expected(row)}" for row in week), True


# --- the evening-before preparation (5e-2b) -------------------------------------------------------------------------------------

def reporting_next(symbols, beijing_day: date) -> list[dict]:
    """The tracked companies reporting in the next half day, seen from a Beijing evening: an after-the-close, during-the-market or not-said
    report on the US date equal to the Beijing date (out tonight or before the Beijing morning), and a before-the-open report on the next US
    date (out tomorrow evening Beijing).  Not reported yet; earliest first."""
    wanted = sorted({str(s).upper() for s in symbols or [] if s})
    if not wanted:
        return []
    tomorrow = beijing_day + timedelta(days=1)
    with SessionLocal() as db:
        rows = [as_dict(row) for row in db.scalars(select(EarningsCalendar).where(
            EarningsCalendar.symbol.in_(wanted), EarningsCalendar.report_date.in_([beijing_day, tomorrow]), EarningsCalendar.eps_actual.is_(None))
            .order_by(EarningsCalendar.report_date, EarningsCalendar.symbol)).all()]
    return [row for row in rows if (row["report_date"] == beijing_day.isoformat() and row.get("hour") != "bmo")
            or (row["report_date"] == tomorrow.isoformat() and row.get("hour") == "bmo")]


def beijing_release(row: dict) -> str:
    """Roughly when the report is out in Beijing time, written by code (the model is told to copy it, not to convert)."""
    reported = date.fromisoformat(row["report_date"])
    hour = row.get("hour")
    if hour == "amc":
        return f"北京时间 {reported + timedelta(days=1):%m-%d} 清晨 4 点到 6 点前后（美东 {reported:%m-%d} 盘后）"
    if hour == "bmo":
        return f"北京时间 {reported:%m-%d} 晚上 7 点到 9 点前后（美东 {reported:%m-%d} 盘前）"
    if hour == "dmh":
        return f"北京时间 {reported:%m-%d} 晚上到 {reported + timedelta(days=1):%m-%d} 凌晨之间（美东 {reported:%m-%d} 盘中）"
    return f"美东 {reported:%m-%d}，盘前还是盘后没有说；最早北京时间 {reported:%m-%d} 晚上，最晚 {reported + timedelta(days=1):%m-%d} 清晨"


class EarningsPrep(Base):
    """One evening's 「财报前瞻」 (``kernel.prep``): claimed before anything happens, finished whatever happened, one per owner and Beijing day."""
    __tablename__ = "earnings_prep"
    __table_args__ = (UniqueConstraint("owner_hash", "day", name="uq_earnings_prep_owner_day"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)                     # Beijing date of the evening
    mode: Mapped[str] = mapped_column(String(8), nullable=False)                     # off | shadow | on, when it ran
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)                 # running | done | skipped | skipped_off | failed
    symbols: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    message: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    delivery: Mapped[str | None] = mapped_column(String(32), nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


PREP_FIELDS = ("outcome", "symbols", "reason", "message", "delivery", "turn_id", "model_calls")


def prep_claim(owner_hash: str, day: str, mode: str) -> int | None:
    from sqlalchemy.exc import IntegrityError
    row = EarningsPrep(owner_hash=owner_hash, day=day, mode=mode, outcome="running")
    with SessionLocal() as db:
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return row.id


def prep_finish(row_id: int, **fields) -> dict:
    if set(fields) - set(PREP_FIELDS):
        raise ValueError("invalid_prep_row")
    with SessionLocal() as db:
        row = db.get(EarningsPrep, row_id)
        for key, value in fields.items():
            setattr(row, key, str(value)[:8000] if key in ("message",) and value is not None else value)
        db.commit()
        return {"id": row.id, "day": row.day, "mode": row.mode, "outcome": row.outcome, "symbols": row.symbols, "reason": row.reason,
                "message": row.message, "delivery": row.delivery, "turn_id": row.turn_id, "model_calls": row.model_calls}


def prep_taken(owner_hash: str, day: str) -> bool:
    with SessionLocal() as db:
        return db.scalar(select(EarningsPrep.id).where(EarningsPrep.owner_hash == owner_hash, EarningsPrep.day == day)) is not None


# --- actual against the consensus in the earnings follow-up (5e-3) --------------------------------------------------------------

def consensus_for(symbol: str, reported: date, window_days: int = 3) -> dict | None:
    """The calendar row of the report a filing on ``reported`` (US Eastern date) belongs to: the same company, its report date within
    ``window_days`` of the filing's, the nearest one; None when the calendar has no such row."""
    with SessionLocal() as db:
        rows = [as_dict(row) for row in db.scalars(select(EarningsCalendar).where(
            EarningsCalendar.symbol == str(symbol).upper(),
            EarningsCalendar.report_date >= reported - timedelta(days=window_days),
            EarningsCalendar.report_date <= reported + timedelta(days=window_days))).all()]
    if not rows:
        return None
    return min(rows, key=lambda row: abs((date.fromisoformat(row["report_date"]) - reported).days))


def _versus(actual: float, expected: float) -> str:
    if not expected:
        return ""
    gap = (actual - expected) / abs(expected) * 100
    if abs(gap) < 0.05:
        return "，与预期持平"
    return f"，比预期{'高' if gap > 0 else '低'} {abs(gap):.1f}%"


def consensus_lines(row: dict | None, revenue_billions: float | None, eps_adjusted: float | None) -> list[str]:
    """The follow-up's 「对比市场预期」 section, written by code: revenue and adjusted EPS against the consensus the calendar holds for this
    report.  A report the calendar does not know says so in one line."""
    head = f"对比市场预期（{SOURCE_NAME}，调整后口径）"
    if row is None or (row.get("eps_estimate") is None and row.get("revenue_estimate") is None):
        return [head, "· 这一季没有拿到市场预期"]
    lines = [head]
    if row.get("revenue_estimate") is not None:
        expected = row["revenue_estimate"] / 1e9
        if revenue_billions is not None:
            lines.append(f"· 营收 {revenue_billions:.2f}B：预期 {expected:.2f}B{_versus(revenue_billions, expected)}")
        else:
            lines.append(f"· 营收：预期 {expected:.2f}B（新闻稿里没取到实际数）")
    if row.get("eps_estimate") is not None:
        if eps_adjusted is not None:
            lines.append(f"· 每股收益（非 GAAP）{eps_adjusted:.2f}：预期 {row['eps_estimate']:.2f}{_versus(eps_adjusted, row['eps_estimate'])}")
        else:
            lines.append(f"· 每股收益：预期 {row['eps_estimate']:.2f}（新闻稿里没取到实际数）")
    return lines
