"""A ``[n]`` that names no source of the turn points at nothing; it leaves the delivered text.

Only the marker goes: the sentence, its figures and every resolvable marker stay byte for byte.  The
invalid/unverified bookkeeping is unchanged; this only keeps a dead pointer from reading as a real citation.
"""
import re

import pytest

from app.agent_workflow.direct import Turn
from app.agent_workflow.evidence import citation_errors, strip_invalid_markers
from app.agent_workflow.state import AgentRuntimeContext

POOL = [{'ordinal': n, 'source_type': 'saved_price', 'quote': 'AAPL 股息率 0.4%', 'symbol': 'AAPL'} for n in (1, 6, 11)]
TITLE = 'Revenue outlook: $100 [2026]'
TITLED = [{'ordinal': 1, 'source_type': 'web', 'title': TITLE, 'quote': TITLE + ' Revenue was 100 USD.'}]


def test_only_the_unresolvable_markers_leave_the_delivered_text():
    answer = ('AAPL 股息率 0.4% [1]，按股价推算年股息约 1.04 美元 [12][13]。\n\n'
              '| 指标 | 数值 |\n|---|---|\n| MSFT 股息率 | 0.8% [6][13] |\n\n来源：[1][6][11]')
    expected = ('AAPL 股息率 0.4% [1]，按股价推算年股息约 1.04 美元。\n\n'
                '| 指标 | 数值 |\n|---|---|\n| MSFT 股息率 | 0.8% [6] |\n\n来源：[1][6][11]')
    assert strip_invalid_markers(answer, POOL) == expected


@pytest.mark.parametrize('answer', [
    'AAPL 股息率 0.4% [1]。',
    '来源：[1][6][11]',
    '| 指标 | 数值 |\n|---|---|\n| 股息率 | 0.4% [1] |\n| 股价 | 180 美元 [6][11] |',
    '**结论**\n- 第一条 [1]\n- 第二条 [6]',
    '没有可核验的资料。',
])
def test_an_answer_with_only_resolvable_markers_is_unchanged(answer):
    assert strip_invalid_markers(answer, POOL) == answer


@pytest.mark.parametrize('answer,expected', [
    ('[13] 文字', '文字'),
    ('句末[13]', '句末'),
    ('句末 [13]', '句末'),
    ('真[1][13]', '真[1]'),
    ('真[13][1]', '真[1]'),
    ('句中 [13] 文字', '句中 文字'),
    ('| [13] | x |', '| | x |'),
    ('| 0.8% | [13] |', '| 0.8% | |'),
])
def test_a_dead_marker_is_removed_wherever_it_sits(answer, expected):
    assert strip_invalid_markers(answer, POOL) == expected


def test_a_bracketed_number_inside_an_exact_source_title_is_text_not_a_marker():
    answer = '**《' + TITLE + '》** [1] 营收 [13]'
    assert strip_invalid_markers(answer, TITLED) == '**《' + TITLE + '》** [1] 营收'


def test_a_bracketed_number_outside_any_source_title_is_removed():
    assert strip_invalid_markers('Revenue was 100 [2026]', TITLED) == 'Revenue was 100'


def test_an_unavailable_source_is_not_a_resolvable_marker():
    pool = [{'ordinal': 2, 'source_type': 'unavailable', 'quote': ''}]
    assert strip_invalid_markers('数据缺失 [2]。', pool) == '数据缺失。'


@pytest.mark.parametrize('answer', [
    '营收 [1] [13]。',
    '甲 [12][13]\n乙 [1][6]',
    '| 指标 | 值 |\n|---|---|\n| 甲 | 1 [13][12] |\n| 乙 | 2 [11] |',
])
def test_after_stripping_no_invalid_marker_is_left_and_no_valid_one_is_lost(answer):
    stripped = strip_invalid_markers(answer, POOL)
    assert citation_errors(stripped, POOL) == []
    assert re.findall(r'\[(\d+)\]', stripped) == [m for m in re.findall(r'\[(\d+)\]', answer) if int(m) in (1, 6, 11)]


def _turn(citations):
    turn = Turn('AAPL 股息率', AgentRuntimeContext('custom', 'test', 'dummy'), None, [], {})
    turn.route = 'A'
    turn.citations = citations
    return turn


def test_the_delivered_answer_and_its_unverified_lines_carry_no_dead_marker():
    answer = 'AAPL 股息率 0.4% [1]。\n按股价推算年股息约 1.04 美元 [12][13]。'
    result = _turn(POOL).finish(answer)
    assert '[12]' not in result['answer'] and '[13]' not in result['answer']
    assert 'AAPL 股息率 0.4% [1]。' in result['answer']
    assert '1.04 美元。' in result['answer']
    assert '未能与来源核对' in result['answer']
    assert 'invalid_citation' in result['audit']['answer_issues']
    assert result['unverified_lines'] and all('[12]' not in e['line'] and '[13]' not in e['line']
                                              for e in result['unverified_lines'])


def test_a_clean_answer_is_delivered_byte_for_byte():
    answer = 'AAPL 股息率 0.4% [1]。\n来源：[1][6][11]'
    result = _turn(POOL).finish(answer)
    assert result['answer'] == answer
