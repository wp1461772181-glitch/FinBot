"""Who said it, and how fresh it is: the system's own ranking of a numbered source and dating of a batch of rows.

Code only, no model call.  The ranking is shown to the model (``来源等级``) and the user; nothing is hidden or reordered by it.  The lists of
domains below are the one place to edit when a source is ranked wrongly.

Tiers: 1 官方, 2 通讯社和主流财经媒体, 3 聚合站和其他新闻, 4 社交平台和通用网页.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

LABELS = {1: "官方", 2: "通讯社和主流媒体", 3: "聚合和其他新闻", 4: "社交平台和网页"}

# Tier 1: regulators, exchanges and company-issued releases.  The release wires publish what companies hand them.
OFFICIAL_DOMAINS = ("sec.gov", "hkexnews.hk", "sse.com.cn", "szse.cn", "cninfo.com.cn", "nasdaq.com", "nyse.com",
                    "businesswire.com", "prnewswire.com", "globenewswire.com")
# Tier 2: wire services and mainstream financial press.
MAINSTREAM_DOMAINS = ("reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com", "apnews.com", "caixin.com", "yicai.com", "stcn.com",
                      "barrons.com", "economist.com", "nytimes.com", "xinhuanet.com")
MAINSTREAM_NAMES = ("财新", "第一财经", "证券时报", "路透", "彭博", "Reuters", "Bloomberg")
# Tier 3 for a web page; a configured news source that is in neither list above is tier 3 anyway.
AGGREGATOR_DOMAINS = ("finance.yahoo.com", "yahoo.com", "jin10.com", "marketwatch.com", "investing.com", "benzinga.com", "seekingalpha.com",
                      "fool.com", "tipranks.com", "zerohedge.com", "msn.com", "google.com")

# Source types that are the system's own records (the archive, quotes it fetched, forecasts it made) or numbers computed from them.
_OFFICIAL_TYPES = frozenset({"official_filing", "saved_filing", "reported_figure", "saved_price", "saved_price_set", "market_quote",
                             "market_data", "market_price", "portfolio", "saved_forecast", "system_state"})
_SOCIAL_TYPES = frozenset({"x_post"})
_CALCULATION_TYPES = frozenset({"calculation", "formula_calculation"})
_NEWS_TYPES = frozenset({"configured_news", "web_news", "news_lead"})

# The field of each source type that says when the item was published or became true (first one present wins).
DATE_FIELDS = {
    "official_filing": ("accepted_at", "filed_at", "published_at"),
    "saved_filing": ("accepted_at", "filed_at", "published_at"),
    "reported_figure": ("period_end", "as_of", "filed_at"),
    "saved_price": ("trading_date", "as_of"),
    "saved_price_set": ("end_date", "as_of"),
    "market_quote": ("as_of", "trading_date", "published_at"),
    "market_data": ("as_of", "published_at", "trading_date"),
}
_DEFAULT_DATE_FIELDS = ("published_at", "accepted_at", "filed_at", "as_of", "trading_date")


def _host(url) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    text = url.strip()
    try:
        host = urlparse(text if "//" in text else "//" + text).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def _in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _named(name, names) -> bool:
    return isinstance(name, str) and any(n.lower() in name.lower() for n in names)


def _web_tier(row: dict, default: int | None) -> int | None:
    host = _host(row.get("source_url") or row.get("url"))
    name = row.get("source_name") or row.get("source")
    if _in(host, OFFICIAL_DOMAINS):
        return 1
    if _in(host, MAINSTREAM_DOMAINS) or _named(name, MAINSTREAM_NAMES):
        return 2
    if _in(host, AGGREGATOR_DOMAINS):
        return 3
    return default


def tier_of(row: dict, citations: list[dict] | None = None) -> int | None:
    """The tier (1-4) of one citation or row, or ``None`` for a calculation whose inputs cannot be found.

    A calculation is only as authoritative as its weakest input."""
    kind = row.get("source_type")
    if kind in _CALCULATION_TYPES or (row.get("derived") and isinstance(row.get("calculation"), dict)):
        parents = set(row.get("parents") or ()) | set((row.get("calculation") or {}).get("parents") or ())
        parents |= {i.get("source_ordinal") for i in (row.get("calculation") or {}).get("inputs") or () if isinstance(i, dict)}
        tiers = []
        for ordinal in parents:
            parent = next((c for c in citations or () if c.get("ordinal") == ordinal), None)
            if parent is not None and parent is not row:
                tiers.append(tier_of(parent, citations))
        tiers = [t for t in tiers if t]
        return max(tiers) if tiers else None
    if kind in _OFFICIAL_TYPES:
        return 1
    if kind in _SOCIAL_TYPES or row.get("origin") == "x":
        return 4
    if kind in _NEWS_TYPES:
        return _web_tier(row, 3)
    # A web page is by where it came from, and an unknown place is the general web.  Anything else (a saved copy, an upload, an analysis) is
    # ranked only when it says where it came from; the owner's own files and the system's analyses get no tier rather than a wrong one.
    return _web_tier(row, 4 if kind == "web" else None)


def rank(citations: list[dict]) -> None:
    """Give every citation without one its ``authority`` (1-4) and ``authority_label``.  Idempotent."""
    for citation in citations:
        if isinstance(citation, dict) and "authority" not in citation:
            tier = tier_of(citation, citations)
            if tier:
                citation["authority"] = tier
                citation["authority_label"] = LABELS[tier]


def _moment(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            match = re.match(r"\d{4}-\d{2}-\d{2}", text)
            if not match:
                return None
            try:
                parsed = datetime.fromisoformat(match.group(0))
            except ValueError:
                return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def row_date(row: dict) -> datetime | None:
    """When the row's item was published or became true, from the field its source type uses; ``None`` for a row with no usable date."""
    for field in DATE_FIELDS.get(row.get("source_type"), _DEFAULT_DATE_FIELDS):
        moment = _moment(row.get(field))
        if moment:
            return moment
    return None


def freshness(rows: list[dict], now: datetime) -> dict:
    """``newest`` (ISO time of the newest dated row) and ``newest_age`` (Chinese, as the latest-known block writes ages), plus
    ``future_dated`` (how many rows are stamped later than now: they are not counted as the newest).  Rows with no date do not count; no dated
    row, no ``newest``."""
    from .latest_known import FUTURE_TOLERANCE, _age_text

    newest, future = None, 0
    for row in rows:
        moment = row_date(row) if isinstance(row, dict) else None
        if moment is None:
            continue
        if moment - now > FUTURE_TOLERANCE:
            future += 1
        elif newest is None or moment > newest:
            newest = moment
    out: dict = {}
    if newest is not None:
        out = {"newest": newest.isoformat(), "newest_age": _age_text(newest, now)}
    if future:
        out["future_dated"] = future
    return out
