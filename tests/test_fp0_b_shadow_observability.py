"""FP0 slice b (WP0 steps 6, 7, 11): the judge's code flags read audit.legacy_review, the judge keeps
judging past its report target, and the citation scores say when they came from the legacy check."""
import pytest

from app.agent_workflow.claim_shadow import _extract_code_flags

REJECTED = {'line': 'AMD 开盘价为 999 美元 [1]。', 'reason': 'unsupported_numeric_claim', 'numbers': ['999']}
HINT = {'line': '公司 CEO 已辞职 [1]。', 'reason': 'event_not_in_source', 'numbers': [], 'ordinal': 1, 'snippet': 'x'}
POLARITY = {'count': 1, 'items': [{'line': '收入下降 [1]。'}]}
EVENT = {'count': 1, 'items': [{'line': '公司 CEO 已辞职 [1]。'}]}
EXPECTED = {'polarity_conflict': [], 'event_not_in_source': [], 'answer_issues': ['unsupported_numeric_claim'],
            'unverified_lines': 2}


def _baseline_shape():
    """A row as the pre-S0 finish stored it: the verdicts at the top of the audit and in the visible list."""
    return {'unverified_lines': [dict(REJECTED), dict(HINT)],
            'audit': {'answer_issues': ['unsupported_numeric_claim'], 'insufficient_evidence_lines': 1,
                      'polarity_conflict': dict(POLARITY), 'event_not_in_source': dict(EVENT)}}


def _s0_shape():
    """The same verdicts as the S0 finish writes them: under audit.legacy_review, with the visible list empty."""
    return {'unverified_lines': [],
            'audit': {'legacy_review': {'version': 'legacy-v1', 'issues': ['unsupported_numeric_claim'],
                                        'rejected_lines': [{'line': REJECTED['line'], 'reason': REJECTED['reason']}],
                                        'unverified_lines': [dict(REJECTED)], 'hints': [dict(HINT)],
                                        'insufficient_evidence_lines': 1, 'scope': {},
                                        'polarity_conflict': dict(POLARITY), 'event_not_in_source': dict(EVENT)}}}


def test_s0_shape_gives_the_same_code_flags_as_the_baseline_shape():
    assert _extract_code_flags(_s0_shape()) == _extract_code_flags(_baseline_shape()) == EXPECTED


def test_list_shaped_polarity_and_event_items_read_the_same_from_either_shape():
    polarity = [{'sentence': '收入下降 [1]。'}]
    event = ['公司 CEO 已辞职']
    base = _baseline_shape()
    base['audit']['polarity_conflict'] = list(polarity)
    base['audit']['event_not_in_source'] = list(event)
    s0 = _s0_shape()
    s0['audit']['legacy_review']['polarity_conflict'] = list(polarity)
    s0['audit']['legacy_review']['event_not_in_source'] = list(event)
    flags = _extract_code_flags(s0)
    assert flags == _extract_code_flags(base)
    assert flags['polarity_conflict'] == ['收入下降 [1]。'] and flags['event_not_in_source'] == ['公司 CEO 已辞职']


def test_a_row_without_legacy_review_falls_back_to_the_top_level_keys():
    assert _extract_code_flags(_baseline_shape()) == EXPECTED


def test_legacy_review_wins_over_stale_top_level_keys():
    row = _s0_shape()
    row['audit']['answer_issues'] = ['stale_top_level']
    row['audit']['unverified_lines'] = ['stale', 'stale', 'stale']
    assert _extract_code_flags(row) == EXPECTED


@pytest.mark.parametrize('row', [{}, {'audit': None}, {'audit': {}}, {'audit': {'legacy_review': None}},
                                 {'audit': {'legacy_review': {}}}])
def test_neither_source_present_gives_empty_flags_without_error(row):
    assert _extract_code_flags(row) == {'polarity_conflict': [], 'event_not_in_source': [],
                                        'answer_issues': [], 'unverified_lines': 0}


def test_a_hint_on_a_sentence_already_listed_is_not_counted_twice():
    row = _s0_shape()
    legacy = row['audit']['legacy_review']
    legacy['hints'] = [dict(REJECTED), dict(HINT), dict(HINT)]
    assert _extract_code_flags(row)['unverified_lines'] == 2
