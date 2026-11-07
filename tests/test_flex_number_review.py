import json
import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent_workflow.citation_issuance import CitationIssuer
from app.agent_workflow.flex_number_review import (
    Evidence, positions, review_offline, run_shadow, unit_of_text, verify as raw_verify, verify_pairs)
from app.agent_workflow.flex_number_review import _written


def verify(item, position, evidence):
    # Existing model stubs interpret the answer as its literal parsed value by default.
    item = dict(item)
    if "answer_value" not in item:
        value = _written(position, item.get("answer_sign"))
        item.update(answer_value=str(value["value"]), answer_quantum=str(value["quantum"]))
    return raw_verify(item, position, evidence)


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


def test_selected_unit_declaration_must_exist():
    ev = Evidence({'29': 'Amounts in millions. Operating income 19,171'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '19,171')}
    # The model chooses the unit; code checks the selected declaration.
    item['unit_span'] = uid(ev, 'millions')
    assert verify(item, pos('191.71 亿'), ev)['status'] == 'supported'
    item.pop('unit_span')
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
    # The model did not supply a direction, so the comparison uses the literal unsigned value.
    assert verify(item, pos('4.7%'), ev)['status'] == 'finding'
    assert verify(item, pos('+4.7%'), ev)['status'] == 'finding'
    # "跌了 4.41%": the direction is in the words; the model supplies answer_sign and the sign is kept.
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '-4.41%')}
    assert verify({**item, 'answer_sign': '-'}, pos('昨日跌了 4.41%'), ev)['status'] == 'supported'
    # Without answer_sign, the literal unsigned value is compared.
    assert verify(item, pos('昨日跌了 4.41%'), ev)['status'] == 'finding'


def test_model_selected_direction_is_used_in_comparison():
    ev = Evidence({'13': 'client revenue to decline more than 20% sequentially; guidance down to 38%; +4.41% close; '
                         '-4.41% open'})
    unsigned = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '20%')}
    # The model-selected answer direction is used in the comparison.
    out = verify({**unsigned, 'answer_sign': '-'}, pos('营收降超 20%'), ev)
    assert out['status'] == 'finding'
    # Both sides declare the decline: consistent, supported.
    assert verify({**unsigned, 'sign': '-', 'answer_sign': '-'}, pos('营收降超 20%'), ev)['status'] == 'supported'
    # A level, not a change: no answer_sign, so the unsigned 38% is simply 38%.
    assert verify({**unsigned, 'span': sid(ev, '38%')}, pos('降至 38%'), ev)['status'] == 'supported'
    # Both explicit and opposite: a real sign finding.
    opposite = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '+4.41%')}
    out = verify({**opposite, 'answer_sign': '-'}, pos('跌了 4.41%'), ev)
    assert out['status'] == 'finding' and out['error_type'] == 'sign'
    # Computed direction follows the model's expression and answer interpretation.
    nodes = [{'id': 'a', 'span': sid(ev, '+4.41%')}, {'id': 'b', 'span': sid(ev, '-4.41%')},
             {'id': 'd', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': '%'}]
    derived = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': nodes,
               'result_node': 'd', 'answer_sign': '-'}
    assert verify(derived, pos('跌了 8.82%'), ev)['status'] == 'finding'


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


# ---- Round 5 (Haiku flex5, defects D1-D7 from the 2026-11-07 reproduction set) ----

from app.agent_workflow import flex_number_review as flex  # noqa: E402


def _dispatch(main_replies, challenge_reply=None, challenge_raise=False):
    """Stub by system prompt: main review replies in order; one challenge reply (or a failure)."""
    calls = {'main': [], 'challenge': []}

    async def call(model, system, user):
        if system == flex.CHALLENGE_PROMPT:
            calls['challenge'].append(json.loads(user))
            if challenge_raise:
                raise RuntimeError('provider down')
            content = challenge_reply if isinstance(challenge_reply, str) else json.dumps(challenge_reply, ensure_ascii=False)
            return {}, {'content': content}
        calls['main'].append(json.loads(user))
        reply = json.loads(json.dumps(main_replies[min(len(calls['main']) - 1, len(main_replies) - 1)]))
        parsed_positions = {p['id']: p for p in positions(calls['main'][-1]['answer'])}
        existing = {r['id'] for r in reply.get('results', [])}
        for pair in reply.get('pairs', []):
            for ident in (pair.get('a'), pair.get('b')):
                if ident in parsed_positions and ident not in existing:
                    reply.setdefault('results', []).append({'id': ident})
                    existing.add(ident)
        for result in reply.get('results', []):
            if result.get('id') in parsed_positions and 'answer_value' not in result:
                value = _written(parsed_positions[result['id']], result.get('answer_sign'))
                result.update(answer_value=str(value['value']), answer_quantum=str(value['quantum']))
        return {}, {'content': json.dumps(reply, ensure_ascii=False)}
    return call, calls


def test_D4_glued_word_before_digits_keeps_the_number_and_codes_stay_out():
    ev = Evidence({'3': 'Dividend yield2.19% and COVID19 and Q4 cut 3%'})
    assert sorted(v['raw'] for v in ev.spans.values() if v['type'] == 'N') == ['2.19%', '3%']
    assert [p['figure'] for p in positions('股息率 yield2.19%')] == ['2.19%']
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '2.19%')}
    assert verify(item, pos('股息率 2.19%'), ev)['status'] == 'supported'


def test_D2_comparison_uses_both_sides_display_precision_not_only_the_answers():
    ev = Evidence({'5': 'Oracle shares fell 5% on the day'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '5%')}
    # The source states 5% (display precision 1 point); 5.48% lies inside that rounding interval: no difference.
    assert verify(item, pos('下跌 5.48%'), ev)['status'] == 'supported'
    # A real difference outside both intervals is still a finding.
    assert verify(item, pos('下跌 5.9%'), ev)['status'] == 'finding'


def test_D1_range_lower_end_inherits_the_shared_unit_of_the_range():
    answer = '营收 150–160 亿美元'
    ev = Evidence({'28': 'Q4 revenue guidance $15 billion to $16 billion'})
    lo, hi = positions(answer)
    assert lo['figure'] == '150' and lo['quantity']['cur'] == 'USD' and lo['quantity']['kind'] == 'amount'
    assert verify({'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                   'span': sid(ev, '$15 billion')}, lo, ev)['status'] == 'supported'
    assert verify({'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                   'span': sid(ev, '$16 billion')}, hi, ev)['status'] == 'supported'


def test_model_interprets_unitless_answer_from_context():
    ev = Evidence({'28': 'iPhone revenue was $57.6 billion for the quarter'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '$57.6 billion')}
    out = verify({**item, 'answer_value': '57600000000', 'answer_quantum': '100000000'}, pos('占比 = 57.6 ÷ 114.5'), ev)
    assert out['status'] == 'supported'


def test_D1_dimensionless_figures_still_compare_both_ways():
    ev = Evidence({'1': 'The filing lists 4 patents granted'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '4')}
    assert verify(item, pos('获得 3 项专利'), ev)['status'] == 'finding'
    assert verify(item, pos('获得 4 项专利'), ev)['status'] == 'supported'


def test_model_selected_pairs_are_compared():
    answer = '共 3 家，即 4 家'
    by_id = {p['id']: verify({}, p, Evidence({})) for p in positions(answer)}
    findings, records = verify_pairs([{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['3 家', '4 家']}], by_id, answer)
    assert findings and findings[0]['reason'] == 'internal_inconsistency'
    answer = '市值 1.26 万亿美元，即 1.2584'
    by_id = {p['id']: verify({}, p, Evidence({})) for p in positions(answer)}
    findings, records = verify_pairs([{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['1.26 万亿美元']}], by_id, answer)
    assert findings and records[0]['status'] == 'finding'


def test_D5_model_interpretation_keeps_consistent_pair_supported():
    answer = '营收 900.07 亿美元，即 900.07'
    text = {'1': 'Revenue 900.07 亿美元 for the quarter'}
    e = Evidence(text)
    reply = {'results': [
        {'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(e, '900.07 亿美元')},
        {'id': 1, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(e, '900.07 亿美元'), 'answer_value': '90007000000', 'answer_quantum': '1000000'}],
        'pairs': [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['900.07 亿美元', '900.07']}]}
    call, _ = _dispatch([reply])
    out = asyncio.run(review_offline(answer, text, {'api_key': 'x'}, call=call))
    assert out['findings'] == []
    assert [r['status'] for r in out['results']] == ['supported', 'supported']
    assert out['pairs'][0]['status'] == 'consistent'


def test_D5_bare_figures_paired_as_one_quantity_are_challenged_not_gated_by_units():
    answer = '占比 = 57.6 ÷ 114.5'
    text = {'28': 'iPhone revenue was $57.6 billion; Today revenue of 114.5 billion dollars'}
    e = Evidence(text)
    reply = {'results': [
        {'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(e, '$57.6 billion'), 'answer_value': '57600000000', 'answer_quantum': '100000000'},
        {'id': 1, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(e, '114.5 billion'), 'answer_value': '114500000000', 'answer_quantum': '100000000'}],
        'pairs': [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['57.6', '114.5']}]}
    # Both figures are bare: the pair is a plain-number comparison, so it reaches the challenge; withdrawn, it is not kept.
    call, calls = _dispatch([reply], {'challenges': [{'candidate': 1, 'verdict': 'withdraw', 'reason': '不同数量'}]})
    out = asyncio.run(review_offline(answer, text, {'api_key': 'x'}, call=call))
    assert out['findings'] == []
    assert [r['status'] for r in out['results']] == ['supported', 'supported']
    assert out['pairs'][0]['status'] == 'disagreement'
    assert len(calls['challenge']) == 1


def test_D3_declared_scale_with_a_qualifier_applies_only_where_the_model_says_so():
    ev = Evidence({'33': 'Amounts in millions, except per share data. Diluted EPS 2.46 1.08 4.85'})
    unit = uid(ev, 'millions')
    assert ev.spans[unit]['qualifier'] == {'text': 'per share data'}
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '2.46'), 'unit_span': unit}
    assert verify(item, pos('稀释 EPS 为 2.46 美元'), ev)['status'] == 'finding'
    assert verify({**item, 'unit_excepted': True}, pos('稀释 EPS 为 2.46 美元'), ev)['status'] == 'supported'
    # A declaration with no qualifier has no exception to apply: the flag is ignored, the scale still applies.
    plain = Evidence({'29': 'Amounts in millions. Operating income 19,171'})
    item2 = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(plain, '19,171'),
             'unit_span': uid(plain, 'millions'), 'unit_excepted': True}
    assert verify(item2, pos('191.71 亿'), plain)['status'] == 'supported'


def test_D3_chinese_qualifier_is_parsed_into_the_declaration():
    ev = Evidence({'3': '单位：百万美元，每股数据除外。每股收益 2.46'})
    assert ev.spans[uid(ev, '百万美元')]['qualifier'] == {'text': '每股数据'}


def test_D6_only_a_confirmed_difference_stays_a_finding():
    ev_text = {'1': 'Revenue 900.07 亿美元'}
    e = Evidence(ev_text)
    reply = {'results': [{'id': 0, 'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
                          'span': sid(e, '900.07 亿美元')}], 'pairs': []}
    cases = {
        'confirm': ({'challenges': [{'candidate': 1, 'verdict': 'confirm', 'reason': '同一营收'}]}, 'finding', None),
        'withdraw': ({'challenges': [{'candidate': 1, 'verdict': 'withdraw', 'reason': '不同期间'}]}, 'disagreement', 'challenge_disagreement'),
        'unconfirmed': ({'challenges': [{'candidate': 1, 'verdict': 'unconfirmed', 'reason': '依据不足'}]}, 'doubt', 'challenge_unconfirmed'),
        'missing': ({'challenges': []}, 'doubt', 'challenge_unconfirmed'),
        'old_vocabulary': ({'challenges': [{'candidate': 1, 'verdict': 'keep'}]}, 'doubt', 'challenge_unconfirmed'),
        'not_json': ('not json at all', 'doubt', 'challenge_unconfirmed'),
    }
    for name, (challenge, status, reason) in cases.items():
        call, _ = _dispatch([reply], challenge)
        out = asyncio.run(review_offline('营收 9.7 亿美元', ev_text, {'api_key': 'x'}, call=call))
        r = out['results'][0]
        assert r['status'] == status, name
        assert (r['reason'] if status != 'finding' else None) == reason, name
        assert r['status'] != 'supported', name
    call, _ = _dispatch([reply], challenge_raise=True)
    out = asyncio.run(review_offline('营收 9.7 亿美元', ev_text, {'api_key': 'x'}, call=call))
    assert out['results'][0]['reason'] == 'challenge_unconfirmed' and out['findings'] == []


def test_D6_challenge_input_carries_unit_basis_and_calculation_steps():
    ev_text = {'1': 'Revenue 900.07 亿美元 and 764.41 亿美元'}
    e = Evidence(ev_text)
    nodes = [{'id': 'a', 'span': sid(e, '900.07 亿美元')}, {'id': 'b', 'span': sid(e, '764.41 亿美元')},
             {'id': 'diff', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': 'USD'}]
    reply = {'results': [{'id': 0, 'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': nodes,
                          'result_node': 'diff'}], 'pairs': []}
    call, calls = _dispatch([reply], {'challenges': [{'candidate': 1, 'verdict': 'confirm'}]})
    asyncio.run(review_offline('营收增加 9 亿美元', ev_text, {'api_key': 'x'}, call=call))
    cand = calls['challenge'][0]['candidates'][0]
    assert len(cand['steps']) >= 3 and Decimal(cand['computed_value']) == Decimal('13566000000')
    assert cand['written_unit']['kind'] == 'amount' and cand['written_unit']['cur'] == 'USD'
    assert 'source' in cand and 'figure' in cand and 'explanation' in cand


def test_D7_pair_challenge_view_gives_each_side_its_figure_and_unit_basis():
    answer = '去年同期 36.70 亿美元，本期 11.30 亿美元'
    ev_text = {'27': 'interest and other income of 36.70 and 11.30'}
    reply = {'results': [], 'pairs': [{'a': 0, 'b': 1, 'relation': 'same', 'witness': ['36.70 亿美元', '11.30 亿美元'],
                                       'explanation': '利息及其他'}]}
    call, calls = _dispatch([reply], {'challenges': [{'candidate': 1, 'verdict': 'withdraw'}]})
    out = asyncio.run(review_offline(answer, ev_text, {'api_key': 'x'}, call=call))
    assert out['pairs'][0]['status'] == 'disagreement'
    view = calls['challenge'][0]['candidates'][0]
    assert view['figures'] == ['36.70 亿美元', '11.30 亿美元']
    assert [(u['kind'], u['cur']) for u in view['written_units']] == [('amount', 'USD'), ('amount', 'USD')]


def test_D7_prompts_name_the_pair_pitfalls_the_model_must_judge():
    for needle in ('同比', '中心值', '指引', '被减数'):
        assert needle in flex.PROMPT and needle in flex.CHALLENGE_PROMPT


def test_D8_month_slash_range_rank_period_and_form_tokens_are_not_positions():
    text = ('10 月议息会、9 月纪要、11/03 盘前、24/7 Wall St、第 20 大、过去 5 天、10-Q 申报、'
            'December 8-9 加息、Dec 2025 财报、涨超3%')
    assert [p['figure'] for p in positions(text)] == ['3%']


def test_D8_a_date_range_leaves_no_negative_residue_in_a_source():
    ev = Evidence({'6': 'FOMC December 8-9 meeting; dividend yield2.19%'})
    assert sorted(v['raw'] for v in ev.spans.values() if v['type'] == 'N') == ['2.19%']


def test_D8_a_slash_pair_is_a_date_only_when_it_reads_as_month_and_day():
    # "59/60 位分析师" is a count of analysts, not a date: both figures stay positions.
    assert [p['figure'] for p in positions('59/60 位分析师给予买入评级')] == ['59', '60']


def test_open_quote_binding_checks_snapshot_and_keeps_model_interpretation():
    ev = Evidence({'7': 'roughly two out of every five stocks rose'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same',
            'source_ref': '7', 'quote': 'two out of every five', 'value': '0.4', 'quantum': '0',
            'explanation': 'two fifths'}
    out = verify(item, pos('40%'), ev)
    assert out['status'] == 'supported' and out['source']['raw'] == item['quote']
    assert verify({**item, 'source_ref': '8'}, pos('40%'), ev)['reason'] == 'quote_unverified'
    assert verify({**item, 'quote': 'invented'}, pos('40%'), ev)['reason'] == 'quote_unverified'


def test_open_calculation_records_bound_leaves_across_sources():
    ev = Evidence({'1': 'close=385.19', '2': 'decreased $9.38'})
    item = {'binding': 'derived', 'responsibility': 'current', 'relation': 'same', 'nodes': [
        {'id': 'a', 'source_ref': '1', 'quote': 'close=385.19', 'value': '385.19'},
        {'id': 'b', 'source_ref': '2', 'quote': 'decreased $9.38', 'value': '9.38'},
        {'id': 'c', 'expression': 'a+b', 'inputs': {'a': 'a', 'b': 'b'}}], 'result_node': 'c'}
    out = verify(item, pos('394.57'), ev)
    assert out['status'] == 'supported' and out['steps'][0]['input']['source_ref'] == '1'
    item['nodes'][1]['quote'] = 'not in source'
    assert verify(item, pos('394.57'), ev)['reason'] == 'quote_unverified'


def test_uninterpreted_mismatch_remains_a_doubt():
    ev = Evidence({'1': 'revenue $57.6 billion'})
    item = {'binding': 'direct', 'responsibility': 'current', 'relation': 'same', 'span': sid(ev, '$57.6 billion')}
    out = raw_verify(item, pos('57.6'), ev)
    assert out['status'] == 'incomplete' and out['reason'] == 'answer_value_unconfirmed'
