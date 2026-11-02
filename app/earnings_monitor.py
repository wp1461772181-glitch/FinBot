"""Earnings monitor, API side (plan Task 9): the sentinel finds the 8-K, this module speaks.

* first message (minutes after the release): key numbers vs last quarter's guidance, new guidance, what
  management said, quality of the beat -- from ``earnings_reader.extract_release`` + ``compare``;
* second message (about 30 minutes after the release): ``judge`` with the after-hours / pre-market move; sent only
  when the direction is not ``unclear`` and the confidence reaches the model's bar.  A model without a passing
  blind-test verdict (``config/earnings_blind_test_gate.json``, default: none) sends a plain notice labelled so;
* a holding is pushed to Telegram and recorded in the bot's line, a research-queue company is only recorded;
* every timer and status is in ``earnings_events``, so a restart continues with what is unsent;
* ``earnings_history``: past quarters, filled once on first use, point-in-time (only what existed before the release).

Everything that touches the outside world (SEC, prices, the portfolio) is behind ``Sources`` and the two model
calls behind ``reader``, so tests run on scripted data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.request
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from . import agent_tasks as tasks
from .agent_chat_models import AgentBot, EarningsEvent, EarningsHistory
from .database import SessionLocal

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
FOLLOWUP_AFTER = timedelta(minutes=30)
FOLLOWUP_STALE = timedelta(hours=4)       # a follow-up this late would describe a market that has moved on
STUCK_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3
HISTORY_QUARTERS = 8
MIN_HISTORY = 4
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
UNVALIDATED_MIN = "medium"
VALIDATED_MIN = "high"
DISAGREE_AT = 0.01                         # an after-hours move this large against the call is a disagreement
DEFAULT_GATE = Path(__file__).resolve().parent.parent / "config" / "earnings_blind_test_gate.json"


# --- the blind-test gate ------------------------------------------------------------------------------------

def gate_status(model_name: str, version: str) -> dict:
    """``{"validated": bool, "min_confidence": str}`` from the verdict file; no file / no entry / other reader
    version = not validated."""
    path = Path(os.environ.get("EARNINGS_GATE_PATH") or DEFAULT_GATE)
    try:
        entry = (json.loads(path.read_text(encoding="utf-8")).get("models") or {}).get(model_name) or {}
    except (OSError, ValueError):
        entry = {}
    validated = bool(entry.get("passed")) and entry.get("reader_version") == version
    default = VALIDATED_MIN if validated else UNVALIDATED_MIN
    bar = entry.get("min_confidence") if entry.get("min_confidence") in CONFIDENCE_RANK else default
    return {"validated": validated, "min_confidence": bar, "detail": entry}


# --- small helpers ------------------------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def quarter_label(accepted: datetime) -> str:
    """Calendar quarter that ended before the release (an approximation for fiscal years that differ)."""
    d = accepted.astimezone(NY).date() - timedelta(days=30)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def prices_before(closes: list[tuple[date, float]], accepted: datetime) -> list[tuple[date, float]]:
    """Closes known when the release came out: through the release day if it came after the close, else the day before."""
    local = accepted.astimezone(NY)
    after_close = local.time() >= time(16, 0)
    return [(d, c) for d, c in closes if d < local.date() or (after_close and d == local.date())]


def reaction(closes: list[tuple[date, float]], accepted: datetime):
    """(R, base_date, end_date): first-trading-day close over the last close before the release; None if not yet known."""
    local = accepted.astimezone(NY)
    close = dict(closes)
    dates = sorted(close)
    if local.time() < time(16, 0) and local.date() in close:
        base, end = max((d for d in dates if d < local.date()), default=None), local.date()
    else:
        base, end = max((d for d in dates if d <= local.date()), default=None), min((d for d in dates if d > local.date()), default=None)
    if base is None or end is None:
        return None
    return close[end] / close[base] - 1, base, end


def commentary_from(text: str) -> str:
    """Management's words in the release: the paragraphs quoting an executive."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    quoted = [p for p in paragraphs if re.search(r"[“\"].{40,}[”\"]", p) and re.search(r"\b(said|says|stated|commented)\b", p)]
    return "\n".join(quoted)[:4000]


def _guidance(data: dict | None):
    from .earnings_reader import Guidance
    return Guidance(**{k: v for k, v in (data or {}).items() if k in Guidance.__dataclass_fields__})


def _pct(value, signed=True) -> str:
    return "—" if value is None else f"{value:+.1f}%" if signed else f"{value:.1f}%"


def _pp(value) -> str:
    return "—" if value is None else f"{value:+.1f}"


def _clip(text: str, limit: int = 300) -> str:
    """At most ``limit`` characters, cut at the last sentence end (or space) and marked with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(mark) for mark in ("。", ". ", "! ", "? "))
    return (cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]) + "…"


def _num(value, digits=2) -> str:
    return "—" if value is None else f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:.0f}"


# --- sources (the outside world) -----------------------------------------------------------------------------

_RELEASE_NAME = re.compile(r"(?i)(?:^|[-_.])(?:ex(?:hibit)?[-_.]?99[-_.]?0?1|99[-_.]?1)|earnings|release|press")


def pick_release_document(names: list[str], primary: str) -> str | None:
    """The press-release page of an 8-K folder when it is not named like an exhibit 99.1 (Intel: q326earningsrelease.htm).
    None when nothing looks like a release: the cover page alone is not an earnings release."""
    pages = sorted(n for n in names if n.lower().endswith((".htm", ".html")) and n != primary and not n.lower().endswith("-index.htm"))
    exhibits = [n for n in pages if re.search(r"(?i)ex(?:hibit)?[-_.]?99[-_.]?0?1", n)]
    return (exhibits or [n for n in pages if _RELEASE_NAME.search(n)] or [None])[0]


class LiveSources:
    """SEC, Yahoo and the portfolio as used in production."""

    def earnings_filings(self, symbol: str, cik: str) -> list[dict]:
        from sentinel.filings import SUBMISSIONS_URL, parse_earnings_filings
        from .sec_filings import SecEdgarProvider
        return parse_earnings_filings(SecEdgarProvider()._get_json(SUBMISSIONS_URL.format(cik=cik)))

    def release_text(self, symbol: str, cik: str, accession: str) -> str | None:
        from . import sec_filings
        provider = sec_filings.SecEdgarProvider()
        with SessionLocal() as db:
            known = {r.accession_number for r in sec_filings.inventory_for_symbol(symbol=symbol, db=db)}
            if accession not in known:
                sec_filings.scan_sec_filings(symbol=symbol, db=db, provider=provider)
            filing, _ = sec_filings.fetch_inventory_content(symbol=symbol, accession_number=accession, db=db, provider=provider)
            if filing.form == "8-K" and filing.content_kind != "exhibit_99_1":
                # No exhibit the shared matcher recognises: look for the release page by name before settling for the cover.
                folder = sec_filings.canonical_sec_filing_url(cik=filing.cik, accession_number=accession,
                                                              primary_document=filing.primary_document).rsplit("/", 1)[0]
                index = provider._get_json(f"{folder}/index.json")
                names = [i["name"] for i in (index.get("directory") or {}).get("item") or [] if isinstance(i, dict) and i.get("name")]
                picked = pick_release_document(names, filing.primary_document)
                if picked is None:
                    return None
                raw = provider._get_bytes(f"{folder}/{picked}", allowed_content_types=sec_filings.PRIMARY_DOCUMENT_CONTENT_TYPES,
                                          reject_nul_bytes=True)
                return sec_filings._html_text(raw)
            return filing.content_text or None

    def daily_closes(self, symbol: str) -> list[tuple[date, float]]:
        from .market_data import fetch_daily_prices
        today = datetime.now(UTC).date()
        return [(p.trading_date, p.close) for p in fetch_daily_prices(symbol, today - timedelta(days=3 * 365), today)]

    def extended_move(self, symbol: str, accepted: datetime, until: datetime | None = None) -> float | None:
        """Return of the last 1-minute bar (pre/post-market included) at ``until`` over the reference close: the
        release day's regular close for an after-close release, the previous close for a pre-market one."""
        from .symbols import yahoo_symbol
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_symbol(symbol)}?range=5d&interval=1m&includePrePost=true"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https host
            result = json.loads(response.read())["chart"]["result"][0]
        bars = [(datetime.fromtimestamp(t, UTC), c) for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]) if c is not None]
        return move_from_bars(bars, accepted, until)

    def holding_for(self, owner: str, symbol: str) -> dict | None:
        from . import portfolio
        summary = portfolio.build_summary(owner)
        for p in summary["positions"]:
            if p["symbol"] == symbol and p["shares"]:
                plan = p.get("plan") or {}
                number = lambda v: None if v is None else float(v)  # noqa: E731
                return {"shares": number(p["shares"]), "avg_cost": number(p["avg_cost"]), "price": number(p["price"]),
                        "weight_pct": number(p["weight_pct"]), "plan_text": plan.get("plan_text") or "",
                        "add_price": number(plan.get("add_price")), "available_funds": number(summary.get("available_funds"))}
        return None


def move_from_bars(bars: list[tuple[datetime, float]], accepted: datetime, until: datetime | None) -> float | None:
    """The extended-hours move: see LiveSources.extended_move.  ``bars`` are (UTC time, close), oldest first."""
    local = accepted.astimezone(NY)
    regular = lambda t: time(9, 30) <= t.astimezone(NY).time() < time(16, 0)  # noqa: E731
    pre_market = local.time() < time(16, 0)
    if pre_market:
        days = sorted({t.astimezone(NY).date() for t, _ in bars if regular(t) and t.astimezone(NY).date() < local.date()})
        base_day = days[-1] if days else None
    else:
        base_day = local.date()
    base_bars = [c for t, c in bars if base_day and t.astimezone(NY).date() == base_day and regular(t)]
    window = [c for t, c in bars if t >= accepted and (until is None or t <= until)]
    if not base_bars or not window:
        return None
    return window[-1] / base_bars[-1] - 1


# --- history (point-in-time) ---------------------------------------------------------------------------------

def history_for(symbol: str, before: datetime) -> list:
    """The past quarters released strictly before ``before``, newest first, as ``HistoryQuarter`` (each carries what
    the quarter before it had guided)."""
    from .earnings_reader import HistoryQuarter
    with SessionLocal() as db:
        rows = db.scalars(select(EarningsHistory).where(EarningsHistory.symbol == symbol, EarningsHistory.released_at < before)
                          .order_by(EarningsHistory.released_at.desc())).all()
        data = [(r.quarter, r.actual or {}, r.guidance or {}) for r in rows]
    out = []
    for i, (quarter, actual, _) in enumerate(data):
        older = data[i + 1][2] if i + 1 < len(data) else None
        out.append(HistoryQuarter(period=quarter, revenue=actual.get("revenue"), eps=actual.get("eps"),
                                  gross_margin=actual.get("gross_margin"), guided=_guidance(older) if older else None,
                                  same_quarter_last_year=(i == 3)))
    return out


def prior_guidance(symbol: str, before: datetime):
    """What the most recent earlier release guided for this quarter, or None."""
    with SessionLocal() as db:
        latest = db.scalars(select(EarningsHistory).where(EarningsHistory.symbol == symbol, EarningsHistory.released_at < before)
                            .order_by(EarningsHistory.released_at.desc()).limit(1)).first()
        return _guidance(latest.guidance) if latest else None


def _store_history(symbol: str, accession: str, accepted: datetime, facts, version: str, closes) -> None:
    from dataclasses import asdict
    actual = {"revenue": facts.revenue, "gross_margin": facts.gross_margin, "eps": facts.eps, "eps_gaap": facts.eps_gaap}
    with SessionLocal() as db:
        if db.scalar(select(EarningsHistory.id).where(EarningsHistory.accession == accession)) is not None:
            return
        db.add(EarningsHistory(symbol=symbol, quarter=quarter_label(accepted), accession=accession, released_at=accepted,
                               guidance=asdict(facts.guidance), actual=actual, reader_version=version))
        db.commit()


def _fill_reactions(symbol: str, closes, reader, before: datetime) -> None:
    """R, σ and the verdict of past quarters whose reaction is known by ``before``: σ from closes up to the day before."""
    with SessionLocal() as db:
        rows = db.scalars(select(EarningsHistory).where(EarningsHistory.symbol == symbol, EarningsHistory.released_at < before)
                          .order_by(EarningsHistory.released_at)).all()
        reacted = [(r, reaction(closes, r.released_at)) for r in rows]
        excluded = {x[2] for _, x in reacted if x}
        for row, found in reacted:
            if row.reaction is not None or not found or found[2] >= before.astimezone(NY).date():
                continue
            r, base, _ = found
            sigma = reader.daily_sigma([(d, c) for d, c in closes if d <= base], excluded)
            row.reaction, row.sigma = r, sigma
            row.verdict = reader.label_reaction(r, sigma) if sigma else None
        db.commit()


def ensure_history(symbol: str, cik: str, before: datetime, sources, reader, model, closes, quarters: int = HISTORY_QUARTERS) -> None:
    """Fill ``earnings_history`` from SEC on first use.  Only filings accepted before ``before`` are looked at."""
    with SessionLocal() as db:
        have = db.query(EarningsHistory).filter(EarningsHistory.symbol == symbol, EarningsHistory.released_at < before).count()
    if have < MIN_HISTORY:
        filings = sorted((f for f in sources.earnings_filings(symbol, cik) if f["accepted"] < before),
                         key=lambda f: f["accepted"], reverse=True)[:quarters]
        for filing in filings:
            try:
                text = sources.release_text(symbol, cik, filing["accession"])
                if text:
                    facts = _run(reader.extract_release(text, model))
                    _store_history(symbol, filing["accession"], filing["accepted"], facts, reader.READER_VERSION, closes)
            except Exception as exc:   # one unreadable old release only thins the history
                log.warning("earnings history %s %s skipped: %s", symbol, filing["accession"], type(exc).__name__)
    _fill_reactions(symbol, closes, reader, before)


# --- events --------------------------------------------------------------------------------------------------

def receive_event(payload: dict, owner: str) -> dict:
    """Store an ``earnings_detected`` event (once per accession) and arm its follow-up timer."""
    accession, symbol = str(payload.get("accession") or ""), str(payload.get("symbol") or "").upper()
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Z.\-]{1,10}", symbol):
        raise ValueError("invalid_event")
    accepted = _utc(payload["accepted_at"])
    with SessionLocal() as db:
        existing = db.scalar(select(EarningsEvent).where(EarningsEvent.owner_hash == owner, EarningsEvent.accession == accession))
        if existing is not None:
            return {"accepted": True, "duplicate": True, "status": existing.status}
        db.add(EarningsEvent(owner_hash=owner, symbol=symbol, accession=accession, cik=str(payload.get("cik") or ""),
                             held=bool(payload.get("held")), source_url=str(payload.get("url") or "")[:500], accepted_at=accepted,
                             detected_at=_utc(payload["detected_at"]) if payload.get("detected_at") else None,
                             followup_due_at=accepted + FOLLOWUP_AFTER, detail={}))
        db.commit()
    return {"accepted": True, "duplicate": False, "status": "received"}


def _claim_first(now: datetime):
    with SessionLocal() as db:
        row = db.scalars(select(EarningsEvent).where(
            EarningsEvent.attempts < MAX_ATTEMPTS,
            (EarningsEvent.status == "received") | ((EarningsEvent.status == "analysing") & (EarningsEvent.claimed_at < now - STUCK_AFTER)))
            .order_by(EarningsEvent.accepted_at).with_for_update(skip_locked=True).limit(1)).first()
        if row is None:
            return None
        row.status, row.claimed_at, row.attempts = "analysing", now, row.attempts + 1
        db.commit()
        return row.id


def _claim_followup(now: datetime):
    with SessionLocal() as db:
        row = db.scalars(select(EarningsEvent).where(
            EarningsEvent.status == "first_sent", EarningsEvent.followup_due_at <= now,
            (EarningsEvent.followup_status == "pending") | ((EarningsEvent.followup_status == "running") & (EarningsEvent.claimed_at < now - STUCK_AFTER)))
            .order_by(EarningsEvent.followup_due_at).with_for_update(skip_locked=True).limit(1)).first()
        if row is None:
            return None
        if now - row.followup_due_at > FOLLOWUP_STALE:
            row.followup_status = "skipped_stale"
            db.commit()
            return None
        row.followup_status, row.claimed_at = "running", now
        db.commit()
        return row.id


def tick(now: datetime | None = None, *, sources=None, reader=None) -> dict:
    """One pass: first messages that are due, then follow-ups that are due.  Safe to call from several places."""
    now = now or datetime.now(UTC)
    if reader is None:
        from . import earnings_reader as reader
    sources = sources or LiveSources()
    done = {"first": 0, "followup": 0}
    while (event_id := _claim_first(now)) is not None:
        try:
            send_first(event_id, sources, reader, now)
            done["first"] += 1
        except Exception:
            log.exception("earnings first message failed")
            with SessionLocal() as db:
                row = db.get(EarningsEvent, event_id)
                row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "received"
                if row.status == "failed":
                    row.followup_status = "skipped_no_first"
                db.commit()
    while (event_id := _claim_followup(now)) is not None:
        try:
            send_followup(event_id, sources, reader, now)
            done["followup"] += 1
        except Exception:
            log.exception("earnings follow-up failed")
            with SessionLocal() as db:
                db.get(EarningsEvent, event_id).followup_status = "failed"
                db.commit()
    return done


# --- delivery ------------------------------------------------------------------------------------------------

def bot_for(owner: str, symbol: str):
    """The bot that follows ``symbol`` (focus company), else the owner's default bot."""
    from .agent_bots import ensure_default_bot
    with SessionLocal() as db:
        for bot in db.scalars(select(AgentBot).where(AgentBot.owner_hash == owner).order_by(AgentBot.created_at)):
            if symbol in [c.get("symbol") for c in (bot.focus or {}).get("companies") or []]:
                return bot.id
    return ensure_default_bot(owner).id


def _deliver(event: EarningsEvent, kind: str, title: str, body: str, now: datetime) -> bool:
    """Record in the bot's line; a holding is also queued for Telegram.  Same key = same message, never twice."""
    bot_id = bot_for(event.owner_hash, event.symbol)
    return tasks.add_item(event.owner_hash, section="brief", kind="filing", title=title, body=body, bot_id=bot_id, now=now,
                          payload={"earnings": event.accession, "stage": kind, "symbol": event.symbol, "held": event.held},
                          dedupe_key=f"earnings:{event.accession}:{kind}", telegram=bool(event.held),
                          post={"head": tasks.post_head("财报监控", now, "UTC"), "citations": []})


def render_first(event: EarningsEvent, facts, c, prior_known: bool, commentary: str) -> tuple[str, str]:
    local = event.accepted_at.astimezone(NY)
    guid = facts.guidance
    lines = [f"{event.symbol} 于美东 {local:%m-%d %H:%M} 发布财报（8-K Item 2.02），{quarter_label(event.accepted_at)} 季度。", "", "关键数字（对比上季指引）"]
    if prior_known:
        lines += [f"· 营收 {_num(facts.revenue)}B：对上季指引中值 {_pct(c.revenue_vs_guidance_pct)}"
                  + (f"，扣除该公司惯常超出（{_pct(c.habitual_revenue_beat_pct)}）后 {_pct(c.revenue_beat_excess_pct)}" if c.habitual_revenue_beat_pct is not None else ""),
                  f"· 每股收益（非 GAAP）{_num(facts.eps)}：对上季指引 {_pct(c.eps_vs_guidance_pct)}"
                  + (f"，扣除惯常超出（{_pct(c.habitual_eps_beat_pct)}）后 {_pct(c.eps_beat_excess_pct)}" if c.habitual_eps_beat_pct is not None else ""),
                  f"· 毛利率 {_num(facts.gross_margin)}%：对上季指引 {_pp(c.gross_margin_vs_guidance_pp)} 个百分点"]
    else:
        lines += [f"· 营收 {_num(facts.revenue)}B，每股收益（非 GAAP）{_num(facts.eps)}，毛利率 {_num(facts.gross_margin)}%（没有上季指引可比）"]
    lines += ["", "新指引（下季）"]
    if guid.revenue_low is not None:
        lines.append(f"· 营收 {_num(guid.revenue_low)}–{_num(guid.revenue_high)}B，指引中值 {_num(guid.revenue_mid)}B：对本季 {_pct(c.new_revenue_vs_actual_pct)}"
                     + (f"，对去年同期 {_pct(c.new_revenue_vs_year_ago_pct)}" if c.new_revenue_vs_year_ago_pct is not None else ""))
    if guid.eps is not None:
        lines.append(f"· 每股收益 {_num(guid.eps)}：对本季 {_pct(c.new_eps_vs_actual_pct)}")
    if guid.gross_margin is not None:
        lines.append(f"· 毛利率 {_num(guid.gross_margin)}%：对本季 {_pp(c.new_gross_margin_vs_actual_pp)} 个百分点")
    if guid.revenue_low is None and guid.eps is None and guid.gross_margin is None:
        lines.append("· 新闻稿里没有读到下季指引")
    lines += ["", "管理层说法", f"· {_clip(commentary.splitlines()[0])}" if commentary else "· 新闻稿里没有高管引语"]
    quality = []
    if c.eps_gaap_minus_nongaap is not None:
        quality.append(f"GAAP 每股收益比非 GAAP 少 {abs(c.eps_gaap_minus_nongaap):.2f}" if c.eps_gaap_minus_nongaap < 0 else f"GAAP 每股收益比非 GAAP 多 {c.eps_gaap_minus_nongaap:.2f}")
    if c.pre_release_return_20d_pct is not None:
        quality.append(f"财报前 20 个交易日股价 {_pct(c.pre_release_return_20d_pct)}")
    lines += ["", "超出的质量", "· " + ("；".join(quality) if quality else "数据不足")]
    lines += ["", f"原文：{event.source_url}", "（约 30 分钟后带盘后/盘前走势再给判断）"]
    return f"{event.symbol} 财报已出：分析", "\n".join(lines)


def send_first(event_id, sources, reader, now: datetime) -> None:
    from dataclasses import asdict
    with SessionLocal() as db:
        event = db.get(EarningsEvent, event_id)
        db.expunge(event)
    model = reader.model_for_owner(event.owner_hash)
    text = sources.release_text(event.symbol, event.cik, event.accession)
    if not text:
        raise RuntimeError("release_text_unavailable")
    closes = sources.daily_closes(event.symbol)
    ensure_history(event.symbol, event.cik, event.accepted_at, sources, reader, model, closes)
    facts = _run(reader.extract_release(text, model))
    history = history_for(event.symbol, event.accepted_at)
    prior = prior_guidance(event.symbol, event.accepted_at)
    comparison = reader.compare(facts, prior, history, prices_before(closes, event.accepted_at))
    _store_history(event.symbol, event.accession, event.accepted_at, facts, reader.READER_VERSION, closes)
    title, body = render_first(event, facts, comparison, prior is not None, commentary_from(text))
    _deliver(event, "first", title, body, now)
    with SessionLocal() as db:
        row = db.get(EarningsEvent, event_id)
        row.status, row.first_sent_at = "first_sent", now
        facts_data = asdict(facts)
        facts_data.pop("source_text", None)
        row.detail = {**(row.detail or {}), "comparison": asdict(comparison), "facts": facts_data,
                      "model": model["model"], "reader_version": reader.READER_VERSION}
        db.commit()


# --- the follow-up -------------------------------------------------------------------------------------------

DIRECTION_TEXT = {"up": "偏涨", "down": "偏跌"}
CONFIDENCE_TEXT = {"high": "高", "medium": "中", "low": "低"}


def render_followup(event: EarningsEvent, j, after_hours, holding, gate: dict) -> tuple[str, str]:
    label = "" if gate["validated"] else "｜该模型未经盲测"
    head = "财报追加提醒" if gate["validated"] else "财报追加判断（普通通知）"
    lines = [f"【{head}{label}】{event.symbol}", f"判断：{DIRECTION_TEXT[j.direction]}（发布后首个交易日预计出现明显{'上涨' if j.direction == 'up' else '下跌'}）　把握：{CONFIDENCE_TEXT[j.confidence]}"]
    if not gate["validated"]:
        lines.append("该模型未经盲测，命中率没有统计支持，只供参考，不要据此直接下单。")
    lines += ["", "理由（附原文）"]
    for n, reason in enumerate(j.reasons[:3], 1):
        lines.append(f"{n}. {reason['text']}\n   原文：“{reason['quote']}”")
    if j.counter_argument:
        lines.append(f"反方：{j.counter_argument}")
    if after_hours is not None:
        lines += ["", f"盘后/盘前走势：{after_hours * 100:+.1f}%"]
        against = (j.direction == "down" and after_hours >= DISAGREE_AT) or (j.direction == "up" and after_hours <= -DISAGREE_AT)
        if against:
            lines.append(f"⚠ 判断与盘后走势有分歧：判断{DIRECTION_TEXT[j.direction]}，盘后{after_hours * 100:+.1f}%。")
    if holding:
        lines += ["", f"对你的仓位：持有 {_num(holding['shares'], 0)} 股，均价 {_num(holding['avg_cost'])}，现价 {_num(holding['price'])}"
                      + (f"，占总资产 {_num(holding['weight_pct'], 1)}%" if holding.get("weight_pct") is not None else "")]
        if after_hours is not None and holding.get("price"):
            lines.append(f"按盘后/盘前 {after_hours * 100:+.1f}% 估算，持仓约变动 {holding['shares'] * holding['price'] * after_hours:+.0f} 美元。")
        lines.append(f"你预设的计划：{holding['plan_text'] or '没有写计划'}" + (f"；补仓价 {_num(holding['add_price'])}" if holding.get("add_price") else ""))
        funds = holding.get("available_funds")
        if funds is None:
            lines.append("可用资金：未记录。")
        else:
            ref = holding.get("add_price") or holding.get("price")
            can = int(funds // ref) if ref else 0
            lines.append(f"可用资金：{funds:.0f} 美元，按{'补仓价' if holding.get('add_price') else '现价'} {_num(ref)} 可买 {can} 股"
                         + ("（够补仓）" if can >= 1 else "（不够买一股）"))
    else:
        lines += ["", "你目前没有持仓（研究队列公司，只做记录）。"]
    return f"{event.symbol} 财报追加判断", "\n".join(lines)


def send_followup(event_id, sources, reader, now: datetime) -> None:
    from dataclasses import asdict
    with SessionLocal() as db:
        event = db.get(EarningsEvent, event_id)
        db.expunge(event)
    model = reader.model_for_owner(event.owner_hash)
    gate = gate_status(model["model"], reader.READER_VERSION)
    text = sources.release_text(event.symbol, event.cik, event.accession)
    closes = sources.daily_closes(event.symbol)
    saved = (event.detail or {}).get("facts")
    if saved:   # the numbers the first message was built from, not a second reading
        from .earnings_reader import Guidance, ReleaseFacts
        facts = ReleaseFacts(**{**saved, "guidance": Guidance(**saved["guidance"]), "source_text": text})
    else:
        facts = _run(reader.extract_release(text, model))
    history = history_for(event.symbol, event.accepted_at)
    prior = prior_guidance(event.symbol, event.accepted_at)
    comparison = reader.compare(facts, prior, history, prices_before(closes, event.accepted_at))
    try:
        after_hours = sources.extended_move(event.symbol, event.accepted_at, event.accepted_at + FOLLOWUP_AFTER)
    except Exception as exc:
        log.warning("extended-hours move unavailable for %s: %s", event.symbol, type(exc).__name__)
        after_hours = None
    j = _run(reader.judge(facts, comparison, commentary_from(text), after_hours, model))
    if j.direction == "unclear":
        status = "skipped_unclear"
    elif CONFIDENCE_RANK[j.confidence] < CONFIDENCE_RANK[gate["min_confidence"]]:
        status = "skipped_low_confidence"
    else:
        holding = sources.holding_for(event.owner_hash, event.symbol) if event.held else None
        title, body = render_followup(event, j, after_hours, holding, gate)
        _deliver(event, "followup", title, body, now)
        status = "sent"
    with SessionLocal() as db:
        row = db.get(EarningsEvent, event_id)
        row.followup_status = status
        row.followup_sent_at = now if status == "sent" else None
        row.detail = {**(row.detail or {}), "followup": {"direction": j.direction, "confidence": j.confidence, "after_hours": after_hours,
                                                         "validated": gate["validated"], "bar": gate["min_confidence"], "reasons": j.reasons,
                                                         "counter_argument": j.counter_argument}}
        db.commit()
