"""Source types do not restrict judge packages."""
from app.agent_workflow.claim_shadow_extract import to_judge_sources
from app.agent_workflow import number_review


def test_private_and_calculated_sources_are_packaged():
    citations = [{"ordinal": 1, "source_type": "portfolio", "quote": "holdings 100"},
                 {"ordinal": 2, "source_type": "calculation", "quote": "value 5000"}]
    sources, metadata = to_judge_sources([1, 2], citations)
    assert [s.ordinal for s in sources] == [1, 2]
    assert set(metadata) == {"1", "2"}
    sources, _, dropped, _ = number_review._package([{"own": [1, 2], "neighbours": []}], citations)
    assert [s.ordinal for s in sources] == [1, 2]
    assert dropped == []
