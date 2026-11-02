#!/usr/bin/env python3
"""Earnings-reader blind test (plan Task 8).

For every company in config/blind_test_universe.txt, takes the latest N earnings releases (8-K Item 2.02,
Exhibit 99.1), runs the reader on each twice — a *masked* version (company name, ticker and dates hidden, so
the model cannot lean on remembered price history) and the original — and scores the calls against what the
stock really did.  The masked version is the one that counts.

    python scripts/earnings_blind_test.py run    --out .local/blind/results.jsonl [--tickers AAPL,INTC] [--quarters 2]
                                                  [--model NAME] [--max-releases N] [--workers 4]
    python scripts/earnings_blind_test.py report --in .local/blind/results.jsonl [--out docs/reports/2026-11-earnings-blind-test.md]
    python scripts/earnings_blind_test.py intel  [--model NAME]       # the Intel acceptance run (original text)

Resumable: ``run`` skips every (accession, variant) already in the JSONL without an error, so an interrupted
run continues where it stopped.  Needs the app's environment (DATABASE_URL for the model catalog, the model's
key, SEC_EDGAR_USER_AGENT).  The JSONL and the SEC / price caches live under .local/blind/ and are not committed.

Scoring (plan): only confidence=high calls count; "up" must meet an actual up, "down" an actual down;
an actual flat or the opposite direction is a miss.  Coverage = high-confidence calls / releases.
Launch bar: at least 20 high-confidence calls with a hit rate of at least 80% (masked variant).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl
import sys
import time as _time
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import earnings_reader as er  # noqa: E402

UNIVERSE = ROOT / "config" / "blind_test_universe.txt"
WORK = ROOT / ".local" / "blind"
DEFAULT_REPORT = ROOT / "docs" / "reports" / "2026-11-earnings-blind-test.md"
NY = ZoneInfo("America/New_York")
HISTORY_RELEASES = 4          # earlier releases fetched per target (prior guidance, habitual beat, year-ago)
LAUNCH_MIN_CALLS, LAUNCH_MIN_HIT = 20, 0.80
SEC_GAP_SECONDS = 0.15


# --- small helpers -----------------------------------------------------------------------------------------

def universe() -> list[str]:
    return [line.strip().upper() for line in UNIVERSE.read_text().splitlines() if line.strip() and not line.startswith("#")]


def _cache(name: str) -> Path:
    path = WORK / "cache" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_last_sec = 0.0


def _http_get(url: str, *, sec: bool = True) -> bytes:
    import httpx
    global _last_sec
    from app.sec_filings import configured_sec_user_agent
    headers = {"User-Agent": configured_sec_user_agent() if sec else "Mozilla/5.0 FinBot-blind-test"}
    for attempt in range(4):
        wait = SEC_GAP_SECONDS - (_time.monotonic() - _last_sec)
        if sec and wait > 0:
            _time.sleep(wait)
        _last_sec = _time.monotonic()
        try:
            # trust_env off: httpx cannot parse a NO_PROXY that lists "[::1]"; the proxy is passed explicitly, and the
            # system CA store (not certifi) is used because the egress proxy re-signs TLS.
            with httpx.Client(proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None,
                              trust_env=False, verify=ssl.create_default_context(), timeout=45,
                              follow_redirects=True) as client:
                response = client.get(url, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                _time.sleep(2 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.content
        except httpx.TransportError:
            _time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}")


def cached_get(name: str, url: str, *, sec: bool = True) -> bytes:
    path = _cache(name)
    if path.exists():
        return path.read_bytes()
    data = _http_get(url, sec=sec)
    path.write_bytes(data)
    return data


# --- SEC: company map, releases ----------------------------------------------------------------------------

def company_map() -> dict[str, tuple[str, str]]:
    raw = json.loads(cached_get("company_tickers.json", "https://www.sec.gov/files/company_tickers.json"))
    return {row["ticker"].upper(): (f"{int(row['cik_str']):010d}", row["title"]) for row in raw.values()}


def sec_ticker(ticker: str) -> str:
    return ticker.replace(".", "-")


def earnings_filings(cik: str, count: int) -> list[dict]:
    """The latest ``count`` 8-Ks with Item 2.02 (results of operations), newest first."""
    data = json.loads(_http_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = data["filings"]["recent"]
    rows = []
    for i, form in enumerate(recent["form"]):
        if form == "8-K" and "2.02" in (recent["items"][i] or "").split(","):
            rows.append({"accession": recent["accessionNumber"][i], "filed": recent["filingDate"][i],
                         "accepted": recent["acceptanceDateTime"][i], "primary": recent["primaryDocument"][i]})
    rows.sort(key=lambda r: r["accepted"], reverse=True)
    return rows[:count]


def release_text(cik: str, accession: str, primary: str) -> str | None:
    from app.sec_filings import _html_text
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    index = json.loads(cached_get(f"idx-{accession}.json", f"{folder}/index.json"))
    names = [(item["name"], int(item.get("size") or 0)) for item in index["directory"]["item"]]
    pick = [n for n, _ in names if re.search(r"(?i)(ex|exhibit)[-_]?99[-_.]?0?1|99[-_.]?1|earnings|release|press", n) and n.lower().endswith((".htm", ".html"))]
    if not pick:   # fall back to the biggest page that is not the 8-K cover
        pick = [n for n, size in sorted(names, key=lambda x: -x[1]) if n.lower().endswith((".htm", ".html")) and n != primary]
    if not pick:
        return None
    return _html_text(cached_get(f"doc-{accession}-{pick[0]}", f"{folder}/{pick[0]}"))


# --- prices and the market's reaction ----------------------------------------------------------------------

def prices(ticker: str) -> list[tuple[date, float]]:
    """Daily closes, oldest first (Yahoo chart, 3 years).  Cached per day."""
    stamp = date.today().isoformat()
    raw = cached_get(f"px-{ticker}-{stamp}.json",
                     f"https://query1.finance.yahoo.com/v8/finance/chart/{sec_ticker(ticker)}?range=3y&interval=1d", sec=False)
    result = json.loads(raw)["chart"]["result"][0]
    offset = result["meta"].get("gmtoffset", 0)
    out = []
    for stamp_s, close in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]):
        if close is not None:
            out.append((datetime.fromtimestamp(stamp_s + offset, timezone.utc).date(), float(close)))
    return out


def reaction(series: list[tuple[date, float]], accepted_utc: datetime):
    """(R, base_date, end_date, timing): first-trading-day close over the last close before the release."""
    et = accepted_utc.astimezone(NY)
    day = et.date()
    dates = [d for d, _ in series]
    close = dict(series)
    trading_day = day in close
    if et.time() < time(16, 0) and trading_day:
        timing = "pre_market" if et.time() < time(9, 30) else "intraday"
        base = max((d for d in dates if d < day), default=None)
        end = day
    else:
        timing = "after_close"
        base = max((d for d in dates if d <= day), default=None)
        end = min((d for d in dates if d > day), default=None)
    if base is None or end is None:
        return None
    return close[end] / close[base] - 1, base, end, timing


# --- masking -----------------------------------------------------------------------------------------------

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_SUFFIX = r"(?:,?\s+(?:Inc|Corp|Corporation|Company|Co|Ltd|Limited|plc|PLC|Holdings|Group|N\.V|S\.A)\.?)+"


def mask_text(text: str, ticker: str, title: str) -> str:
    """Hide the company name, ticker and every date/year, so only the business facts are left."""
    core = re.sub(_SUFFIX + r"\s*$", "", title.title().replace("\\", ""), flags=re.I).strip(" ,.")
    names = {title, title.title(), core, core.upper(), core.split()[0] if core else ""}
    names = sorted((n for n in names if len(n) >= 3), key=len, reverse=True)
    out = text
    for name in names:
        out = re.sub(re.escape(name) + r"(?:" + _SUFFIX + r")?", "[COMPANY]", out, flags=re.I)
    out = re.sub(r"(?<![A-Za-z])" + re.escape(ticker.split(".")[0]) + r"(?![A-Za-z])", "[TICKER]", out)
    out = re.sub(r"\b(?:" + _MONTHS + r")\s+\d{1,2}(?:,\s*\d{4})?", "[DATE]", out)
    out = re.sub(r"\b(?:" + _MONTHS + r")\s+\d{4}\b", "[DATE]", out)
    out = re.sub(r"\b(?:19|20)\d{2}\b", "[YEAR]", out)
    out = re.sub(r"\b(?:" + _MONTHS + r")\b", "[MONTH]", out)
    return out


def commentary_from(text: str) -> str:
    """Management's words in the release: the paragraphs quoting an executive."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    quoted = [p for p in paragraphs if re.search(r"[“\"].{40,}[”\"]", p) and re.search(r"\b(said|says|stated|commented)\b", p)]
    return "\n".join(quoted)[:4000]


# --- one release -------------------------------------------------------------------------------------------

def facts_cache(model: dict, accession: str) -> Path:
    return _cache(f"facts-{er.READER_VERSION}-{re.sub(r'[^A-Za-z0-9.-]', '_', model['model'])}-{accession}.json")


async def extract_cached(text: str, model: dict, accession: str) -> er.ReleaseFacts:
    path = facts_cache(model, accession)
    if path.exists():
        data = json.loads(path.read_text())
        return er.ReleaseFacts(**{**data, "guidance": er.Guidance(**data["guidance"]), "source_text": text})
    facts = await er.extract_release(text, model)
    data = asdict(facts)
    data.pop("source_text")
    path.write_text(json.dumps(data))
    return facts


async def prepare(ticker: str, cik: str, count: int) -> list[dict]:
    """Newest-first releases of one company, each with text, facts' inputs and the market's reaction."""
    filings = await asyncio.to_thread(earnings_filings, cik, count)
    series = await asyncio.to_thread(prices, ticker)
    out = []
    for f in filings:
        text = await asyncio.to_thread(release_text, cik, f["accession"], f["primary"])
        accepted = datetime.fromisoformat(f["accepted"].replace("Z", "+00:00"))
        out.append({**f, "text": text, "accepted_utc": accepted, "reaction": reaction(series, accepted)})
    return out


async def analyse(ticker: str, title: str, releases: list[dict], i: int, series, model: dict,
                  variants: list[str], done: set[str], emit, model_label: str):
    rel = releases[i]
    if not rel["text"]:
        await emit({"key": f"{rel['accession']}|-", "ticker": ticker, "accession": rel["accession"], "error": "no_release_text"})
        return
    if rel["reaction"] is None:
        await emit({"key": f"{rel['accession']}|-", "ticker": ticker, "accession": rel["accession"], "error": "no_price_reaction"})
        return
    r, base, end, timing = rel["reaction"]
    excluded = {x["reaction"][2] for x in releases if x["reaction"]}
    sigma = er.daily_sigma([(d, c) for d, c in series if d <= base], excluded)
    if sigma is None:
        await emit({"key": f"{rel['accession']}|-", "ticker": ticker, "accession": rel["accession"], "error": "sigma_unavailable"})
        return
    pending = [v for v in variants if f"{rel['accession']}|{v}" not in done]
    if not pending:
        return
    facts = await extract_cached(rel["text"], model, rel["accession"])
    prior = releases[i + 1] if i + 1 < len(releases) and releases[i + 1]["text"] else None
    prior_facts = await extract_cached(prior["text"], model, prior["accession"]) if prior else None
    history = []
    for k in range(i + 1, len(releases)):
        if not releases[k]["text"]:
            continue
        past = await extract_cached(releases[k]["text"], model, releases[k]["accession"])
        before = releases[k + 1] if k + 1 < len(releases) and releases[k + 1]["text"] else None
        guided = (await extract_cached(before["text"], model, before["accession"])).guidance if before else None
        history.append(er.HistoryQuarter(period=releases[k]["filed"], revenue=past.revenue, eps=past.eps,
                                         gross_margin=past.gross_margin, guided=guided,
                                         same_quarter_last_year=(k - i == 4)))
    series_before = [(d, c) for d, c in series if d <= base]
    comparison = er.compare(facts, prior_facts.guidance if prior_facts else None, history, series_before)
    actual = er.label_reaction(r, sigma)
    commentary = commentary_from(rel["text"])
    for variant in pending:
        shown_facts, shown_comment = facts, commentary
        if variant == "masked":
            shown_facts = replace(facts, source_text=mask_text(rel["text"], ticker, title))
            shown_comment = mask_text(commentary, ticker, title)
        record = {"key": f"{rel['accession']}|{variant}", "ticker": ticker, "accession": rel["accession"],
                  "release_date": rel["filed"], "timing": timing, "variant": variant, "model": model_label,
                  "reader_version": er.READER_VERSION, "R": round(r, 5), "sigma": round(sigma, 5), "actual": actual}
        try:
            j = await er.judge(shown_facts, comparison, shown_comment, None, model)
            record.update(direction=j.direction, confidence=j.confidence, reasons=j.reasons,
                          counter_argument=j.counter_argument, comparison=asdict(comparison))
        except Exception as exc:   # one bad call must not stop the run; it is retried on the next run
            record.update(error=f"{type(exc).__name__}: {str(exc)[:200]}")
        await emit(record)


# --- run ---------------------------------------------------------------------------------------------------

def load_done(path: Path) -> set[str]:
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if "error" not in rec or rec["key"].endswith("|-"):
                done.add(rec["key"])
    return done


def resolve_model(name: str | None) -> tuple[dict, str]:
    from app import agent_model_catalog as catalog
    model = er.model_for_owner(None) if not name else catalog.resolve(name)
    return model, f"{model['name']}/{model['model']}"


async def run(args) -> None:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(out)
    model, label = resolve_model(args.model)
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else universe()
    cmap = company_map()
    variants = args.variants.split(",")
    lock, sem = asyncio.Lock(), asyncio.Semaphore(args.workers)
    count = args.quarters + HISTORY_RELEASES
    budget = {"left": args.max_releases}
    stats = defaultdict(int)

    async def emit(record):
        async with lock:
            with out.open("a") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["error" if "error" in record else "written"] += 1
        if "error" in record:
            print(f"  ! {record['ticker']} {record.get('key')}: {record['error']}", flush=True)

    async def company(ticker: str):
        entry = cmap.get(sec_ticker(ticker))
        if not entry:
            await emit({"key": f"{ticker}|-", "ticker": ticker, "error": "no_cik"})
            return
        cik, title = entry
        try:
            releases = await prepare(ticker, cik, count)
            series = await asyncio.to_thread(prices, ticker)
        except Exception as exc:
            await emit({"key": f"{ticker}|-", "ticker": ticker, "error": f"prepare: {type(exc).__name__}: {str(exc)[:160]}"})
            return
        for i in range(min(args.quarters, len(releases))):
            if budget["left"] is not None:
                if budget["left"] <= 0:
                    return
                budget["left"] -= 1
            async with sem:
                try:
                    await analyse(ticker, title, releases, i, series, model, variants, done, emit, label)
                except Exception as exc:
                    await emit({"key": f"{releases[i]['accession']}|-", "ticker": ticker, "accession": releases[i]["accession"],
                                "error": f"analyse: {type(exc).__name__}: {str(exc)[:160]}"})
        print(f"  {ticker} done", flush=True)

    started = _time.monotonic()
    # Up to ``workers`` companies are walked at once; SEC pacing is global.
    pending = list(tickers)
    workers = [asyncio.create_task(_worker(pending, company)) for _ in range(args.workers)]
    await asyncio.gather(*workers)
    print(f"finished: {stats['written']} records, {stats['error']} errors, {_time.monotonic() - started:.0f}s -> {out}")


async def _worker(queue: list, fn):
    while queue:
        await fn(queue.pop(0))


# --- report ------------------------------------------------------------------------------------------------

def read_results(path: Path) -> list[dict]:
    rows = {}
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if "error" not in rec:
            rows[rec["key"]] = rec            # a later record for the same key wins
    return list(rows.values())


def score(rows: list[dict]) -> dict:
    high = [r for r in rows if r.get("confidence") == "high" and r.get("direction") in ("up", "down")]
    hits = [r for r in high if r["direction"] == r["actual"]]
    return {"n": len(rows), "high": len(high), "hits": len(hits),
            "hit_rate": (len(hits) / len(high)) if high else None, "coverage": (len(high) / len(rows)) if rows else None}


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def report(args) -> None:
    src = Path(args.inp)
    rows = read_results(src)
    errors = [json.loads(l) for l in src.read_text().splitlines() if l.strip() and '"error"' in l]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["reader_version"], r["variant"])].append(r)
    lines = ["# 财报阅读器离线盲测报告", "",
             f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}　原始结果：`{src}`（JSONL，不入库）　"
             f"记录数：{len(rows)}（出错/跳过 {len(errors)}）", "",
             *(["> ⚠ 这是冒烟/部分结果（不足 100 份财报），只验证流程，**不能**用来判定上线标准。", ""]
               if len({r["accession"] for r in rows}) < 100 else []),
             "## 口径", "",
             "- 反应 R = 发布后第一个交易日收盘 ÷ 发布前最后一个收盘 − 1（盘前/盘中发布用当天收盘对前一日收盘，盘后发布用下一交易日）。",
             "- σ = 发布前 126 个交易日日涨跌幅标准差（剔除该公司各次财报反应日）；R ≥ +max(2σ, 3%) 为涨，R ≤ −max(2σ, 3%) 为跌，其余为没大动。",
             "- 只统计 `confidence=high` 且方向为涨/跌的判断：判涨且实际涨、判跌且实际跌算对；实际没大动或方向相反算错。覆盖率 = 高把握判断数 ÷ 财报份数。",
             "- 遮名版（公司名/代码/日期遮掉）为准；原版仅用来看模型是否靠记忆沾光。",
             "- 判断时不提供盘后涨跌（它就是答案）；管理层说法取新闻稿内高管引语（离线没有电话会原文）。", "",
             f"上线标准：遮名版高把握判断 ≥ {LAUNCH_MIN_CALLS} 次且命中率 ≥ {LAUNCH_MIN_HIT:.0%}。", "",
             "## 结果（按模型与 READER_VERSION 分组）", "",
             "| 模型 | READER_VERSION | 版本 | 财报份数 | 高把握 | 命中 | 命中率 | 覆盖率 |", "|---|---|---|---:|---:|---:|---:|---:|"]
    verdicts = []
    for (model, version, variant), items in sorted(groups.items()):
        s = score(items)
        lines.append(f"| {model} | {version} | {'遮名版（准）' if variant == 'masked' else '原版'} | {s['n']} | {s['high']} | {s['hits']} | {_pct(s['hit_rate'])} | {_pct(s['coverage'])} |")
        if variant == "masked":
            ok = s["high"] >= LAUNCH_MIN_CALLS and (s["hit_rate"] or 0) >= LAUNCH_MIN_HIT
            verdicts.append((model, version, s, ok))
    lines += ["", "## 上线标准判定", ""]
    if not verdicts:
        lines.append("还没有遮名版结果。")
    for model, version, s, ok in verdicts:
        lines.append(f"- {model} / {version}：高把握 {s['high']} 次，命中率 {_pct(s['hit_rate'])} → "
                     + ("**达标**。" if ok else "**未达标**（样本不足或命中率不够）；第二条消息只按普通通知发。"))
    # Masked vs original on the same release.
    by_release = defaultdict(dict)
    for r in rows:
        by_release[(r["model"], r["accession"])][r["variant"]] = r
    both = [v for v in by_release.values() if "masked" in v and "original" in v]
    if both:
        same = sum(1 for v in both if (v["masked"]["direction"], v["masked"]["confidence"]) == (v["original"]["direction"], v["original"]["confidence"]))
        lines += ["", "## 遮名版与原版的差异", "",
                  f"同一份财报两版都有结果的 {len(both)} 份，其中方向与把握完全一致 {same} 份。不一致的：", "",
                  "| 公司 | 发布日 | 实际 | 遮名版 | 原版 |", "|---|---|---|---|---|"]
        for v in both:
            m, o = v["masked"], v["original"]
            if (m["direction"], m["confidence"]) != (o["direction"], o["confidence"]):
                lines.append(f"| {m['ticker']} | {m['release_date']} | {m['actual']}（{m['R'] * 100:+.1f}%） | {m['direction']}/{m['confidence']} | {o['direction']}/{o['confidence']} |")
    lines += ["", "## 逐份明细（遮名版）", "", "| 公司 | 发布日 | 时点 | R | σ | 实际 | 判断 | 把握 | 对错 |", "|---|---|---|---:|---:|---|---|---|---|"]
    for r in sorted((r for r in rows if r["variant"] == "masked"), key=lambda r: (r["ticker"], r["release_date"])):
        verdict = "—"
        if r["confidence"] == "high" and r["direction"] in ("up", "down"):
            verdict = "对" if r["direction"] == r["actual"] else "错"
        lines.append(f"| {r['ticker']} | {r['release_date']} | {r['timing']} | {r['R'] * 100:+.1f}% | {r['sigma'] * 100:.2f}% | {r['actual']} | {r['direction']} | {r['confidence']} | {verdict} |")
    skipped = defaultdict(int)
    for e in errors:
        skipped[e["error"].split(":")[0]] += 1
    if skipped:
        lines += ["", "## 跳过 / 出错", ""] + [f"- {k}：{v}" for k, v in sorted(skipped.items())]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"report -> {out} ({len(rows)} records)")


# --- the Intel acceptance run ------------------------------------------------------------------------------

INTEL = {"accession": "0000050863-26-000188", "prior": "0000050863-26-000155"}


async def intel(args) -> None:
    model, label = resolve_model(args.model)
    cik = "0000050863"
    releases = await prepare("INTC", cik, 1 + HISTORY_RELEASES + 2)
    index = next(i for i, r in enumerate(releases) if r["accession"] == INTEL["accession"])
    assert releases[index + 1]["accession"] == INTEL["prior"], "prior release is not the expected accession"
    series = await asyncio.to_thread(prices, "INTC")
    records = []

    async def emit(record):
        records.append(record)
    await analyse("INTC", "INTEL CORP", releases, index, series, model, ["original"], set(), emit, label)
    record = records[0]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--out", default=str(WORK / "results.jsonl"))
    p.add_argument("--tickers")
    p.add_argument("--quarters", type=int, default=2)
    p.add_argument("--model", help="catalog entry name (default: the 财报判断模型 role's default = server default)")
    p.add_argument("--variants", default="masked,original")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-releases", type=int, default=None, help="stop after this many releases (smoke runs)")
    p = sub.add_parser("report")
    p.add_argument("--in", dest="inp", default=str(WORK / "results.jsonl"))
    p.add_argument("--out", default=str(DEFAULT_REPORT))
    p = sub.add_parser("intel")
    p.add_argument("--model")
    p.add_argument("--out", default=str(WORK / "intel-acceptance.json"))
    args = parser.parse_args()
    if args.cmd == "run":
        asyncio.run(run(args))
    elif args.cmd == "report":
        report(args)
    else:
        asyncio.run(intel(args))


if __name__ == "__main__":
    main()
