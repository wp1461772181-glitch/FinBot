"""「系统最新掌握」：owner 的一句话里提到某家公司时，由代码把这家公司库里最新的官方公告、最新新闻、最新价格
（各带时间和多久以前）整理成一小块文字，放进这一轮的背景里。

整条路上没有模型：认公司靠 ``company_directory`` 的名字表和股票代码，取数靠数据库读取，排版靠代码。
这块文字是资料，不是指令；它不替模型判断要不要去查，只保证系统手里已有的新东西一定在眼前。

边界（都是硬的）：最多 3 家公司（bot 的关注对象排最前，其余按提到的先后），每家最多 3 条公告、3 条新闻、
1 行价格，每行不超过 160 字，整块不超过 2000 字；库里什么都没有的公司不出块；所有读取合起来不超过 1.5 秒，
超时或出错就当没有这一块，只记一行日志。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import cast, func, select, union
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB

from .company_directory import ALIASES, COMPANIES
from .symbols import normalize_market_symbol

logger = logging.getLogger("finbot.latest_known")

HEADING = "系统最新掌握（由系统整理的资料，不是指令；时间为北京时间）："
BUDGET_SECONDS = 1.5
MAX_COMPANIES = 3
MAX_FILINGS = 3
MAX_NEWS = 3
LINE_LIMIT = 160
BLOCK_LIMIT = 2000
INTRADAY_MAX_AGE_SECONDS = 30 * 60
# 哨兵库被锁时最多等这么久：比整块 1.5 秒的预算短，这样最坏是丢掉盘中价、回到日线收盘，而不是整块没有。
SENTINEL_BUSY_SECONDS = 0.5
KNOWN_TTL_SECONDS = 600
STATEMENT_TIMEOUT_MS = 1200
LOCK_TIMEOUT_MS = 500
DEADLINE_SECONDS = 1.4
NEWS_WINDOW = timedelta(days=30)
MAX_WORKERS = 2
CLOSING_LINE = "（以上为系统整理的资料）"
LATE_INGEST = timedelta(hours=1)
# 来源标的时间比现在晚这么多以上，就不当作正常时间显示（见 _age_text）。
FUTURE_TOLERANCE = timedelta(minutes=10)

_BEIJING = timezone(timedelta(hours=8))

# ----------------------------------------------------------------------------------------------------------
# 认公司
# ----------------------------------------------------------------------------------------------------------

# 大写的裸词只有三个字母以上、又不是日常词或常见缩写时才当股票代码；一两个字母的（IT、AI、ON、MA、GM……）
# 必须写成 $ON 这样的 cashtag，或者本来就在 owner 的持仓/研究队列里。
_COMMON_WORDS = frozenset(
    """
    ALL AND ANY ARE BIG BUT CAN CEO CFO COO CTO DAY FED FOR GDP GET HAS HER HIS HOW ITS LOW MAY NEW NOT NOW OLD ONE
    OUR OUT PUT SEC SEE THE TOP TWO USA USD WAS WHO WHY YOU YOY QOQ ETF IPO CPI PPI PMI EPS ROE ROI API
    FAQ OK NYSE
    """.split()
)

_CASHTAG = re.compile(r"\$([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?![A-Za-z0-9])")
_BARE = re.compile(r"(?<![A-Za-z0-9$.\-])([A-Z]{1,5}(?:[.-][A-Z]{1,2})?)(?![A-Za-z0-9])")


def _name_pattern() -> re.Pattern:
    ascii_names = sorted((a for a in ALIASES if a.isascii()), key=len, reverse=True)
    other_names = sorted((a for a in ALIASES if not a.isascii()), key=len, reverse=True)
    parts = []
    if ascii_names:
        parts.append(r"(?<![a-z0-9])(?:" + "|".join(re.escape(a) for a in ascii_names) + r")(?![a-z0-9])")
    if other_names:
        parts.append("(?:" + "|".join(re.escape(a) for a in other_names) + ")")
    return re.compile("|".join(parts))


_NAMES = _name_pattern()

_known_cache: frozenset[str] | None = None
_known_lock = threading.Lock()
_known_failing = False
_refresher: threading.Thread | None = None
_stop = threading.Event()


@contextmanager
def _read_session():
    """只读会话：库自己在 1.2 秒后取消查询，等锁最多 0.5 秒；用完一定关。"""
    from .database import SessionLocal

    session = SessionLocal()
    try:
        session.execute(sql_text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        session.execute(sql_text(f"SET LOCAL lock_timeout = {LOCK_TIMEOUT_MS}"))
        yield session
    finally:
        session.close()


def refresh_known() -> bool:
    """重读「库里有公告或日线价格的代码」。加锁；出错时保留上一份，同一段连续失败只记一行日志。"""
    global _known_cache, _known_failing
    from .models import MarketPrice, SecFilingInventory

    with _known_lock:
        try:
            with _read_session() as session:
                symbols = frozenset(row[0] for row in session.execute(
                    union(select(SecFilingInventory.symbol), select(MarketPrice.symbol))) if row[0])
        except Exception as exc:
            if not _known_failing:
                logger.warning("latest_known: reading known symbols failed (%s: %s); keeping the previous set",
                               type(exc).__name__, exc)
            _known_failing = True
            return False
        _known_cache = symbols
        _known_failing = False
        return True


def _known_symbols() -> frozenset[str]:
    """当前缓存的已知代码；回合路径上从不读库（启动时预热，之后后台每 10 分钟刷新）。还没读到过就是空集。"""
    return _known_cache or frozenset()


def forget_known() -> None:
    global _known_cache, _known_failing
    _known_cache = None
    _known_failing = False


def start_known_refresh() -> None:
    """启动时调用一次：后台线程先读一遍，之后每 10 分钟刷新；失败后 30 秒起逐步退避（上限 10 分钟）。"""
    global _refresher
    if _refresher is not None and _refresher.is_alive():
        return
    _stop.clear()

    def loop() -> None:
        delay = 0.0
        failed_for = 0.0
        while not _stop.wait(delay):
            if refresh_known():
                failed_for = 0.0
                delay = float(KNOWN_TTL_SECONDS)
            else:
                failed_for = min(max(failed_for * 2, 30.0), float(KNOWN_TTL_SECONDS))
                delay = failed_for

    _refresher = threading.Thread(target=loop, name="latest-known-refresh", daemon=True)
    _refresher.start()


def stop_known_refresh() -> None:
    """关机时调用：停掉后台刷新线程（最多等 2 秒让它读完手头那一次），并忘掉缓存，之后的启动从头预热。"""
    global _refresher
    _stop.set()
    thread = _refresher
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2)
    if thread is None or not thread.is_alive():
        _refresher = None
    forget_known()


def _normalize(value: str) -> str | None:
    try:
        return normalize_market_symbol(value)
    except ValueError:
        return None


# 日常词也是公司名的英文名，只在首字母大写时才算；meta 还要后面不是 analysis/data 这类词。
_CAPITAL_ONLY = frozenset({"meta", "apple", "amazon", "oracle"})
_META_NOT_COMPANY = re.compile(r"\s*[-\s]?(analysis|analyses|data|description|tags?|learning|physics|model|tag)\b", re.I)
# 「苹果」同时是水果：后面紧跟这些产品词时说的是产品，不是公司。
_AMBIGUOUS_CJK = frozenset({"苹果", "蘋果"})
_PRODUCT_NOUNS = ("手机", "电脑", "平板", "手表", "耳机", "汽车")
_EXCHANGE_SUFFIXES = frozenset({"O", "OQ", "N", "K", "A", "P", "Z"})


def _resolve(symbol: str | None, known) -> str | None:
    """NVDA.O / BRK.B：先按原样，不在已知里时去掉交易所后缀（.O .N …）再试。"""
    if not symbol:
        return None
    if symbol in known:
        return symbol
    base, _, suffix = symbol.partition(".")
    if suffix in _EXCHANGE_SUFFIXES and base in known:
        return base
    return None


def _scan(text: str, known: set[str] | frozenset[str], owned: set[str] | frozenset[str]) -> list[str]:
    """一段话里提到的股票代码，按先后排，去重。"""
    hits: list[tuple[int, str]] = []
    for match in _CASHTAG.finditer(text):
        symbol = _resolve(_normalize(match.group(1)), known)
        if symbol:
            hits.append((match.start(), symbol))
    for match in _BARE.finditer(text):
        raw = _normalize(match.group(1))
        symbol = _resolve(raw, known)
        if not symbol:
            continue
        letters = len(symbol.split(".")[0])
        if symbol in owned or (letters >= 3 and symbol not in _COMMON_WORDS):
            hits.append((match.start(), symbol))
    for match in _NAMES.finditer(text.lower()):
        name = match.group(0)
        symbol = ALIASES.get(name)
        if not symbol or symbol not in known:
            continue
        start, end = match.start(), match.end()
        if name in _CAPITAL_ONLY and not text[start:start + 1].isupper():
            continue
        if name == "meta" and _META_NOT_COMPANY.match(text, end):
            continue
        if name in _AMBIGUOUS_CJK and text.startswith(_PRODUCT_NOUNS, end):
            continue
        hits.append((start, symbol))
    hits.sort(key=lambda hit: hit[0])
    ordered: list[str] = []
    for _, symbol in hits:
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered


_PRONOUN = re.compile(r"它们?|这家|该公司|其|\b(?:this|it|they)\b", re.I)
_SHORT_FOLLOW_UP = 12


def mentions(text: str, *, previous: str | None = None, focus: str | None = None,
             owned: set[str] = frozenset(), known: set[str] | None = None) -> list[str]:
    """这句话提到了哪些公司：先 bot 的关注对象，再按提到的先后。

    ``previous`` 只在这句话本身没提到任何公司、且像追问（带「它/这家/该公司/this/it/they」或不超过 12 个字）时才用，最多沿用 3 家。
    ``known`` 默认是库里有公告或日线价格的代码。"""
    if known is None:
        known = _known_symbols()
    owned = {s for s in (_normalize(o) for o in owned) if s}
    found = _scan(text or "", known, owned)
    follow_up = bool(_PRONOUN.search(text or "")) or len((text or "").strip()) <= _SHORT_FOLLOW_UP
    if not found and previous and follow_up:
        found = _scan(previous, known, owned)[:MAX_COMPANIES]
    ordered: list[str] = []
    focus_symbol = _normalize(focus) if focus else None
    for symbol in ([focus_symbol] if focus_symbol else []) + found:
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered


# ----------------------------------------------------------------------------------------------------------
# 取数
# ----------------------------------------------------------------------------------------------------------

_EXHIBIT_PREFIX = re.compile(
    r"^(?:EX-\d+(?:\.\d+)?\s+(?:\d+\s+\S+\.htm\s+)?)+(?:Document\s+)?(?:Exhibit\s+\d+(?:\.\d+)?\s+)?", re.I)
_FORM_LABELS = {"10-K": "年报", "10-Q": "季报", "20-F": "年报", "40-F": "年报", "DEF 14A": "股东大会委托书"}
_ITEM_LINE = re.compile(r"Item\s+\d\.\d\d\.?\s+[A-Z][^\n]{0,90}")
_HEAD_CHARS = 80


def _shorten(text: str) -> str:
    return text if len(text) <= _HEAD_CHARS else text[:_HEAD_CHARS].rstrip() + "…"


def _clean(value) -> str:
    """外来的文字（新闻标题、来源、公告开头、公司名）压成一行纯文字：控制字符、各种换行/段落分隔符
    （含 U+2028、U+2029、U+0085）、制表符和连续空白都变成一个空格。"""
    chars = (" " if ch.isspace() or unicodedata.category(ch).startswith("C") else ch for ch in str(value or ""))
    return " ".join("".join(chars).split())


def _head(excerpt: str | None, kind: str | None) -> str:
    """公告没有标题列：新闻稿取摘录开头的文字；8-K 正文取第一条 Item 的名称；封面套话不算。"""
    if not excerpt:
        return ""
    if kind == "primary_document":
        item = _ITEM_LINE.search(excerpt)
        return _shorten(_clean(item.group(0))) if item else ""
    return _shorten(_EXHIBIT_PREFIX.sub("", _clean(excerpt)))


def _parse_accepted(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _display_name(symbol: str) -> str:
    for name in COMPANIES.get(symbol, ()):
        if not name.isascii():
            return _clean(name)
    return ""


def _sentinel_path() -> Path:
    configured = os.environ.get("SENTINEL_DB_PATH")
    return Path(configured) if configured else Path(__file__).resolve().parent.parent / "data" / "sentinel.db"


def _sentinel_prices(symbols: list[str], now: datetime) -> dict[str, tuple[float, datetime]]:
    """哨兵库里 30 分钟内的盘中价；库不存在、被锁、表不对、数据太旧，都当没有。"""
    path = _sentinel_path()
    if not symbols or not path.is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=SENTINEL_BUSY_SECONDS)
    except sqlite3.Error:
        return {}
    try:
        marks = ",".join("?" for _ in symbols)
        rows = conn.execute(f"SELECT symbol, price, ts FROM price_state WHERE symbol IN ({marks})", symbols).fetchall()
    except sqlite3.Error as exc:
        logger.info("latest_known: sentinel price_state unreadable (%s)", exc)
        return {}
    finally:
        conn.close()
    found: dict[str, tuple[float, datetime]] = {}
    for symbol, price, ts in rows:
        try:
            at = datetime.fromtimestamp(float(ts), UTC)
            value = float(price)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        age = (now - at).total_seconds()
        if value > 0 and -FUTURE_TOLERANCE.total_seconds() <= age <= INTRADAY_MAX_AGE_SECONDS:
            found[symbol] = (value, at)
    return found


def _trading_day(at: datetime) -> date:
    try:
        from zoneinfo import ZoneInfo
        return at.astimezone(ZoneInfo("America/New_York")).date()
    except Exception:
        return (at - timedelta(hours=5)).date()


def gather(symbols: list[str], *, now: datetime, deadline: float | None = None) -> list[dict]:
    """每个代码库里最新的东西；什么都没有的代码不出现在结果里。同步函数，调用方放进线程。"""
    from .agent_chat_models import NewsItem
    from .models import MarketPrice, SecFilingInventory

    intraday = _sentinel_prices(symbols, now)
    items: list[dict] = []
    with _read_session() as session:
        for symbol in symbols:
            if deadline is not None and time.monotonic() > deadline:
                break
            filing_rows = session.execute(
                select(SecFilingInventory.form, SecFilingInventory.filed_at, SecFilingInventory.accepted_at,
                       SecFilingInventory.observed_at, SecFilingInventory.content_status,
                       SecFilingInventory.content_kind, func.left(SecFilingInventory.content_excerpt, 6000),
                       SecFilingInventory.source_url, SecFilingInventory.accession_number)
                .where(SecFilingInventory.symbol == symbol, SecFilingInventory.review_status != "rejected")
                .order_by(SecFilingInventory.filed_at.desc(), SecFilingInventory.accepted_at.desc().nulls_last(),
                          SecFilingInventory.observed_at.desc())
                .limit(MAX_FILINGS)
            ).all()
            filings = [{
                "form": form,
                "accepted_at": _parse_accepted(accepted),
                "filed_at": filed,
                "observed_at": observed,
                "kind": kind,
                "fetched": status == "fetched",
                "head": _head(excerpt, kind),
                "url": url,
                "accession": accession,
            } for form, filed, accepted, observed, status, kind, excerpt, url, accession in filing_rows]

            news_rows = session.execute(
                select(NewsItem.title, NewsItem.source_name, NewsItem.published_at, NewsItem.time_inferred, NewsItem.url)
                .where(NewsItem.published_at >= now - NEWS_WINDOW, cast(NewsItem.tickers, JSONB).contains([symbol]))
                # 来源写错成将来的时间也不能排到最前：按「发布时间」和「入库时间」里较早的那个排
                .order_by(func.least(NewsItem.published_at, NewsItem.fetched_at).desc())
                .limit(MAX_NEWS * 4)
            ).all()
            news: list[dict] = []
            seen: set[str] = set()
            for title, source, published, inferred, link in news_rows:
                key = _clean(title)
                if not key or key in seen:
                    continue
                seen.add(key)
                news.append({"title": key, "source": _clean(source), "published_at": published, "inferred": bool(inferred), "url": link})
                if len(news) == MAX_NEWS:
                    break

            bars = session.execute(
                select(MarketPrice.trading_date, MarketPrice.close, MarketPrice.fetched_at)
                .where(MarketPrice.symbol == symbol)
                .distinct(MarketPrice.trading_date)
                .order_by(MarketPrice.trading_date.desc(), MarketPrice.fetched_at.desc())
                .limit(2)
            ).all()
            price = None
            if symbol in intraday:
                value, at = intraday[symbol]
                previous = session.execute(
                    select(MarketPrice.close).where(MarketPrice.symbol == symbol, MarketPrice.trading_date < _trading_day(at))
                    .order_by(MarketPrice.trading_date.desc(), MarketPrice.fetched_at.desc()).limit(1)
                ).scalar()
                price = {"kind": "intraday", "value": value, "at": at,
                         "change_pct": (value / previous - 1) * 100 if previous else None}
            elif bars:
                latest = bars[0]
                prev_close = bars[1][1] if len(bars) > 1 else None
                price = {"kind": "close", "value": float(latest[1]), "at": latest[2], "date": latest[0],
                         "change_pct": (latest[1] / prev_close - 1) * 100 if prev_close else None}

            if filings or news or price:
                items.append({"symbol": symbol, "name": _display_name(symbol),
                              "filings": filings, "news": news, "price": price})
    return items


# ----------------------------------------------------------------------------------------------------------
# 排版
# ----------------------------------------------------------------------------------------------------------

def _beijing(at: datetime, now: datetime) -> str:
    local = at.astimezone(_BEIJING)
    if local.year != now.astimezone(_BEIJING).year:
        return local.strftime("%Y-%m-%d %H:%M")
    return local.strftime("%m-%d %H:%M")


def _age_text(at: datetime, now: datetime) -> str:
    seconds = (now - at).total_seconds()
    if seconds < -FUTURE_TOLERANCE.total_seconds():
        return "标注时间晚于当前，来源时间可能有误"
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes} 分钟前"
    if minutes < 24 * 60:
        return f"{minutes // 60} 小时前"
    return f"{minutes // (24 * 60)} 天前"


def _stamp(at: datetime, now: datetime) -> str:
    return f"{_beijing(at, now)} · {_age_text(at, now)}"


def _cap(line: str) -> str:
    # 最后一道：不论字段干不干净，一行里绝不留换行、分隔符和控制字符（保留空格数量不动）
    line = "".join(" " if ch.isspace() or unicodedata.category(ch).startswith("C") else ch for ch in line)
    return line if len(line) <= LINE_LIMIT else line[: LINE_LIMIT - 1] + "…"


def _filing_line(filing: dict, now: datetime) -> str:
    accepted = filing.get("accepted_at")
    observed = filing.get("observed_at")
    if accepted is not None:
        stamp = _stamp(accepted, now)
        if observed is not None and observed - accepted > LATE_INGEST:
            stamp += f"（入库 {_beijing(observed, now)}）"
    elif observed is not None:
        stamp = f"入库 {_stamp(observed, now)}"
    else:
        stamp = "时间不详"
    label = _clean(filing.get("form", ""))
    if label in _FORM_LABELS:
        label += f"（{_FORM_LABELS[label]}）"
    if filing.get("kind") == "exhibit_99_1":
        label += "（新闻稿 EX-99.1）"
    head = _clean(filing.get("head"))
    tail = f"：{head}" if head else ""
    if not filing.get("fetched", True):
        tail += "（正文还没取到）"
    return _cap(f"  官方公告  {stamp}  {label}{tail}")


def _news_line(news: dict, now: datetime) -> str:
    stamp = _stamp(news["published_at"], now)
    if news.get("inferred"):
        stamp += "（时间为推断）"
    source = _clean(news.get("source"))
    source = f"{source}：" if source else ""
    return _cap(f"  新闻      {stamp}  {source}{_clean(news.get('title'))}")


def _price_line(price: dict, now: datetime) -> str:
    change = price.get("change_pct")
    tail = f"，较前收 {change:+.1f}%" if change is not None else ""
    if price["kind"] == "intraday":
        return _cap(f"  价格      {_stamp(price['at'], now)}  盘中价 {price['value']:.2f}（哨兵报价）{tail}")
    day = price.get("date")
    label = f"收盘价（日线，{day.strftime('%m-%d')} 收盘）" if day else "收盘价（日线）"
    return _cap(f"  价格      {label} {price['value']:.2f}{tail}（{_stamp(price['at'], now)} 记录）")


def _marked(line: str, row: dict, rows: list | None) -> str:
    """With ``rows`` (a list to fill), the line is a citable row: its text is what the model sees, ``[#k]`` is where its citation number goes."""
    if rows is None:
        return line
    row = {**row, "excerpt": " ".join(line.split()), "_k": len(rows) + 1}
    rows.append(row)
    return f"  [#{row['_k']}] " + line[2:]


def _section(item: dict, now: datetime, rows: list | None = None) -> list[str]:
    symbol = item["symbol"]
    name = item.get("name") or ""
    name = _clean(name)
    lines = [f"关于 {name}（{symbol}）：" if name else f"关于 {symbol}："]
    for f in item.get("filings", [])[:MAX_FILINGS]:
        stamp = f.get("accepted_at") or f.get("observed_at")
        lines.append(_marked(_filing_line(f, now), {
            "id": f"latest-known:{symbol}:filing:{f.get('accession') or f.get('form')}", "symbol": symbol, "title": f"{symbol} {_clean(f.get('form'))}",
            "source_type": "official_filing", "source_url": f.get("url"), "url": f.get("url"), "source_name": "SEC EDGAR",
            "published_at": stamp.isoformat() if stamp else None}, rows))
    for n in item.get("news", [])[:MAX_NEWS]:
        lines.append(_marked(_news_line(n, now), {
            "id": f"latest-known:{symbol}:news:{n.get('url') or n['title']}", "symbol": symbol, "title": n["title"],
            "source_type": "configured_news", "source_name": n.get("source") or None, "url": n.get("url"), "source_url": n.get("url"),
            "published_at": n["published_at"].isoformat()}, rows))
    if item.get("price"):
        price = item["price"]
        lines.append(_marked(_price_line(price, now), {
            "id": f"latest-known:{symbol}:price:{price['kind']}", "symbol": symbol, "title": f"{symbol} 最新价格",
            "source_type": "market_data", "published_at": price["at"].isoformat() if price.get("at") else None}, rows))
    return lines


def _render(items: list[dict], now: datetime, extra, rows: list | None = None) -> tuple[str | None, list[str]]:
    kept = [dict(item, filings=list(item.get("filings") or [])[:MAX_FILINGS], news=list(item.get("news") or [])[:MAX_NEWS])
            for item in items if item.get("filings") or item.get("news") or item.get("price")][:MAX_COMPANIES]
    if not kept:
        return None, []
    tail = [_cap(line) for line in extra] + [CLOSING_LINE]

    def assemble() -> str:
        if rows is not None:
            rows.clear()       # the rows of the layout that is finally kept
        return "\n".join([HEADING] + [line for item in kept for line in _section(item, now, rows)] + tail)

    text = assemble()
    # 超长时先舍各家多出来的旧新闻、再舍旧公告（从最后一家往前），每家至少留一条公告、一条新闻和价格。
    for key, keep in (("news", 2), ("filings", 2), ("news", 1), ("filings", 1)):
        for item in reversed(kept):
            while len(text) > BLOCK_LIMIT and len(item[key]) > keep:
                item[key].pop()
                text = assemble()
    if len(text) > BLOCK_LIMIT:  # 三家、每行 ≤160 字时到不了这里；留作兜底
        text = text[: BLOCK_LIMIT - len(CLOSING_LINE) - 2] + "…\n" + CLOSING_LINE
        if rows is not None:
            rows[:] = [r for r in rows if f"[#{r['_k']}]" in text]
    return text, [item["symbol"] for item in kept]


def render(items: list[dict], *, now: datetime, extra: list[str] = ()) -> str | None:
    """整块文字；没有任何公司有内容时返回 None。年龄全部按 ``now`` 算。"""
    return _render(items, now, extra)[0]


# ----------------------------------------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------------------------------------

def _owned_symbols(owner_hash: str) -> set[str]:
    """owner 的持仓和研究队列里的代码；只用来决定「IT」「ON」这种词算不算代码，以及顺序之外别无他用。"""
    from .agent_chat_models import AgentResearchQueue
    from . import portfolio

    owned: set[str] = set()
    with _read_session() as session:
        row = session.get(AgentResearchQueue, owner_hash)
        for symbol in (row.symbols if row else None) or []:
            normalized = _normalize(str(symbol))
            if normalized:
                owned.add(normalized)
        try:
            txns = [portfolio._row_to_txn(r) for r in portfolio.load_transactions(session, owner_hash)]
            owned.update(s for s, p in portfolio.replay(txns).positions.items() if p.shares > 0 and s)
        except Exception as exc:  # 持仓历史有问题不该挡住这一块
            logger.info("latest_known: holdings unreadable (%s)", exc)
    return owned


def _build(text: str, previous: str | None, focus: str | None, owner_hash: str | None,
           now: datetime, rows: list | None = None) -> tuple[str | None, list[str]]:
    deadline = time.monotonic() + DEADLINE_SECONDS
    owned = _owned_symbols(owner_hash) if owner_hash else set()
    candidates = mentions(text, previous=previous, focus=focus, owned=owned)
    if not candidates:
        return None, []
    items: list[dict] = []
    cursor = 0
    # 取够 3 家有内容的；前面的没有内容就往后补，最多看 6 个；过了期限就不再开新的一批。
    while cursor < min(len(candidates), 2 * MAX_COMPANIES) and len(items) < MAX_COMPANIES and time.monotonic() < deadline:
        batch = candidates[cursor:cursor + (MAX_COMPANIES - len(items))]
        cursor += len(batch)
        items.extend(gather(batch, now=now, deadline=deadline))
    items = items[:MAX_COMPANIES]
    if not items:
        return None, []
    shown_symbols = {item["symbol"] for item in items}
    rest = [s for s in candidates[cursor:] if s not in shown_symbols]
    extra = []
    if rest:
        extra.append("另提到：" + "、".join(f"{_display_name(s)}（{s}）" if _display_name(s) else s for s in rest)
                     + "（没有展开）")
    return _render(items, now, extra, rows)


# 读库只用这两个线程，不占应用默认线程池；两个都在忙就直接放弃这一块（不排队）。
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="latest-known")
_busy = 0
_busy_lock = threading.Lock()
_last_warned: float | None = None


def _warn(message: str, *args) -> None:
    """一分钟最多一行。"""
    global _last_warned
    now = time.monotonic()
    if _last_warned is not None and now - _last_warned < 60:
        return
    _last_warned = now
    logger.warning(message, *args)


async def block_for(text, *, previous, focus, owner_hash, now=None, rows=None) -> tuple[str | None, list[str]]:
    """这一轮的「系统最新掌握」块和得到了块的代码。慢或出错就放弃这一块，一分钟最多记一行日志。

    给了 ``rows``（一个列表）时，块里每条能当引用的行带一个 ``[#k]`` 记号，对应的行（字典，``_k`` 是 k）在成功返回后放进 ``rows``；
    调用方给它们编号后把记号换成真正的引用号。失败或没有块时 ``rows`` 保持原样。"""
    global _busy
    when = now or datetime.now(UTC)
    with _busy_lock:
        if _busy >= MAX_WORKERS:
            _warn("latest_known: skipped, both reader threads are busy")
            return None, []
        _busy += 1

    found_rows: list | None = [] if rows is not None else None

    def job():
        global _busy
        try:
            return _build(text or "", previous, focus, owner_hash, when, found_rows)
        finally:
            with _busy_lock:
                _busy -= 1

    try:
        future = asyncio.get_running_loop().run_in_executor(_executor, job)
    except Exception as exc:
        with _busy_lock:
            _busy -= 1
        _warn("latest_known: skipped (%s: %s)", type(exc).__name__, exc)
        return None, []
    try:
        result = await asyncio.wait_for(future, timeout=BUDGET_SECONDS)
        if rows is not None and result[0]:
            rows.extend(found_rows)
        return result
    except asyncio.TimeoutError:
        _warn("latest_known: gave up after %.1fs", BUDGET_SECONDS)
    except Exception as exc:
        _warn("latest_known: skipped (%s: %s)", type(exc).__name__, exc)
    return None, []
