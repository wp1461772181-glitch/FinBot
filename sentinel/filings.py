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
NORMAL_EVERY = 600.0             # a new filing of any kind is told now (11-28): ten minutes, not thirty
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


# Every other new filing of a holding or a queued company is told (owner design 4.11 / 7.2: 「关注对象的每一份新的官方公告默认都
# 告诉你」; the watch presets call it a hard guarantee).  The forms an investor reads; the per-trade insider forms (3/4/5), 144 and
# the prospectus pieces (424B*, FWP) come many a week and are left out.  An 8-K with Item 2.02 is earnings: the earnings path has it.
FILING_FORMS = frozenset({"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "40-F", "6-K", "DEF 14A", "DEFM14A",
                          "S-1", "S-3", "S-4", "SC 13D", "SC 13D/A", "SC TO-T", "SC 14D9"})
ITEM_WORDS = {"1.01": "签订重大协议", "1.02": "终止重大协议", "1.03": "破产或接管", "1.05": "网络安全事件", "2.01": "完成收购或处置资产",
              "2.03": "新增重大债务", "2.04": "债务加速到期", "2.05": "重组或退出业务", "2.06": "资产减值", "3.01": "退市或上市规则通知",
              "3.02": "未登记的股票发行", "3.03": "股东权利变更", "4.01": "更换审计师", "4.02": "之前的财报不可再依赖",
              "5.01": "控制权变更", "5.02": "高管或董事变动", "5.03": "章程或财年变更", "5.07": "股东大会表决结果",
              "7.01": "公开披露（Reg FD）", "8.01": "其他事项", "9.01": "财务报表和附件"}
FORM_WORDS = {"10-Q": "季报", "10-K": "年报", "20-F": "年报（境外公司）", "40-F": "年报（加拿大公司）", "6-K": "临时报告（境外公司）",
              "DEF 14A": "股东大会委托书", "DEFM14A": "并购委托书", "S-1": "上市注册", "S-3": "增发注册", "S-4": "并购注册",
              "SC 13D": "大股东持股报告", "SC TO-T": "要约收购", "SC 14D9": "对要约收购的回应"}


def parse_new_filings(submissions: dict) -> list[dict]:
    """The filings of FILING_FORMS, newest first, without the earnings 8-Ks (Item 2.02).  Each with its 8-K items and SEC's own
    one-line description when it gives one."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    described = recent.get("primaryDocDescription") or []
    rows = []
    for i, form in enumerate(recent.get("form") or []):
        if form not in FILING_FORMS:
            continue
        items = [x.strip() for x in str((recent.get("items") or [""] * (i + 1))[i] or "").split(",") if x.strip()]
        if form.startswith("8-K") and "2.02" in items:
            continue
        accepted = datetime.fromisoformat(recent["acceptanceDateTime"][i].replace("Z", "+00:00"))
        rows.append({"accession": recent["accessionNumber"][i], "form": form, "items": items, "filed": recent["filingDate"][i],
                     "accepted": accepted, "primary": recent["primaryDocument"][i],
                     "description": str(described[i]).strip() if i < len(described) and described[i] else ""})
    rows.sort(key=lambda r: r["accepted"], reverse=True)
    return rows


def filing_text(symbol: str, filing: dict, url: str) -> str:
    """The sentinel's own line for a new filing: which company, which form, what kind (8-K items, else the form's words), the date
    and the link.  Its meaning for the owner is the duty turn's (woken right after)."""
    if filing["form"].startswith("8-K"):
        kinds = [ITEM_WORDS.get(item, f"Item {item}") for item in filing["items"] if item != "9.01"] or ["临时报告"]
        what = "、".join(f"{k}" for k in kinds)
    else:
        what = FORM_WORDS.get(filing["form"].removesuffix("/A"), filing["description"] or "公告") + ("（修订）" if filing["form"].endswith("/A") else "")
    return f"【新公告】{symbol} {filing['form']}（{what}），{filing['filed']} 提交。\nSEC 原文：{url}"


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
                 sleep: Callable[[float], None] = time.sleep, announce: Callable[[int, dict], None] | None = None) -> None:
        self.store, self.get_snapshot, self.fetch_json = store, get_snapshot, fetch_json
        self.post_event, self.raise_alert, self.sleep = post_event, raise_alert, sleep
        self.announce = announce            # wakes the duty turn for an alert already stored and sent (main.Sentinel._announce)
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
        submissions = self._get(SUBMISSIONS_URL.format(cik=cik))
        self.check_other_filings(symbol, cik, held, now_ts, submissions)
        for filing in parse_earnings_filings(submissions):
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

    def check_other_filings(self, symbol: str, cik: str, held: bool, now_ts: float, submissions: dict) -> None:
        """Every new filing that is not earnings: the sentinel tells it (its own line, the hard guarantee: at night it waits for the
        8 a.m. digest like every quiet alert) and wakes the duty turn, which reads it and says what it means for him, or records
        why not.  A company's first look only notes what is older than a day (history, not news)."""
        fresh = self.store.filings_count(symbol) == 0
        for filing in parse_new_filings(submissions):
            accepted = filing["accepted"].timestamp()
            seeded = fresh and now_ts - accepted > SEED_OLDER_THAN
            url = filing_url(cik, filing["accession"], filing["primary"])
            row = {"accession": filing["accession"], "symbol": symbol, "cik": cik, "form": filing["form"], "items": ",".join(filing["items"]),
                   "filed": filing["filed"], "accepted_at": accepted, "url": url, "detected_at": now_ts, "seeded": int(seeded)}
            if not self.store.add_filing(row) or seeded:
                continue
            alert = {"symbol": symbol, "kind": "filing", "direction": "", "held": held, "text": filing_text(symbol, filing, url),
                     "escalate": False, "weight_pct": None, "earnings_unacked": False,
                     "filing": {"accession": filing["accession"], "form": filing["form"], "items": filing["items"], "url": url,
                                "filed": filing["filed"], "description": filing["description"] or None}}
            alert_id = self.raise_alert(self.get_snapshot(), alert)
            if isinstance(alert_id, int):
                self.store.set_filing_alert(filing["accession"], alert_id)
                if self.announce is not None:
                    self.announce(alert_id, alert)

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
