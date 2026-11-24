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
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import cast, func, select, union
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

_known_cache: tuple[float, frozenset[str]] | None = None
_clock = time.monotonic  # 测试里替换，用来验证缓存刷新


def _known_symbols() -> frozenset[str]:
    """库里有公告或日线价格的股票代码；缓存 10 分钟。"""
    global _known_cache
    now = _clock()
    if _known_cache is not None and now - _known_cache[0] < KNOWN_TTL_SECONDS:
        return _known_cache[1]
    from .database import SessionLocal
    from .models import MarketPrice, SecFilingInventory

    query = union(select(SecFilingInventory.symbol), select(MarketPrice.symbol))
    with SessionLocal() as session:
        symbols = frozenset(row[0] for row in session.execute(query) if row[0])
    _known_cache = (now, symbols)
    return symbols


def forget_known() -> None:
    global _known_cache
    _known_cache = None


def _normalize(value: str) -> str | None:
    try:
        return normalize_market_symbol(value)
    except ValueError:
        return None


def _scan(text: str, known: set[str] | frozenset[str], owned: set[str] | frozenset[str]) -> list[str]:
    """一段话里提到的股票代码，按先后排，去重。"""
    hits: list[tuple[int, str]] = []
    for match in _CASHTAG.finditer(text):
        symbol = _normalize(match.group(1))
        if symbol and symbol in known:
            hits.append((match.start(), symbol))
    for match in _BARE.finditer(text):
        symbol = _normalize(match.group(1))
        if not symbol or symbol not in known:
            continue
        letters = len(symbol.split(".")[0])
        if symbol in owned or (letters >= 3 and symbol not in _COMMON_WORDS):
            hits.append((match.start(), symbol))
    for match in _NAMES.finditer(text.lower()):
        symbol = ALIASES.get(match.group(0))
        if symbol and symbol in known:
            hits.append((match.start(), symbol))
    hits.sort(key=lambda hit: hit[0])
    ordered: list[str] = []
    for _, symbol in hits:
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered


def mentions(text: str, *, previous: str | None = None, focus: str | None = None,
             owned: set[str] = frozenset(), known: set[str] | None = None) -> list[str]:
    """这句话提到了哪些公司：先 bot 的关注对象，再按提到的先后。

    ``previous`` 只在这句话本身没提到任何公司时才用（「那它的现金流呢」），最多沿用 3 家。
    ``known`` 默认是库里有公告或日线价格的代码。"""
    if known is None:
        known = _known_symbols()
    owned = {s for s in (_normalize(o) for o in owned) if s}
    found = _scan(text or "", known, owned)
    if not found and previous:
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


def _head(excerpt: str | None, kind: str | None) -> str:
    """公告没有标题列：新闻稿取摘录开头的文字；8-K 正文取第一条 Item 的名称；封面套话不算。"""
    if not excerpt:
        return ""
    text = excerpt.strip()
    if kind == "primary_document":
        item = _ITEM_LINE.search(text)
        return _shorten(re.sub(r"\s+", " ", item.group(0)).strip()) if item else ""
    text = _EXHIBIT_PREFIX.sub("", text)
    return _shorten(re.sub(r"\s+", " ", text).strip())


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
            return name
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


def gather(symbols: list[str], *, now: datetime) -> list[dict]:
    """每个代码库里最新的东西；什么都没有的代码不出现在结果里。同步函数，调用方放进线程。"""
    from .agent_chat_models import NewsItem
    from .database import SessionLocal
    from .models import MarketPrice, SecFilingInventory

    intraday = _sentinel_prices(symbols, now)
    items: list[dict] = []
    with SessionLocal() as session:
        for symbol in symbols:
            filing_rows = session.execute(
                select(SecFilingInventory.form, SecFilingInventory.filed_at, SecFilingInventory.accepted_at,
                       SecFilingInventory.observed_at, SecFilingInventory.content_status,
                       SecFilingInventory.content_kind, func.left(SecFilingInventory.content_excerpt, 6000))
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
            } for form, filed, accepted, observed, status, kind, excerpt in filing_rows]

            news_rows = session.execute(
                select(NewsItem.title, NewsItem.source_name, NewsItem.published_at, NewsItem.time_inferred)
                .where(cast(NewsItem.tickers, JSONB).contains([symbol]))
                .order_by(NewsItem.published_at.desc())
                .limit(MAX_NEWS * 2)
            ).all()
            news: list[dict] = []
            seen: set[str] = set()
            for title, source, published, inferred in news_rows:
                key = (title or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                news.append({"title": key, "source": source or "", "published_at": published, "inferred": bool(inferred)})
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
    label = filing.get("form", "")
    if label in _FORM_LABELS:
        label += f"（{_FORM_LABELS[label]}）"
    if filing.get("kind") == "exhibit_99_1":
        label += "（新闻稿 EX-99.1）"
    head = filing.get("head") or ""
    tail = f"：{head}" if head else ""
    if not filing.get("fetched", True):
        tail += "（正文还没取到）"
    return _cap(f"  官方公告  {stamp}  {label}{tail}")


def _news_line(news: dict, now: datetime) -> str:
    stamp = _stamp(news["published_at"], now)
    if news.get("inferred"):
        stamp += "（时间为推断）"
    source = f"{news['source']}：" if news.get("source") else ""
    return _cap(f"  新闻      {stamp}  {source}{news['title']}")


def _price_line(price: dict, now: datetime) -> str:
    change = price.get("change_pct")
    if price["kind"] == "intraday":
        what = f"盘中价 {price['value']:.2f}（哨兵报价）"
    else:
        day = price.get("date")
        what = f"日线收盘 {price['value']:.2f}" + (f"（交易日 {day.strftime('%m-%d')}）" if day else "")
    if change is not None:
        what += f"，较前收 {change:+.1f}%"
    return _cap(f"  价格      {_stamp(price['at'], now)}  {what}")


def _section(item: dict, now: datetime) -> list[str]:
    symbol = item["symbol"]
    name = item.get("name") or ""
    lines = [f"关于 {name}（{symbol}）：" if name else f"关于 {symbol}："]
    lines += [_filing_line(f, now) for f in item.get("filings", [])[:MAX_FILINGS]]
    lines += [_news_line(n, now) for n in item.get("news", [])[:MAX_NEWS]]
    if item.get("price"):
        lines.append(_price_line(item["price"], now))
    return lines


def _render(items: list[dict], now: datetime, extra) -> tuple[str | None, list[str]]:
    kept = [dict(item, filings=list(item.get("filings") or [])[:MAX_FILINGS], news=list(item.get("news") or [])[:MAX_NEWS])
            for item in items if item.get("filings") or item.get("news") or item.get("price")][:MAX_COMPANIES]
    if not kept:
        return None, []
    tail = [_cap(line) for line in extra]

    def assemble() -> str:
        return "\n".join([HEADING] + [line for item in kept for line in _section(item, now)] + tail)

    text = assemble()
    # 超长时先舍各家多出来的旧新闻、再舍旧公告（从最后一家往前），每家至少留一条公告、一条新闻和价格。
    for key, keep in (("news", 2), ("filings", 2), ("news", 1), ("filings", 1)):
        for item in reversed(kept):
            while len(text) > BLOCK_LIMIT and len(item[key]) > keep:
                item[key].pop()
                text = assemble()
    if len(text) > BLOCK_LIMIT:  # 三家、每行 ≤160 字时到不了这里；留作兜底
        text = text[: BLOCK_LIMIT - 1] + "…"
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
    from .database import SessionLocal
    from . import portfolio

    owned: set[str] = set()
    with SessionLocal() as session:
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
           now: datetime) -> tuple[str | None, list[str]]:
    owned = _owned_symbols(owner_hash) if owner_hash else set()
    candidates = mentions(text, previous=previous, focus=focus, owned=owned)
    if not candidates:
        return None, []
    items: list[dict] = []
    cursor = 0
    # 取够 3 家有内容的；前面的没有内容就往后补，最多看 6 个。
    while cursor < min(len(candidates), 2 * MAX_COMPANIES) and len(items) < MAX_COMPANIES:
        batch = candidates[cursor:cursor + (MAX_COMPANIES - len(items))]
        cursor += len(batch)
        items.extend(gather(batch, now=now))
    items = items[:MAX_COMPANIES]
    if not items:
        return None, []
    shown_symbols = {item["symbol"] for item in items}
    rest = [s for s in candidates[cursor:] if s not in shown_symbols]
    extra = []
    if rest:
        extra.append("另提到：" + "、".join(f"{_display_name(s)}（{s}）" if _display_name(s) else s for s in rest)
                     + "（没有展开）")
    return _render(items, now, extra)


async def block_for(text, *, previous, focus, owner_hash, now=None) -> tuple[str | None, list[str]]:
    """这一轮的「系统最新掌握」块和得到了块的代码。慢或出错就放弃这一块，只记一行日志。"""
    when = now or datetime.now(UTC)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_build, text or "", previous, focus, owner_hash, when), timeout=BUDGET_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("latest_known: gave up after %.1fs", BUDGET_SECONDS)
    except Exception as exc:
        logger.warning("latest_known: skipped (%s: %s)", type(exc).__name__, exc)
    return None, []
