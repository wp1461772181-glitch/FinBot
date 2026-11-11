"""FP7 step 2: every calculate input is judged; an unbound one says which, why, and what to do next,
and the receipts reach the model.  The sentences are the FP7 decisions (D-F2), asserted verbatim."""
import asyncio
import json

import pytest

from app.agent_workflow import direct
from app.agent_workflow.calculation import CalculationUnbound, calculate
from app.agent_workflow.state import AgentRuntimeContext

SWITCH = 'FINBOT_FP7_INPUT_RECEIPTS'

NEXT = {
    'origin_invalid': '每个输入必须且只能有一个出处：source_ordinal（资料）或 user_stated（用户原话）；name 必须是单个小写字母且不重复。',
    'source_not_cited': '本轮没有这个序号的引用。只能使用本轮工具结果里已经给出的 [n]。',
    'value_not_finite': '数值必须是有限的十进制数。',
    'value_not_in_user_words': '这个数不在用户本轮的原话里；只有用户亲自写出的数才能标 user_stated。它若来自资料，请改用 source_ordinal 指向那条资料。',
    'token_suffix_unrecognized': '引用 [1] 里这个数后面紧跟着系统不认识的后缀「bps」，所以无法绑定。这是系统解析的限制，不是你的输入有误；可以改用同一资料里写法完整的数，或换一条资料。',
    'value_in_other_source': '这个数不在引用 [1] 里，但出现在 other_ordinals 所列引用的可核对文本里。这只是候选：请自行确认是同一指标、同一期间后，再改用那条引用的序号。',
    'value_not_in_source': '引用 [1] 的可核对文本里没有这个数。请先核对序号；资料里若是不同单位或不同精度的写法，按资料里的写法传入，换算写进 expression。',
}

HINT = '有输入没有绑定到来源，逐项原因见 input_receipts。只需改正其中 found 为 false 的输入，其余保持不变；不要把数值改写成更长的小数去试。closest_in_source 与 bindable_values 都只是不完整的候选。'

REVENUE = [{'ordinal': 1, 'quote': 'Total revenue was 331,839 million for the year.'}]


@pytest.fixture(autouse=True)
def _receipts_on(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


def _unbound(args, citations, user_text=''):
    with pytest.raises(CalculationUnbound) as exc:
        calculate(args, citations, user_text)
    return exc.value.receipts


def _one(item, citations, user_text=''):
    return _unbound({'expression': 'a*2', 'inputs': [item]}, citations, user_text)[0]


def _turn(citations):
    async def emit(_):
        pass
    turn = direct.Turn('算一下', AgentRuntimeContext('custom', 'test', 'dummy'), emit, [], {})
    turn.route = 'A'
    turn.citations = citations
    turn.observations = [{'accepted_evidence': True}]
    return turn


def test_all_inputs_are_judged_before_the_error():
    args = {'expression': 'a+b+c', 'inputs': [
        {'name': 'a', 'value': '331839', 'source_ordinal': 1},
        {'name': 'b', 'value': '999', 'source_ordinal': 1},
        {'name': 'c', 'value': '12.5', 'source_ordinal': 1}]}
    citations = [{'ordinal': 1, 'quote': 'Total revenue was 331,839 million and margin 12.5%.'}]
    with pytest.raises(ValueError) as exc:
        calculate(args, citations, '')
    assert isinstance(exc.value, CalculationUnbound)
    assert str(exc.value) == 'calculation_input_unbound'
    receipts = exc.value.receipts
    assert len(receipts) == 3
    assert [receipt['found'] for receipt in receipts] == [True, False, True]
    assert receipts[0]['selected_token'] == '331839' and receipts[0]['next_action'] == ''
    assert receipts[2]['selected_token'] == '12.5'


def test_the_receipt_keys_are_the_fixed_set():
    receipt = _one({'name': 'b', 'value': '999', 'source_ordinal': 1}, REVENUE)
    assert set(receipt) == {'name', 'requested_value', 'declared_origin', 'found', 'selected_token',
                            'parsed_value', 'reason', 'next_action', 'closest_in_source'}
    assert receipt['requested_value'] == '999' and receipt['declared_origin'] == 'source_ordinal:1'
    assert receipt['parsed_value'] == '999' and receipt['selected_token'] is None


def test_origin_invalid():
    receipt = _one({'name': 'ab', 'value': '1', 'source_ordinal': 1}, REVENUE)
    assert receipt['reason'] == 'origin_invalid' and receipt['found'] is False
    assert receipt['next_action'] == NEXT['origin_invalid']
    assert receipt['declared_origin'] == 'source_ordinal:1' and receipt['parsed_value'] is None


def test_source_not_cited():
    receipt = _one({'name': 'a', 'value': '1', 'source_ordinal': 9}, REVENUE)
    assert receipt['reason'] == 'source_not_cited'
    assert receipt['next_action'] == NEXT['source_not_cited']
    assert 'closest_in_source' not in receipt and 'other_ordinals' not in receipt


def test_value_not_finite():
    receipt = _one({'name': 'a', 'value': 'NaN', 'source_ordinal': 1}, REVENUE)
    assert receipt['reason'] == 'value_not_finite' and receipt['parsed_value'] == 'NaN'
    assert receipt['next_action'] == NEXT['value_not_finite']


def test_value_not_in_user_words():
    receipt = _one({'name': 'a', 'value': '77', 'user_stated': True}, [], 'I have 5 apples.')
    assert receipt['reason'] == 'value_not_in_user_words' and receipt['declared_origin'] == 'user_stated'
    assert receipt['next_action'] == NEXT['value_not_in_user_words']


def test_token_suffix_unrecognized_names_the_suffix_and_has_no_candidates():
    citations = [{'ordinal': 1, 'quote': 'margin rose 35bps'}]
    receipt = _one({'name': 'a', 'value': '35', 'source_ordinal': 1}, citations)
    assert receipt['reason'] == 'token_suffix_unrecognized'
    assert receipt['next_action'] == NEXT['token_suffix_unrecognized']
    assert receipt['closest_in_source'] == []


def test_value_in_other_source_reports_and_does_not_rebind():
    citations = [{'ordinal': 1, 'quote': 'Alpha reported 50 units.'},
                 {'ordinal': 2, 'quote': 'Beta reported 77 units.'}]
    args = {'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '77', 'source_ordinal': 1}]}
    receipt = _unbound(args, citations)[0]
    assert receipt['reason'] == 'value_in_other_source'
    assert receipt['other_ordinals'] == [2]
    assert receipt['closest_in_source'] == ['50']
    assert receipt['next_action'] == NEXT['value_in_other_source']


def test_model_rewrites_the_ordinal_and_the_call_succeeds():
    citations = [{'ordinal': 1, 'quote': 'Alpha reported 50 units.'},
                 {'ordinal': 2, 'quote': 'Beta reported 77 units.'}]
    args = {'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '77', 'source_ordinal': 2}]}
    assert calculate(args, citations, '')['value'] == '154.00'


def test_value_not_in_source():
    citations = [{'ordinal': 1, 'quote': 'Alpha reported 50 units.'}]
    receipt = _one({'name': 'a', 'value': '77', 'source_ordinal': 1}, citations)
    assert receipt['reason'] == 'value_not_in_source'
    assert receipt['closest_in_source'] == ['50']
    assert receipt['next_action'] == NEXT['value_not_in_source']


def test_bound_inputs_have_a_bound_receipt_with_no_next_action():
    receipts = _unbound({'expression': 'a+b', 'inputs': [
        {'name': 'a', 'value': '331839', 'source_ordinal': 1},
        {'name': 'b', 'value': '5', 'source_ordinal': 1}]}, REVENUE)
    assert receipts[0]['found'] is True and receipts[0]['reason'] == 'bound'
    assert receipts[0]['next_action'] == '' and receipts[0]['selected_token'] == '331839'


def test_closest_in_source_is_at_most_three_and_hints_never_suggest_expansion():
    citations = [{'ordinal': 1, 'quote': 'values 1 2 3 4 5 6 7 8 9 10 and 11 and 12'}]
    receipts = _unbound({'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '77', 'source_ordinal': 1}]}, citations)
    assert len(receipts[0]['closest_in_source']) == 3
    for text in [receipt['next_action'] for receipt in receipts] + [HINT]:
        assert '展开' not in text and '更多小数' not in text


def test_replay_of_a_user_stated_input_is_taken_as_recorded():
    args = {'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '77', 'user_stated': True}]}
    assert calculate(args, [], None)['value'] == '154.00'


def test_receipts_reach_the_model_through_accept_and_the_tool_message():
    args = {'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '123', 'source_ordinal': 1}], 'decimals': 2}
    turn = _turn(REVENUE)
    outcome = asyncio.run(turn.execute_read('calculate', args))
    assert outcome['ok'] is False and outcome['error_code'] == 'calculation_input_unbound'
    assert outcome['candidates_complete'] is False and outcome['hint'] == HINT
    turn.accept('calculate', args, outcome)
    entry = turn.feedback[-1]
    assert entry['ok'] is False and entry['candidates_complete'] is False
    assert entry['input_receipts'][0]['reason'] == 'value_not_in_source'
    # agent_loop's tool message, as direct.py assembles it (last_accepted, then the feedback entry, then tools.error).
    safe_result = turn.last_accepted
    if safe_result is None and turn.feedback:
        feedback = turn.feedback[-1]
        safe_result = feedback.get('result') or (feedback if 'ok' in feedback else None)
    assert safe_result is not None and 'input_receipts' in safe_result
    assert safe_result['input_receipts'][0]['found'] is False
    json.dumps(safe_result)


def test_switch_off_is_the_bare_code_with_no_receipts(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    args = {'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '123', 'source_ordinal': 1}], 'decimals': 2}
    with pytest.raises(ValueError) as exc:
        calculate(args, REVENUE, '')
    assert type(exc.value) is ValueError and str(exc.value) == 'calculation_input_unbound'
    turn = _turn(REVENUE)
    outcome = asyncio.run(turn.execute_read('calculate', args))
    assert 'input_receipts' not in outcome and 'candidates_complete' not in outcome
    turn.accept('calculate', args, outcome)
    assert turn.feedback[-1] == {'name': 'calculate', 'error_code': 'calculation_input_unbound', 'hint': None}


def test_the_exception_carries_its_receipts_and_the_bare_message():
    error = CalculationUnbound([{'name': 'a', 'found': False}])
    assert str(error) == 'calculation_input_unbound' and error.receipts == [{'name': 'a', 'found': False}]
    assert isinstance(error, ValueError)
