import json
from pathlib import Path

from app.agent_workflow import direct
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


def test_flag_off_does_not_record_a_claim_gate(monkeypatch):
    monkeypatch.delenv("CLAIM_QUOTE_GATE", raising=False)
    result = _turn().finish("Revenue was 16,128 [1].")
    assert "claim_gate" not in result["audit"]
    assert "claim_gate_shadow" not in result["audit"]
    assert result["status"] == "succeeded"
    assert "16,128" in result["answer"]


def test_shadow_records_a_bad_quote_while_legacy_keeps_the_prose(monkeypatch):
    monkeypatch.setenv("CLAIM_QUOTE_GATE", "shadow")
    result = _turn().finish(_answer("This sentence does not appear anywhere in the filing text."))
    assert result["status"] == "succeeded"
    assert "16,128" in result["answer"]
    assert "evidence_quote" not in result["answer"]
    shadow = result["audit"]["claim_gate_shadow"]
    assert "quote_not_found" in shadow["drop_reasons"]
    assert "latency_ms" in shadow
    assert shadow["answer_quality_notes"]["prose_chars"] > 0
    assert "legacy_disagreement" in shadow["answer_quality_notes"]


def test_shadow_fixture_quote_not_found_keeps_numeric_prose(monkeypatch):
    monkeypatch.setenv("CLAIM_QUOTE_GATE", "shadow")
    case = json.loads((FIXTURES / "quote_not_found.json").read_text())
    claim = case["claims"]["claims"][0]
    answer = f"{claim['statement']} [{claim['citation_ordinal']}]\n" + json.dumps(case["claims"])
    turn = _turn()
    turn.citations = case["citations"]
    result = turn.finish(answer)
    assert result["status"] == "succeeded"
    assert "16,128" in result["answer"]
    shadow = result["audit"]["claim_gate_shadow"]
    assert shadow["drop_reasons"] == ["quote_not_found"]
    assert shadow["answer_quality_notes"]["prose_chars"] > 0


def test_enforce_drops_a_claim_the_resolved_span_does_not_support(monkeypatch):
    monkeypatch.setenv("CLAIM_QUOTE_GATE", "enforce")
    claims = {
        "claims": [{
            "id": "c1",
            "statement": "Revenue was 16,182 million.",
            "citation_ordinal": 1,
            "evidence": {"type": "quote", "evidence_quote": "Total net sales were 16,182 for fiscal 2024."},
        }]
    }
    answer = "Revenue was 16,182 million [1].\n" + json.dumps(claims)
    result = _turn().finish(answer)
    # S0: enforce is retired. The sentence stays, is recorded by the shadow gate, and the turn's reason is unchanged.
    assert "16,182" in result["answer"]
    assert "待核对" not in result["answer"] and "claim_gate" not in result["audit"]
    assert result["audit"]["claim_gate_retired"] == "enforce->shadow"
    assert "unsupported_numeric" in result["audit"]["claim_gate_shadow"]["drop_reasons"]
    assert result["reason"] is None


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


def test_enforce_only_records_a_product_answer_that_cites_nothing(monkeypatch):
    monkeypatch.setenv("CLAIM_QUOTE_GATE", "enforce")
    turn = direct.Turn("你能做什么？", AgentRuntimeContext("custom", "test", "dummy"), lambda *_: None, [], {})
    turn.route = "D"
    answer = "我负责盯关注范围里公司和主题的新闻，只把重要的告诉你。"
    result = turn.finish(answer)
    assert result["answer"].startswith(answer)
    assert "claim_gate" not in result["audit"] and "claim_gate_shadow" in result["audit"]
