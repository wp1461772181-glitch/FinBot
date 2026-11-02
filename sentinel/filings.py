"""Earnings discovery (Task 9, sentinel side).  Stdlib only; never imports ``app``.

Every held or queued company's ``data.sec.gov/submissions/CIK##########.json`` is read; only ``form=8-K`` with Item
2.02 counts, once per accession (SQLite, so a restart never repeats one).  Ordinary cadence 30 minutes; inside the
earnings window (last earnings date + 91 days, +-10 days, New York 06:00-09:30 and 16:00-17:30, zoneinfo) 2
minutes.  Requests are spaced >= 0.2 s (<= 5/s overall) and carry ``SEC_EDGAR_USER_AGENT``.  A new filing is posted
to the API as ``earnings_detected``; if the API has not accepted it within 2 minutes a holding gets the fallback
"财报已出（SEC 链接），分析暂时不可用" straight from here.  A research-queue company is record-only, never pushed.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from .store import Store

logger = logging.getLogger("sentinel.filings")

NY = ZoneInfo("America/New_York")
NORMAL_EVERY = 1800.0
WINDOW_EVERY = 120.0
FALLBACK_AFTER = 120.0
MIN_GAP = 0.25                      # seconds between SEC requests: 4/s, under the 5/s ceiling
SEED_OLDER_THAN = 24 * 3600.0       # a filing older than this on a symbol's first look is history, not news
SESSIONS = ((dtime(6, 0), dtime(9, 30)), (dtime(16, 0), dtime(17, 30)))
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def parse_earnings_filings(submissions: dict) -> list[dict]:
    """The 8-Ks with Item 2.02, newest first.  ``acceptanceDateTime``'s Z is real UTC (checked against SEC)."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    rows = []
    for i, form in enumerate(recent.get("form") or []):
        items = [x.strip() for x in str(recent["items"][i] or "").split(",")]
        if form != "8-K" or "2.02" not in items:
            continue
        accepted = datetime.fromisoformat(recent["acceptanceDateTime"][i].replace("Z", "+00:00"))
        rows.append({"accession": recent["accessionNumber"][i], "filed": recent["filingDate"][i],
                     "accepted": accepted, "primary": recent["primaryDocument"][i]})
    rows.sort(key=lambda r: r["accepted"], reverse=True)
    return rows


def in_earnings_window(now: datetime, last_earnings: date | None) -> bool:
    if last_earnings is None:
        return False
    local = now.astimezone(NY)
    target = last_earnings + timedelta(days=91)
    if abs((local.date() - target).days) > 10:
        return False
    return any(start <= local.time() < end for start, end in SESSIONS)


def poll_interval(now: datetime, last_earnings: date | None) -> float:
    return WINDOW_EVERY if in_earnings_window(now, last_earnings) else NORMAL_EVERY


def filing_url(cik: str, accession: str, primary: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary}"


def sec_get_json(url: str) -> dict:
    agent = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    if "@" not in agent:
        raise RuntimeError("SEC_EDGAR_USER_AGENT must carry a contact email")
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https hosts
        return json.loads(response.read())


class FilingWatcher:
    def __init__(self, store: Store, get_snapshot: Callable[[], dict], *, fetch_json: Callable[[str], dict] = sec_get_json,
                 post_event: Callable[[str, dict], None], raise_alert: Callable[[dict, dict], object],
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.store, self.get_snapshot, self.fetch_json = store, get_snapshot, fetch_json
        self.post_event, self.raise_alert, self.sleep = post_event, raise_alert, sleep
        self.next_poll: dict[str, float] = {}

    def _get(self, url: str) -> dict:
        self.sleep(MIN_GAP)                 # every SEC request is preceded by a pause: <= 4 requests/s in total
        return self.fetch_json(url)

    def cik_for(self, symbol: str) -> str | None:
        cached = self.store.get_kv("cik_map")
        if cached is None or time.time() - cached[1] > 86400:
            raw = self._get(TICKERS_URL)
            mapping = {row["ticker"].upper(): f"{int(row['cik_str']):010d}" for row in raw.values()}
            self.store.set_kv("cik_map", mapping)
        else:
            mapping = cached[0]
        return mapping.get(symbol.upper().replace(".", "-"))

    def poll(self, now_ts: float) -> None:
        """Check every company that is due; one failing company never stops the others."""
        snap = self.get_snapshot()
        held = [p["symbol"] for p in snap.get("positions") or [] if p.get("symbol") and p.get("shares")]
        queued = [s for s in snap.get("research_queue") or [] if s not in held]
        now = datetime.fromtimestamp(now_ts, UTC)
        for symbol, is_held in [(s, True) for s in held] + [(s, False) for s in queued]:
            if now_ts < self.next_poll.get(symbol, 0.0):
                continue
            try:
                self.check_symbol(symbol, is_held, now_ts)
            except Exception as exc:
                logger.warning("earnings poll for %s failed: %s", symbol, type(exc).__name__)
            self.next_poll[symbol] = now_ts + poll_interval(now, self.store.last_earnings_date(symbol))

    def check_symbol(self, symbol: str, held: bool, now_ts: float) -> None:
        cik = self.cik_for(symbol)
        if cik is None:
            return
        fresh = not self.store.earnings_rows("symbol = ?", (symbol,))
        for filing in parse_earnings_filings(self._get(SUBMISSIONS_URL.format(cik=cik))):
            accepted = filing["accepted"].timestamp()
            seeded = fresh and now_ts - accepted > SEED_OLDER_THAN
            row = {"accession": filing["accession"], "symbol": symbol, "cik": cik, "held": int(held), "filed": filing["filed"],
                   "accepted_at": accepted, "primary_doc": filing["primary"],
                   "url": filing_url(cik, filing["accession"], filing["primary"]), "detected_at": now_ts, "seeded": int(seeded)}
            if not self.store.add_earnings(row) or seeded:
                continue
            payload = {"accession": filing["accession"], "symbol": symbol, "cik": cik, "held": held, "url": row["url"],
                       "filed": filing["filed"], "accepted_at": filing["accepted"].isoformat(),
                       "detected_at": datetime.fromtimestamp(now_ts, UTC).isoformat(), "primary_document": filing["primary"]}
            try:
                self.post_event("earnings_detected", payload)
                self.store.update_earnings(filing["accession"], delivered_at=now_ts)
            except Exception:
                self.store.enqueue("earnings_detected", payload)   # resent by the events job; fallback timer keeps running

    def mark_delivered(self, accession: str, now_ts: float) -> None:
        self.store.update_earnings(accession, delivered_at=now_ts)

    def fallbacks(self, now_ts: float) -> None:
        """A holding whose event the API did not accept within 2 minutes: say so ourselves, once."""
        snap = self.get_snapshot()
        for row in self.store.earnings_rows("delivered_at IS NULL AND fallback_at IS NULL AND seeded = 0 AND held = 1"):
            if now_ts - row["detected_at"] < FALLBACK_AFTER:
                continue
            text = f"【财报已出】{row['symbol']} 刚发布财报（8-K Item 2.02），分析暂时不可用。\nSEC 原文：{row['url']}"
            self.raise_alert(snap, {"symbol": row["symbol"], "kind": "earnings", "direction": "", "held": True,
                                    "text": text, "escalate": False, "weight_pct": None, "earnings_unacked": False})
            self.store.update_earnings(row["accession"], fallback_at=now_ts)
