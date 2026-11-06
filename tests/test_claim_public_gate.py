import json
import os
import stat

import pytest

from app.agent_workflow import claim_public_gate as gate


def _record(sentences, complete=True):
    return {'turn_id': 't1', 'sources': {'1': {'complete_sent': complete, 'truncated': False}}, 'sentences': sentences}


def _sentence(idx, *, subtype='number', name='', passed=True, verdict='contradiction', reason='REASON-SECRET'):
    return {'idx': idx, 'text': f'句子 {idx}', 'status': 'ok', 'verdict': verdict, 'subtype': subtype,
            'name_span': name, 'quote': 'Holder A removed 21,071,170 shares', 'quote_verified': True,
            'quote_ordinal': 1, 'reason': reason,
            'short_review': {'status': 'ok', 'passed': passed} if passed is not None else None}


def _mark(idx, **kw):
    m = gate.public_annotation(_record([_sentence(idx, **kw)]), _sentence(idx, **kw))
    assert m is not None
    return m


def test_only_verified_contradiction_with_passed_short_review_gets_a_mark():
    assert gate.public_annotation(_record([]), _sentence(0, passed=False)) is None
    assert gate.public_annotation(_record([]), _sentence(0, passed=None)) is None
    assert gate.public_annotation(_record([]), _sentence(0, verdict='not_in_source')) is None
    bad = _sentence(0); bad['quote_verified'] = False
    assert gate.public_annotation(_record([]), bad) is None
    assert gate.public_annotation(_record([]), _sentence(0)) is not None


def test_mark_has_code_template_and_no_judge_free_text():
    mark = _mark(3, subtype='subject', name='BlackRock')
    dumped = json.dumps(mark, ensure_ascii=False)
    assert 'REASON-SECRET' not in dumped
    assert mark['template'] == '来源中这组数据属于另一主体（BlackRock）'
    assert mark['hover']['evidence'] == {'ordinal': 1, 'quote': 'Holder A removed 21,071,170 shares',
                                         'completeness': 'complete'}
    assert mark['marker'] == 'neutral' and mark['hit_kind'] == 'subject'


def test_templates_avoid_fact_check_wording_and_unknown_subtype_falls_back():
    for key, template in gate.TEMPLATES.items():
        rendered = template.format(ordinal=1, name='X')
        assert not any(word in rendered for word in gate.FORBIDDEN_PUBLIC_WORDS), key
    assert _mark(0, subtype=None)['hit_kind'] == 'other'
    assert _mark(0, subtype='subject', name='')['hit_kind'] == 'other'


def test_excerpt_source_is_labelled_as_excerpt():
    mark = gate.public_annotation(_record([], complete=False), _sentence(0))
    assert mark['hover']['evidence']['completeness'] == 'excerpt'


def test_first_ten_need_person_review_then_auto():
    state = gate.new_state()
    marks = [_mark(i) for i in range(10)]
    for m in marks:
        assert gate.submit(state, m) == 'awaiting_human'
        assert not gate.is_public(state, m['id'])
    for i, m in enumerate(marks):
        gate.decide_pre_review(state, m['id'], 'reject' if i == 0 else 'approve')
    assert state['phase'] == 'auto' and state['candidate_false_positives'] == 1
    assert not gate.is_public(state, marks[0]['id'])
    assert gate.is_public(state, marks[1]['id'])
    assert gate.submit(state, _mark(99)) == 'display'


def test_two_confirmed_mislabels_within_window_pause_and_first_does_not():
    state = gate.new_state(); state['phase'] = 'auto'
    marks = [_mark(i) for i in range(5)]
    for m in marks:
        gate.submit(state, m)
    gate.review_displayed(state, marks[0]['id'], 'confirmed_mislabel')
    assert not state['paused'] and len(state['regression']) == 1
    gate.review_displayed(state, marks[1]['id'], 'confirmed_mislabel')
    assert state['paused'] and state['pause_reason']
    assert not gate.is_public(state, marks[2]['id'])
    assert gate.submit(state, _mark(50)) == 'shadow_only'


def test_unreviewed_displays_do_not_dilute_and_old_mislabels_leave_the_window():
    state = gate.new_state(); state['phase'] = 'auto'
    first = _mark(0); gate.submit(state, first)
    gate.review_displayed(state, first['id'], 'confirmed_mislabel')
    for i in range(1, 21):
        m = _mark(i); gate.submit(state, m); gate.review_displayed(state, m['id'], 'ok')
    assert not state['paused']  # the old mislabel has left the latest 20 reviewed marks
    later = _mark(30); gate.submit(state, later); gate.review_displayed(state, later['id'], 'confirmed_mislabel')
    assert not state['paused']
    unreviewed = [_mark(40 + i) for i in range(18)]
    for m in unreviewed:
        gate.submit(state, m)
    nxt = _mark(60); gate.submit(state, nxt); gate.review_displayed(state, nxt['id'], 'confirmed_mislabel')
    assert state['paused']


def test_resume_needs_replay_reference_and_is_recorded():
    state = gate.new_state(); state['phase'] = 'auto'; state['paused'] = True; state['pause_reason'] = 'x'
    with pytest.raises(ValueError):
        gate.resume(state, replay_ref='', note='n')
    gate.resume(state, replay_ref='replay-r7', note='frozen set re-run')
    assert not state['paused'] and state['resumes'][0]['replay_ref'] == 'replay-r7'


def test_state_file_is_private_and_round_trips(tmp_path):
    state = gate.new_state()
    path = tmp_path / 'gate.json'
    gate.save_state(path, state)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert gate.load_state(path) == state
