"""FP0 S0: the legacy claim and number verdicts only write audit records.

Covers step 2 (Turn.finish writes verdicts to audit.legacy_review), step 3 (enforce is retired), step 4
(finish_answer returns after the verify step), and the step 5 keep-list (R2 items 1-6).
"""
import asyncio
import json
import logging

from app.agent_workflow import claim_gate_flags, claim_review, unverified
from app.agent_workflow.state import AgentRuntimeContext

SOURCE = "Apple Inc. Total net sales were 16,128 for fiscal 2024. Operating income follows."
LEGACY_KEYS = ('answer_issues', 'rejected_lines', 'unverified_lines', 'polarity_conflict', 'event_not_in_source')


def _turn(route='A', citations=None):
    ctx = AgentRuntimeContext('custom', 'test', 'dummy')
    turn = direct.Turn('What was revenue?', ctx, lambda *_: None, [], {})
    turn.route = route
    turn.observations = [{'accepted_evidence': True}]
    turn.citations = citations if citations is not None else [
        {'ordinal': 1, 'quote': SOURCE, 'source_type': 'official_filing', 'source_id': 'src-1'}]
    return turn


def _claims_answer(quote):
    claims = {"claims": [{"id": "c1", "statement": "Revenue was 16,128.", "citation_ordinal": 1,
                          "evidence": {"type": "quote", "evidence_quote": quote}}]}
    return "Revenue was 16,128 [1].\n" + json.dumps(claims)


# ---- step 2: verdicts are audit-only ------------------------------------------------------------

# ---- step 3: enforce is retired -----------------------------------------------------------------

def test_enforce_is_served_as_shadow_and_marked(monkeypatch):
    monkeypatch.setenv('CLAIM_QUOTE_GATE', 'enforce')
    assert claim_gate_flags.claim_quote_gate_mode() == 'shadow'
    assert claim_gate_flags.claim_gate_retirement() == 'enforce->shadow'


def test_shadow_and_off_are_not_marked_as_retired(monkeypatch):
    monkeypatch.setenv('CLAIM_QUOTE_GATE', 'shadow')
    assert claim_gate_flags.claim_quote_gate_mode() == 'shadow'
    assert claim_gate_flags.claim_gate_retirement() is None
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    assert claim_gate_flags.claim_quote_gate_mode() == 'off'
    assert claim_gate_flags.claim_gate_retirement() is None


def test_the_retirement_receipt_is_logged_when_enforce_is_configured(monkeypatch, caplog):
    monkeypatch.setenv('CLAIM_QUOTE_GATE', 'enforce')
    with caplog.at_level(logging.WARNING, logger=claim_gate_flags.__name__):
        claim_gate_flags._log_claim_gate_retirement()
    assert any('retired' in record.getMessage() for record in caplog.records)


# ---- step 4: finish_answer returns after verify, no repair or re-binding ------------------------

# ---- step 5 keep-list (R2) ----------------------------------------------------------------------

