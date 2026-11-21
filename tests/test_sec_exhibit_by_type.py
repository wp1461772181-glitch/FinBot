"""Exhibit 99.1 located by SEC's official file type, and the re-check of 8-Ks judged not_found."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import app.sec_filings as sec_filings
from app.database import SessionLocal
from app.sec_filings import SecFilingsError, create_sec_filing_inventory_table, fetch_inventory_content, scan_sec_filings
from test_sec_filings import _clear_inventory, _provider, _responses


def _headers_html(documents: list[tuple[str, str]]) -> bytes:
    """An ``<accession>-index-headers.html`` body: HTML-escaped SGML, one block per file."""
    body = "".join(
        f"<DOCUMENT>\n<TYPE>{doc_type}\n<SEQUENCE>{sequence}\n<FILENAME>{name}\n<DESCRIPTION>{doc_type}\n</DOCUMENT>\n"
        for sequence, (doc_type, name) in enumerate(documents, start=1)
    )
    body = body.replace("<", "&lt;").replace(">", "&gt;")
    return f"<html><body><pre>{body}</pre></body></html>".encode()


def _setup(db, files, headers, bodies=None):
    create_sec_filing_inventory_table()
    _clear_inventory()
    opener, _ = _responses()
    provider = _provider(opener)
    rows, _, _ = scan_sec_filings(symbol="AAPL", db=db, provider=provider)
    filing = next(row for row in rows if row.form == "8-K")
    directory = filing.source_url.rsplit("/", 1)[0]
    opener.responses[f"{directory}/index.json"] = json.dumps({"directory": {"item": [{"name": n} for n in files]}}).encode()
    if headers is not None:
        opener.responses[f"{directory}/{filing.accession_number}-index-headers.html"] = _headers_html(headers)
    for name in files:
        opener.responses[f"{directory}/{name}"] = (bodies or {}).get(name, f"<html><body>{name} text</body></html>".encode())
    return opener, provider, filing, directory


def test_nvidia_style_press_release_is_found_by_type_and_only_99_1_is_read():
    with SessionLocal() as db:
        opener, provider, filing, directory = _setup(
            db,
            ["nvda-20261117.htm", "q3fy27pr.htm", "q3fy27cfocommentary.htm", "supplementalfinancialinfor.htm"],
            [("8-K", "nvda-20261117.htm"), ("EX-99.1", "q3fy27pr.htm"), ("EX-99.2", "q3fy27cfocommentary.htm"),
             ("EX-99.3", "supplementalfinancialinfor.htm")],
        )
        exhibit = provider.fetch_exhibit_99_1(filing)
    assert exhibit is not None and exhibit.document_name == "q3fy27pr.htm"
    assert exhibit.source_url == f"{directory}/q3fy27pr.htm"
    assert f"{directory}/q3fy27cfocommentary.htm" not in opener.urls
    assert f"{directory}/{filing.accession_number}-index-headers.html" in opener.urls
    assert all(agent == provider._user_agent for agent in opener.user_agents)


def test_apple_style_name_with_trailing_characters_is_found_by_type():
    name = "a8-kex991q4202609272026.htm"
    assert sec_filings._EXHIBIT_99_1.search(name) is None  # the file-name pattern cannot see it
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(db, ["aapl-8k.htm", name], [("8-K", "aapl-8k.htm"), ("EX-99.1", name)])
        assert provider.fetch_exhibit_99_1(filing).document_name == name


@pytest.mark.parametrize("doc_type", ["ex-99.1", " EX-99.01 "])
def test_type_comparison_ignores_case_whitespace_and_leading_zero(doc_type):
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(db, ["aapl-8k.htm", "pr.htm"], [("8-K", "aapl-8k.htm"), (doc_type, "pr.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "pr.htm"


def test_bare_ex_99_is_accepted_only_when_there_is_no_ex_99_1():
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(db, ["aapl-8k.htm", "a.htm"], [("8-K", "aapl-8k.htm"), ("EX-99", "a.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "a.htm"
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(
            db, ["aapl-8k.htm", "a.htm", "b.htm"], [("8-K", "aapl-8k.htm"), ("EX-99", "a.htm"), ("EX-99.1", "b.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "b.htm"


def test_several_official_ex_99_1_documents_resolve_to_the_lowest_sequence():
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(
            db, ["aapl-8k.htm", "second.htm", "first.htm"],
            [("8-K", "aapl-8k.htm"), ("EX-99.1", "first.htm"), ("EX-99.1", "second.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "first.htm"


@pytest.mark.parametrize("exhibit_name", ["ex-99.1.htm", "avgo-08022026x8kxex99.htm"])
def test_missing_headers_fall_back_to_the_file_name_pattern(exhibit_name):
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(db, ["aapl-8k.htm", exhibit_name], None)
        assert provider.fetch_exhibit_99_1(filing).document_name == exhibit_name


def test_headers_without_ex_99_1_fall_back_to_the_file_name_pattern():
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(
            db, ["aapl-8k.htm", "ex-99.1.htm"], [("8-K", "aapl-8k.htm"), ("EX-99.2", "other.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "ex-99.1.htm"


def test_unreadable_headers_fall_back_and_no_candidate_anywhere_returns_none():
    with SessionLocal() as db:
        opener, provider, filing, directory = _setup(db, ["aapl-8k.htm", "q3pr.htm"], None)
        opener.responses[f"{directory}/{filing.accession_number}-index-headers.html"] = b"\x00\x01 not a header"
        assert provider.fetch_exhibit_99_1(filing) is None


@pytest.mark.parametrize("bad_name", ["../ex99-1.htm", "elsewhere.htm", "a/b.htm"])
def test_header_names_outside_the_directory_listing_or_unsafe_are_not_used(bad_name):
    with SessionLocal() as db:
        opener, provider, filing, _ = _setup(db, ["aapl-8k.htm"], [("8-K", "aapl-8k.htm"), ("EX-99.1", bad_name)])
        assert provider.fetch_exhibit_99_1(filing) is None
    assert not any(bad_name in url for url in opener.urls)


def test_switch_off_restores_the_file_name_only_behaviour(monkeypatch):
    monkeypatch.setenv("FINBOT_SEC_EXHIBIT_BY_TYPE", "off")
    with SessionLocal() as db:
        opener, provider, filing, _ = _setup(
            db, ["aapl-8k.htm", "q3fy27pr.htm"], [("8-K", "aapl-8k.htm"), ("EX-99.1", "q3fy27pr.htm")])
        assert provider.fetch_exhibit_99_1(filing) is None
    assert not any(url.endswith("-index-headers.html") for url in opener.urls)


# --- re-checking 8-Ks that were judged not_found -------------------------------------------------------------

def _notfound_8k(db, monkeypatch):
    """An 8-K saved while only the file-name pattern existed: cover page stored, attachment not_found."""
    monkeypatch.setenv("FINBOT_SEC_EXHIBIT_BY_TYPE", "off")
    opener, provider, filing, directory = _setup(
        db, ["aapl-8k.htm", "q3fy27pr.htm"], [("8-K", "aapl-8k.htm"), ("EX-99.1", "q3fy27pr.htm")],
        bodies={"aapl-8k.htm": b"<html><body>Cover page only.</body></html>",
                "q3fy27pr.htm": b"<html><body>Revenue was $44 billion.</body></html>"},
    )
    first, _ = fetch_inventory_content(symbol="AAPL", accession_number=filing.accession_number, db=db, provider=provider,
                                       observed_at=datetime(2026, 11, 2, 10, tzinfo=UTC))
    assert first.related_attachment_status == "not_found" and first.content_kind == "primary_document"
    monkeypatch.delenv("FINBOT_SEC_EXHIBIT_BY_TYPE")
    return opener, provider, filing, directory


def test_recheck_turns_a_not_found_8k_into_the_exhibit_while_the_default_path_leaves_it(monkeypatch):
    with SessionLocal() as db:
        opener, provider, filing, directory = _notfound_8k(db, monkeypatch)
        before = len(opener.urls)
        again, hit = fetch_inventory_content(symbol="AAPL", accession_number=filing.accession_number, db=db, provider=provider)
        assert hit is True and again.related_attachment_status == "not_found"
        assert len(opener.urls) == before  # the default path never looks again

        rechecked, hit = fetch_inventory_content(
            symbol="AAPL", accession_number=filing.accession_number, db=db, provider=provider, recheck_attachment=True,
            observed_at=datetime(2026, 11, 20, 10, tzinfo=UTC))
    assert hit is False
    assert rechecked.related_attachment_status == "fetched"
    assert rechecked.content_kind == "exhibit_99_1"
    assert rechecked.content_document_name == "q3fy27pr.htm"
    assert rechecked.content_source_url == f"{directory}/q3fy27pr.htm"
    assert rechecked.content_text == "Revenue was $44 billion."
    assert opener.urls.count(f"{directory}/q3fy27pr.htm") == 1  # fetched once, not twice


def test_recheck_with_nothing_new_or_a_failed_lookup_leaves_the_row_untouched(monkeypatch):
    with SessionLocal() as db:
        opener, provider, filing, directory = _notfound_8k(db, monkeypatch)
        opener.responses[f"{directory}/{filing.accession_number}-index-headers.html"] = _headers_html([("8-K", "aapl-8k.htm")])
        same, hit = fetch_inventory_content(
            symbol="AAPL", accession_number=filing.accession_number, db=db, provider=provider, recheck_attachment=True)
        assert hit is True and same.related_attachment_status == "not_found" and same.content_text == "Cover page only."

        def broken(_filing):
            raise SecFilingsError("SEC request failed")

        monkeypatch.setattr(provider, "fetch_exhibit_99_1", broken)
        with pytest.raises(SecFilingsError):
            fetch_inventory_content(symbol="AAPL", accession_number=filing.accession_number, db=db, provider=provider,
                                    recheck_attachment=True)
        db.refresh(same)
        assert same.content_status == "fetched" and same.content_text == "Cover page only."


@pytest.mark.parametrize("name", ["q3pr.pdf", "chart.jpg", "release.PDF"])
def test_a_non_text_document_typed_ex_99_1_is_not_chosen(disposable_database, name):
    with SessionLocal() as db:
        opener, provider, filing, directory = _setup(db, ["primary.htm", name], [("8-K", "primary.htm"), ("EX-99.1", name)])
        # No readable exhibit by type, none by name: the primary document stays in use and nothing is downloaded.
        assert provider.fetch_exhibit_99_1(filing) is None
        assert f"{directory}/{name}" not in [request for request in getattr(opener, "requested", [])]


def test_a_text_ex_99_1_is_still_chosen_beside_a_pdf_copy(disposable_database):
    with SessionLocal() as db:
        _, provider, filing, _ = _setup(db, ["primary.htm", "q3pr.pdf", "q3pr.htm"],
                                        [("8-K", "primary.htm"), ("EX-99.1", "q3pr.pdf"), ("EX-99.1", "q3pr.htm")])
        assert provider.fetch_exhibit_99_1(filing).document_name == "q3pr.htm"


def test_fetch_sec_answers_from_the_saved_text_when_the_exhibit_recheck_fails(disposable_database, monkeypatch):
    from runpy import run_path
    from types import SimpleNamespace
    from app.agent_workflow import actions
    run_path("scripts/migrate_agent_actions.py")["apply"]()
    monkeypatch.setattr(actions, "owner_credential_matches", lambda value: value == "owner-session")
    seen = []
    saved = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    def fake_fetch(*, symbol, accession_number, db, force_refresh=False, recheck_attachment=False, **_):
        seen.append(recheck_attachment)
        if recheck_attachment:
            raise SecFilingsError("SEC request failed; no filing data was saved")
        return saved, True
    monkeypatch.setattr(sec_filings, "fetch_inventory_content", fake_fetch)
    done = actions.execute_action(credential="owner-session", request_key="fetch-recheck-1", action="fetch_sec",
                                  payload={"symbol": "NVDA", "accession_number": "0001045810-26-000088"})
    assert seen == [True, False]
    assert done["ok"] is True and done["result"]["cached"] is True
