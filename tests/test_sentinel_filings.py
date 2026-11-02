"""Task 9, sentinel side: find earnings 8-Ks (Item 2.02 only), once per accession even across restarts, poll fast
only inside the New-York-time earnings window, and send a fallback when the API did not answer within 2 minutes."""
from datetime import UTC, date, datetime

from sentinel.filings import MIN_GAP, FilingWatcher, in_earnings_window, parse_earnings_filings, poll_interval
from sentinel.store import Store

TICKERS = {"0": {"cik_str": 50863, "ticker": "INTC", "title": "INTEL CORP"},
           "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}}
NOW = datetime(2026, 10, 30, 1, 0, tzinfo=UTC).timestamp()   # 21:00 EDT on the 29th


def submissions(*rows):
    keys = ["form", "items", "accessionNumber", "filingDate", "acceptanceDateTime", "primaryDocument"]
    return {"filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}


def r(form, items, acc, filed="2026-10-29", accepted="2026-10-29T20:31:07.000Z"):
    return (form, items, acc, filed, accepted, "x.htm")


class World:
    """Fake SEC + API: records every call so a test can count them."""
    def __init__(self, tmp_path, rows, held=("INTC",), api_up=True):
        self.rows, self.api_up, self.events, self.alerts, self.fetched = rows, api_up, [], [], []
        self.snap = {"positions": [{"symbol": s, "shares": 10} for s in held], "research_queue": [], "telegram": {"chat_id": 1}}
        self.store = Store(tmp_path / "s.db")
        self.build()

    def build(self):
        self.watcher = FilingWatcher(self.store, lambda: self.snap, fetch_json=self.fetch, post_event=self.post,
                                     raise_alert=lambda snap, alert: self.alerts.append(alert) or 1, sleep=lambda s: None)

    def fetch(self, url):
        self.fetched.append(url)
        if url.endswith("company_tickers.json"):
            return TICKERS
        symbol = {"CIK0000050863": "INTC", "CIK0001045810": "NVDA"}[url.rsplit("/", 1)[1].removesuffix(".json")]
        return submissions(*self.rows.get(symbol, []))

    def post(self, event_type, payload):
        if not self.api_up:
            raise OSError("api down")
        self.events.append((event_type, payload))


def test_only_item_202_triggers(tmp_path):
    rows = {"INTC": [r("8-K", "5.02,9.01", "0000050863-26-000100"), r("10-Q", "", "0000050863-26-000101"),
                     r("8-K", "2.02,9.01", "0000050863-26-000188")]}
    parsed = parse_earnings_filings(submissions(*rows["INTC"]))
    assert [p["accession"] for p in parsed] == ["0000050863-26-000188"]
    world = World(tmp_path, {"INTC": [r("8-K", "5.02", "0000050863-26-000100")]})
    world.watcher.poll(NOW)
    assert world.events == [] and world.alerts == []


def test_same_accession_once_across_restart(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02,9.01", "0000050863-26-000188")]})
    world.watcher.poll(NOW)
    assert [e[1]["accession"] for e in world.events] == ["0000050863-26-000188"]
    assert world.events[0][1]["held"] is True and world.events[0][1]["symbol"] == "INTC"
    world.build()                                   # a restart: new objects, same sentinel.db
    world.watcher.poll(NOW + 600)
    assert len(world.events) == 1


def test_window_uses_new_york_time():
    def at(y, m, d, hh, mm):
        return datetime(y, m, d, hh, mm, tzinfo=UTC)
    last_summer = date(2026, 7, 23)                 # +91 days = 2026-10-22, still EDT (UTC-4)
    assert in_earnings_window(at(2026, 10, 22, 20, 45), last_summer)        # 16:45 EDT
    assert not in_earnings_window(at(2026, 10, 22, 21, 45), last_summer)    # 17:45 EDT, after 17:30
    assert in_earnings_window(at(2026, 10, 22, 12, 30), last_summer)        # 08:30 EDT
    last_winter = date(2025, 10, 30)                # +91 days = 2026-01-29, EST (UTC-5)
    assert in_earnings_window(at(2026, 1, 29, 21, 30), last_winter)         # 16:30 EST
    assert not in_earnings_window(at(2026, 1, 29, 20, 30), last_winter)     # 15:30 EST: a fixed -4 offset would say 16:30
    assert in_earnings_window(at(2026, 1, 29, 13, 45), last_winter)         # 08:45 EST
    assert not in_earnings_window(at(2026, 1, 29, 14, 45), last_winter)     # 09:45 EST
    assert not in_earnings_window(at(2026, 2, 20, 21, 30), last_winter)     # far from the 91-day mark
    assert in_earnings_window(at(2026, 2, 8, 21, 30), last_winter)          # +10 days still inside
    assert not in_earnings_window(at(2026, 1, 29, 21, 30), None)            # no last earnings date: ordinary cadence
    assert poll_interval(at(2026, 1, 29, 21, 30), last_winter) == 120
    assert poll_interval(at(2026, 1, 29, 20, 30), last_winter) == 1800


def test_polls_are_spaced_for_the_sec_rate_limit(tmp_path):
    world = World(tmp_path, {})
    slept = []
    world.watcher.sleep = slept.append
    world.snap["positions"] = [{"symbol": "INTC", "shares": 1}, {"symbol": "NVDA", "shares": 1}]
    world.watcher.poll(NOW)
    assert MIN_GAP >= 0.2 and len(slept) >= 2 and all(s > 0 for s in slept)


def test_api_down_sends_fallback(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02,9.01", "0000050863-26-000188")]}, api_up=False)
    world.watcher.poll(NOW)
    world.watcher.fallbacks(NOW + 60)
    assert world.alerts == []                                   # inside the 2 minutes: still waiting
    world.watcher.fallbacks(NOW + 121)
    assert len(world.alerts) == 1
    text = world.alerts[0]["text"]
    assert "财报已出" in text and "分析暂时不可用" in text and "0000050863-26-000188".replace("-", "") in text
    world.watcher.fallbacks(NOW + 400)
    assert len(world.alerts) == 1                               # once


def test_no_fallback_when_api_answered(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02", "0000050863-26-000188")]})
    world.watcher.poll(NOW)
    world.watcher.fallbacks(NOW + 500)
    assert world.alerts == []


def test_queue_company_never_gets_fallback(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02", "0000050863-26-000188")]}, held=(), api_up=False)
    world.snap["research_queue"] = ["INTC"]
    world.watcher.poll(NOW)
    assert world.events == [] and len(world.store.earnings_rows()) == 1
    world.watcher.fallbacks(NOW + 500)
    assert world.alerts == []                                   # a research-queue company is record-only, never a push


def test_old_filing_on_first_poll_is_seeded_not_announced(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02", "0000050863-26-000155", "2026-07-23", "2026-07-23T20:15:00.000Z")]})
    world.watcher.poll(NOW)
    assert world.events == []
    assert world.store.last_earnings_date("INTC") == date(2026, 7, 23)   # but it fixes the window for next time


def test_detection_delay_is_recorded(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "2.02", "0000050863-26-000188", "2026-10-29", "2026-10-29T20:31:07.000Z")]})
    world.watcher.poll(datetime(2026, 10, 29, 20, 33, 7, tzinfo=UTC).timestamp())
    row = world.store.earnings_rows()[0]
    assert round(row["detected_at"] - datetime(2026, 10, 29, 20, 31, 7, tzinfo=UTC).timestamp()) == 120
