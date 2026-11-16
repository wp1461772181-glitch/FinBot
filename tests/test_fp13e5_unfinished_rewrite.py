"""FP13-E5 (ruling-fp13-e5-fix.md section 3, pins K1-K13).

S1 (FINBOT_FP13E5_RESOLVER_UNFINISHED): the resolver prompt says what an unfinished earlier request in the history is.
S2 (FINBOT_FP13E5_UNFINISHED_FACT): when a rewrite comes back to such a request and the user's own words do not, the
answering model is given that fact as a hint. Nothing is changed, deleted or blocked by either slice.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from app import agent_context as layers
from app.agent_workflow import direct
from app.agent_workflow.direct import REFERENCE_PROMPT, resolver_prompt
from app.agent_workflow.state import AgentRuntimeContext

S1 = 'FINBOT_FP13E5_RESOLVER_UNFINISHED'
S2 = 'FINBOT_FP13E5_UNFINISHED_FACT'
SW1 = 'FINBOT_SW1_RESOLVER_RULES'
BASE = '8640abf'      # the commit this package is cut from

# sha256 of the UTF-8 text, measured on the unmodified direct.py at 8640abf before any FP13-E5 edit.
BASE_REFERENCE_PROMPT_SHA = '25036339441a2744e2338dc00a8cdb9cc39d2337471087a7c13c90ff2f3885da'
BASE_RESOLVER_PROMPT_SW1_ON_SHA = 'e0e37bedc3bc3671baa167ecf23180b61ab246bb3cf43fae7bfad93a3ed8ae48'
BASE_RESOLVER_PROMPT_SW1_OFF_SHA = '25036339441a2744e2338dc00a8cdb9cc39d2337471087a7c13c90ff2f3885da'

# The anchor sentence of REFERENCE_PROMPT that S1 is inserted after (ruling 3.1).
S1_ANCHOR = 'canonical_question 始终用用户的口吻复述用户这一轮的请求（问题或指令），绝不是反问用户，也不请用户确认。'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@pytest.fixture(autouse=True)
def flags_at_their_defaults(monkeypatch):
    for name in (S1, S2, SW1, 'FINBOT_FP1_ORIGINAL_WORDS', 'FINBOT_FP3_UNFINISHED_TURNS'):
        monkeypatch.delenv(name, raising=False)


# ---- S1: resolver prompt ------------------------------------------------------------------------

def test_k1_default_on_puts_the_unfinished_rule_once_right_after_its_anchor():
    rule = direct.RESOLVER_UNFINISHED_TEXT
    prompt = resolver_prompt()
    assert REFERENCE_PROMPT.count(S1_ANCHOR) == 1
    assert prompt.count(rule) == 1
    assert (S1_ANCHOR + rule) in prompt


@pytest.mark.parametrize('sw1', ['on', 'off'])
def test_k1_holds_with_the_sw1_rules_on_and_off(monkeypatch, sw1):
    monkeypatch.setenv(S1, 'on')
    monkeypatch.setenv(SW1, sw1)
    prompt = resolver_prompt()
    assert prompt.count(direct.RESOLVER_UNFINISHED_TEXT) == 1
    assert (S1_ANCHOR + direct.RESOLVER_UNFINISHED_TEXT) in prompt
    assert (direct.RESOLVER_RULE_TEXT in prompt) is (sw1 == 'on')


@pytest.mark.parametrize('sw1,expected', [('on', BASE_RESOLVER_PROMPT_SW1_ON_SHA),
                                         ('off', BASE_RESOLVER_PROMPT_SW1_OFF_SHA)])
def test_k2_switch_off_is_byte_identical_to_8640abf(monkeypatch, sw1, expected):
    monkeypatch.setenv(S1, 'off')
    monkeypatch.setenv(SW1, sw1)
    prompt = resolver_prompt()
    assert sha(prompt) == expected, f'resolver_prompt() differs from {BASE} with SW1={sw1}'
    assert '对话里后面跟着' not in prompt


def test_k3_reference_prompt_constant_is_unchanged():
    assert sha(REFERENCE_PROMPT) == BASE_REFERENCE_PROMPT_SHA


# ---- S2: the system's fact that a rewrite came back to an unfinished earlier request --------------

LONG = '请逐个查询英伟达、AMD、微软、苹果这四家公司最近一个财年的营收和毛利率，分别取数、逐个计算，最后做一个对比表。'
LONG_REWRITE = '请逐个查询英伟达（NVDA）、AMD、微软（MSFT）、苹果（AAPL）这四家公司最近一个财年的营收和毛利率，分别取数、逐个计算，最后做一个对比表。'
SHORT = '苹果公司最新股价是多少？'
SYSTEM = {'role': 'system', 'content': '你是 FinBot。'}
S2_TEXT_KEY = 'unfinished_note'
UNDERSTANDING = direct.UNDERSTANDING_NOTE


async def emit(_):
    pass


def user(content):
    return {'role': 'user', 'content': content}


def complete(question, answer='四家公司对比表。'):
    return [user(question), {'role': 'assistant', 'content': answer}]


def unfinished(question, state='cancelled'):
    return [user(question), {'role': 'assistant', 'content': layers.UNFINISHED_NOTES[state]}]


def accident_history():
    """The shape of the 2026-11-16 failure: the long question answered four times, then cancelled, then the short one."""
    answered = [m for _ in range(4) for m in complete(LONG)]
    return [SYSTEM, *answered, *unfinished(LONG)]


def returning(canonical, relationship='new'):
    return lambda _: {'relationship': relationship, 'canonical_question': canonical}


def turn_for(question, messages, resolver):
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', resolver=resolver, classifier=lambda _: {'category': 'D'})
    return direct.Turn(question, ctx, emit, messages, {})


def hint_text(messages):
    return next(m['content'] for m in messages if m['role'] == 'system' and m['content'].startswith(UNDERSTANDING))


def hint_of(messages):
    text = hint_text(messages)
    return json.loads(text[len(UNDERSTANDING):])


def run_reference(monkeypatch, enabled, question, messages, canonical, relationship='new'):
    monkeypatch.setenv(S2, 'on' if enabled else 'off')
    turn = turn_for(question, messages, returning(canonical, relationship))
    asyncio.run(turn.reference())
    return turn


def tool_msgs(turn):
    return turn.tool_messages()


def test_k4_accident_shape_is_matched_and_the_hint_carries_the_fact():
    turn = turn_for(SHORT, accident_history() + [user(SHORT)], returning(LONG_REWRITE))
    asyncio.run(turn.reference())
    assert turn.unfinished_rewrite == LONG
    assert turn.audit['resolver_unfinished_match'] is True
    assert turn.question == LONG_REWRITE
    hint = hint_of(tool_msgs(turn))
    assert hint[S2_TEXT_KEY] == direct.UNFINISHED_FACT_TEXT
    assert hint['user_original_words'] == SHORT


@pytest.mark.parametrize('words', ['继续', '再试一次'])
def test_k5_continue_or_retry_still_matches_and_the_rewrite_still_rules(words):
    classified, seen = [], []

    def classify(question):
        classified.append(question)
        return {'category': 'D'}

    def decide(messages, tools):
        seen.append(messages)
        return {'content': '好的。'}

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', resolver=returning(LONG_REWRITE), classifier=classify, decider=decide)
    result = asyncio.run(direct.run_direct_turn(words, ctx, emit=emit, messages=accident_history() + [user(words)]))
    messages = seen[0]
    assert result['audit']['resolver_unfinished_match'] is True
    assert classified == [LONG_REWRITE]
    assert [m['content'] for m in messages if m['role'] == 'user'][-1] == LONG_REWRITE
    hint = hint_of(messages)
    assert hint['resolved_question'] == LONG_REWRITE
    assert hint[S2_TEXT_KEY] == direct.UNFINISHED_FACT_TEXT
    assert hint['user_original_words'] == words


def test_k6_resending_the_same_long_question_is_not_matched(monkeypatch):
    messages = accident_history() + [user(LONG)]
    on = run_reference(monkeypatch, True, LONG, messages, LONG)
    off = run_reference(monkeypatch, False, LONG, messages, LONG)
    assert on.unfinished_rewrite is None and 'resolver_unfinished_match' not in on.audit
    assert hint_text(tool_msgs(on)) == hint_text(tool_msgs(off))
    assert S2_TEXT_KEY not in hint_of(tool_msgs(on))


def test_k7_a_long_question_seen_only_in_complete_turns_is_not_matched(monkeypatch):
    messages = [SYSTEM, *complete(LONG), *complete(LONG), user(SHORT)]
    on = run_reference(monkeypatch, True, SHORT, messages, LONG_REWRITE)
    off = run_reference(monkeypatch, False, SHORT, messages, LONG_REWRITE)
    assert on.unfinished_rewrite is None and 'resolver_unfinished_match' not in on.audit
    assert hint_text(tool_msgs(on)) == hint_text(tool_msgs(off))
    assert S2_TEXT_KEY not in hint_of(tool_msgs(on))


@pytest.mark.parametrize('state', ['cancelled', 'failed', 'interrupted'])
def test_k8_each_of_the_three_records_is_recognised(state):
    assert set(layers.UNFINISHED_NOTES) == {'cancelled', 'failed', 'interrupted'}
    messages = [SYSTEM, *unfinished(LONG, state), user(SHORT)]
    assert direct.unfinished_rewrite(messages, LONG_REWRITE, SHORT) == LONG


def test_k8_direct_py_never_spells_out_the_three_records():
    source = Path(direct.__file__).read_text(encoding='utf-8')
    for note in layers.UNFINISHED_NOTES.values():
        assert note not in source


def test_k9_switch_off_adds_nothing_to_the_hint_and_writes_no_audit(monkeypatch):
    messages = accident_history() + [user(SHORT)]
    off = run_reference(monkeypatch, False, SHORT, messages, LONG_REWRITE)
    on = run_reference(monkeypatch, True, SHORT, messages, LONG_REWRITE)
    assert off.question == LONG_REWRITE and 'resolver_unfinished_match' not in off.audit
    off_hint, on_hint = hint_of(tool_msgs(off)), hint_of(tool_msgs(on))
    assert S2_TEXT_KEY not in off_hint
    assert on.unfinished_rewrite is not None and on.audit['resolver_unfinished_match'] is True
    assert on_hint[S2_TEXT_KEY] == direct.UNFINISHED_FACT_TEXT
    assert {k: v for k, v in on_hint.items() if k != S2_TEXT_KEY} == off_hint


def test_k10_with_the_original_words_switch_off_the_fact_brings_the_words(monkeypatch):
    monkeypatch.setenv('FINBOT_FP1_ORIGINAL_WORDS', 'off')
    turn = run_reference(monkeypatch, True, SHORT, accident_history() + [user(SHORT)], LONG_REWRITE)
    hint = hint_of(tool_msgs(turn))
    assert hint['user_original_words'] == SHORT
    assert hint[S2_TEXT_KEY] == direct.UNFINISHED_FACT_TEXT
    assert 'original_words_note' not in hint


def test_k11_the_period_note_and_the_fact_sit_side_by_side(monkeypatch):
    period = {'start': '2026-07-01', 'end': '2026-09-30', 'today': '2026-11-16'}
    turn = run_reference(monkeypatch, True, SHORT, accident_history() + [user(SHORT)], LONG_REWRITE)
    turn.audit['resolver_period_unfinished'] = period
    on = hint_of(tool_msgs(turn))
    off_turn = run_reference(monkeypatch, False, SHORT, accident_history() + [user(SHORT)], LONG_REWRITE)
    off_turn.audit['resolver_period_unfinished'] = period
    off = hint_of(tool_msgs(off_turn))
    assert on['period_note'] == off['period_note'] and on['period_note'].startswith('系统事实：改写里的期间 2026-07-01 至 2026-09-30')
    assert on[S2_TEXT_KEY] == direct.UNFINISHED_FACT_TEXT


def test_k12_a_failed_resolver_and_a_card_never_compute_the_fact():
    def broken(_):
        raise RuntimeError('resolver down')

    failed = turn_for(SHORT, accident_history() + [user(SHORT)], broken)
    asyncio.run(failed.reference())
    assert failed.resolver_failed is True
    assert failed.unfinished_rewrite is None and 'resolver_unfinished_match' not in failed.audit

    def card(_):
        return {'relationship': 'clarify', 'question': '要看哪一个？', 'choices': ['英伟达', '苹果']}

    carded = turn_for(SHORT, accident_history() + [user(SHORT)], card)
    asyncio.run(carded.reference())
    assert carded.pending is not None
    assert carded.unfinished_rewrite is None


def test_k13_the_fp3_records_are_unchanged():
    # The diff scope (only app/agent_workflow/direct.py under app/) is checked at acceptance, not in the standing suite.
    assert layers.UNFINISHED_NOTES == {
        'cancelled': '（系统记录：这条消息的回答被取消，没有完成。）',
        'failed': '（系统记录：这条消息的回答失败了，没有完成。）',
        'interrupted': '（系统记录：这条消息没有得到回答，过程中断。）',
    }
