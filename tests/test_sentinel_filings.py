"""Task 9, sentinel side: find earnings 8-Ks (Item 2.02 only), once per accession even across restarts, poll fast
only inside the New-York-time earnings window, and send a fallback when the API did not answer within 2 minutes."""
from datetime import UTC, date, datetime

from sentinel.filings import (MIN_GAP, FilingWatcher, filing_text, in_earnings_window, parse_earnings_filings, parse_new_filings,
                              poll_interval)
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
        self.announced = []
        self.build()

    def build(self):
        self.watcher = FilingWatcher(self.store, lambda: self.snap, fetch_json=self.fetch, post_event=self.post,
                                     raise_alert=lambda snap, alert: self.alerts.append(alert) or len(self.alerts), sleep=lambda s: None,
                                     announce=lambda alert_id, alert: self.announced.append((alert_id, alert["symbol"])))

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


def test_only_item_202_is_earnings(tmp_path):
    rows = [r("8-K", "5.02,9.01", "0000050863-26-000100"), r("10-Q", "", "0000050863-26-000101"),
            r("8-K", "2.02,9.01", "0000050863-26-000188")]
    assert [p["accession"] for p in parse_earnings_filings(submissions(*rows))] == ["0000050863-26-000188"]
    # every other new filing is told by the other path, the earnings 8-K is not told twice
    assert sorted(p["accession"] for p in parse_new_filings(submissions(*rows))) == ["0000050863-26-000100", "0000050863-26-000101"]


def test_other_new_filing_is_told_and_wakes_the_duty_turn(tmp_path):
    """11-28: an NVDA 8-K about its CEO went untold.  Every new filing of a holding is told now, once, and wakes the duty turn."""
    world = World(tmp_path, {"INTC": [r("8-K", "5.02,9.01", "0000050863-26-000100")]})
    world.watcher.poll(NOW)
    assert world.events == []                                   # not earnings: no earnings event
    assert len(world.alerts) == 1
    alert = world.alerts[0]
    assert alert["kind"] == "filing" and alert["symbol"] == "INTC" and alert["held"] is True and not alert["escalate"]
    assert "8-K" in alert["text"] and "高管或董事变动" in alert["text"] and "财务报表" not in alert["text"]
    assert alert["filing"]["url"].startswith("https://www.sec.gov/Archives/edgar/data/50863/")
    assert "tier" not in alert                                  # no cause-hunt: the duty turn reads the filing itself
    assert world.announced == [(1, "INTC")]
    world.build()                                               # a restart: same sentinel.db
    world.watcher.poll(NOW + 900)
    assert len(world.alerts) == 1 and len(world.announced) == 1


def test_queue_company_filing_is_told_too(tmp_path):
    world = World(tmp_path, {"NVDA": [r("DEF 14A", "", "0001045810-26-000050")]}, held=())
    world.snap["research_queue"] = ["NVDA"]
    world.watcher.poll(NOW)
    assert [(a["symbol"], a["held"]) for a in world.alerts] == [("NVDA", False)]
    assert "股东大会委托书" in world.alerts[0]["text"]


def test_noise_forms_are_left_out(tmp_path):
    world = World(tmp_path, {"INTC": [r("4", "", "0000050863-26-000300"), r("144", "", "0000050863-26-000301"),
                                      r("424B2", "", "0000050863-26-000302"), r("FWP", "", "0000050863-26-000303")]})
    world.watcher.poll(NOW)
    assert world.alerts == []


def test_first_look_seeds_old_filings_quietly(tmp_path):
    old = "2026-10-20T20:31:07.000Z"                            # nine days before NOW
    world = World(tmp_path, {"INTC": [r("10-Q", "", "0000050863-26-000400", filed="2026-10-20", accepted=old),
                                      r("8-K", "8.01", "0000050863-26-000401")]})
    world.watcher.poll(NOW)
    assert [a["filing"]["accession"] for a in world.alerts] == ["0000050863-26-000401"]   # only the fresh one
    assert world.store.filings_count("INTC") == 2


def test_filing_text_words():
    url = "https://example.test/x"
    eight_k = {"form": "8-K", "items": ["1.01", "9.01"], "filed": "2026-11-20", "description": ""}
    assert filing_text("NVDA", eight_k, url) == "【新公告】NVDA 8-K（签订重大协议），2026-11-20 提交。\nSEC 原文：https://example.test/x"
    amended = {"form": "10-K/A", "items": [], "filed": "2026-11-20", "description": ""}
    assert "年报（修订）" in filing_text("NVDA", amended, url)
    unknown = {"form": "8-K", "items": ["9.01"], "filed": "2026-11-20", "description": ""}
    assert "（临时报告）" in filing_text("NVDA", unknown, url)


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
    assert poll_interval(at(2026, 1, 29, 20, 30), last_winter) == 600


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


def test_a_failing_filing_check_never_blocks_earnings(tmp_path):
    """Review 11-28: a half-filled SEC row in another form must not keep the earnings 8-K out."""
    world = World(tmp_path, {"INTC": [r("8-K", "2.02,9.01", "0000050863-26-000188"), r("10-Q", "", "0000050863-26-000189", accepted="")]})
    world.watcher.poll(NOW)
    assert [e[1]["accession"] for e in world.events] == ["0000050863-26-000188"]
    world2 = World(tmp_path / "b", {"INTC": [r("8-K", "2.02,9.01", "0000050863-26-000188")]}) if (tmp_path / "b").mkdir() is None else None
    world2.watcher.raise_alert = lambda snap, alert: (_ for _ in ()).throw(RuntimeError("other path broken"))
    world2.watcher.check_other_filings = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    world2.watcher.poll(NOW)
    assert [e[1]["accession"] for e in world2.events] == ["0000050863-26-000188"]


def test_half_filled_rows_are_skipped_not_fatal():
    sub = submissions(r("10-Q", "", "A1", accepted=""), r("8-K", "8.01", "A2"))
    sub["filings"]["recent"]["items"] = ["", "8.01"][:1]          # items shorter than form
    assert [p["accession"] for p in parse_new_filings(sub)] == ["A2"]


def test_an_alert_that_fails_is_tried_again_not_lost(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "5.02", "0000050863-26-000100")]})
    real = world.watcher.raise_alert
    world.watcher.raise_alert = lambda snap, alert: (_ for _ in ()).throw(OSError("disk"))
    world.watcher.poll(NOW)
    assert world.alerts == [] and not world.store.filing_seen("0000050863-26-000100")
    world.watcher.raise_alert = real
    world.watcher.next_poll.clear()
    world.watcher.poll(NOW + 600)
    assert [a["filing"]["accession"] for a in world.alerts] == ["0000050863-26-000100"]


def test_a_first_look_that_fails_halfway_does_not_flood(tmp_path):
    old = "2026-10-01T20:31:07.000Z"
    rows = [r("8-K", "8.01", "NEW1"), *[r("10-Q", "", f"OLD{n}", filed="2026-10-01", accepted=old) for n in range(5)]]
    world = World(tmp_path, {"INTC": rows})
    real, calls = world.watcher.raise_alert, []
    def flaky(snap, alert):
        calls.append(alert)
        raise OSError("disk")
    world.watcher.raise_alert = flaky
    world.watcher.poll(NOW)
    world.watcher.raise_alert = real
    world.watcher.next_poll.clear()
    world.watcher.poll(NOW + 600)
    assert [a["filing"]["accession"] for a in world.alerts] == ["NEW1"]      # the old ones stay history


def test_back_in_the_holdings_after_days_is_a_first_look_again(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "8.01", "0000050863-26-000100")]})
    world.watcher.poll(NOW)
    assert len(world.alerts) == 1
    later = NOW + 10 * 86400                                    # out of the watch for ten days, then back
    world.rows["INTC"].append(r("10-Q", "", "0000050863-26-000500", filed="2026-11-02", accepted="2026-11-02T20:00:00.000Z"))
    world.watcher.next_poll.clear()
    world.watcher.poll(later)
    assert len(world.alerts) == 1                               # seven days old on its return: history, not news


def test_amended_earnings_and_schedule_13d_are_told(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K/A", "2.02,9.01", "A-AMEND"), r("SCHEDULE 13D", "", "A-13D"), r("SCHEDULE 13G/A", "", "A-13G")]})
    world.watcher.poll(NOW)
    assert sorted(a["filing"]["accession"] for a in world.alerts) == ["A-13D", "A-AMEND"]
    assert world.events == []                                   # an amended earnings 8-K is not a new earnings event


def test_the_digest_line_keeps_the_link(tmp_path):
    world = World(tmp_path, {"INTC": [r("8-K", "5.02", "0000050863-26-000100")]})
    world.watcher.poll(NOW)
    line = world.alerts[0]["digest_text"]
    assert "\n" not in line and "高管或董事变动" in line and "https://www.sec.gov/" in line
