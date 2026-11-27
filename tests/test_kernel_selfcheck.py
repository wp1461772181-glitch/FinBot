"""5c-3a: the daily missed-alert check and the lines it adds to the morning brief.

No network: the price check gets scripted 5-minute bars (``tests.test_sentinel_replay``), the sentinel's database is a ``Store`` in
``tmp_path``, the model is a script; the rest is the suite's disposable PostgreSQL."""
import asyncio
import copy
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.agent_chat_provider as provider
from app import agent_task_runner as runner
from app import duty_brief, duty_log, duty_selfcheck
from app.agent_chat_models import EarningsEvent
from app.agent_workflow import tools
from app.database import SessionLocal
from app.kernel import act, brief, loop, prompt, selfcheck
from sentinel.store import Store
from tests.test_agent_notify import OWNER, OWNER_HASH, owner  # noqa: F401  (fixture)
from tests.test_kernel_brief import ANSWER, brief_now, duty
from tests.test_kernel_loop import OK_ROWS, Script, step
from tests.test_kernel_wake import MODEL
from tests.test_sentinel_replay import SNAP, data, et

NOW = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)          # Beijing Wednesday 08:00; New York Tuesday 11-03 19:00
SINCE = NOW - timedelta(days=1)
HELD = {"NVDA", "INTC"}
EVENT_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000001/q3.htm"
SEEN_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000002/q3.htm"
PORTFOLIO = {"positions": [{"symbol": "NVDA", "shares": 10}, {"symbol": "INTC", "shares": 100}], "research_queue": [],
             "total_assets": 1_000_000.0}
_ACCESSIONS = iter(range(100_000, 999_999))


def _clean():
    with SessionLocal() as db:
        db.query(duty_selfcheck.DutySelfcheck).delete()
        db.query(EarningsEvent).filter(EarningsEvent.owner_hash == OWNER_HASH).delete()
        db.query(duty_log.DutyLog).delete()
        db.query(duty_brief.DutyBrief).delete()
        db.commit()


@pytest.fixture
def env(owner, monkeypatch, tmp_path):
    _clean()
    monkeypatch.setenv("FINBOT_DUTY_MODE", "shadow")
    path = tmp_path / "sentinel.db"
    yield SimpleNamespace(db=path, store=Store(path), monkeypatch=monkeypatch, tmp=tmp_path)
    _clean()           # the brief reads these rows: none may outlive the test


def accession() -> str:
    return f"0001045810-26-{next(_ACCESSIONS):06d}"


def event(symbol="NVDA", status="failed", age=timedelta(hours=3), acc=None, url=EVENT_URL) -> str:
    """An ``earnings_events`` row that came in ``age`` before NOW."""
    acc = acc or accession()
    with SessionLocal() as db:
        db.add(EarningsEvent(owner_hash=OWNER_HASH, symbol=symbol, accession=acc, cik="1045810", held=symbol in HELD, source_url=url,
                             accepted_at=NOW - age, detected_at=NOW - age, status=status, attempts=3 if status == "failed" else 1,
                             created_at=NOW - age, detail={}))
        db.commit()
    return acc


def seen(env, symbol="NVDA", age=timedelta(hours=3), acc=None, url=SEEN_URL, seeded=0) -> str:
    """A sentinel ``earnings_seen`` row detected ``age`` before NOW."""
    acc = acc or accession()
    stamp = (NOW - age).timestamp()
    env.store.add_earnings({"accession": acc, "symbol": symbol, "cik": "1045810", "held": int(symbol in HELD), "filed": "2026-11-03",
                            "accepted_at": stamp, "primary_doc": "q3.htm", "url": url, "detected_at": stamp, "seeded": seeded})
    return acc


def earnings(env, held=HELD, since=SINCE):
    return selfcheck.earnings_findings(OWNER_HASH, since, NOW, set(held), env.db)


class Bars:
    """A scripted ``fetch``: the replay test's INTC session (-16% from 10:00 on 11-03) whatever is asked, and what was asked."""

    def __init__(self):
        self.asked = []

    def __call__(self, symbols):
        self.asked.append(list(symbols))
        return data()


def prices(env, snapshot=SNAP, fetch=None):
    return selfcheck.price_findings(date(2026, 11, 3), snapshot, env.db, fetch or Bars())


# --- when it is due ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utc,day", [((23, 44), None), ((23, 45), "2026-11-28"), ((3, 59), "2026-11-28"), ((4, 0), None)])
def test_a_check_is_due_from_07_45_until_noon_beijing(utc, day):
    when = datetime(2026, 11, 27 if utc[0] >= 12 else 28, *utc, tzinfo=UTC)
    assert selfcheck.due_day(when) == day


@pytest.mark.parametrize("when,session", [
    (datetime(2026, 11, 27, 18, 45, tzinfo=selfcheck.ET), date(2026, 11, 27)),     # Friday after the close
    (datetime(2026, 11, 28, 18, 45, tzinfo=selfcheck.ET), None),                   # Saturday
    (datetime(2026, 11, 24, 15, 0, tzinfo=selfcheck.ET), None),                    # Tuesday before the close
])
def test_the_session_is_the_new_york_weekday_after_its_close(when, session):
    assert selfcheck.session_day(when) == session


def test_held_symbols_are_the_positions_with_shares():
    assert selfcheck.held_symbols({"positions": [{"symbol": "NVDA", "shares": 1}, {"symbol": "AMD", "shares": 0}, {"shares": 3}]}) == {"NVDA"}


# --- earnings ---------------------------------------------------------------------------------------------------------------

def test_a_failed_held_event_is_a_finding_with_its_link(env):
    event(status="failed")
    found, counts = earnings(env)
    assert [(f["kind"], f["symbol"], f["why"], f["url"], f["at"]) for f in found] == [
        ("earnings", "NVDA", selfcheck.WHY_FAILED, EVENT_URL, "2026-11-04 05:00")]
    assert counts == {"earnings_events": 1, "earnings_seen": 0}


def test_a_failed_event_of_a_symbol_he_neither_holds_nor_watches_is_not_a_finding(env):
    event(symbol="AMD", status="failed")
    assert earnings(env)[0] == []


def test_the_earnings_check_covers_the_research_queue_too():
    snap = {"positions": [{"symbol": "INTC", "shares": 100}], "research_queue": ["NVDA", "INTC"]}
    assert selfcheck.watched_symbols(snap) == {"INTC", "NVDA"}


def test_an_event_stuck_over_an_hour_is_a_finding_and_a_recent_one_is_not(env):
    event(status="analysing", age=timedelta(minutes=61))
    event(symbol="INTC", status="received", age=timedelta(minutes=30))
    event(symbol="INTC", status="first_sent", age=timedelta(hours=5))
    found, _ = earnings(env)
    assert [(f["symbol"], f["why"]) for f in found] == [("NVDA", selfcheck.WHY_STUCK)]


def test_an_earnings_filing_the_sentinel_saw_without_an_event_is_a_finding(env):
    seen(env)
    found, counts = earnings(env)
    assert [(f["symbol"], f["why"], f["url"]) for f in found] == [("NVDA", selfcheck.WHY_UNSEEN, SEEN_URL)]
    assert counts["earnings_seen"] == 1


def test_a_seen_filing_with_its_event_is_not_a_finding(env):
    acc = seen(env)
    event(status="first_sent", acc=acc)
    assert earnings(env)[0] == []


def test_an_event_without_a_link_takes_the_sentinels(env):
    acc = seen(env)
    event(status="failed", acc=acc, url="")
    assert [f["url"] for f in earnings(env)[0]] == [SEEN_URL]


def test_filings_older_than_14_days_and_seeded_history_are_not_findings(env):
    event(status="failed", age=timedelta(days=15))
    seen(env, age=timedelta(days=15))
    seen(env, seeded=1)
    seen(env, symbol="AMD")
    found, counts = earnings(env)
    assert found == [] and counts == {"earnings_events": 0, "earnings_seen": 1}


def test_a_filing_from_before_the_last_check_that_failed_after_it_is_still_found(env):
    event(status="failed", age=timedelta(days=2))         # before SINCE: the window is on the filing, at least 14 days back
    found, _ = earnings(env)
    assert [f["why"] for f in found] == [selfcheck.WHY_FAILED]


def test_a_filing_an_earlier_check_reported_is_not_reported_again(env):
    event(status="failed")
    found, _ = earnings(env)
    checked(found)
    again, _ = earnings(env)
    assert len(found) == 1 and again == []


def test_an_unreadable_sentinel_database_keeps_the_events_findings(env):
    event(status="failed")
    found, counts = selfcheck.earnings_findings(OWNER_HASH, SINCE, NOW, HELD, env.tmp / "missing" / "sentinel.db")
    assert [f["why"] for f in found] == [selfcheck.WHY_FAILED] and "earnings_seen" in counts["error"]


# --- prices -----------------------------------------------------------------------------------------------------------------

def test_a_replayed_major_move_with_no_live_alert_that_day_is_a_finding(env):
    fetch = Bars()
    found, checked = prices(env, fetch=fetch)
    assert fetch.asked == [["INTC", "SPY"]]
    assert [(f["kind"], f["symbol"]) for f in found] == [("price", "INTC")]
    assert found[0]["at"].startswith("2026-11-03 10:") and "INTC" in found[0]["text"] and "\n" not in found[0]["text"]
    assert checked == {"price_symbols": ["INTC"], "replayed": 1, "live": 0}


def test_any_live_alert_on_the_symbol_that_day_means_nothing_was_missed(env):
    env.store.add_alert("INTC", "rule", "【你的规则】INTC 跌破 35", False, et(3, 15, 0).timestamp())     # another kind, hours later
    found, checked = prices(env)
    assert found == [] and checked["live"] == 1


def test_a_merged_live_alert_counts_for_each_of_its_symbols(env):
    env.store.add_alert("NVDA+INTC", "merged", "【多只异动】", True, et(3, 10, 30).timestamp())
    assert prices(env)[0] == []


def test_a_live_alert_the_day_before_or_an_earnings_alert_does_not_cover_the_move(env):
    env.store.add_alert("INTC", "daily", "【盘中异动】INTC 跌 5%", True, et(2, 12, 0).timestamp())
    env.store.add_alert("INTC", "earnings", "【财报】INTC", True, et(3, 16, 30).timestamp())
    found, checked = prices(env)
    assert [f["symbol"] for f in found] == ["INTC"] and checked["live"] == 0


def test_two_replayed_alerts_on_one_symbol_are_one_finding(env):
    found, checked = prices(env, snapshot=SNAP | {"plans": [{"symbol": "INTC", "stop_price": 35.0}]})
    assert checked["replayed"] >= 2 and [f["symbol"] for f in found] == ["INTC"]


# --- the run ----------------------------------------------------------------------------------------------------------------

def run(env, now=NOW, snapshot=PORTFOLIO, fetch=None, **kwargs):
    return selfcheck.run_once(OWNER_HASH, now, sentinel_db=env.db, snapshot=snapshot, fetch=fetch or Bars(), **kwargs)


def test_a_run_writes_both_checks_findings_sorted_by_time(env):
    event(status="failed")
    row = run(env)
    assert row["outcome"] == "done" and row["day"] == "2026-11-04" and row["session"] == "2026-11-03"
    assert [(f["kind"], f["symbol"]) for f in row["findings"]] == [("earnings", "NVDA"), ("price", "INTC")]
    assert row["checked"]["errors"] == {} and row["checked"]["earnings_events"] == 1 and row["checked"]["price_symbols"] == ["NVDA", "INTC"]
    assert duty_selfcheck.get(OWNER_HASH, "2026-11-04")["outcome"] == "done"


def test_a_price_check_that_raises_keeps_the_earnings_findings(env):
    def broken(symbols):
        raise RuntimeError("yahoo")

    event(status="failed")
    row = run(env, fetch=broken)
    assert row["outcome"] == "done" and "RuntimeError" in row["checked"]["errors"]["price"]
    assert [(f["kind"], f["symbol"]) for f in row["findings"]] == [("earnings", "NVDA")]


def test_an_earnings_check_that_raises_keeps_the_price_findings(env):
    def broken(*args):
        raise ValueError("db")

    env.monkeypatch.setattr(selfcheck, "earnings_findings", broken)
    row = run(env)
    assert row["outcome"] == "done" and "ValueError" in row["checked"]["errors"]["earnings"]
    assert [f["kind"] for f in row["findings"]] == ["price"]


def test_no_price_check_before_a_session_has_closed(env):
    fetch = Bars()
    row = run(env, now=datetime(2026, 11, 2, 0, 0, tzinfo=UTC), fetch=fetch)        # Beijing Monday 08:00: New York Sunday
    assert row["outcome"] == "done" and row["session"] is None and fetch.asked == []


def test_a_second_run_the_same_day_does_nothing(env):
    assert run(env)["outcome"] == "done"
    claims = []
    env.monkeypatch.setattr(duty_selfcheck, "claim", lambda *a, **k: claims.append(a))
    assert run(env) is None and claims == []


def test_a_time_outside_the_window_runs_nothing(env):
    assert run(env, now=datetime(2026, 11, 4, 5, 0, tzinfo=UTC)) is None
    with SessionLocal() as db:
        assert db.query(duty_selfcheck.DutySelfcheck).count() == 0


def test_off_checks_nothing(env):
    env.monkeypatch.setenv("FINBOT_DUTY_MODE", "off")
    event(status="failed")
    fetch = Bars()
    row = run(env, fetch=fetch)
    assert row["outcome"] == "skipped_off" and row["findings"] == [] and fetch.asked == []


def test_the_first_window_reaches_back_14_days_and_the_next_starts_at_the_last_check(env):
    event(status="failed", age=timedelta(days=13))
    event(symbol="INTC", status="failed", age=timedelta(days=15))
    first = run(env)
    assert [f["symbol"] for f in first["findings"] if f["kind"] == "earnings"] == ["NVDA"]
    second = run(env, now=NOW + timedelta(days=1))           # the window starts at the first row's real creation: the event is before it
    assert second["day"] == "2026-11-05" and [f for f in second["findings"] if f["kind"] == "earnings"] == []


def test_a_failure_outside_both_checks_finishes_the_row_as_failed(env):
    def broken(owner, now):
        raise KeyError("x")

    env.monkeypatch.setattr(selfcheck, "_window_start", broken)
    row = run(env)
    assert row["outcome"] == "failed" and "KeyError" in row["reason"]


def test_by_default_it_reads_the_snapshot_and_the_sentinel_database_the_sentinel_uses(env):
    snap = env.tmp / "snap.json"
    snap.write_text(json.dumps(PORTFOLIO), encoding="utf-8")
    env.monkeypatch.setenv("SENTINEL_CONFIG_PATH", str(snap))
    env.monkeypatch.setenv("SENTINEL_DB_PATH", str(env.db))
    seen(env)
    row = selfcheck.run_once(OWNER_HASH, NOW, fetch=Bars())
    assert row["outcome"] == "done" and ("earnings", "NVDA") in [(f["kind"], f["symbol"]) for f in row["findings"]]


# --- the brief carries the findings -----------------------------------------------------------------------------------------

FINDINGS = [
    {"kind": "earnings", "symbol": "NVDA", "at": "2026-11-20 05:20", "text": "status=failed attempts=3", "why": selfcheck.WHY_FAILED,
     "url": EVENT_URL},
    {"kind": "price", "symbol": "INTC", "at": "2026-11-25 10:05", "text": "【盘中异动】INTC 较昨收跌 16.0%", "why": "replayed"},
]


def test_the_lines_are_written_by_code():
    assert brief.selfcheck_lines([]) == ""
    assert brief.selfcheck_lines(FINDINGS) == (
        "漏报自查（每天收盘后核对，代码写的）：\n"
        f"· NVDA 的财报（2026-11-20 05:20）没发给你：财报解读试了三次都没做成。原文：{EVENT_URL}\n"
        "· INTC 美东 2026-11-25 10:05：【盘中异动】INTC 较昨收跌 16.0%——按现在的设置应当提醒，但当时没有发出（收盘后用五分钟线重算发现）。")


@pytest.fixture
def model(env):
    """The brief's model turn, scripted (as in tests.test_kernel_brief)."""
    mp = env.monkeypatch
    for module in (loop, prompt, act):
        mp.setattr(module, "owner_credential_matches", lambda value: bool(value))
    mp.setattr(runner, "owner_credential", lambda: OWNER)
    mp.setattr(runner, "task_model", lambda owner_hash, name: dict(MODEL))

    async def fake_invoke(name, args, context, *, emit=None, page_chars=None):
        return copy.deepcopy(OK_ROWS)

    mp.setattr(tools, "invoke", fake_invoke)

    def script(steps):
        fake = Script(steps)
        mp.setattr(provider, "stream_decision", fake)
        return fake
    return script


def checked(findings, day="2000-01-01", outcome="done"):
    row_id = duty_selfcheck.claim(OWNER_HASH, day)
    return duty_selfcheck.finish(row_id, outcome=outcome, findings=findings)


def write_brief():
    return asyncio.run(brief.run_once(OWNER_HASH, brief_now()))


def test_findings_alone_are_the_code_written_lines_without_a_model_call(env, model):
    checked(FINDINGS)
    fake = model([])
    row = write_brief()
    assert fake.calls == [] and row["outcome"] == "done" and row["model_calls"] == 0 and row["turn_id"] is None
    assert row["message"] == brief.HEAD + brief.selfcheck_lines(FINDINGS)
    assert row["counts"]["missed"] == 2


def test_with_kept_items_the_lines_come_between_the_body_and_the_filtered_line(env, model):
    duty("digest")
    duty("record")
    checked(FINDINGS)
    fake = model([step(text=ANSWER)])
    row = write_brief()
    body, lines, line = row["message"].split("\n\n")
    assert body == brief.HEAD + ANSWER and lines == brief.selfcheck_lines(FINDINGS) and line.startswith("从 ")
    shown = str(fake.calls[0]["messages"])
    assert "漏报自查" not in shown and EVENT_URL not in shown and "16.0%" not in shown
    assert row["counts"]["missed"] == 2 and row["counts"]["digest"] == 1


def test_the_same_finding_in_two_checks_is_told_once_and_an_unfinished_check_is_not_read(env, model):
    checked(FINDINGS[:1], day="2000-01-01")
    checked(FINDINGS, day="2000-01-02")
    checked([{**FINDINGS[1], "symbol": "AMD"}], day="2000-01-03", outcome="failed")
    model([])
    row = write_brief()
    assert row["counts"]["missed"] == 2 and "AMD" not in row["message"]


def test_a_carried_check_is_not_told_again_and_a_check_that_ends_after_the_brief_rides_the_next(env, model):
    checked(FINDINGS[:1], day="2000-01-01")
    model([])
    first = write_brief()
    assert first["counts"]["missed"] == 1
    checked(FINDINGS[1:], day="2000-01-02")             # finished after the day's brief
    model([])
    second = asyncio.run(brief.run_once(OWNER_HASH, brief_now(1), day="2000-12-31"))
    assert second["counts"]["missed"] == 1 and "INTC" in second["message"] and "NVDA" not in second["message"]


def test_without_findings_the_brief_counts_are_unchanged(env, model):
    duty("record")
    model([])
    row = write_brief()
    assert "missed" not in row["counts"] and "漏报自查" not in row["message"]


def test_the_loop_runs_the_check_for_the_owner_and_does_nothing_without_one(monkeypatch):
    from app import background, sentinel_bridge
    seen_runs = []
    monkeypatch.setattr(selfcheck, "run_once", lambda owner_hash, now: seen_runs.append((owner_hash, now.tzinfo is not None)) or {"day": "d"})
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: None)
    background.run_selfcheck()
    assert seen_runs == []
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: OWNER_HASH)
    background.run_selfcheck()
    assert seen_runs == [(OWNER_HASH, True)]
    assert {n: i for n, i, _ in background.LOOPS}["duty-selfcheck"] == background.SELFCHECK_SECONDS == 60
