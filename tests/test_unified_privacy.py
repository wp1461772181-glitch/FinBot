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
