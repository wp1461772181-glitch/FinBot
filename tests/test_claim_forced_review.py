import importlib.util
import json
from collections import Counter
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'claim_forced_review', Path(__file__).resolve().parents[1] / 'scripts' / 'claim_forced_review.py')
forced = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forced)


def test_honest_twins_are_twenty_per_kind_and_quote_their_own_source():
    cases = forced.build_s4()
    assert len(cases) == 6 * 20
    assert Counter(c['kind'] for c in cases) == {kind: 20 for kind in forced.TWIN_KINDS}
    for case in cases:
        source = case['sources'][0]
        assert source.ordinal == case['quote_ordinal'] == 1
        assert case['quote'] in source.text
        assert case['context'] == ''


def test_neighbour_context_takes_at_most_two_sentences_each_side_in_idx_order():
    seq = [(i, f's{i}') for i in range(6)]
    assert forced._neighbour_context(seq, 0) == 's1\ns2'
    assert forced._neighbour_context(seq, 3) == 's1\ns2\ns4\ns5'


def test_control_quote_is_the_line_with_the_q2_period(tmp_path):
    pack = [{'id': 'practice-C2-00', 'class': 'C2', 'sentence': '2026年第二季度变动为下降约 12.3% [1]',
             'sources': [{'ordinal': 1, 'text': '| Period | Change % |\n|---|---|\n| Q2 2026 | −12.3% |',
                          'source_type': 'web', 'complete': True}]},
            {'id': 'practice-T1-00', 'class': 'T1', 'sentence': 'ignored', 'sources': []}]
    path = tmp_path / 'pack.json'
    path.write_text(json.dumps(pack, ensure_ascii=False), encoding='utf-8')
    cases = forced.build_s2(path)
    assert [c['id'] for c in cases] == ['practice-C2-00']
    assert cases[0]['quote'] == '| Q2 2026 | −12.3% |'
    assert cases[0]['quote'] in pack[0]['sources'][0]['text']
