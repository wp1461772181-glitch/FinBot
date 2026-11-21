"""fetch_sec: a named accession is not vetoed by the turn's financial_only scope."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.agent_workflow import tools
from app.agent_workflow.sec_sources import prepare_filing
from app.database import SessionLocal
from app.models import SecFilingInventory
from app.sec_filings import DiscoveredSecFiling, SecEdgarProvider, create_sec_filing_inventory_table

ACCESSION = "0001045810-26-000088"
URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000088/nvda-20261117.htm"


@pytest.fixture()
def saved_8k():
    create_sec_filing_inventory_table()
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.add(SecFilingInventory(
            symbol="NVDA", cik="0001045810", accession_number=ACCESSION, form="8-K", filed_at=date(2026, 11, 17),
            primary_document="nvda-20261117.htm", source_url=URL, source="sec-edgar", review_status="pending_review",
            content_status="not_fetched", observed_at=datetime(2026, 11, 18, tzinfo=UTC)))
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.commit()


def _discovery(monkeypatch, rows):
    monkeypatch.setattr(SecEdgarProvider, "__init__", lambda *_: None)
    monkeypatch.setattr(SecEdgarProvider, "discover", lambda *_: rows)


def test_named_saved_8k_enters_confirmation_under_financial_only(saved_8k):
    args = {"symbol": "NVDA", "form": "8-K", "accession_number": ACCESSION}
    op = prepare_filing("fetch_sec", args, financial_only=True)
    assert op["discovery"]["form"] == "8-K" and op["arguments"]["accession_number"] == ACCESSION


def test_named_accession_found_only_in_the_official_listing_is_not_filtered_either(monkeypatch):
    create_sec_filing_inventory_table()
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.commit()
    _discovery(monkeypatch, [DiscoveredSecFiling("0001045810", ACCESSION, "8-K", date(2026, 11, 17), None, "nvda-20261117.htm", URL)])
    op = prepare_filing("fetch_sec", {"symbol": "NVDA", "form": None, "accession_number": ACCESSION}, financial_only=True)
    assert op["discovery"]["accession_number"] == ACCESSION


def test_switch_off_keeps_the_old_refusal(saved_8k, monkeypatch):
    monkeypatch.setenv("FINBOT_SEC_FETCH_NAMED_FORM", "off")
    _discovery(monkeypatch, [DiscoveredSecFiling("0001045810", ACCESSION, "8-K", date(2026, 11, 17), None, "nvda-20261117.htm", URL)])
    with pytest.raises(ValueError, match="sec_filing_not_found"):
        prepare_filing("fetch_sec", {"symbol": "NVDA", "form": "8-K", "accession_number": ACCESSION}, financial_only=True)


def test_unnamed_scope_still_narrows_to_10k_10q(monkeypatch):
    rows = [
        DiscoveredSecFiling("0001045810", ACCESSION, "8-K", date(2026, 11, 17), None, "a.htm", URL),
        DiscoveredSecFiling("0001045810", "0001045810-26-000010", "10-Q", date(2026, 8, 1), None, "q.htm",
                            "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000010/q.htm"),
    ]
    _discovery(monkeypatch, rows)
    op = prepare_filing("fetch_sec", {"symbol": "NVDA", "form": None, "accession_number": None}, financial_only=True)
    assert op["discovery"]["form"] == "10-Q"


def test_named_form_outside_scope_without_accession_says_so_not_not_found(monkeypatch):
    _discovery(monkeypatch, [])
    with pytest.raises(ValueError, match="sec_form_outside_scope"):
        prepare_filing("fetch_sec", {"symbol": "NVDA", "form": "8-K", "accession_number": None}, financial_only=True)
    out = tools.error("sec_form_outside_scope")
    assert out["error_code"] == "sec_form_outside_scope" and "10-K/10-Q" in out["hint"] and "8-K" not in out["error_code"]


def test_a_missing_named_accession_is_still_not_found(monkeypatch):
    create_sec_filing_inventory_table()
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete(synchronize_session=False)
        db.commit()
    _discovery(monkeypatch, [])
    with pytest.raises(ValueError, match="sec_filing_not_found"):
        prepare_filing("fetch_sec", {"symbol": "NVDA", "form": "8-K", "accession_number": ACCESSION}, financial_only=True)
