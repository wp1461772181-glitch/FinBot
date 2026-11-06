"""Privacy boundaries for judge packages."""
import asyncio
from types import SimpleNamespace

from app.agent_workflow.claim_shadow_extract import is_private_citation, to_judge_sources
from app.agent_workflow import number_review


def test_source_admission_rejects_private_unknown_and_conflicting_scope():
    for source in (
        {"source_type": "portfolio"}, {"source_type": "saved_workspace"},
        {"source_type": "uploaded_media"}, {}, {"source_type": "new_type"},
        {"source_type": "web", "scope": "private"},
        {"source_type": "web", "scope": "unexpected"},
        {"source_type": "saved_material", "fields": {"material_type": "uploaded_media"}},
    ):
        assert is_private_citation(source, [source])[0]
    assert not is_private_citation({"source_type": "web"}, [])[0]


def test_conflicting_metadata_and_ordinal_cannot_mask_private_material():
    for source in (
        {"source_type": "web", "visibility": "private"},
        {"source_type": "web", "fields": {"material_type": "uploaded_media"}},
        {"source_type": "saved_material", "fields": "official_filing"},
    ):
        assert is_private_citation(source, [source])[0]
    public = {"ordinal": 1, "source_type": "web", "quote": "public"}
    private = {"ordinal": 1, "source_type": "portfolio", "quote": "secret"}
    assert is_private_citation(public, [public, private])[0]
    sources, _ = to_judge_sources([1], [private, public])
    assert not sources


def test_calculation_inherits_private_turn_and_packaging_filters():
    citations = [{"ordinal": 1, "source_type": "web", "quote": "public"},
                 {"ordinal": 2, "source_type": "portfolio", "quote": "secret"},
                 {"ordinal": 3, "source_type": "calculation", "quote": "derived secret"}]
    sources, metadata = to_judge_sources([1, 2, 3], citations)
    assert [s.ordinal for s in sources] == [1]
    assert set(metadata) == {"1"}
    sources, _, dropped, _ = number_review._package([{"own": [1, 2, 3], "neighbours": []}], citations)
    assert [s.ordinal for s in sources] == [1]
    assert dropped == [2, 3]


def test_number_review_keeps_mixed_turn_local(monkeypatch):
    monkeypatch.setattr(number_review, "enabled", lambda: True)
    turn = SimpleNamespace(citations=[{"ordinal": 1, "source_type": "portfolio", "quote": "secret"}], audit={})
    result = {"answer": "A private figure", "unverified_lines": [{"line": "A private figure"}]}
    assert asyncio.run(number_review.settle(turn, result)) is result
    assert turn.audit["number_review"]["skipped"] == "private_turn"


def test_number_review_remains_closed_even_if_switch_is_on(monkeypatch):
    monkeypatch.setenv("CLAIM_NUMBER_REVIEW", "on")
    assert not number_review.enabled()


def test_calculation_requires_public_operand_provenance():
    public = {"ordinal": 1, "source_type": "web", "quote": "price 10"}
    calc = {"ordinal": 2, "source_type": "calculation", "calculation": {
        "inputs": [{"name": "a", "source_ordinal": 1, "value": "10"}]}}
    assert not is_private_citation(calc, [public, calc])[0]
    for inputs in ([], [{"name": "a", "user_stated": True, "value": "10"}],
                   [{"name": "a", "origin": "user_stated", "value": "10"}],
                   [{"name": "a", "source_ordinal": 9}], [None]):
        bad = {**calc, "calculation": {"inputs": inputs}}
        assert is_private_citation(bad, [public, bad])[0]
    assert is_private_citation({"source_type": "formula_calculation"}, [public])[0]


def test_number_review_does_not_discard_malformed_citation(monkeypatch):
    monkeypatch.setattr(number_review, "enabled", lambda: True)
    turn = SimpleNamespace(citations=[{"ordinal": 1, "source_type": "web"}, None], audit={})
    result = {"answer": "A figure", "unverified_lines": [{"line": "A figure"}]}
    assert asyncio.run(number_review.settle(turn, result)) is result
    assert turn.audit["number_review"]["skipped"] == "private_turn"
