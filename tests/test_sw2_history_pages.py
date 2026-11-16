"""SW2 S1 (R2): a saved source reads back in pages of its full text, and each page says where it sits."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.agent_tool_catalog import validate
from app.agent_workflow.direct import Turn
from app.agent_workflow.history_citations import (
    HISTORY_PAGE_NOTE, HISTORY_STORED_PARTIAL_NOTE, bind_history_citation, read_history_citation)
from app.agent_workflow.state import AgentRuntimeContext
from app.agent_workflow.truncation import fit_observations

TURN = "0c1f1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b"
# 11,248 characters; the figure sits at 8,991–8,996, beyond the 5,000-character display quote and on page 2.
BODY = "a" * 8990 + "x74421" + "b" * (11248 - 8990 - 6)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    for name in ("FINBOT_SW2_HISTORY_PAGES", "FINBOT_SW2_MEMORY_PRELOAD", "FINBOT_SW2_SELF_STATE_WORDING", "FINBOT_SW2_SELF_STATE"):
        monkeypatch.delenv(name, raising=False)


def _store(monkeypatch, citations_by_ordinal):
    import app.agent_chat_store as store
    import app.agent_chat_stream as stream

    async def loaded(_conversation, _credential, turn_id, ordinal):
        citation = citations_by_ordinal.get(ordinal)
        if citation is None:
            return {"ok": False, "error_code": "history_citation_not_found"}
        return {"ok": True, "citation": citation, "origin": {"turn_id": turn_id, "ordinal": ordinal}}

    monkeypatch.setattr(store, "load_turn_citation", loaded)
    monkeypatch.setattr(stream, "_restore_citations", lambda items, _credential: items)


def _context(ordinals=(1,)):
    return AgentRuntimeContext("p", "m", "k", conversation_id="conversation", identity_credential="owner",
        history_citation_catalogue=({"turn_id": TURN, "sources": [
            {"ordinal": n, "source_type": "official_filing", "available": True} for n in ordinals]},))


def _filing(ordinal, body, **extra):
    return {"ordinal": ordinal, "title": f"filing {ordinal}", "source_type": "official_filing",
            "quote": body[:5000], "check_text": body, **extra}


def test_off_reads_the_display_quote_and_calls_it_whole(monkeypatch):
    """The v1 shape: quote is the first 5,000 characters, the figure is not in it, and truncated is false."""
    monkeypatch.setenv("FINBOT_SW2_HISTORY_PAGES", "off")
    _store(monkeypatch, {1: _filing(1, BODY)})
    row = asyncio.run(read_history_citation({"turn_id": TURN, "ordinal": 1}, _context()))["data"][0]
    assert row["truncated"] is False
    assert "74421" not in row["quote"]
    assert not {"offset", "chars_total", "next_offset", "complete", "stored_partial", "note"} & set(row)


def test_on_pages_the_full_text_and_states_where_each_page_sits(monkeypatch):
    _store(monkeypatch, {1: _filing(1, BODY)})
    first = asyncio.run(read_history_citation({"turn_id": TURN, "ordinal": 1}, _context()))
    row = first["data"][0]
    assert (row["offset"], row["chars_total"], row["next_offset"], row["complete"]) == (0, 11248, 8000, False)
    assert row["truncated"] is True and "74421" not in row["quote"]
    assert row["note"] == HISTORY_PAGE_NOTE.format(start=1, end=8000, total=11248, next_offset=8000)
    second = asyncio.run(read_history_citation({"turn_id": TURN, "ordinal": 1, "offset": 8000}, _context()))
    last = second["data"][0]
    assert last["complete"] is True and last["next_offset"] is None and "74421" in last["quote"]
    assert last["truncated"] is False and "note" not in last
    citations = []
    one = bind_history_citation(first, citations)["data"][0]
    two = bind_history_citation(second, citations)["data"][0]
    assert one["citation"] == two["citation"] == "[1]" and len(citations) == 1
    assert two["offset"] == 8000 and two["complete"] is True


def test_offset_past_the_end_is_an_empty_complete_page(monkeypatch):
    _store(monkeypatch, {1: _filing(1, BODY)})
    row = asyncio.run(read_history_citation({"turn_id": TURN, "ordinal": 1, "offset": 20000}, _context()))["data"][0]
    assert row["quote"] == "" and row["complete"] is True and row["next_offset"] is None
    assert row["chars_total"] == 11248


def test_offset_must_be_an_integer_at_the_schema():
    with pytest.raises(Exception):
        validate("read_history_citation", {"turn_id": TURN, "ordinal": 1, "offset": "8000"})


def test_stored_partial_last_page_says_the_saved_text_ends_there(monkeypatch):
    _store(monkeypatch, {1: _filing(1, "short saved text " * 20, evidence_incomplete=True)})
    row = asyncio.run(read_history_citation({"turn_id": TURN, "ordinal": 1}, _context()))["data"][0]
    assert row["complete"] is True and row["stored_partial"] is True and row["truncated"] is True
    assert row["note"] == HISTORY_STORED_PARTIAL_NOTE


def test_bound_row_carries_the_page_facts_only_when_they_were_read():
    paged = {"ok": True, "_snapshot": {"title": "t"}, "data": [{
        "title": "t", "source_type": "s", "quote": "q", "truncated": True, "origin": {"turn_id": TURN, "ordinal": 1},
        "offset": 0, "chars_total": 11248, "next_offset": 8000, "complete": False, "stored_partial": False, "note": "n"}]}
    bound = bind_history_citation(paged, [])["data"][0]
    assert set(bound) == {"citation", "title", "source_type", "quote", "truncated",
                          "offset", "chars_total", "next_offset", "complete", "stored_partial", "note"}
    assert (bound["offset"], bound["chars_total"], bound["next_offset"], bound["complete"], bound["note"]) == (0, 11248, 8000, False, "n")
    legacy = {"ok": True, "_snapshot": {"title": "t"}, "data": [{
        "title": "t", "source_type": "s", "quote": "q", "truncated": False, "origin": {"turn_id": TURN, "ordinal": 1}}]}
    assert set(bind_history_citation(legacy, [])["data"][0]) == {"citation", "title", "source_type", "quote", "truncated"}


def _recall_turn(monkeypatch, ordinals_bodies):
    """Three resolver-bound long sources; the marker sits at 7,500, past the display length and inside one 8,000 page."""
    citations = {n: _filing(n, body) for n, body in ordinals_bodies.items()}
    _store(monkeypatch, citations)
    context = _context(tuple(ordinals_bodies))
    async def emit(_):
        pass
    turn = Turn("q", context, emit, [], {})
    turn.bound_history_citations = [{"turn_id": TURN, "ordinal": n, "derived": False} for n in ordinals_bodies]
    return turn


def test_auto_recall_reads_the_first_long_source_in_full_and_later_ones_at_display_length(monkeypatch):
    marker = "M7500"
    long_body = lambda tag: "a" * 7450 + f"{tag}{marker}" + "b" * (11000 - 7450 - len(tag) - len(marker))
    turn = _recall_turn(monkeypatch, {1: long_body("X1"), 2: long_body("X2"), 3: long_body("X3")})
    assert asyncio.run(turn.recall_bound_citations()) is True
    reads = [o for o in turn.observations if o.get("name") == "read_history_citation"]
    quotes = [o["result"]["data"][0]["quote"] for o in reads]
    assert [len(q) for q in quotes] == [8000, 5000, 5000]
    assert "X1" + marker in quotes[0]
    kept, omitted, _, _ = fit_observations(turn.observations, 22000)
    assert omitted == []
    assert any("X1" + marker in str(o.get("result")) for o in kept)


def test_auto_recall_with_the_flag_off_reads_as_before(monkeypatch):
    monkeypatch.setenv("FINBOT_SW2_HISTORY_PAGES", "off")
    turn = _recall_turn(monkeypatch, {1: "a" * 11000, 2: "b" * 11000})
    asyncio.run(turn.recall_bound_citations())
    reads = [o for o in turn.observations if o.get("name") == "read_history_citation"]
    assert [len(o["result"]["data"][0]["quote"]) for o in reads] == [5000, 5000]
    assert all("note" not in o["result"]["data"][0] for o in reads)


def test_one_full_page_fits_the_evidence_budget_beside_its_neighbours(monkeypatch):
    """B9: an 8,000-character page is kept whole by the 22,000-character evidence budget."""
    turn = _recall_turn(monkeypatch, {1: "c" * 11000})
    asyncio.run(turn.recall_bound_citations())
    kept, omitted, _, used = fit_observations(turn.observations, 22000)
    assert omitted == [] and used <= 22000
    assert any(len(o["result"]["data"][0]["quote"]) == 8000 for o in kept)


@pytest.mark.parametrize("value,offset_present,sentence_present", [("on", True, True), ("off", False, False)])
def test_offset_and_tool_sentence_follow_the_flag_at_import(value, offset_present, sentence_present):
    env = {**os.environ, "FINBOT_SW2_HISTORY_PAGES": value}
    code = ("from app.agent_tool_catalog import HistoryCitationArgs, definitions;"
            "d=definitions()['read_history_citation'].description;"
            "print('offset' in HistoryCitationArgs.model_fields, 'pass next_offset as offset' in d)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split() == [str(offset_present), str(sentence_present)]
