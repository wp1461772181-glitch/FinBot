import json
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent_workflow.citation_issuance import CitationIssuer
from app.agent_workflow.flex_number_review import (
    Evidence, positions, review_offline, run_shadow, unit_of_text, verify, verify_pairs)


def sid(ev, raw):
    return next(k for k, v in ev.spans.items() if v['type'] == 'N' and v['raw'] == raw)


def uid(ev, raw):
    return next(k for k, v in ev.spans.items() if v['type'] == 'U' and v['raw'] == raw)


def pos(text, index=0):
    return positions(text)[index]


def stub(replies):
    calls = []

    async def call(model, system, user):
        calls.append(json.loads(user))
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return {}, {'content': json.dumps(reply, ensure_ascii=False)}
    return call, calls


def test_microsoft_difference_and_uncertain_relation_still_replays():
    ev = Evidence({'1': 'Revenue 900.07 亿美元 and 764.41 亿美元'})
    nodes = [{'id': 'a', 'span': sid(ev, '900.07 亿美元')}, {'id': 'b', 'span': sid(ev, '764.41 亿美元')},
             {'id': 'diff', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': 'USD'}]
    item = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': nodes, 'result_node': 'diff'}
    assert verify(item, pos('135.7 亿'), ev)['status'] == 'supported'
    item['relation'] = 'uncertain'
    out = verify(item, pos('135.7 亿'), ev)
    assert out['reason'] == 'relation_unconfirmed'
    assert Decimal(out['computed_value']) == Decimal('13566000000')


@pytest.mark.parametrize('value,written', [('19,171', '191.71 亿'), ('27,461', '274.61 亿'), ('51,313', '513.13 亿')])
def test_amazon_conversion_with_declared_unit_and_tenfold_error(value, written):
    ev = Evidence({'29': 'Amounts in millions. Operating income 19,171 27,461 37,576 51,313'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
            'span': sid(ev, value), 'unit_span': uid(ev, 'millions')}
    assert verify(item, pos(written), ev)['status'] == 'supported'
    tenfold = format(Decimal(written.split()[0]) / 10, 'f') + ' 亿'
    out = verify(item, pos(tenfold), ev)
    assert out['status'] == 'finding' and out['error_type'] == 'magnitude'


def test_unit_must_come_from_a_declaration_not_from_guessing():
    ev = Evidence({'29': 'Amounts in millions. Operating income 19,171'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '19,171')}
    # No unit chosen: the plain number cannot be compared with a 亿 figure, and a mismatch is not a finding.
    out = verify(item, pos('191.71 亿'), ev)
    assert out['reason'] == 'unit_binding_unconfirmed' and out['status'] == 'incomplete'
    item['span'] = 'N29-99'
    assert verify(item, pos('191.71 亿'), ev)['reason'] == 'span_id_unknown'
    item['span'] = sid(ev, '19,171'); item['unit_span'] = 'U29-99'
    assert verify(item, pos('191.71 亿'), ev)['reason'] == 'unit_span_unknown'


def test_tesla_multistep_unit_propagation_and_same_quantity_pair():
    ev = Evidence({'1': 'Net income 3,794 million USD; EPS 1.08 USD; price 358.22 USD'})
    nodes = [{'id': 'income', 'span': sid(ev, '3,794 million USD')}, {'id': 'eps', 'span': sid(ev, '1.08 USD')},
             {'id': 'price', 'span': sid(ev, '358.22 USD')},
             {'id': 'shares', 'expression': 'a/b', 'inputs': {'a': 'income', 'b': 'eps'}, 'unit': 'shares'},
             {'id': 'cap', 'expression': 'a*b', 'inputs': {'a': 'shares', 'b': 'price'}, 'unit': 'USD'}]
    good = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': nodes, 'result_node': 'cap'}
    assert verify(good, pos('1.26 万亿美元'), ev)['status'] == 'supported'
    wrong = verify(good, pos('1,258.4 亿美元'), ev)
    assert wrong['status'] == 'finding' and wrong['reason'] == 'arithmetic_difference' and wrong['error_type'] == 'magnitude'

    answer = '推算市值 1,258.4 亿美元，即约 1.26 万亿美元'
    by_id = {p['id']: verify({}, p, ev) for p in positions(answer)}
    pairs = [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['1,258.4 亿美元', '1.26 万亿美元'], 'explanation': '同一市值'}]
    findings, records = verify_pairs(pairs, by_id, answer)
    assert findings and findings[0]['reason'] == 'internal_inconsistency' and findings[0]['ids'] == [0, 1]
    assert records[0]['status'] == 'finding'
    assert verify_pairs([{**pairs[0], 'relation': 'different'}], by_id, answer) == ([], [{'a': 0, 'b': 1,
                         'relation': 'different', 'explanation': '同一市值', 'status': 'not_same'}])
    bad_witness = [{**pairs[0], 'witness': ['2,000 亿美元']}]
    assert verify_pairs(bad_witness, by_id, answer)[0] == []
    assert verify_pairs(bad_witness, by_id, answer)[1][0]['status'] == 'witness_missing'


def test_pair_intervals_use_each_figures_own_display_precision():
    answer = '市值 1.26 万亿美元，约 1.2584 万亿美元'
    by_id = {p['id']: verify({}, p, Evidence({})) for p in positions(answer)}
    consistent = [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['1.26 万亿美元']}]
    assert verify_pairs(consistent, by_id, answer)[0] == []
    assert verify_pairs(consistent, by_id, answer)[1][0]['status'] == 'consistent'


def test_answer_sign_and_source_sign_are_kept_before_comparison():
    ev = Evidence({'1': 'removed 21,071,170 shares (-4.7%) from their portfolio; 昨日涨跌幅 -4.41%'})
    # Answer "（-4.7%）": the sign is written in the answer, so it must reach the comparison.
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '-4.7%')}
    assert verify(item, pos('（-4.7%）'), ev)['status'] == 'supported'
    # An unsigned answer "4.7%" with no declared direction is not a sign finding: the sign is re-asked.
    assert verify(item, pos('4.7%'), ev)['reason'] == 'sign_unconfirmed'
    assert verify(item, pos('+4.7%'), ev)['status'] == 'finding'
    # "跌了 4.41%": the direction is in the words; the model supplies answer_sign and the sign is kept.
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '-4.41%')}
    assert verify({**item, 'answer_sign': '-'}, pos('昨日跌了 4.41%'), ev)['status'] == 'supported'
    # Without an answer_sign the decline is not declared on the answer side: re-ask, not a finding.
    assert verify(item, pos('昨日跌了 4.41%'), ev)['reason'] == 'sign_unconfirmed'


def test_sign_only_difference_is_a_finding_only_when_both_sides_declare_direction():
    ev = Evidence({'13': 'client revenue to decline more than 20% sequentially; guidance down to 38%; +4.41% close; '
                         '-4.41% open'})
    unsigned = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '20%')}
    # Answer reads a decline into "降超 20%" but the evidence does not declare one: re-ask, not a finding.
    out = verify({**unsigned, 'answer_sign': '-'}, pos('营收降超 20%'), ev)
    assert out['reason'] == 'sign_unconfirmed' and out['status'] == 'incomplete'
    # Both sides declare the decline: consistent, supported.
    assert verify({**unsigned, 'sign': '-', 'answer_sign': '-'}, pos('营收降超 20%'), ev)['status'] == 'supported'
    # A level, not a change: no answer_sign, so the unsigned 38% is simply 38%.
    assert verify({**unsigned, 'span': sid(ev, '38%')}, pos('降至 38%'), ev)['status'] == 'supported'
    # Both explicit and opposite: a real sign finding.
    opposite = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '+4.41%')}
    out = verify({**opposite, 'answer_sign': '-'}, pos('跌了 4.41%'), ev)
    assert out['status'] == 'finding' and out['error_type'] == 'sign'
    # A computed value's sign is the expression's direction: a sign-only mismatch there is re-asked, never a finding.
    nodes = [{'id': 'a', 'span': sid(ev, '+4.41%')}, {'id': 'b', 'span': sid(ev, '-4.41%')},
             {'id': 'd', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': '%'}]
    derived = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': nodes,
               'result_node': 'd', 'answer_sign': '-'}
    assert verify(derived, pos('跌了 8.82%'), ev)['reason'] == 'sign_unconfirmed'


def test_scale_b_and_dollar_parse_and_magnitude_error_is_classified():
    ev = Evidence({'4': 'Implied market cap may vary.$899.74B'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '$899.74B')}
    out = verify(item, pos('市值 $8,997.4B'), ev)
    assert out['status'] == 'finding' and out['reason'] == 'numeric_difference' and out['error_type'] == 'magnitude'
    assert out['source']['raw'] == '$899.74B'


@pytest.mark.parametrize('raw,written', [('242 million shares', '242 万股'), ('210.5 million', '210.5 万股')])
def test_share_count_magnitude_error_on_both_figures_of_one_sentence(raw, written):
    ev = Evidence({'12': 'approximately 242 million shares; 210.5 million new shares'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, raw)}
    out = verify(item, pos(written), ev)
    assert out['status'] == 'finding' and out['error_type'] == 'magnitude'


def test_dates_and_periods_are_objects_not_positions():
    text = '11-03 盘前 2026-11-05 07:17AM Nov 5, 2026 Q2 2026 截至 2026年 3 月 涨超3%'
    assert [p['figure'] for p in positions(text)] == ['3%']


def test_arithmetic_without_settled_relation_never_becomes_a_finding():
    ev = Evidence({'1': 'Revenue 900.07 亿美元 and 764.41 亿美元'})
    nodes = [{'id': 'a', 'span': sid(ev, '900.07 亿美元')}, {'id': 'b', 'span': sid(ev, '764.41 亿美元')},
             {'id': 'diff', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': 'USD'}]
    item = {'binding': 'derived', 'responsibility': 'current', 'relation': 'uncertain', 'nodes': nodes, 'result_node': 'diff'}
    out = verify(item, pos('营收增加 9 亿美元'), ev)
    assert out['status'] == 'incomplete' and out['reason'] == 'relation_unconfirmed' and 'computed_value' in out


def test_a_self_correction_reply_takes_its_last_complete_object():
    from app.agent_workflow.flex_number_review import _parse_reply
    first = '{"results": [{"id": 0, "binding": "none"}], "pairs": [{"a": 3, "b": 4, "relation": "same"}]}'
    second = '{"results": [{"id": 0, "binding": "direct"}, {"id": 1, "binding": "direct"}], "pairs": []}'
    parsed = _parse_reply(f'{first}\n\n更正：\n\n{second}')
    assert [r['id'] for r in parsed['results']] == [0, 1] and parsed['pairs'] == []
    assert _parse_reply('no json here') is None


def test_calculation_accepts_a_declared_span_as_an_implicit_leaf_and_names_unknown_inputs():
    ev = Evidence({'1': 'close 224.58 and 200.13'})
    expr = {'id': 'r', 'expression': '(b - a) / a', 'inputs': {'a': sid(ev, '224.58'), 'b': sid(ev, '200.13')}, 'unit': '%'}
    item = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': [expr], 'result_node': 'r',
            'answer_sign': '-'}
    out = verify(item, pos('下跌约 10.9%'), ev)
    assert out['status'] == 'supported' and out['steps'][0]['implicit_leaf'] is True
    bad = {**item, 'nodes': [{**expr, 'inputs': {'a': 'N1-99', 'b': sid(ev, '200.13')}}]}
    assert verify(bad, pos('下跌约 10.9%'), ev)['reason'] == 'calculation_inputs_unknown'


def test_none_and_insufficient_are_legitimate_answers_not_technical_failures():
    from app.agent_workflow.flex_number_review import TECHNICAL
    ev = Evidence({'1': 'x 1'})
    assert verify({'binding': 'none', 'responsibility': 'current'}, pos('64.53%'), ev)['reason'] == 'no_binding'
    assert verify({'binding': 'insufficient', 'responsibility': 'current'}, pos('64.53%'), ev)['reason'] == 'insufficient_material'
    assert 'no_binding' not in TECHNICAL and 'insufficient_material' not in TECHNICAL


def test_historical_responsibility_and_citation_issuance():
    ev = Evidence({'28': 'Market cap 741.38 亿美元 as of 2024-07-31', '27': 'PE ratio 23.83 as of 2026-09-30'})
    item = {'binding': 'direct', 'responsibility': 'historical', 'relation': 'same', 'span': sid(ev, '741.38 亿美元')}
    assert verify(item, pos('741.38 亿'), ev)['responsibility'] == 'historical'
    item['responsibility'] = 'current'
    assert verify(item, pos('741.38 亿'), ev)['responsibility'] == 'current'
    issuer = CitationIssuer({'28': 'Market cap 741.38', '27': 'PE ratio 23.83'}); issuer.register_block('b1', 1)
    issue = issuer.issue({'anchor': {'block_id': 'b1', 'revision': 1}, 'source_ref': '27', 'quote': 'PE ratio 23.83'})
    assert issue['ok'] and issue['item']['source_ref'] == '27'
    assert issuer.issue({'anchor': {'block_id': 'b1', 'revision': 1}, 'source_ref': '28', 'quote': 'fabricated'})['error'] == 'quote_not_in_snapshot'
    assert [p['figure'] for p in positions('营业利润 191.71 [28→注]')] == ['191.71']


def test_unit_of_text_reads_dimension_only():
    assert unit_of_text('USD') == {'cur': 'USD', 'kind': 'amount'}
    assert unit_of_text('shares') == {'cur': None, 'kind': 'shares'}
    assert unit_of_text('USD/share')['kind'] == 'per_share'
    assert unit_of_text('%')['kind'] == 'ratio'
    assert unit_of_text('') is None


def test_retry_carries_receipt_and_withdrawn_pairs_are_replaced(tmp_path):
    ev_text = {'1': 'Market cap 1,258.4 亿美元 (1.26 万亿美元)'}
    answer = '推算市值 1,258.4 亿美元，即约 1.26 万亿美元'
    e = Evidence(ev_text)
    bad = {'results': [{'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': 'N9-9'},
                       {'id': 1, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': 'N9-9'}],
           'pairs': [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['1,258.4 亿美元', '1.26 万亿美元']}]}
    good = {'results': [{'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                         'span': sid(e, '1,258.4 亿美元')},
                        {'id': 1, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                         'span': sid(e, '1.26 万亿美元')}],
            'pairs': []}
    call, calls = stub([bad, good])
    out = asyncio.run(review_offline(answer, ev_text, {'api_key': 'x'}, call=call))
    assert len(calls) == 2
    assert 'retry' not in calls[1]
    receipt = {r['id']: r for r in calls[1]['receipt']}
    assert set(receipt) == {0, 1}
    assert receipt[0]['reason'] == 'span_id_unknown' and receipt[0]['previous']['span'] == 'N9-9'
    assert any(c['raw'] == '1,258.4 亿美元' for c in receipt[0]['candidates']['number_spans'])
    assert out['pairs'] == [] and not [f for f in out['findings'] if f['reason'] == 'internal_inconsistency']
    assert [r['status'] for r in out['results']] == ['supported', 'supported']


def test_offline_trace_keeps_request_reply_binding_and_relation():
    ev_text = {'1': 'Revenue 900.07 亿美元'}
    e = Evidence(ev_text)
    reply = {'results': [{'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                          'span': sid(e, '900.07 亿美元'), 'explanation': '营收'}], 'pairs': []}
    call, _ = stub([reply])
    out = asyncio.run(review_offline('营收 900.07 亿美元', ev_text, {'api_key': 'x'}, call=call))
    kinds = [t['kind'] for t in out['trace']]
    assert kinds == ['request', 'response', 'parsed']
    assert out['trace'][1]['raw_response'] and out['trace'][0]['payload']['sources'][0]['text']
    r = out['results'][0]
    assert r['status'] == 'supported' and r['kind'] == 'direct' and r['selection']['span'] == sid(e, '900.07 亿美元')


def test_shadow_retries_and_saves_invalid_raw_without_public_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv('FLEX_NUMBER_SHADOW', 'on'); monkeypatch.setenv('CLAIM_JUDGE_SHADOW_DIR', str(tmp_path))
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_MODEL', 'test')
    calls = []

    async def call(model, system, user):
        calls.append(json.loads(user))
        return {}, {'content': 'invalid json'}

    async def resolve(name): return {'api_key': 'x'}
    turn = SimpleNamespace(owner=True, state={'turn_id': 't'}, citations=[])
    result0 = {'answer': 'Revenue 135.7', 'unverified_lines': []}
    asyncio.run(run_shadow(turn, result0, call=call, resolve=resolve))
    assert len(calls) == 2 and 'retry' not in calls[1] and calls[1]['receipt'][0]['reason'] == 'no_answer'
    rows = [json.loads(line) for line in next((tmp_path / 'flex-numbers').glob('*.jsonl')).read_text().splitlines()]
    assert [r['raw_response'] for r in rows if r['kind'] == 'response'] == ['invalid json'] * 2
    assert rows[-1]['pending_ids'] == [0] and result0 == {'answer': 'Revenue 135.7', 'unverified_lines': []}


def test_shadow_daily_budget_limits_attempts_and_records_skip(tmp_path, monkeypatch):
    monkeypatch.setenv('FLEX_NUMBER_SHADOW', 'on')
    monkeypatch.setenv('FLEX_NUMBER_DAILY_CALL_LIMIT', '1')
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_DIR', str(tmp_path))
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_MODEL', 'test')
    calls = []

    async def call(*args):
        calls.append(1)
        return {}, {'content': 'invalid'}

    async def resolve(name): return {'api_key': 'x'}
    turn = SimpleNamespace(owner=True, state={}, citations=[])
    asyncio.run(run_shadow(turn, {'answer': 'Revenue 123'}, call=call, resolve=resolve))
    rows = [json.loads(line) for line in next((tmp_path / 'flex-numbers').glob('*.jsonl')).read_text().splitlines()]
    assert len(calls) == 1
    assert rows[-1]['status'] == 'budget_exhausted'
    assert rows[-1]['pending_ids'] == [0]


def test_shadow_scheduling_does_not_wait_for_review(monkeypatch):
    from app.agent_workflow import flex_number_review as flex
    monkeypatch.setenv('FLEX_NUMBER_SHADOW', 'on')

    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        captured = []

        async def slow(turn, result):
            captured.append((turn, result))
            started.set()
            await release.wait()
        monkeypatch.setattr(flex, 'run_shadow', slow)
        turn = SimpleNamespace(owner=True, state={'turn_id': 'one'}, citations=[])
        result = {'answer': '123'}
        flex.schedule_shadow(turn, result)
        result['answer'] = 'changed'
        await started.wait()
        assert captured[0][1]['answer'] == '123'
        assert flex._TASKS
        release.set()
        await asyncio.gather(*list(flex._TASKS))
    asyncio.run(check())
