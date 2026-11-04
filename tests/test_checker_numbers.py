"""The number check: [n] is the declaration, plus the A1 numeric fixes (user figures, derived values,
restated figures, labelled inference, approximation, non-amounts, evidence quotes).

Every relaxation here is paired with a negative: an invented figure is still flagged.
"""
import json
import random

import pytest

from app import observability
from app.agent_tool_catalog import CalculateArgs
from app.agent_workflow import claim_numeric, evidence
from app.agent_workflow.calculation import calculate
from app.agent_workflow.direct import Turn
from app.agent_workflow.evidence import (answer_scope, labelled_inference_lines, number_check, reviewed_answer,
                                         user_figure_values)
from app.agent_workflow.state import AgentRuntimeContext
from app.agent_workflow.unverified import merge_repair

SRC = [{'ordinal': 1, 'source_type': 'official_filing', 'quote': '得分为 90，营收 $391.0 billion。'}]


def _turn(question='AAPL 收盘价', messages=None):
    return Turn(question, AgentRuntimeContext('custom', 'test', 'dummy'), None, messages or [], {})


# --- Part 1: scope -------------------------------------------------------------------------------------

def test_an_unmarked_clock_time_and_small_integer_are_not_checked():
    assert number_check('运行叙述：21:25 开始检索，得分为 87。', []) == ([], [])


def test_the_same_clock_time_inside_a_marked_sentence_is_no_figure():
    assert number_check('比赛于 21:25 开始，得分为 90 [1]。', SRC) == ([], [])
    # ...and the sentence is still checked for what it does state.
    assert number_check('比赛于 21:25 开始，得分为 91 [1]。', SRC) == ([91.0], [])


def test_a_small_integer_is_checked_when_the_sentence_is_marked():
    assert number_check('得分为 87 [1]。', SRC) == ([87.0], [])


def test_unmarked_money_and_percentages_are_still_checked_with_their_own_wording():
    kept, issues = reviewed_answer('营收为 500 美元。', SRC)
    assert issues == ['missing_citation'] and kept == ''
    assert number_check('利润率为 12.5%。', SRC) == ([12.5], [])
    assert number_check('营收 3 亿。', SRC) == ([3e8], [])
    # The same figure in a marked sentence is a source mismatch, a different message.
    assert reviewed_answer('营收为 500 美元 [1]。', SRC)[1] == ['unsupported_numeric_claim']


def test_an_unmarked_bare_decimal_and_a_bare_integer_of_1000_or_more_are_checked():
    assert number_check('成交 12,345 股。', SRC) == ([12345.0], [])
    assert number_check('比率为 3.14。', SRC) == ([3.14], [])
    # A calendar year and a small count are not.
    assert number_check('2026 年成交 345 股。', SRC) == ([], [])


def test_an_unmarked_table_row_with_a_wrong_figure_is_flagged_and_a_right_one_is_not():
    table = '| 项目 | 数量 |\n|---|---|\n| 苹果 | 54 |'
    kept, issues = reviewed_answer(table, SRC)
    assert issues == ['missing_citation']
    stated = '苹果得分为 90 [1]。\n\n' + table.replace('54', '90')
    assert reviewed_answer(stated, SRC)[1] == []


def test_a_repair_that_removes_every_marker_from_a_line_is_refused():
    draft = '营收为 100 美元 [1]。\n得分为 90 [1]。'
    assert merge_repair(draft, '营收为 100 美元。\n得分为 90 [1]。') == draft
    # Re-pointing a marker is the repair that is allowed.
    assert merge_repair(draft, '营收为 100 美元 [2]。\n得分为 90 [1]。') == '营收为 100 美元 [2]。\n得分为 90 [1]。'
    # A line that had no marker may gain one or stay without.
    assert merge_repair('没有标注的一句。', '没有标注的一句 [1]。') == '没有标注的一句 [1]。'


def test_an_absence_report_without_a_marker_states_no_fact():
    assert reviewed_answer('本次没有查到 500 美元的记录。', SRC)[1] == []


def test_the_scope_audit_lists_what_was_left_alone_and_what_no_source_holds():
    cites = [{'ordinal': 1, 'source_type': 'official_filing', 'quote': '营收为 100 美元'}]
    scope = answer_scope('营收为 100 美元 [1]。得分为 87。营收为 500 美元。', cites)
    assert scope['marked_figures'] == 1
    assert scope['unmarked_exempted'] == [{'value': 87.0, 'line': '得分为 87', 'why': 'below_backstop'}]
    assert scope['unmarked_backstopped'] == [{'value': 500.0, 'line': '营收为 500 美元', 'flagged': True}]
    assert [item['value'] for item in scope['unmarked_no_holder']] == [87.0, 500.0]
    assert scope['counts'] == {'marked_figures': 1, 'unmarked_backstopped': 1, 'unmarked_exempted': 1, 'unmarked_no_holder': 2}


def test_every_turn_records_audit_scope_and_it_reaches_the_trace_scores():
    turn = _turn()
    turn.route = 'A'
    turn.citations = [{'ordinal': 1, 'quote': '100', 'source_type': 'saved_price'}]
    result = turn.finish('AAPL 收盘价为 100 美元 [1]。')
    scope = result['audit']['scope']
    assert scope['marked_figures'] >= 1 and set(scope['counts']) == {
        'marked_figures', 'unmarked_backstopped', 'unmarked_exempted', 'unmarked_no_holder'}

    class Obs:
        def __init__(self):
            self.scores = {}

        def score_trace(self, name, value, data_type, comment=None):
            self.scores[name] = (value, comment)

    obs = Obs()
    observability.score_citation_audit(observability.Handle(obs), verified=1, unverified=0, scope={
        'counts': {'marked_figures': 2, 'unmarked_backstopped': 0, 'unmarked_exempted': 1, 'unmarked_no_holder': 1},
        'unmarked_exempted': [{'value': 87.0, 'line': '得分为 87'}], 'unmarked_no_holder': [{'value': 87.0, 'line': '得分为 87'}]})
    assert obs.scores['scope_marked_figures'] == (2.0, None)
    assert obs.scores['scope_unmarked_exempted'] == (1.0, '87.0: 得分为 87')
    assert obs.scores['scope_unmarked_no_holder'][0] == 1.0


def test_the_prompt_says_run_narration_needs_no_marker_and_does_not_describe_the_backstop():
    from app.agent_system_prompt import INSTRUCTION
    text = ''.join(INSTRUCTION)
    assert '运行叙述' in text and '不需要 [n]' in text
    assert '兜底' not in text and 'backstop' not in text.lower()


# --- F1: figures the user wrote ---------------------------------------------------------------------------

def test_chinese_numeral_amounts_are_the_users_figures():
    assert {50000.0, 100000.0, 3000.0, 2000000.0, 100000000.0} <= user_figure_values('五万美元，十万，三千，两百万，一亿')
    assert 50000.0 in user_figure_values('我有 5 万美元')


def test_a_user_stated_figure_is_grounded_and_an_invented_one_is_not():
    assert number_check('按你的 5 万美元，可以买入。', [], user_text='我有 5 万美元') == ([], [])
    assert number_check('按你的 5 万美元和收盘价 $227.5 [1]。', [{'ordinal': 1, 'quote': 'close 227.5'}],
                        user_text='我有 5 万美元') == ([], [])
    assert number_check('按你的 5 万美元，可以买入。', [], user_text='我有 3 万美元') == ([5e4], [])
    assert number_check('按你的 5 万美元，可以买入。', []) == ([5e4], [])


def test_user_stated_text_is_only_what_the_user_typed():
    messages = [{'role': 'user', 'content': '我有 5 万美元'}, {'role': 'assistant', 'content': '你有 99 万美元'},
                {'role': 'system', 'content': '系统说 77 万美元'}, {'role': 'user', 'content': 'confirm:abc 66 万美元'}]
    turn = _turn('按我的钱算一下', messages)
    turn.question = '模型改写后的问题：88 万美元'
    text = turn.user_stated_text()
    assert '5 万美元' in text and '按我的钱算一下' in text
    for forbidden in ('99', '77', '66', '88'):
        assert forbidden not in text
    # An assistant-history figure and a figure only in the rewritten question ground nothing.
    assert number_check('按 99 万美元计算。', [], user_text=text) == ([990000.0], [])
    assert number_check('按 88 万美元计算。', [], user_text=text) == ([880000.0], [])


def test_calculate_binds_a_user_stated_input_and_records_its_origin():
    source = [{'ordinal': 1, 'quote': '收盘价 227.5'}]
    args = {'expression': 'a/b', 'inputs': [{'name': 'a', 'value': '50000', 'user_stated': True},
                                            {'name': 'b', 'value': '227.5', 'source_ordinal': 1}], 'decimals': 2}
    result = calculate(args, source, '我有 5 万美元')
    assert result['value'] == '219.78' and result['parents'] == [1]
    assert result['inputs'][0]['origin'] == 'user_stated'
    # The user never wrote that figure: unbound.
    with pytest.raises(ValueError, match='calculation_input_unbound'):
        calculate(args, source, '我有 3 万美元')
    with pytest.raises(ValueError, match='calculation_input_unbound'):
        calculate(args, source)
    # A replay of a stored calculation has no user words; the recorded binding stands.
    assert calculate({**args, 'inputs': result['inputs']}, source, None)['value'] == '219.78'
    # Only user figures: no source ordinal at all.
    only = calculate({'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '50000', 'user_stated': True}]}, [], '五万美元')
    assert only['parents'] == [] and only['value'] == '100000.00'


def test_a_calculation_input_has_exactly_one_origin():
    base = {'expression': 'a', 'inputs': [{'name': 'a', 'value': '1'}]}
    for item in ({'name': 'a', 'value': '5'}, {'name': 'a', 'value': '5', 'source_ordinal': 1, 'user_stated': True}):
        with pytest.raises(Exception):
            CalculateArgs.model_validate({**base, 'inputs': [item]})
    assert CalculateArgs.model_validate({**base, 'inputs': [{'name': 'a', 'value': '5', 'user_stated': True}]})
    assert CalculateArgs.model_validate({**base, 'inputs': [{'name': 'a', 'value': '5', 'source_ordinal': 1}]})


def test_the_whole_number_part_of_a_calculation_result_passes_and_other_whole_numbers_do_not():
    result = calculate({'expression': 'a/b', 'inputs': [{'name': 'a', 'value': '50000', 'user_stated': True},
                                                        {'name': 'b', 'value': '227.5', 'source_ordinal': 1}]},
                       [{'ordinal': 1, 'quote': '收盘价 227.5'}], '五万美元')
    cites = [{'ordinal': 1, 'quote': '收盘价 227.5'},
             {'ordinal': 2, 'source_type': 'calculation', 'quote': json.dumps(result, ensure_ascii=False), 'calculation': result}]
    assert number_check('按 5 万美元可买 219 股 [2]。', cites, user_text='我有 5 万美元') == ([], [])
    assert number_check('按 5 万美元可买 218 股 [2]。', cites, user_text='我有 5 万美元') == ([218.0], [])
    # Only a calculation's result is floored: a source's 227.5 is not 227.
    assert number_check('收盘价 227 [1]。', cites, user_text='') == ([227.0], [])


def test_a_user_figure_is_never_a_closure_operand():
    cites = [{'ordinal': 1, 'quote': '收益 300'}]
    assert number_check('合计 636 [1]。', cites, user_text='我之前有 336') == ([636.0], [])


def test_a_rewritten_question_is_never_user_text():
    turn = _turn('AAPL 收盘价')
    turn.question = '改写：5 万美元'
    assert '5 万' not in turn.user_stated_text()


def test_a_turn_with_the_users_figure_in_its_history_is_not_flagged_for_restating_it():
    turn = _turn('AAPL 收盘价是多少？', [{'role': 'user', 'content': '我有 5 万美元，AAPL 收盘价是多少？'}])
    turn.route = 'A'
    turn.citations = [{'ordinal': 1, 'quote': '227.5', 'source_type': 'saved_price'}]
    result = turn.finish('按你的 5 万美元和收盘价 227.5 [1]。')
    assert result['status'] == 'succeeded' and not result['unverified_lines']
    other = _turn('AAPL 收盘价是多少？')
    other.route = 'A'
    other.citations = [{'ordinal': 1, 'quote': '227.5', 'source_type': 'saved_price'}]
    flagged = other.finish('按你的 5 万美元和收盘价 227.5 [1]。')
    assert flagged['status'] == 'partially_succeeded' and flagged['unverified_lines']


# --- F2: constants, the laundering guard, closure ----------------------------------------------------------

def test_calculate_accepts_literals_and_records_them():
    source = [{'ordinal': 1, 'quote': '营收 100'}]
    result = calculate({'expression': 'a*4+0.5', 'inputs': [{'name': 'a', 'value': '100', 'source_ordinal': 1}]}, source)
    assert result['value'] == '400.50' and result['constants'] == ['4', '0.5']
    assert 'constants' not in calculate({'expression': 'a/100', 'inputs': [{'name': 'a', 'value': '100', 'source_ordinal': 1}]}, source)
    # A ratio is not laundering.
    ratio = calculate({'expression': 'a/b*100', 'inputs': [{'name': 'a', 'value': '100', 'source_ordinal': 1},
                                                           {'name': 'b', 'value': '400', 'source_ordinal': 2}]},
                      [source[0], {'ordinal': 2, 'quote': '总计 400'}])
    assert ratio['value'] == '25.00'


@pytest.mark.parametrize('expression', ['a*0+394', 'a-a+394', 'a/a*394', 'a*1001', 'a*0.00001', 'a**0+394', 'a**21'])
def test_a_constant_cannot_be_laundered_into_a_result(expression):
    with pytest.raises(ValueError, match='invalid_calculation'):
        calculate({'expression': expression, 'inputs': [{'name': 'a', 'value': '100', 'source_ordinal': 1}]},
                  [{'ordinal': 1, 'quote': '营收 100'}])


ADD = [{'ordinal': 1, 'quote': 'A 项收入 300'}, {'ordinal': 2, 'quote': 'B 项收入 336'}]


def test_a_sum_of_two_cited_figures_is_accepted_and_logged():
    log = []
    assert number_check('A 项 300 [1]。B 项 336 [2]。合计 636 [1][2]。', ADD, closure_log=log) == ([], [])
    assert len(log) == 1 and log[0]['kind'] == 'sum' and sorted(log[0]['operands']) == [300.0, 336.0]
    assert log[0]['candidates'] / log[0]['bins'] <= evidence.CLOSURE_FALSE_ACCEPT_BOUND
    # An invented total is not the sum of anything.
    assert number_check('A 项 300 [1]。B 项 336 [2]。合计 700 [1][2]。', ADD) == ([700.0], [])
    # The closure only reads the sources the sentence cites.
    assert number_check('合计 636 [1]。', ADD) == ([636.0], [])


def test_a_ratio_and_a_percent_change_of_cited_figures_are_accepted():
    cites = [{'ordinal': 1, 'quote': '本期 120'}, {'ordinal': 2, 'quote': '上期 100'}]
    assert number_check('同比增长 20.0% [1][2]。', cites) == ([], [])
    assert number_check('同比增长 25.0% [1][2]。', cites) == ([25.0], [])


def test_the_closure_bound_refuses_a_pool_that_would_accept_nearly_anything():
    big = [300.0, 336.0] + [float(x) for x in range(11, 29)]
    assert evidence._amount_closure(636.0, 3, big) is None
    assert evidence._amount_closure(636.0, 3, [300.0, 336.0])[0] == 'sum'
    assert evidence.CLOSURE_FALSE_ACCEPT_BOUND == 0.05


def test_a_large_source_falls_back_to_the_figures_the_answer_has_already_verified():
    others = ' '.join(f'项目{chr(97 + i)} {710 + i}' for i in range(18))
    cites = [{'ordinal': 1, 'quote': f'甲 300 乙 336 {others}'}]
    log = []
    assert number_check('甲 300 [1]。乙 336 [1]。合计 636 [1]。', cites, closure_log=log) == ([], [])
    assert log and log[0]['pool'] == 'verified'
    assert number_check('甲 300 [1]。乙 336 [1]。合计 637 [1]。', cites) == ([637.0], [])


def test_the_false_accept_rate_of_the_closure_is_bounded():
    rng = random.Random(20261104)
    figures = rng.sample(range(100, 1000), 20)
    cites = [{'ordinal': 1, 'quote': ' '.join(f'项目{chr(97 + i)} {value}.{rng.randint(0, 9)}' for i, value in enumerate(figures))}]
    invented = [rng.randint(100, 999) for _ in range(500)]
    accepted = sum(number_check(f'合计 {value} [1]。', cites) == ([], []) for value in invented)
    assert accepted / len(invented) <= evidence.CLOSURE_FALSE_ACCEPT_BOUND, accepted


def test_a_closure_accepted_figure_reaches_the_turn_audit():
    turn = _turn()
    turn.route = 'A'
    turn.citations = [{'ordinal': 1, 'quote': '300', 'source_type': 'saved_price'}, {'ordinal': 2, 'quote': '336', 'source_type': 'saved_price'}]
    result = turn.finish('甲 300 [1]。乙 336 [2]。合计 636 [1][2]。')
    assert result['status'] == 'succeeded'
    assert result['audit']['closure_accepted'][0]['kind'] == 'sum' and len(result['audit']['closure_accepted']) <= 8


# --- F3: the answer-wide verified set --------------------------------------------------------------------------

REVENUE = [{'ordinal': 1, 'source_type': 'official_filing', 'quote': 'Apple revenue was $94.9 billion.'},
           {'ordinal': 2, 'source_type': 'official_filing', 'quote': 'Services revenue was $24.2 billion.'}]


def test_a_restated_figure_passes_in_a_summary_before_or_after_the_detail():
    detail = 'Apple 上季度营收 $94.9 billion [1]。'
    summary = '结论：Apple 上季度营收 $94.9 billion，同比增长 6%。'
    assert reviewed_answer(detail + '\n' + summary, REVENUE, require_citations=True)[1] == []
    assert reviewed_answer(summary + '\n' + detail, REVENUE, require_citations=True)[1] == []
    # A summary that changes the figure, or restates one nobody verified, is flagged.
    assert reviewed_answer(detail + '\n结论：Apple 上季度营收 $99.4 billion。', REVENUE, require_citations=True)[1] == ['missing_citation']
    assert reviewed_answer('结论：Apple 上季度营收 $94.9 billion。', REVENUE, require_citations=True)[1] == ['missing_citation']


def test_a_figure_verified_for_one_source_is_not_flagged_when_a_marked_recap_cites_another():
    answer = 'Apple 营收 $94.9 billion [1]。服务营收 $24.2 billion [2]。回顾：营收 $94.9 billion [2]。'
    assert reviewed_answer(answer, REVENUE)[1] == []
    assert reviewed_answer('Apple 营收 $94.9 billion [1]。回顾：营收 $95.9 billion [2]。', REVENUE)[1] == ['unsupported_numeric_claim']


def test_the_line_level_callers_agree_with_the_answer_level_verdict():
    from app.agent_workflow.unverified import entries, line_numbers
    answer = 'Apple 营收 $94.9 billion [1]。\n回顾：营收 $94.9 billion [2]。'
    verified = evidence.answer_verified_figures(answer, REVENUE)
    assert 94.9e9 in verified
    rejected, _ = line_numbers('回顾：营收 $94.9 billion [2]。', REVENUE, verified=verified)
    assert rejected == set()
    assert line_numbers('回顾：营收 $94.9 billion [2]。', REVENUE)[0] == {94.9e9}
    assert entries([('回顾：营收 $94.9 billion [2]。', 'unsupported_numeric_claim')], REVENUE, verified=verified)[0]['numbers'] == []


# --- F5: labelled inference ----------------------------------------------------------------------------------------

LABELLED = '推断：若营收 $94.9 billion 保持 6% 增速，明年可达 $100.6 billion [1]。'


def test_a_labelled_inference_stands_on_its_premises():
    assert reviewed_answer(LABELLED, REVENUE, require_citations=True)[1] == []
    # The same projection without the label is an unsupported figure.
    assert reviewed_answer('明年可达 $100.6 billion [1]。', REVENUE)[1] == ['unsupported_numeric_claim']
    # Premises that fail keep the flag.
    assert reviewed_answer('推断：若营收 $50.0 billion 增长，明年可达 $403 billion [1]。', REVENUE)[1] == ['unsupported_numeric_claim']
    # A bad marker is still a bad marker.
    assert reviewed_answer('推断：营收 $94.9 billion [9]。', REVENUE)[1] == ['invalid_citation']


def test_a_labelled_inference_without_a_marker_needs_none_and_an_unlabelled_one_does():
    assert reviewed_answer('推断：明年营收可能达到 $403 billion。', REVENUE, require_citations=True)[1] == []
    assert reviewed_answer('Estimate: revenue $403 billion.', REVENUE, require_citations=True)[1] == []
    assert reviewed_answer('明年营收可能达到 $403 billion（推断）', REVENUE, require_citations=True)[1] == []
    assert reviewed_answer('明年营收可能达到 $403 billion。', REVENUE, require_citations=True)[1] == ['missing_citation']


def test_the_label_is_anchored_so_it_cannot_be_smuggled_in():
    for sentence in ('这不是推断，营收 $500 billion [1]', '营收 $500 billion，推断仍在继续 [1]', 'The estimate is wrong: $500 billion [1]'):
        assert not evidence.is_inference_label(sentence), sentence
    for sentence in ('推断：营收', '**推断**：营收', '- 推断：营收', '若假设营收增长', '如果估算营收', '（推断）营收', 'Assuming growth', 'estimated revenue'):
        assert evidence.is_inference_label(sentence), sentence
    assert reviewed_answer('这不是推断，营收 $500 billion [1]。', REVENUE)[1] == ['unsupported_numeric_claim']


def test_a_labelled_figure_does_not_enter_the_verified_set():
    answer = LABELLED + '\n结论：明年营收 $100.6 billion。'
    assert 100.6e9 not in evidence.answer_verified_figures(answer, REVENUE)
    assert reviewed_answer(answer, REVENUE, require_citations=True)[1] == ['missing_citation']


def test_labelled_inference_lines_returns_the_ones_that_passed():
    answer = LABELLED + '\n推断：若营收 $50.0 billion 增长，明年可达 $403 billion [1]。\nApple 营收 $94.9 billion [1]。'
    assert labelled_inference_lines(answer, REVENUE) == [LABELLED.rstrip('。')]


# --- F6: approximation ----------------------------------------------------------------------------------------------

BILLIONS = [{'ordinal': 1, 'source_type': 'official_filing', 'quote': '营收 $391.0 billion'}]


def test_an_approximation_word_admits_a_coarse_rounding_and_a_near_figure():
    assert number_check('营收接近 4,000 亿美元 [1]。', BILLIONS) == ([], [])
    assert number_check('营收约 380 亿美元 [1]。', [{'ordinal': 1, 'quote': '营收 391 亿美元'}]) == ([], [])
    assert number_check('营收 ≈ $400 billion [1]。', BILLIONS) == ([], [])


def test_without_an_approximation_word_or_beyond_five_percent_the_figure_is_flagged():
    assert number_check('最近营收 4,000 亿美元 [1]。', BILLIONS) == ([4e11], [])
    assert number_check('附近营收 4,000 亿美元 [1]。', BILLIONS) == ([4e11], [])
    assert number_check('合约营收 4,000 亿美元 [1]。', BILLIONS) == ([4e11], [])
    assert number_check('营收 4,000 亿美元 [1]。', BILLIONS) == ([4e11], [])
    assert number_check('营收约 4,700 亿美元 [1]。', BILLIONS) == ([4.7e11], [])


# --- F7: non-amounts ---------------------------------------------------------------------------------------------------

def test_counting_words_a_bare_month_and_index_names_are_no_figures():
    assert number_check('筛选出 13 家公司 [1]。', SRC) == ([], [])
    assert number_check('12 月议息会议预期降息 [1]。', SRC) == ([], [])
    assert number_check('过去 12 个月和 3 只基金 [1]。', SRC) == ([], [])
    assert number_check('标普500 表现平稳 [1]。', SRC) == ([], [])
    # What is written after them is still checked, and so are real amounts.
    assert number_check('标普500 上涨 1.2% [1]。', SRC) == ([1.2], [])
    assert number_check('标普500 上涨 1.2% [1]。', [{'ordinal': 1, 'quote': '上涨 1.2%'}]) == ([], [])
    assert number_check('12 月降息幅度为 37 [1]。', SRC) == ([37.0], [])
    assert number_check('筛选出 13 亿美元 [1]。', SRC) == ([13e8], [])


def test_both_checkers_share_one_list_of_counting_words():
    assert claim_numeric._DURATION.pattern.startswith(r'\d+(?:\.\d+)?\s*(?:' + evidence.COUNT_UNITS)
    assert claim_numeric._DURATION.search('1.2 个百分点') is None
    assert claim_numeric._DURATION.search('13 家') and claim_numeric._DURATION.search('3 months')
    assert claim_numeric.numbers_supported('12 月议息会议', 'nothing') == []
    assert claim_numeric.numbers_supported('标普500 上涨 1.2%', 'nothing') == [1.2]


# --- F8: evidence quotes ---------------------------------------------------------------------------------------------------

ANALYSIS = {'ordinal': 3, 'source_type': 'ai_analysis', 'quote': '营收增长稳健', 'evidence_quotes': ['Services revenue was $24.2 billion']}


def test_a_figure_in_a_saved_analysis_evidence_quote_is_checked_as_source_text():
    assert '24.2' in evidence.citation_check_text(ANALYSIS)
    assert number_check('服务业务营收 $24.2 billion [3]。', [ANALYSIS]) == ([], [])
    assert number_check('服务业务营收 $24.3 billion [3]。', [ANALYSIS]) == ([24.3e9], [])


def test_calculate_reads_the_same_text_as_the_checker():
    result = calculate({'expression': 'a*2', 'inputs': [{'name': 'a', 'value': '24200000000', 'source_ordinal': 3}]}, [ANALYSIS])
    assert result['value'] == '48400000000.00'
