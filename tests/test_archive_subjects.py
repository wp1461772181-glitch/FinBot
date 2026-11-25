"""Archive subjects (2c task 1): the list of companies the archive keeps, the bounded build worker, the monitor set.  SEC is faked; no network."""
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError

import pytest
from sqlalchemy import delete, select

from app import archive_subjects as subjects
from app.active_symbols import active_symbols
from app.agent_chat_models import AgentResearchQueue, PortfolioTransaction
from app.database import Base, SessionLocal, engine
from app.models import ArchiveSubject, SecFilingInventory
from app.sec_filings import SEC_SUBMISSIONS_URL, SEC_TICKERS_URL, SecEdgarProvider, SecFilingsError
from tests.test_sec_filings import FakeSecOpener, _responses

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
TICKERS = {str(i): {"ticker": t, "cik_str": 1000 + i, "title": t} for i, t in enumerate(["AAPL", "XYZ", "ABCD", "BRK-B", "NEWCO"] + [f"Q{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"])}


@pytest.fixture(autouse=True)
def world(disposable_database, monkeypatch):
    Base.metadata.create_all(engine)
    monkeypatch.setattr(subjects, "_fetch_ticker_list", lambda: TICKERS)
    monkeypatch.setattr(subjects, "_now", lambda: NOW)
    subjects._TICKERS.update(at=None, symbols=None)
    with SessionLocal() as db:
        db.execute(delete(ArchiveSubject))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(ArchiveSubject))
        db.commit()


def row(symbol):
    with SessionLocal() as db:
        return db.get(ArchiveSubject, symbol)


def put(symbol, **kw):
    values = dict(held=False, queued=False, asked_at=None, first_seen_at=NOW, last_active_at=NOW, build_status="never", filings_added=0)
    values.update(kw)
    with SessionLocal() as db:
        db.add(ArchiveSubject(symbol=symbol, **values))
        db.commit()


# --- SEC's ticker list ------------------------------------------------------------------------------------------

def test_sec_symbol_knows_only_what_sec_lists_and_normalises():
    assert subjects.sec_symbol(" xyz ") == "XYZ"
    assert subjects.sec_symbol("brk-b") == "BRK.B"
    assert subjects.sec_symbol("CEO") is None
    assert subjects.sec_symbol("ABCDE") is None
    assert subjects.sec_symbol("not a ticker!") is None
    assert subjects.sec_symbol(None) is None


def test_the_ticker_list_is_cached_for_a_day_and_a_failed_fetch_keeps_the_old_one(monkeypatch):
    calls = []
    clock = {"now": NOW}
    monkeypatch.setattr(subjects, "_now", lambda: clock["now"])

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise SecFilingsError("down")
        return TICKERS
    monkeypatch.setattr(subjects, "_fetch_ticker_list", fetch)
    assert subjects.sec_symbol("XYZ") == "XYZ"
    assert subjects.sec_symbol("XYZ") == "XYZ" and len(calls) == 1
    clock["now"] = NOW + timedelta(hours=25)
    assert subjects.sec_symbol("XYZ") == "XYZ"       # refetch failed: the previous list stays
    assert len(calls) == 2


def test_with_no_list_at_all_nothing_is_known(monkeypatch):
    def down():
        raise SecFilingsError("down")
    monkeypatch.setattr(subjects, "_fetch_ticker_list", down)
    assert subjects.sec_symbol("XYZ") is None


# --- asking -----------------------------------------------------------------------------------------------------

def test_an_unknown_word_makes_no_row_and_no_build():
    assert subjects.note_asked("CEO") == "unknown"
    assert subjects.note_asked("ABCDE") == "unknown"
    with SessionLocal() as db:
        assert db.scalars(select(ArchiveSubject)).all() == []


def test_a_new_company_is_recorded_and_queued_and_the_state_follows_the_build():
    assert subjects.note_asked("xyz") == "queued"
    r = row("XYZ")
    assert (r.build_status, r.asked_at, r.first_seen_at, r.held, r.queued) == ("queued", NOW, NOW, False, False)
    assert subjects.note_asked("XYZ") == "queued"           # a second mention does not queue twice
    for status, state in (("building", "building"), ("ok", "ok")):
        with SessionLocal() as db:
            db.get(ArchiveSubject, "XYZ").build_status = status
            db.commit()
        assert subjects.note_asked("XYZ") == state


def test_a_company_we_already_hold_filings_for_triggers_no_fetch():
    symbol = "ZZQA"
    with SessionLocal() as db:
        db.add(SecFilingInventory(symbol=symbol, cik="0000000001", accession_number="0000000001-26-000001", form="10-K", filed_at=NOW.date(),
                                  accepted_at="2026-11-01T00:00:00Z", primary_document="a.htm", source_url="https://www.sec.gov/x", source="sec-edgar",
                                  review_status="pending_review", content_status="fetched", observed_at=NOW, related_attachment_status="not_applicable"))
        db.commit()
    try:
        TICKERS["900"] = {"ticker": symbol, "cik_str": 1, "title": symbol}
        assert subjects.note_asked(symbol) == "ok"
        assert row(symbol).build_status == "ok"
    finally:
        TICKERS.pop("900")
        with SessionLocal() as db:
            db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == symbol))
            db.commit()


def test_a_burst_of_new_tickers_queues_at_most_twenty_the_rest_are_limited():
    states = [subjects.note_asked(f"Q{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:25]]
    assert states.count("queued") == 20 and states.count("limited") == 5
    assert states[:20] == ["queued"] * 20
    with SessionLocal() as db:
        assert len(db.scalars(select(ArchiveSubject).where(ArchiveSubject.build_status == "queued")).all()) == 20
    assert row("QY").build_status == "never"                 # a limited ask is recorded, not built


def test_thirty_builds_in_an_hour_is_the_ceiling_across_messages():
    for i in range(30):
        put(f"H{i:02d}", build_status="ok", build_started_at=NOW - timedelta(minutes=10 + i), build_finished_at=NOW - timedelta(minutes=9 + i))
    assert subjects.note_asked("XYZ") == "limited"
    with SessionLocal() as db:                                # builds that started over an hour ago no longer count
        for r in db.scalars(select(ArchiveSubject).where(ArchiveSubject.symbol.like("H%"))):
            r.build_started_at = NOW - timedelta(hours=2)
        db.commit()
    assert subjects.note_asked("XYZ") == "queued"


def test_no_rebuild_within_six_hours_of_a_success_or_one_hour_of_a_failure():
    put("XYZ", build_status="ok", build_started_at=NOW - timedelta(hours=7), build_finished_at=NOW - timedelta(hours=7))
    assert subjects.note_asked("XYZ") == "ok"                 # ok stays ok, and is not queued again
    assert row("XYZ").build_status == "ok"
    put("ABCD", build_status="failed", build_error="http_403", build_started_at=NOW - timedelta(minutes=50), build_finished_at=NOW - timedelta(minutes=45))
    assert subjects.note_asked("ABCD") == "failed:http_403"
    assert row("ABCD").build_status == "failed"
    with SessionLocal() as db:
        db.get(ArchiveSubject, "ABCD").build_finished_at = NOW - timedelta(minutes=70)
        db.commit()
    assert subjects.note_asked("ABCD") == "queued"            # an hour on, a new mention tries again


def test_enqueue_build_queues_and_reports(monkeypatch):
    assert asyncio.run(subjects.enqueue_build("XYZ")) is True
    assert row("XYZ").build_status == "queued"
    assert asyncio.run(subjects.enqueue_build("XYZ")) is False   # already waiting
    assert asyncio.run(subjects.enqueue_build("CEO")) is False   # SEC does not know it


# --- the build --------------------------------------------------------------------------------------------------

def inventory(symbol, forms):
    """Rows as a scan would leave them: newest first by position in ``forms``."""
    rows = []
    for i, form in enumerate(forms):
        rows.append(SecFilingInventory(symbol=symbol, cik="0000000002", accession_number=f"0000000002-26-{i:06d}", form=form, filed_at=(NOW - timedelta(days=10 * i)).date(),
                                       accepted_at="2026-11-01T00:00:00Z", primary_document=f"d{i}.htm", source_url="https://www.sec.gov/x", source="sec-edgar",
                                       review_status="pending_review", content_status="not_fetched", observed_at=NOW,
                                       related_attachment_status="not_checked" if form == "8-K" else "not_applicable"))
    return rows


@pytest.fixture
def fake(monkeypatch):
    log = {"steps": [], "fetched": [], "refreshed": [], "refresh_flags": []}
    stored = []

    def scan(*, symbol, db, provider=None, observed_at=None):
        log["steps"].append("scan")
        rows = inventory(symbol, ["8-K", "8-K", "10-Q", "8-K", "10-K", "10-Q", "8-K", "10-Q", "10-Q", "8-K", "10-K"])
        db.add_all(rows)
        db.commit()
        stored.extend(r.accession_number for r in rows)
        return rows, len(rows), 0

    def fetch(*, symbol, accession_number, db, provider=None, refresh_facts=True, **kw):
        log["steps"].append("fetch")
        log["fetched"].append(accession_number)
        log["refresh_flags"].append(refresh_facts)
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_status = "fetched"
        db.commit()
        return filing, False

    def refresh(symbol, **kw):
        log["steps"].append("refresh")
        log["refreshed"].append(symbol)
        return {"symbol": symbol, "facts": 3}

    monkeypatch.setattr(subjects, "scan_sec_filings", scan)
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)
    monkeypatch.setattr(subjects, "_refresh_facts", refresh)
    monkeypatch.setattr(subjects, "_provider", lambda: object())
    yield log
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.cik == "0000000002"))
        db.commit()


def test_a_build_scans_then_fetches_the_filings_that_matter_then_refreshes_once(fake):
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert fake["steps"][0] == "scan" and fake["steps"][-1] == "refresh" and fake["steps"].count("refresh") == 1
    assert set(fake["refresh_flags"]) == {False}              # the per-filing facts hook is off: one refresh at the end
    # newest annual, newest three quarterlies, newest four 8-Ks; annual first, then quarterlies, then 8-Ks
    forms = {}
    with SessionLocal() as db:
        for r in db.scalars(select(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO")):
            forms[r.accession_number] = r.form
    assert [forms[a] for a in fake["fetched"]] == ["10-K"] + ["10-Q"] * 3 + ["8-K"] * 4
    assert fake["fetched"][0] == "0000000002-26-000004"       # the newest 10-K, not the older one
    assert out["status"] == "ok" and out["filings_added"] == 11 and out["fetched"] == 8
    r = row("NEWCO")
    assert (r.build_status, r.build_error, r.filings_added, r.build_finished_at) == ("ok", None, 11, NOW)
    assert r.build_started_at == NOW
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_a_failed_scan_is_marked_failed_with_a_short_reason_and_never_raises(monkeypatch):
    def scan(**kw):
        raise SecFilingsError("SEC request failed; no filing data was saved") from HTTPError("u", 403, "Forbidden", {}, None)
    monkeypatch.setattr(subjects, "scan_sec_filings", scan)
    monkeypatch.setattr(subjects, "_provider", lambda: object())
    subjects.note_asked("XYZ")
    out = subjects.build("XYZ")
    assert out["status"] == "failed"
    r = row("XYZ")
    assert (r.build_status, r.build_error) == ("failed", "http_403")
    assert subjects.note_asked("XYZ") == "failed:http_403"


def test_a_timeout_is_named_and_a_surprise_error_is_contained(monkeypatch):
    monkeypatch.setattr(subjects, "_provider", lambda: object())
    def surprise(**kw):
        raise RuntimeError("boom " * 50)
    monkeypatch.setattr(subjects, "scan_sec_filings", surprise)
    subjects.note_asked("XYZ")
    assert subjects.build("XYZ")["status"] == "failed"
    assert row("XYZ").build_error == "error" and len(row("XYZ").build_error) <= 64

    def timing_out(**kw):
        raise SecFilingsError("SEC request failed; no filing data was saved") from TimeoutError()
    monkeypatch.setattr(subjects, "scan_sec_filings", timing_out)
    subjects.note_asked("ABCD")
    subjects.build("ABCD")
    assert row("ABCD").build_error == "timeout"


def test_sec_going_away_mid_build_keeps_the_rows_already_stored_and_marks_failed(fake, monkeypatch):
    def fetch(*, symbol, accession_number, db, **kw):
        fake["fetched"].append(accession_number)
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_status = "fetched" if len(fake["fetched"]) <= 2 else "unavailable"
        filing.content_error = "SEC request failed; no filing data was saved"
        db.commit()
        return filing, False
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    r = row("NEWCO")
    assert (out["status"], r.build_status, r.build_error) == ("failed", "failed", "sec_unavailable")
    assert len(fake["fetched"]) == 4                          # stopped after two in a row failed
    with SessionLocal() as db:
        stored = db.scalars(select(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO")).all()
        assert len(stored) == 11 and sum(f.content_status == "fetched" for f in stored) == 2
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_the_five_minute_wall_clock_stops_a_build(fake, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(subjects, "_monotonic", lambda: clock["t"])
    original = subjects.fetch_inventory_content

    def slow(**kw):
        clock["t"] += 120.0
        return original(**kw)
    monkeypatch.setattr(subjects, "fetch_inventory_content", slow)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert (out["status"], row("NEWCO").build_error) == ("failed", "timeout")
    assert len(fake["fetched"]) == 3
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_a_whole_build_against_a_faked_sec_stores_filings_and_never_touches_the_network(monkeypatch):
    opener, _ = _responses()
    provider = SecEdgarProvider(user_agent="Market Evidence Agent test@example.com", opener=opener, sleeper=lambda _: None, clock=lambda: 0.0)
    monkeypatch.setattr(subjects, "_provider", lambda: provider)
    monkeypatch.setattr(subjects, "_refresh_facts", lambda symbol: {"facts": 0})
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "AAPL"))
        db.commit()
    subjects.note_asked("AAPL")
    try:
        out = subjects.build("AAPL")
        assert out["status"] == "ok" and out["filings_added"] == 3 and out["fetched"] == 3
        assert all(url.startswith(("https://www.sec.gov", "https://data.sec.gov")) for url in opener.urls)
    finally:
        with SessionLocal() as db:
            db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "AAPL"))
            db.commit()


# --- the worker -------------------------------------------------------------------------------------------------

def test_the_worker_takes_the_queue_one_at_a_time_oldest_ask_first_and_stops_at_the_hourly_cap(monkeypatch):
    built = []
    monkeypatch.setattr(subjects, "build", lambda symbol, **kw: built.append(symbol) or {"status": "ok"})
    put("QA", build_status="queued", asked_at=NOW - timedelta(minutes=3))
    put("QB", build_status="queued", asked_at=NOW - timedelta(minutes=5))
    assert subjects.run_pending() == 2
    assert built == ["QB", "QA"]
    for i in range(30):
        put(f"H{i:02d}", build_status="ok", build_started_at=NOW - timedelta(minutes=20), build_finished_at=NOW - timedelta(minutes=19))
    put("QC", build_status="queued", asked_at=NOW)
    assert subjects.run_pending() == 0 and built == ["QB", "QA"]   # the cap holds: QC waits


def test_a_build_left_building_by_a_restart_is_put_back_in_the_queue():
    put("XYZ", build_status="building", build_started_at=NOW - timedelta(minutes=30))
    assert subjects.recover_interrupted() == 1
    assert row("XYZ").build_status == "queued"


def test_the_worker_starts_with_the_api_builds_and_stops(monkeypatch):
    monkeypatch.setenv("FINBOT_ARCHIVE_BUILDS", "on")
    built = []
    monkeypatch.setattr(subjects, "build", lambda symbol, **kw: built.append(symbol) or {"status": "ok"})

    async def scenario():
        subjects.start()
        assert subjects._STATE["task"] is not None and not subjects._STATE["task"].done()
        assert await subjects.enqueue_build("XYZ") is True
        for _ in range(100):
            if built:
                break
            await asyncio.sleep(0.05)
        await subjects.stop()
        assert subjects._STATE["task"] is None
    asyncio.run(scenario())
    assert built == ["XYZ"]


def test_the_worker_is_off_when_the_flag_says_so(monkeypatch):
    monkeypatch.setenv("FINBOT_ARCHIVE_BUILDS", "off")

    async def scenario():
        subjects.start()
        assert subjects._STATE["task"] is None
        await subjects.stop()
    asyncio.run(scenario())


# --- the owner's list and retirement ----------------------------------------------------------------------------

@pytest.fixture
def owner():
    owner_hash = uuid.uuid4().hex + uuid.uuid4().hex
    yield owner_hash
    with SessionLocal() as db:
        db.execute(delete(PortfolioTransaction).where(PortfolioTransaction.owner_hash == owner_hash))
        db.execute(delete(AgentResearchQueue).where(AgentResearchQueue.owner_hash == owner_hash))
        db.commit()


def buy(owner_hash, symbol, kind="buy", quantity=10, on="2026-10-01"):
    from datetime import date
    with SessionLocal() as db:
        db.add(PortfolioTransaction(owner_hash=owner_hash, symbol=symbol, kind=kind, quantity=quantity, price=10, fee=0, amount=quantity * 10, ratio=0, occurred_on=date.fromisoformat(on), note=""))
        db.commit()


def test_sync_sets_held_and_queued_from_holdings_and_the_research_queue(owner):
    buy(owner, "XYZ")
    buy(owner, "ABCD")
    buy(owner, "ABCD", kind="sell", quantity=10, on="2026-10-02")      # sold out: not held
    with SessionLocal() as db:
        db.add(AgentResearchQueue(owner_hash=owner, symbols=["newco", "xyz", "CEO"]))
        db.commit()
    out = subjects.sync_owner_subjects(owner)
    assert (row("XYZ").held, row("XYZ").queued) == (True, True)
    assert (row("NEWCO").held, row("NEWCO").queued) == (False, True)
    assert row("ABCD") is None or (row("ABCD").held is False)
    assert row("CEO") is None                                          # SEC does not list it
    assert out["held"] == 1 and out["queued"] == 2


def test_selling_a_holding_or_dropping_a_queue_symbol_updates_the_reason_but_does_not_retire_it_at_once(owner):
    buy(owner, "XYZ")
    with SessionLocal() as db:
        db.add(AgentResearchQueue(owner_hash=owner, symbols=["NEWCO"]))
        db.commit()
    subjects.sync_owner_subjects(owner)
    buy(owner, "XYZ", kind="sell", on="2026-10-05")
    with SessionLocal() as db:
        db.get(AgentResearchQueue, owner).symbols = []
        db.commit()
    out = subjects.sync_owner_subjects(owner)
    assert (row("XYZ").held, row("NEWCO").queued) == (False, False)
    assert row("XYZ").retired_at is None and row("NEWCO").retired_at is None and out["retired"] == 0


def test_a_subject_nobody_holds_queues_or_asked_about_for_ninety_days_is_retired_and_its_filings_stay(owner):
    put("XYZ", last_active_at=NOW - timedelta(days=91), asked_at=NOW - timedelta(days=91), build_status="ok")
    put("ABCD", last_active_at=NOW - timedelta(days=89), asked_at=NOW - timedelta(days=89), build_status="ok")
    put("NEWCO", held=False, last_active_at=NOW - timedelta(days=200), build_status="ok")
    buy(owner, "NEWCO")                                                  # still held: the sync keeps it alive
    out = subjects.sync_owner_subjects(owner)
    assert row("XYZ").retired_at == NOW and out["retired"] == 1
    assert row("ABCD").retired_at is None and row("NEWCO").retired_at is None
    assert row("NEWCO").held is True and row("NEWCO").last_active_at == NOW
    # a retired subject that is asked about again is a subject again
    assert subjects.note_asked("XYZ") in {"ok", "queued"}
    assert row("XYZ").retired_at is None and row("XYZ").asked_at == NOW


# --- the monitor set --------------------------------------------------------------------------------------------

def test_active_symbols_puts_subjects_after_the_defaults_held_then_queue_then_latest_asked(monkeypatch):
    from app.forecast_jobs import DEFAULT_STOCKS
    put("QA", asked_at=NOW - timedelta(days=3))
    put("QB", asked_at=NOW - timedelta(days=1))
    put("QC", queued=True)
    put("QD", held=True)
    put("QE", held=True, retired_at=NOW)
    put("AAPL")                                                         # a default: listed once, in the defaults
    with SessionLocal() as db:
        symbols = active_symbols(db)
    defaults = sorted(DEFAULT_STOCKS)
    assert list(symbols[:len(defaults)]) == defaults
    tail = list(symbols[len(defaults):])
    assert tail[:4] == ["QD", "QC", "QB", "QA"] and "QE" not in tail
    assert len(set(symbols)) == len(symbols)


def test_the_monitor_cap_is_configurable_and_defaults_to_eighty(monkeypatch):
    from app.forecast_jobs import DEFAULT_STOCKS
    for i in range(100):
        put(f"S{i:03d}", asked_at=NOW - timedelta(minutes=i))
    monkeypatch.delenv("FINBOT_ACTIVE_SYMBOLS_MAX", raising=False)
    with SessionLocal() as db:
        assert len(active_symbols(db)) == 80
    monkeypatch.setenv("FINBOT_ACTIVE_SYMBOLS_MAX", "20")
    with SessionLocal() as db:
        got = active_symbols(db)
    assert len(got) == 20 and got[len(DEFAULT_STOCKS)] == "S000"


def test_the_six_hour_sweep_syncs_the_owner_and_survives_a_sync_failure(monkeypatch):
    from app import background, company_facts, sentinel_bridge
    seen = []
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: "o" * 64)
    monkeypatch.setattr(subjects, "sync_owner_subjects", lambda owner: seen.append(owner) or {"held": 0})
    monkeypatch.setattr(company_facts, "refresh_all", lambda: {"symbols": 0, "facts": 0, "ratios": 0, "check_failures": [], "errors": {}})
    background.run_company_facts()
    assert seen == ["o" * 64]
    monkeypatch.setattr(subjects, "sync_owner_subjects", lambda owner: (_ for _ in ()).throw(RuntimeError("db down")))
    background.run_company_facts()           # no raise: the facts sweep still ran
