"""Archive subjects (2c task 1): the list of companies the archive keeps, the bounded build worker, the monitor set.  SEC is faked; no network."""
import asyncio
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app import archive_subjects as subjects
from app.active_symbols import active_symbols
from app.agent_chat_models import AgentResearchQueue, PortfolioTransaction
from app.database import Base, SessionLocal, engine
from app.models import ArchiveSubject, CompanyFact, SecFilingInventory
from app.sec_filings import SEC_SUBMISSIONS_URL, SEC_TICKERS_URL, SecEdgarProvider, SecFilingsError, scan_sec_filings
from tests.test_sec_filings import FakeSecOpener, _responses

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
TICKERS = {str(i): {"ticker": t, "cik_str": 1000 + i, "title": t} for i, t in enumerate(["AAPL", "XYZ", "ABCD", "BRK-B", "NEWCO"] + [f"Q{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"])}


@pytest.fixture(autouse=True)
def world(disposable_database, monkeypatch):
    Base.metadata.create_all(engine)
    monkeypatch.setattr(subjects, "_fetch_ticker_list", lambda: TICKERS)
    monkeypatch.setattr(subjects, "_now", lambda: NOW)
    subjects._TICKERS.update(at=None, symbols=None, tried_at=None)
    subjects._STOPPING.clear()
    assert subjects.refresh_ticker_list() is True           # the list is read in the background; here, once, by hand
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


def test_the_ticker_list_is_fetched_at_most_once_a_day_and_a_failure_is_not_retried_for_an_hour(monkeypatch):
    calls = []
    clock = {"now": NOW}
    monkeypatch.setattr(subjects, "_now", lambda: clock["now"])

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise SecFilingsError("down")
        return TICKERS
    monkeypatch.setattr(subjects, "_fetch_ticker_list", fetch)
    subjects._TICKERS.update(at=None, symbols=None, tried_at=None)
    assert subjects.refresh_ticker_list() is True and subjects.sec_symbol("XYZ") == "XYZ"
    assert subjects.refresh_ticker_list() is False and len(calls) == 1      # fresh: no fetch
    clock["now"] = NOW + timedelta(hours=25)
    assert subjects.refresh_ticker_list() is False and len(calls) == 2      # stale: tried, failed
    assert subjects.sec_symbol("XYZ") == "XYZ"                              # the previous list stays
    clock["now"] += timedelta(minutes=59)
    assert subjects.refresh_ticker_list() is False and len(calls) == 2      # not retried within the hour
    clock["now"] += timedelta(minutes=2)
    subjects.refresh_ticker_list()
    assert len(calls) == 3


def test_sec_symbol_never_touches_the_network_and_knows_nothing_before_the_first_list(monkeypatch):
    subjects._TICKERS.update(at=None, symbols=None, tried_at=None)
    calls = []
    monkeypatch.setattr(subjects, "_fetch_ticker_list", lambda: calls.append(1) or TICKERS)
    assert subjects.sec_symbol("XYZ") is None and subjects.note_asked("XYZ") == "unknown"
    assert calls == []
    subjects.refresh_ticker_list()
    assert subjects.sec_symbol("XYZ") == "XYZ" and len(calls) == 1


def test_the_list_is_not_fetched_under_the_lock_callers_use(monkeypatch):
    seen = []

    def fetch():
        seen.append(subjects._TICKERS_LOCK.acquire(blocking=False))   # a held lock would make this False
        if seen[-1]:
            subjects._TICKERS_LOCK.release()
        return TICKERS
    monkeypatch.setattr(subjects, "_fetch_ticker_list", fetch)
    subjects._TICKERS.update(at=None, symbols=None, tried_at=None)
    subjects.refresh_ticker_list()
    assert seen == [True]


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


def _archive(symbol, *, figures=True, status="fetched", facts=True, form="10-K"):
    with SessionLocal() as db:
        db.add(SecFilingInventory(symbol=symbol, cik="0000000001", accession_number=f"0000000001-26-{symbol[-3:]:0>6}", form=form, filed_at=NOW.date(),
                                  accepted_at="2026-11-01T00:00:00Z", primary_document="a.htm", source_url="https://www.sec.gov/x", source="sec-edgar",
                                  review_status="pending_review", content_status=status, observed_at=NOW, related_attachment_status="not_applicable",
                                  content_financials=[{"metric": "revenue"}] if figures else None))
        if facts:
            db.add(CompanyFact(id=uuid.uuid4(), symbol=symbol, metric="revenue", period_end=NOW.date(), span="quarter", value=1, kind="stated",
                               basis="x", status="ok", built_at=NOW))
        db.commit()


def _clean(symbol):
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == symbol))
        db.execute(delete(CompanyFact).where(CompanyFact.symbol == symbol))
        db.commit()


def test_a_company_with_a_real_archive_triggers_no_fetch_but_metadata_alone_is_not_an_archive():
    TICKERS["900"] = {"ticker": "ZZQA", "cik_str": 1, "title": "x"}
    TICKERS["901"] = {"ticker": "ZZQB", "cik_str": 2, "title": "x"}
    TICKERS["902"] = {"ticker": "ZZQC", "cik_str": 3, "title": "x"}
    subjects._TICKERS.update(at=None, tried_at=None)
    subjects.refresh_ticker_list()
    _archive("ZZQA")
    _archive("ZZQB", status="not_fetched", figures=False, facts=False)     # what the hourly monitor leaves behind
    _archive("ZZQC", facts=False)                                          # figures but no ok quarter of revenue yet
    try:
        assert subjects.note_asked("ZZQA") == "ok" and row("ZZQA").build_status == "ok"
        assert subjects.note_asked("ZZQB") == "queued"
        assert subjects.note_asked("ZZQC") == "queued"
    finally:
        for key in ("900", "901", "902"):
            TICKERS.pop(key)
        for symbol in ("ZZQA", "ZZQB", "ZZQC"):
            _clean(symbol)
        subjects._TICKERS.update(at=None, tried_at=None)
        subjects.refresh_ticker_list()


def test_asking_again_does_not_send_a_waiting_build_to_the_back_of_the_line(monkeypatch):
    subjects.note_asked("XYZ")
    first = row("XYZ").asked_at
    monkeypatch.setattr(subjects, "_now", lambda: NOW + timedelta(minutes=5))
    assert subjects.note_asked("XYZ") == "queued"
    assert row("XYZ").asked_at == first


def test_two_writers_creating_the_same_subject_at_once_do_not_fail_the_ask(monkeypatch):
    real = subjects._ask_once
    calls = []

    def flaky(symbol, now):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return real(symbol, now)
    monkeypatch.setattr(subjects, "_ask_once", flaky)
    assert subjects.note_asked("XYZ") == "queued" and len(calls) == 2


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


def test_a_finished_build_is_not_rebuilt_by_a_mention_and_a_failure_or_partial_not_within_an_hour():
    put("XYZ", build_status="ok", build_started_at=NOW - timedelta(hours=7), build_finished_at=NOW - timedelta(hours=7))
    assert subjects.note_asked("XYZ") == "ok"                 # ok stays ok, and is not queued again
    put("NEWCO", build_status="partial", build_error="xbrl_429", filings_added=4, build_finished_at=NOW - timedelta(minutes=10))
    assert subjects.note_asked("NEWCO") == "partial:xbrl_429"
    assert row("XYZ").build_status == "ok"
    put("ABCD", build_status="failed", build_error="http_403", build_started_at=NOW - timedelta(minutes=50), build_finished_at=NOW - timedelta(minutes=45))
    assert subjects.note_asked("ABCD") == "failed:http_403"
    assert row("ABCD").build_status == "failed"
    with SessionLocal() as db:
        db.get(ArchiveSubject, "ABCD").build_finished_at = NOW - timedelta(minutes=70)
        db.commit()
    assert subjects.note_asked("ABCD") == "queued"            # an hour on, a new mention tries again
    assert row("ABCD").build_error is None and row("ABCD").filings_added == 0


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
        if filing.form in ("10-K", "10-Q"):
            filing.content_financials = [{"metric": "revenue"}]
        if filing.form == "8-K" and int(accession_number[-1]) % 2 == 0:
            filing.content_kind = "exhibit_99_1"                     # every second 8-K is an earnings release
        db.commit()
        return filing, False

    def refresh(symbol, **kw):
        log["steps"].append("refresh")
        log["refreshed"].append(symbol)
        return {"symbol": symbol, "facts": 3}

    monkeypatch.setattr(subjects, "scan_sec_filings", scan)
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)
    monkeypatch.setattr(subjects, "_refresh_facts", refresh)
    monkeypatch.setattr(subjects, "_revenue_quarter_ok", lambda symbol: True)
    monkeypatch.setattr(subjects, "_provider", lambda: object())
    yield log
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.cik == "0000000002"))
        db.commit()


def test_a_build_scans_then_reads_the_annual_the_quarterlies_and_the_8ks_of_fifteen_months_then_refreshes_once(fake):
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert fake["steps"][0] == "scan" and fake["steps"][-1] == "refresh" and fake["steps"].count("refresh") == 1
    assert set(fake["refresh_flags"]) == {False}              # the per-filing facts hook is off: one refresh at the end
    forms = {}
    with SessionLocal() as db:
        for r in db.scalars(select(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO")):
            forms[r.accession_number] = r.form
    # the newest 10-K, the four 10-Qs and the five 8-Ks of the window (all eleven rows are within fifteen months), in that order
    assert [forms[a] for a in fake["fetched"]] == ["10-K"] + ["10-Q"] * 4 + ["8-K"] * 5
    assert fake["fetched"][0] == "0000000002-26-000004"       # the newest 10-K, not the older one
    assert (out["status"], out["error"], out["filings_added"], out["fetched"], out["releases"], out["with_figures"]) == ("ok", None, 11, 10, 2, 5)
    r = row("NEWCO")
    assert (r.build_status, r.build_error, r.filings_added, r.build_finished_at) == ("ok", None, 11, NOW)
    assert r.build_started_at == NOW
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_the_plan_takes_the_latest_annual_and_only_what_is_inside_fifteen_months():
    rows = []
    forms = [("10-K", 5), ("10-K", 370), ("10-Q", 20), ("10-Q", 110), ("10-Q", 200), ("10-Q", 290), ("10-Q", 380), ("10-Q", 440), ("10-Q", 470),
             ("8-K", 3), ("8-K", 100), ("8-K", 460), ("8-K", 600), ("DEF 14A", 10)]
    for i, (form, age) in enumerate(forms):
        r = inventory("PLAN", [form])[0]
        r.accession_number, r.filed_at, r.cik = f"0000000003-26-{i:06d}", (NOW - timedelta(days=age)).date(), "0000000003"
        rows.append(r)
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()
        try:
            annual, quarterly, eight_k = subjects._plan(db, "PLAN", NOW.date())
        finally:
            db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "PLAN"))
            db.commit()
    assert annual == ["0000000003-26-000000"]
    assert quarterly == [f"0000000003-26-{i:06d}" for i in (2, 3, 4, 5, 6, 7)]       # 440 days is inside 457; 470 is outside; six at most
    assert eight_k == ["0000000003-26-000009", "0000000003-26-000010"]               # the 460- and 600-day-old 8-Ks are outside the window


def test_a_build_with_filings_but_no_figures_is_partial_and_names_what_is_missing(fake, monkeypatch):
    def fetch(*, symbol, accession_number, db, xbrl_errors=None, **kw):
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_status = "fetched"
        db.commit()
        return filing, False
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert (out["status"], out["error"]) == ("partial", "no_figures")
    assert (row("NEWCO").build_status, row("NEWCO").build_error) == ("partial", "no_figures")
    assert subjects.note_asked("NEWCO") == "partial:no_figures"
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_an_xbrl_rate_limit_is_reported_by_the_build_not_swallowed(fake, monkeypatch):
    def fetch(*, symbol, accession_number, db, xbrl_errors=None, **kw):
        xbrl_errors.append(SecFilingsError("SEC request failed") if False else _with_cause(SecFilingsError("SEC request failed"), HTTPError("u", 429, "Too Many", {}, None)))
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_status = "fetched"
        db.commit()
        return filing, False
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert (out["status"], out["error"]) == ("partial", "xbrl_429")
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def _with_cause(exc, cause):
    exc.__cause__ = cause
    return exc


def test_figures_ok_but_no_ok_quarter_of_revenue_is_partial_no_facts(fake, monkeypatch):
    monkeypatch.setattr(subjects, "_revenue_quarter_ok", lambda symbol: False)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert (out["status"], out["error"]) == ("partial", "no_facts")
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_a_filing_stored_without_figures_gets_its_figures_asked_again_not_its_body(fake, monkeypatch):
    asked = []

    def fetch(*, symbol, accession_number, db, xbrl_errors=None, **kw):
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_status = "fetched"
        db.commit()
        return filing, True                                    # a cache hit: body stored earlier, no figures
    monkeypatch.setattr(subjects, "fetch_inventory_content", fetch)

    def again(*, symbol, accession_number, db, provider, xbrl_errors=None):
        asked.append(accession_number)
        filing = db.query(SecFilingInventory).filter_by(symbol=symbol, accession_number=accession_number).one()
        filing.content_financials = [{"metric": "revenue"}]
        db.commit()
        return True
    monkeypatch.setattr(subjects, "store_inventory_figures", again)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert out["status"] == "ok" and len(asked) == 5          # the 10-K and four 10-Qs
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
    assert (out["status"], r.build_status, r.build_error) == ("partial", "partial", "sec_unavailable")
    assert len(fake["fetched"]) == 4                          # stopped after two in a row failed
    with SessionLocal() as db:
        stored = db.scalars(select(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO")).all()
        assert len(stored) == 11 and sum(f.content_status == "fetched" for f in stored) == 2
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


def test_the_five_minute_wall_clock_stops_a_build_at_the_next_filing_and_ends_partial(fake, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(subjects, "_monotonic", lambda: clock["t"])
    original = subjects.fetch_inventory_content

    def slow(**kw):
        clock["t"] += 120.0
        return original(**kw)
    monkeypatch.setattr(subjects, "fetch_inventory_content", slow)
    subjects.note_asked("NEWCO")
    out = subjects.build("NEWCO")
    assert (out["status"], row("NEWCO").build_error) == ("partial", "deadline")
    assert len(fake["fetched"]) == 3
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == "NEWCO"))
        db.commit()


class SlowOpener(FakeSecOpener):
    """Every request takes ``step`` seconds of the build's clock; XBRL concept requests answer with a rate limit when ``limit`` is set."""

    def __init__(self, responses, clock, step=0.0, limit=False):
        super().__init__(responses)
        self.clock, self.step, self.limit = clock, step, limit

    def __call__(self, request, *, timeout):
        self.clock["t"] += self.step
        if "companyconcept" in request.full_url:
            self.urls.append(request.full_url)
            if self.limit:
                raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)
        return super().__call__(request, timeout=timeout)


def real_provider(opener):
    return SecEdgarProvider(user_agent="Market Evidence Agent test@example.com", opener=opener, sleeper=lambda _: None, clock=lambda: 0.0)


def test_the_deadline_is_checked_at_every_sec_request_even_inside_one_filing(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(subjects, "_monotonic", lambda: clock["t"])
    opener, _ = _responses()
    opener = SlowOpener(opener.responses, clock, step=100.0)
    monkeypatch.setattr(subjects, "_provider", lambda: real_provider(opener))
    monkeypatch.setattr(subjects, "_refresh_facts", lambda symbol: {"facts": 0})
    _clean_inventory("AAPL")
    subjects.note_asked("AAPL")
    try:
        out = subjects.build("AAPL")
        assert (out["status"], out["error"]) == ("partial", "deadline")
        assert len(opener.urls) <= 4                          # 100 s a request: a fifth would start after 400 s
    finally:
        _clean_inventory("AAPL")


def _clean_inventory(symbol):
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol == symbol))
        db.commit()


def test_a_stop_request_ends_a_running_build_at_its_next_request(monkeypatch):
    opener, _ = _responses()
    opener = SlowOpener(opener.responses, {"t": 0.0})
    calls = []
    original = opener.__call__

    def stopping(request, *, timeout):
        calls.append(request.full_url)
        if len(calls) == 2:
            subjects._STOPPING.set()
        return original(request, timeout=timeout)
    monkeypatch.setattr(subjects, "_provider", lambda: real_provider(type("O", (), {"__call__": lambda self, request, *, timeout: stopping(request, timeout=timeout)})()))
    _clean_inventory("AAPL")
    subjects.note_asked("AAPL")
    try:
        out = subjects.build("AAPL")
        assert (out["status"], out["error"]) == ("partial", "stopping")
        assert len(calls) == 2
    finally:
        _clean_inventory("AAPL")


def _revenue_concept(opener):
    from app.sec_filings import SEC_ARCHIVES_URL  # noqa: F401
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json"
    entry = {"form": "10-Q", "filed": "2026-08-01", "start": "2026-04-01", "end": "2026-06-30", "val": 94_000_000_000, "fp": "Q3", "fy": 2026}
    opener.responses[url] = json.dumps({"units": {"USD": [entry]}}).encode()


def test_a_whole_build_against_a_faked_sec_stores_filings_and_is_ok_only_with_figures_and_facts(monkeypatch):
    clock = {"t": 0.0}
    base, _ = _responses()
    opener = SlowOpener(base.responses, clock)
    # the concept answers for the 10-Q only; SlowOpener turns the unknown concepts into 404s
    url = "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax.json"
    entry = {"form": "10-Q", "filed": "2026-08-01", "start": "2026-04-01", "end": "2026-06-30", "val": 94_000_000_000, "fp": "Q3", "fy": 2026}
    opener.responses[url] = json.dumps({"units": {"USD": [entry]}}).encode()
    original = SlowOpener.__call__

    def call(self, request, *, timeout):
        if request.full_url == url:
            return FakeSecOpener.__call__(self, request, timeout=timeout)
        return original(self, request, timeout=timeout)
    monkeypatch.setattr(SlowOpener, "__call__", call)
    monkeypatch.setattr(subjects, "_provider", lambda: real_provider(opener))
    monkeypatch.setattr(subjects, "_refresh_facts", lambda symbol: {"facts": 1})
    monkeypatch.setattr(subjects, "_revenue_quarter_ok", lambda symbol: True)
    _clean_inventory("AAPL")
    subjects.note_asked("AAPL")
    try:
        out = subjects.build("AAPL")
        assert (out["status"], out["error"], out["filings_added"], out["fetched"], out["with_figures"]) == ("ok", None, 3, 3, 1)
        assert all(url.startswith(("https://www.sec.gov", "https://data.sec.gov")) for url in opener.urls)
    finally:
        _clean_inventory("AAPL")


def test_a_whole_build_whose_xbrl_requests_are_rate_limited_is_partial_xbrl_429(monkeypatch):
    base, _ = _responses()
    opener = SlowOpener(base.responses, {"t": 0.0}, limit=True)
    monkeypatch.setattr(subjects, "_provider", lambda: real_provider(opener))
    monkeypatch.setattr(subjects, "_refresh_facts", lambda symbol: {"facts": 0})
    _clean_inventory("AAPL")
    subjects.note_asked("AAPL")
    try:
        out = subjects.build("AAPL")
        assert (out["status"], out["error"], out["fetched"]) == ("partial", "xbrl_429", 3)
        assert subjects.note_asked("AAPL") == "partial:xbrl_429"
    finally:
        _clean_inventory("AAPL")


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


def test_stop_ends_the_running_build_thread_and_leaves_the_rest_of_the_queue_alone(monkeypatch):
    monkeypatch.setenv("FINBOT_ARCHIVE_BUILDS", "on")
    monkeypatch.setattr(subjects, "STOP_WAIT_SECONDS", 0.3)
    entered, release, built = threading.Event(), threading.Event(), []

    def slow_build(symbol, **kw):
        built.append(symbol)
        entered.set()
        release.wait(5)
        return {"status": "ok"}
    monkeypatch.setattr(subjects, "build", slow_build)
    put("QA", build_status="queued", asked_at=NOW - timedelta(minutes=5))
    put("QB", build_status="queued", asked_at=NOW - timedelta(minutes=4))

    async def scenario():
        subjects.start()
        assert entered.wait(0) or await asyncio.to_thread(entered.wait, 5)
        await subjects.stop()                                  # the thread is still inside its build: stop waits a bounded time, no more
        assert subjects._STOPPING.is_set() and not subjects._IDLE.is_set()
        subjects.start()                                       # one worker at a time: a draining thread counts
        assert subjects._STATE["task"] is None
        release.set()
        assert await asyncio.to_thread(subjects._IDLE.wait, 5)
    asyncio.run(scenario())
    assert built == ["QA"] and row("QB").build_status == "queued"
    subjects._STOPPING.clear()


def test_the_worker_follows_the_background_flag_when_the_builds_flag_is_unset(monkeypatch):
    monkeypatch.delenv("FINBOT_ARCHIVE_BUILDS")
    monkeypatch.setenv("BACKGROUND_LOOPS", "false")
    assert subjects.builds_enabled() is False
    monkeypatch.setenv("BACKGROUND_LOOPS", "true")
    assert subjects.builds_enabled() is True


def test_a_url_error_that_wraps_a_timeout_is_a_timeout():
    exc = SecFilingsError("SEC request failed")
    exc.__cause__ = URLError(TimeoutError("timed out"))
    assert subjects._reason(exc) == "timeout"


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


def test_a_subject_whose_archive_is_being_built_is_left_out_of_the_monitor_until_the_build_ends():
    put("QA", build_status="queued", asked_at=NOW)
    put("QB", build_status="building", asked_at=NOW)
    put("QC", build_status="partial", asked_at=NOW)
    put("QD", build_status="ok", asked_at=NOW)
    with SessionLocal() as db:
        symbols = active_symbols(db)
    assert "QA" not in symbols and "QB" not in symbols and "QC" in symbols and "QD" in symbols


def test_a_scan_that_meets_a_concurrent_insert_of_one_accession_skips_it_and_keeps_the_rest():
    from app.sec_filings import DiscoveredSecFiling
    import dataclasses
    fields = [f.name for f in dataclasses.fields(DiscoveredSecFiling)]
    base = dict(cik="0000000004", form="10-Q", filed_at=NOW.date(), accepted_at="2026-11-01T00:00:00Z", primary_document="a.htm",
                source_url="https://www.sec.gov/Archives/edgar/data/4/a.htm")
    filings = [DiscoveredSecFiling(**{k: v for k, v in {**base, "accession_number": f"0000000004-26-00000{i}"}.items() if k in fields}) for i in (1, 2)]
    other = inventory("OTHR", ["10-Q"])[0]                      # another writer already stored accession 1 (under the other path's symbol)
    other.cik, other.accession_number = "0000000004", "0000000004-26-000001"
    with SessionLocal() as db:
        db.add(other)
        db.commit()
    try:
        with SessionLocal() as db:
            rows, created, skipped = scan_sec_filings(symbol="MINE", db=db, provider=type("P", (), {"discover": lambda self, symbol: filings})())
        assert created == 1 and [r.accession_number for r in rows] == ["0000000004-26-000002"]
    finally:
        with SessionLocal() as db:
            db.execute(delete(SecFilingInventory).where(SecFilingInventory.cik == "0000000004"))
            db.commit()


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
