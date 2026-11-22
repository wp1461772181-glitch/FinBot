"""Latest-quarter figures from an 8-K earnings press release, for the stretch before the 10-Q/10-K is filed.

A company announces results in an 8-K (Exhibit 99.1) days to weeks before the periodic report; until then
``query_financials`` only knew the previous quarter. This module lets the model copy the ten financial metrics out of the
release and checks each copied value against the text; whatever fails the check is dropped, never repaired. The result is
stored on the 8-K's own ``content_financials`` in the same shape as XBRL figures, flagged ``press_release_unaudited``.
The periodic report replaces it at read time (``query_financials``) once the same period is filed there.

Division of labour (docs/finbot-design-rules.md): the model reads the statements and copies numbers; the code only checks
what can be checked: the copied digits are in the text, the value follows from them and the scale, dates are real and
not after the filing, months are 3/6/9/12, gross profit agrees with revenue minus cost. Nothing is parsed out of the
tables by pattern.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import earnings_reader as reader

log = logging.getLogger(__name__)

BASIS = "press_release_unaudited"
CONCEPT = "press_release"
BACKOFF_SECONDS = 30 * 60
SOURCE_CHARS = reader.EXTRACT_SOURCE_CHARS
PERIODS_MONTHS = (3, 6, 9, 12)
FLOW_METRICS = ("revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow")
POINT_METRICS = ("total_assets", "cash_and_equivalents", "total_liabilities", "stockholders_equity")
LABELS = {"revenue": "Revenue", "cost_of_revenue": "Cost of revenue", "gross_profit": "Gross profit",
          "operating_income": "Operating income", "net_income": "Net income",
          "operating_cash_flow": "Net cash provided by operating activities", "total_assets": "Total assets",
          "cash_and_equivalents": "Cash and cash equivalents", "total_liabilities": "Total liabilities",
          "stockholders_equity": "Total stockholders' equity"}
SCALES = {"millions": 1_000_000, "thousands": 1_000, "units": 1}

PROMPT = """你从一份上市公司的业绩新闻稿（8-K 的 Exhibit 99.1）里，把财务报表中「本期」的数字抄出来。只输出一个 JSON 对象，不要解释。

先判断：这份文件是不是含有财务报表（利润表、资产负债表、现金流量表）的业绩新闻稿。人事任命、产品发布、只有几句业绩概述而没有报表的，都不是。不是就输出 {"is_earnings_release": false}。

是的话输出：
{"is_earnings_release": true,
 "unit": "millions|thousands|units",      // 报表自己写明的单位量级（In millions / In thousands / 整数美元）
 "fiscal_year": 2027, "fiscal_quarter": "Q3",   // 照新闻稿自己的说法，如 Third Quarter Fiscal 2027 -> 2027 / Q3；第四季度写 Q4
 "figures": [
   {"metric": "revenue", "period_end": "2026-10-25", "months": 3,
    "number": "115,844", "value": 115844000000, "quote": "Revenue $ 115,844 $ 57,006 $ 293,681 $ 147,811"}
 ]}

figures 里每一项：
- metric 只能是这十个之一：revenue（营业收入）、cost_of_revenue（营业成本）、gross_profit（毛利）、operating_income（营业利润）、net_income（净利润）、operating_cash_flow（经营活动现金流）、total_assets、cash_and_equivalents（现金及现金等价物）、total_liabilities、stockholders_equity。
- 利润表和现金流量表的指标（前六个）给 period_end（期间结束日，YYYY-MM-DD）和 months（期间月数，只能是 3、6、9、12）。资产负债表的指标（后四个）不给 months，给 as_of（资产负债表日，YYYY-MM-DD）。
- number：这个值在报表里印着的那串数字，逐字照抄，含逗号，如 "115,844"；负数照抄括号或负号，如 "(1,234)"。
- value：同一个数换算成美元整数（报表单位是 millions 就乘 1,000,000，thousands 乘 1,000），亏损或净流出为负数。
- quote：报表里包含这个数字的那一行，逐字照抄（含这一行里其它数字也可以）。
只要「本期」：最新的三个月期间以及与它同一天结束的累计期间（六个月、九个月、全年，有就给），和最新的资产负债表日。不要去年同期、不要上一财年末的对比列。
报表里没有的指标就省略，不要猜，不要推算，不要用非公认会计准则（non-GAAP）的数字代替，不要从正文叙述里取数。"""


class ReleaseModelError(RuntimeError):
    """The model could not be used for this release (call failed, or its reply was not a JSON object); nothing is stored."""


def _parse_number(token) -> tuple[Decimal, str] | None:
    """(signed value as printed, magnitude digits) of a statement number such as '115,844', '(1,234)', '-5.2'."""
    if not isinstance(token, str):
        return None
    text = token.strip().replace("$", "").replace(" ", "")
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith(("-", "−", "–"))
    magnitude = text.strip("()").lstrip("-−–")
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", magnitude):
        return None
    try:
        value = Decimal(magnitude.replace(",", ""))
    except InvalidOperation:
        return None
    return (-value if negative else value), magnitude


def _standalone(token: str, haystack: str) -> bool:
    return bool(re.search(r"(?<![\d,.])" + re.escape(token) + r"(?![\d]|[.,]\d)", haystack))


def _quote_ok(quote, magnitude: str, haystack: str) -> bool:
    """The quoted line is in the text (earnings_reader's rule: verbatim after whitespace squash, commas ignored as a fallback)
    and the copied number is in the quoted line."""
    if not isinstance(quote, str) or not quote.strip():
        return False
    squashed = reader._squash(quote)
    found = reader._in_text(quote, haystack) or squashed.replace(",", "") in haystack.replace(",", "")
    return bool(found and _standalone(magnitude, squashed))


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()) else None
    except ValueError:
        return None


def _integer(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(Decimal(str(value).replace(",", "")).to_integral_value(ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def check_figures(data: dict, text: str, filed_at: date) -> list[dict]:
    """The model's reply, checked against the release text; the figures that pass, in XBRL ``content_financials`` shape.
    A value that fails any check is dropped; nothing is corrected."""
    if data.get("is_earnings_release") is not True:
        return []
    scale = SCALES.get(str(data.get("unit") or "").strip().lower())
    year, quarter = data.get("fiscal_year"), str(data.get("fiscal_quarter") or "").strip().upper()
    if scale is None or isinstance(year, bool) or not isinstance(year, int) or not 1990 <= year <= 2100 or quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        return []
    if scale > 1 and not re.search(r"\b" + ("millions?" if scale == 1_000_000 else "thousands?") + r"\b", text, re.I):
        return []   # the declared scale is not written anywhere in the release
    haystack = reader._squash(text)
    kept: dict[tuple, dict] = {}
    for item in data.get("figures") if isinstance(data.get("figures"), list) else []:
        if not isinstance(item, dict) or item.get("metric") not in FLOW_METRICS + POINT_METRICS:
            continue
        metric = item["metric"]
        end = _day(item.get("period_end") or item.get("as_of"))
        if end is None or end > filed_at:
            continue
        months = None
        if metric in FLOW_METRICS:
            months = item.get("months")
            if isinstance(months, bool) or months not in PERIODS_MONTHS:
                continue
        parsed = _parse_number(item.get("number"))
        value = _integer(item.get("value"))
        if parsed is None or value is None or not _quote_ok(item.get("quote"), parsed[1], haystack):
            continue
        if abs(Decimal(value) - parsed[0] * scale) >= 1:
            continue
        key = (metric, end, months)
        if key not in kept:
            kept[key] = {"metric": metric, "end": end, "months": months, "value": value}
    # Gross profit must agree with revenue less cost, within one unit of the statement's own rounding.
    periods = {(k[1], k[2]) for k in kept if k[0] in {"revenue", "cost_of_revenue", "gross_profit"}}
    for end, months in periods:
        trio = [kept.get((m, end, months)) for m in ("revenue", "cost_of_revenue", "gross_profit")]
        if all(trio) and abs(trio[0]["value"] - trio[1]["value"] - trio[2]["value"]) > scale:
            for m in ("revenue", "cost_of_revenue", "gross_profit"):
                kept.pop((m, end, months), None)
    by_metric: dict[str, list[dict]] = {}
    for (metric, end, months), row in sorted(kept.items(), key=lambda kv: (FLOW_METRICS + POINT_METRICS).index(kv[0][0])):
        entry = {"unit": "USD", "value": row["value"], "start": None, "end": end.isoformat(), "fiscal_period": quarter,
                 "fiscal_year": year, "basis": BASIS}
        if months is not None:
            entry["span_months"] = months
        by_metric.setdefault(metric, []).append(entry)
    return [{"metric": m, "label": LABELS[m], "concept": CONCEPT, "unit": "USD", "basis": BASIS, "periods": periods_}
            for m, periods_ in by_metric.items()]


async def extract_release_figures(text: str, model: dict, filed_at: date) -> list[dict]:
    """The checked figures of one press release; ``[]`` when it is not an earnings release or nothing survives the checks.
    Raises ReleaseModelError when the model call fails or its reply is not a JSON object (the caller stores nothing)."""
    sent = text[:SOURCE_CHARS]
    try:
        raw = await reader._call_model(model, PROMPT, sent)
    except Exception as exc:  # noqa: BLE001 - network, key, timeout: any provider failure
        raise ReleaseModelError(f"model call failed: {type(exc).__name__}") from exc
    data = reader._json_object(raw)
    if data is None:
        raise ReleaseModelError("model reply was not a JSON object")
    return check_figures(data, sent, filed_at)


# --- which releases, and storing ---------------------------------------------------------------------------

_FAILED: dict[str, float] = {}   # accession -> clock time of the last failed attempt (this process only)
_clock = time.monotonic


def _backed_off(accession: str) -> bool:
    failed = _FAILED.get(accession)
    return failed is not None and _clock() - failed < BACKOFF_SECONDS


_UNSET = "(content_financials IS NULL OR content_financials::text = 'null')"
_HAS_FIGURES = "(content_financials IS NOT NULL AND content_financials::text NOT IN ('null', '[]'))"


def find_candidates(symbol: str | None = None) -> list[dict]:
    """Releases worth reading: an 8-K Exhibit 99.1, fetched, never looked at, and filed after the symbol's newest periodic
    report that has XBRL figures. A symbol with no such report: its newest Exhibit 99.1 (if never looked at)."""
    from sqlalchemy import text as sql
    from .database import SessionLocal
    only = " AND symbol = :symbol" if symbol else ""
    params = {"symbol": symbol.upper()} if symbol else {}
    columns = "id, symbol, accession_number, filed_at, content_source_url"
    release = ("form = '8-K' AND content_status = 'fetched' AND content_kind = 'exhibit_99_1' AND content_text IS NOT NULL")
    with SessionLocal() as db:
        newer = db.execute(sql(f"""
            SELECT {columns} FROM sec_filing_inventory f
            WHERE {release}{only} AND {_UNSET}
              AND filed_at > (SELECT max(p.filed_at) FROM sec_filing_inventory p WHERE p.symbol = f.symbol
                              AND p.form IN ('10-K', '10-Q', '20-F') AND p.content_status = 'fetched'
                              AND p.content_financials IS NOT NULL AND p.content_financials::text NOT IN ('null', '[]'))
            ORDER BY symbol, filed_at DESC, accession_number DESC"""), params).mappings().all()
        first = db.execute(sql(f"""
            SELECT DISTINCT ON (symbol) {columns}, ({_UNSET}) AS unset FROM sec_filing_inventory f
            WHERE {release}{only}
              AND NOT EXISTS (SELECT 1 FROM sec_filing_inventory p WHERE p.symbol = f.symbol
                              AND p.form IN ('10-K', '10-Q', '20-F') AND p.content_status = 'fetched'
                              AND p.content_financials IS NOT NULL AND p.content_financials::text NOT IN ('null', '[]'))
            ORDER BY symbol, filed_at DESC, accession_number DESC"""), params).mappings().all()
    rows = [dict(r) for r in newer] + [{k: v for k, v in dict(r).items() if k != "unset"} for r in first if r["unset"]]
    return [{**r, "id": str(r["id"])} for r in rows]


def _owner_model() -> dict | None:
    """The 财报判断模型 of the configured owner (as earnings_monitor / the task runner use it); None with a log line when unavailable."""
    from .agent_chat_store import owner_hash
    from .agent_task_runner import owner_credential
    credential = owner_credential()
    if not credential:
        log.info("release figures: no configured owner, nothing to do")
        return None
    try:
        return reader.model_for_owner(owner_hash(credential))
    except Exception as exc:  # noqa: BLE001 - catalog errors, missing key
        log.info("release figures: no usable model (%s), nothing to do", type(exc).__name__)
        return None


def _store(row_id: str, figures: list[dict]) -> bool:
    import uuid
    from .database import SessionLocal
    from .models import SecFilingInventory
    with SessionLocal() as db:
        row = db.get(SecFilingInventory, uuid.UUID(row_id))
        if row is None or row.content_financials is not None:
            return False
        row.content_financials = figures
        db.commit()
        return True


def _text_of(row_id: str) -> str:
    import uuid
    from .database import SessionLocal
    from .models import SecFilingInventory
    with SessionLocal() as db:
        row = db.get(SecFilingInventory, uuid.UUID(row_id))
        return row.content_text or "" if row else ""


def run_once(*, symbol: str | None = None, model: dict | None = None) -> dict:
    """One pass over the candidates; each is read and committed on its own, so one failure leaves the others alone.
    Returns {candidates, written, no_figures, failed}. A model failure stores nothing (the row stays unset) and the
    accession is not tried again for BACKOFF_SECONDS in this process."""
    from .agent_workflow.fp_flags import flag
    stats = {"candidates": 0, "written": 0, "no_figures": 0, "failed": 0}
    if not flag("FINBOT_RELEASE_FIGURES", True):
        return stats
    candidates = [c for c in find_candidates(symbol) if not _backed_off(c["accession_number"])]
    stats["candidates"] = len(candidates)
    if not candidates:
        return stats
    model = model or _owner_model()
    if model is None:
        return stats
    for item in candidates:
        try:
            text = _text_of(item["id"])
            figures = asyncio.run(extract_release_figures(text, model, item["filed_at"]))
            if _store(item["id"], figures):
                stats["written" if figures else "no_figures"] += 1
        except Exception as exc:  # noqa: BLE001 - one release must not stop the rest
            _FAILED[item["accession_number"]] = _clock()
            stats["failed"] += 1
            log.warning("release figures: %s %s failed (%s)", item["symbol"], item["accession_number"], exc)
    return stats
