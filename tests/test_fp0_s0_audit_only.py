"""FP0 S0: the legacy claim and number verdicts only write audit records.

Covers step 2 (Turn.finish writes verdicts to audit.legacy_review), step 3 (enforce is retired), step 4
(finish_answer returns after the verify step), and the step 5 keep-list (R2 items 1-6).
"""
import asyncio
import json
import logging

from app.agent_workflow import claim_gate_flags, claim_review, direct, unverified
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

def test_a_failed_number_check_adds_no_footnote_and_keeps_status_and_reason(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn()
    result = turn.finish('Revenue was 16,999 [1].')
    assert '另有' not in result['answer'] and '证据不足' not in result['answer']
    assert result['status'] == 'succeeded' and result['reason'] is None
    assert result['unverified_lines'] == [] and turn.unverified_lines == []
    legacy = result['audit']['legacy_review']
    assert legacy['version'] == 'legacy-v1' and legacy['issues']
    assert 'scope' in legacy and 'insufficient_evidence_lines' in legacy


def test_legacy_verdict_keys_are_not_written_at_the_top_of_the_audit(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    result = _turn().finish('Revenue was 16,999 [1].')
    for key in LEGACY_KEYS:
        assert key not in result['audit'], key


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


def test_enforce_never_reaches_the_claim_gate_in_production(monkeypatch):
    """_enforce_lines stays in claim_review but no production call can reach it."""
    monkeypatch.setenv('CLAIM_QUOTE_GATE', 'enforce')
    modes = []
    real_gate = claim_review.apply_claim_gate

    def recording_gate(*args, **kwargs):
        modes.append(kwargs.get('mode'))
        return real_gate(*args, **kwargs)

    def no_enforce_lines(*_args, **_kwargs):
        raise AssertionError('_enforce_lines must not be reached from production')

    monkeypatch.setattr(claim_review, 'apply_claim_gate', recording_gate)
    monkeypatch.setattr(claim_review, '_enforce_lines', no_enforce_lines)
    result = _turn().finish(_claims_answer('Total net sales were 16,182 for fiscal 2024.'))
    assert modes == ['shadow']
    assert result['audit']['claim_gate_retired'] == 'enforce->shadow'
    assert 'claim_gate' not in result['audit'] and 'claim_gate_shadow' in result['audit']


def test_the_claims_payload_never_reaches_the_visible_answer(monkeypatch):
    """Step 2 deviation: the claims JSON is still split off the visible text (extract_claims_payload)."""
    monkeypatch.setenv('CLAIM_QUOTE_GATE', 'shadow')
    result = _turn().finish(_claims_answer('This sentence does not appear anywhere in the filing text.'))
    assert '"claims"' not in result['answer'] and 'evidence_quote' not in result['answer']
    assert result['answer'].startswith('Revenue was 16,128')


# ---- step 4: finish_answer returns after verify, no repair or re-binding ------------------------

def test_finish_answer_runs_no_repair_round(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    calls = []

    async def decider(*args):
        calls.append(args)
        return {'content': 'Revenue was 16,128 [1].'}

    async def emit(_event):
        return None

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', decider=decider)
    turn = direct.Turn('What was revenue?', ctx, emit, [], {})
    turn.route = 'A'
    turn.observations = [{'accepted_evidence': True}]
    turn.citations = [{'ordinal': 1, 'quote': SOURCE, 'source_type': 'official_filing'}]
    result = asyncio.run(turn.finish_answer('Revenue was 16,999 [1].'))
    assert calls == [] and 'answer_repair_count' not in result['audit']
    assert result['status'] == 'succeeded'


def test_remap_and_merge_repair_are_not_called(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError('repair or re-binding must not run')

    async def emit(_event):
        return None

    monkeypatch.setattr(unverified, 'remap_citations', fail)
    monkeypatch.setattr(unverified, 'merge_repair', fail)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy')
    turn = direct.Turn('What was revenue?', ctx, emit, [], {})
    turn.route = 'A'
    turn.observations = [{'accepted_evidence': True}]
    turn.citations = [{'ordinal': 1, 'quote': 'AMD 已保存收盘价 100', 'source_type': 'saved_price'},
                      {'ordinal': 2, 'quote': 'Total revenue 331,839 million', 'source_type': 'official_filing'}]
    result = asyncio.run(turn.finish_answer('AMD 营收为 331,839 百万美元 [1]。'))
    assert result['status'] == 'succeeded' and 'citation_remaps' not in result['audit']


def test_repair_code_is_marked_unreachable_in_the_source():
    import inspect
    source = inspect.getsource(direct.Turn.finish_answer)
    assert 'S0 起不可达' in source


# ---- step 5 keep-list (R2) ----------------------------------------------------------------------

def test_r2_1_an_unexecuted_write_gets_the_server_conclusion(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn()
    turn.write_reasons = {'scan': 'write_tool_not_granted'}
    turn.scope = {'requested_actions': ['add_to_research_queue']}
    result = turn.finish('好的。')
    assert '操作未执行：' in result['answer']
    assert result['audit']['write_outcome'] == 'refused:write_tool_not_granted'


def test_r2_2_a_memory_fallback_gets_its_receipt(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn()
    turn.audit['memory_fallback'] = True
    result = turn.finish('已记下。')
    assert '已按你的原话记下这条偏好。' in result['answer']
    assert result['audit']['write_outcome'] == 'executed'


def test_r2_3_an_entity_mapping_line_is_kept(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn()
    turn.mapped_entity = {'mention': '礼来', 'title': 'ELI LILLY & Co', 'symbol': 'LLY'}
    result = turn.finish('收入为 1 美元。')
    assert '按 礼来 = ELI LILLY & Co（LLY）理解' in result['answer']


def test_r2_4_a_dead_marker_is_stripped_and_a_live_one_kept(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    result = _turn().finish('Revenue was 16,128 [1]. Extra claim [9].')
    assert '[9]' not in result['answer'] and '[1]' in result['answer']


def test_r2_5_a_real_stop_keeps_its_partial_status():
    turn = _turn()
    result = turn.partial_failure('no_progress')
    assert result['status'] == 'partially_succeeded' and result['reason'] == 'no_progress'


def test_r2_5_a_real_tool_failure_status_is_not_cleared_by_the_check(monkeypatch):
    """Reverse assertion: finish never upgrades a status it was given, even when the check flags the text."""
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    for status in ('partially_succeeded', 'failed'):
        result = _turn().finish('Revenue was 16,999 [1].', status=status, reason='tool_failures', generated=True)
        assert result['status'] == status and result['reason'] == 'tool_failures'


def test_r2_6_v2_hand_markers_are_still_stripped(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn()
    turn.citation_protocol = 'v2'
    result = turn.finish('Revenue was 16,128 [1].')
    assert result['citation_protocol'] == 'v2' and '[1]' not in result['answer']


# ---- ruling 1: the status rule (genuine stop and tool failure are partial, a clean turn stays succeeded) ----

def test_a_normal_turn_stays_succeeded(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    result = _turn().finish('Revenue was 16,128 [1].')
    assert result['status'] == 'succeeded'
    assert 'status_basis' not in result['audit'] and 'failed_tools' not in result['audit']


def test_a_turn_with_a_tool_failure_is_partial(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn(route='D', citations=[])
    turn.accept('open_page', {'page': 'sec'}, {'ok': False, 'error_code': 'tool_failed'})
    result = turn.finish('已打开 SEC 页面。')
    assert result['status'] == 'partially_succeeded'
    assert result['audit']['status_basis'] == 'tool_failure'
    assert result['audit']['failed_tools'] == [{'tool': 'open_page', 'error_code': 'tool_failed'}]


def test_a_successful_empty_search_is_not_a_tool_failure(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn(route='D', citations=[])
    turn.feedback.append({'name': 'search_knowledge', 'ok': True, 'data': [], 'error_code': 'no_matching_evidence'})
    result = turn.finish('没有找到相关资料。')
    assert result['status'] == 'succeeded' and 'failed_tools' not in result['audit']


def test_a_genuine_stop_turn_is_partial():
    from app.agent_workflow.direct import run_direct_turn

    async def emit(_event):
        return None

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: 'D',
        decider=lambda *_: {'tool_calls': [{'id': 'p', 'function': {'name': 'query_stock_prices', 'arguments': '{"symbol":"AMD"}'}}]},
        executor=lambda *_: {'ok': True, 'data': [{'id': 'p', 'symbol': 'AMD', 'close': 100}]},
        answerer=lambda *_: 'AMD 收盘价为 100 美元 [1]。')
    result = asyncio.run(run_direct_turn('查 AMD 价格', ctx, emit=emit))
    assert result['reason'] == 'no_progress' and result['status'] == 'partially_succeeded'
    assert result['audit']['status_basis'] == 'genuine_stop'


def test_failed_and_partial_statuses_are_never_changed(monkeypatch):
    monkeypatch.delenv('CLAIM_QUOTE_GATE', raising=False)
    turn = _turn(route='D', citations=[])
    turn.accept('open_page', {'page': 'sec'}, {'ok': False, 'error_code': 'tool_failed'})
    assert turn.finish('x', status='failed', reason='tool_failures', generated=True)['status'] == 'failed'
    assert turn.finish('x', status='partially_succeeded', reason='tool_failures', generated=True)['status'] == 'partially_succeeded'
