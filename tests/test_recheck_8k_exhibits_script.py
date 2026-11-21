from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.database import SessionLocal
from app.models import SecFilingInventory
from app.sec_filings import SecFilingContent, SecFilingsError, SecRelatedExhibit, create_sec_filing_inventory_table
from scripts import recheck_8k_exhibits as script


class FakeProvider:
    def __init__(self, found):
        self.found = found
        self.asked: list[str] = []

    def fetch_exhibit_99_1(self, filing):
        self.asked.append(filing.accession_number)
        outcome = self.found[filing.accession_number]
        if isinstance(outcome, Exception):
            raise outcome
        if not outcome:
            return None
        return SecRelatedExhibit(document_name="q3fy27pr.htm", source_url=filing.source_url.rsplit("/", 1)[0] + "/q3fy27pr.htm",
                                 content=SecFilingContent.from_text("Revenue was $44 billion."))

    def fetch_primary_document(self, filing):
        raise AssertionError("a recheck never refetches the cover page")


def _row(symbol, accession, *, status="not_found", form="8-K"):
    return SecFilingInventory(
        symbol=symbol, cik="0001045810", accession_number=accession, form=form, filed_at=date(2026, 11, 17),
        primary_document="a.htm", source_url=f"https://www.sec.gov/Archives/edgar/data/1045810/{accession.replace('-', '')}/a.htm",
        source="sec-edgar", review_status="pending_review", content_status="fetched", content_excerpt="cover", content_text="cover",
        content_kind="primary_document", content_source_url="x", content_document_name="a.htm",
        related_attachment_status=status, observed_at=datetime(2026, 11, 18, tzinfo=UTC),
    )


@pytest.fixture()
def rows():
    create_sec_filing_inventory_table()
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.add_all([
            _row("NVDA", "0001045810-26-000088"),
            _row("NVDA", "0001045810-26-000077", status="unavailable"),
            _row("NVDA", "0001045810-26-000066", status="fetched"),
            _row("NVDA", "0001045810-26-000055", form="10-Q"),
            _row("AAPL", "0001045810-26-000044"),
        ])
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.commit()


def _snapshot():
    with SessionLocal() as db:
        return sorted((r.accession_number, r.related_attachment_status, r.content_text) for r in db.query(SecFilingInventory))


def test_dry_run_lists_candidates_and_writes_nothing(rows):
    provider = FakeProvider({})
    lines: list[str] = []
    before = _snapshot()
    with SessionLocal() as db:
        stats = script.run(db, provider=provider, apply=False, out=lines.append)
    assert stats.candidates == 3 and stats.rechecked == 0
    assert provider.asked == [] and _snapshot() == before
    assert any("NVDA 0001045810-26-000088" in line for line in lines)
    assert not any("000066" in line or "000055" in line for line in lines)


def test_symbol_and_limit_narrow_the_selection(rows):
    with SessionLocal() as db:
        assert script.run(db, apply=False, symbol="nvda", out=lambda _: None).candidates == 2
        assert script.run(db, apply=False, symbol="NVDA", limit=1, out=lambda _: None).candidates == 1


def test_apply_counts_new_missing_and_failed_and_one_failure_does_not_stop_the_rest(rows):
    provider = FakeProvider({
        "0001045810-26-000088": True,
        "0001045810-26-000077": SecFilingsError("SEC request failed"),
        "0001045810-26-000044": False,
    })
    with SessionLocal() as db:
        stats = script.run(db, provider=provider, apply=True, out=lambda _: None)
    assert (stats.candidates, stats.rechecked, stats.newly_fetched, stats.still_missing, stats.errors) == (3, 3, 1, 1, 1)
    with SessionLocal() as db:
        done = db.query(SecFilingInventory).filter_by(accession_number="0001045810-26-000088").one()
        failed = db.query(SecFilingInventory).filter_by(accession_number="0001045810-26-000077").one()
    assert done.related_attachment_status == "fetched" and done.content_kind == "exhibit_99_1"
    assert done.content_text == "Revenue was $44 billion."
    assert failed.related_attachment_status == "unavailable" and failed.content_text == "cover"
