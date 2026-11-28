import json
from pathlib import Path

from app.agent_workflow.state import AgentRuntimeContext

SOURCE = "Apple Inc. Total net sales were 16,128 for fiscal 2024. Operating income follows."
FIXTURES = Path(__file__).parent / "fixtures" / "claim_gate"


def _turn():
    ctx = AgentRuntimeContext("custom", "test", "dummy")
    turn = direct.Turn("What was revenue?", ctx, lambda *_: None, [], {})
    turn.route = "A"
    turn.observations = [{"accepted_evidence": True}]
    turn.citations = [{"ordinal": 1, "quote": SOURCE, "source_type": "official_filing", "source_id": "src-1"}]
    return turn


def _answer(quote):
    claims = {
        "claims": [{
            "id": "c1",
            "statement": "Revenue was 16,128.",
            "citation_ordinal": 1,
            "evidence": {"type": "quote", "evidence_quote": quote},
        }]
    }
    return "Revenue was 16,128 [1].\n" + json.dumps(claims)


def test_enforce_only_warns_when_the_figure_is_in_another_source_of_the_turn():
    """Claim-level unsupported_numeric (any wording, no keyword list) does not remove a line by itself:
    the line is removed only when no evidence of the turn holds the figure (the row-level check)."""
    from app.agent_workflow.claim_review import apply_claim_gate
    citations = [
        {"ordinal": 1, "quote": "Gross margin was 38.1% in fiscal 2024.", "source_type": "official_filing"},
        {"ordinal": 2, "quote": "Revenue growth was 46% year over year.", "source_type": "official_filing"},
    ]
    claims = {"claims": [{"id": "c1", "statement": "Revenue growth was 46%.", "citation_ordinal": 1,
                          "evidence": {"type": "quote", "evidence_quote": "Gross margin was 38.1% in fiscal 2024."}}]}
    application = apply_claim_gate("Revenue growth was 46% [1].\n" + json.dumps(claims), citations, mode="enforce")
    assert [item["reason"] for item in application.issues] == ["unsupported_numeric"]
    assert application.dropped_lines == [] and "46%" in application.kept_prose
    assert application.audit["warned_lines"] == [{"line": "Revenue growth was 46% [1].", "reason": "unsupported_numeric"}]


