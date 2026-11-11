"""FP2: the earlier conversation the answering model sees follows its window, and a long answer is cut head+tail."""
import asyncio
import re
import pytest
from app.agent_workflow import direct, truncation
from app.agent_workflow.state import AgentRuntimeContext
from app import agent_context as layers


async def emit(_):
    pass


@pytest.fixture(autouse=True)
def _window_on(monkeypatch):
    monkeypatch.setenv('FINBOT_FP2_PRIOR_WINDOW', 'on')


def _turn(messages, question='它呢？', **ctx_kwargs):
    return direct.Turn(question, _ctx(**ctx_kwargs), emit, messages, {})


def _ctx(**kwargs):
    return AgentRuntimeContext('custom', 'test', 'dummy', context_window=kwargs.pop('context_window', 128000), **kwargs)


# --- group 6: truncation.cut_head_tail -------------------------------------------------------------

def test_cut_head_tail_returns_short_text_unchanged():
    text = '短文本' * 10
    assert truncation.cut_head_tail(text, 10_000) == text
    assert truncation.cut_head_tail(text, len(text.encode())) == text


def test_cut_head_tail_returns_empty_when_the_budget_is_too_small():
    assert truncation.cut_head_tail('汉' * 20000, 500) == ''


def test_cut_head_tail_keeps_the_result_within_budget_for_four_byte_characters():
    text = '😀' * 2000                       # 8000 bytes; the 3-byte formula overshoots, the 4-byte one fits
    cut = truncation.cut_head_tail(text, 4000)
    assert cut and len(cut.encode()) <= 4000
    assert cut.startswith('😀') and cut.endswith('😀') and '中间省略' in cut


def test_cut_head_tail_keeps_the_real_end_of_the_text_not_the_whole_text():
    text = 'H' * 10000 + 'T' * 10000          # ASCII: 20000 bytes, budget 3000 -> keep 970, head 485, tail 485
    cut = truncation.cut_head_tail(text, 3000)
    assert cut != text and len(cut.encode()) <= 3000
    head, marker, tail = cut.split('\n')
    assert head == 'H' * 485 and tail == 'T' * 485
    assert marker == '…（中间省略 19030 字）…'


# --- group 1: the newest answer, too long for the budget, keeps its head and tail -------------------

def test_a_long_newest_answer_keeps_its_head_and_tail_within_the_budget():
    answer = '前' * 100 + '中' * 19800 + '后' * 100          # 20000 characters, 60000 bytes > the 48000 budget
    turn = _turn([{'role': 'user', 'content': '查 AMD'}, {'role': 'assistant', 'content': answer},
                  {'role': 'user', 'content': '它呢？'}])
    prior = turn.prior_turns()
    kept = [m for m in prior if m['role'] == 'assistant']
    assert len(kept) == 1
    content = kept[0]['content']
    assert content.startswith('前' * 100) and content.endswith('后' * 100) and '中间省略' in content
    assert len(content.encode()) <= 48000
    assert any(e['site'] == 'prior_turns.newest' for e in turn.audit['truncation_events'])


# --- group 2: a short history is the same with the window on or off -------------------------------

HISTORY3 = [{'role': 'user', 'content': '查 AMD 收盘价'},
            {'role': 'assistant', 'content': 'AMD 收盘价为 160.12 美元 [1]。'},
            {'role': 'user', 'content': '它呢？'}]


def test_a_short_history_comes_back_exactly_as_with_the_window_off(monkeypatch):
    on = _turn(HISTORY3).prior_turns()
    monkeypatch.setenv('FINBOT_FP2_PRIOR_WINDOW', 'off')
    off = _turn(HISTORY3).prior_turns()
    assert on == off and [m['role'] for m in on] == ['user', 'assistant']


# --- group 4: window off pins the old behaviour: a long answer leaves the whole history out ------

def test_window_off_sends_no_earlier_message_when_the_last_answer_is_too_long(monkeypatch):
    monkeypatch.setenv('FINBOT_FP2_PRIOR_WINDOW', 'off')
    turn = _turn([{'role': 'user', 'content': '查 AMD 收盘价'}, {'role': 'assistant', 'content': '汉' * 20000},
                  {'role': 'user', 'content': '它呢？'}])
    assert not any(m['role'] in {'user', 'assistant'} for m in turn.prior_turns())
    assert 'truncation_events' not in turn.audit


# --- group 5: the budget follows the window (the cut's byte budget is the observable) -------------

@pytest.mark.parametrize('window,budget', [(128000, 48000), (16000, 16000), (1000000, 48000)])
def test_the_budget_follows_the_model_window(monkeypatch, window, budget):
    seen = []
    real = truncation.cut_head_tail
    monkeypatch.setattr(truncation, 'cut_head_tail', lambda text, b: seen.append(b) or real(text, b))
    _turn([{'role': 'user', 'content': '查'}, {'role': 'assistant', 'content': '汉' * 30000},
           {'role': 'user', 'content': '它呢？'}], context_window=window).prior_turns()
    assert seen == [budget]


def test_an_explicit_max_bytes_overrides_the_window(monkeypatch):
    seen = []
    real = truncation.cut_head_tail
    monkeypatch.setattr(truncation, 'cut_head_tail', lambda text, b: seen.append(b) or real(text, b))
    _turn([{'role': 'user', 'content': '查'}, {'role': 'assistant', 'content': '汉' * 30000},
           {'role': 'user', 'content': '它呢？'}], context_window=128000).prior_turns(max_bytes=1000)
    assert seen == [1000]


# --- group 3: forty rounds of medium history: the newest whole, the older ones named ---------------

def _forty_rounds():
    messages = []
    for i in range(1, 41):
        messages.append({'role': 'user', 'content': f'第{i}个问题：AMD 营收'})
        messages.append({'role': 'assistant', 'content': f'第{i}个回答：' + '答' * 1000})
    return messages


def test_forty_rounds_keep_the_newest_whole_and_name_the_older_ones_that_were_left_out():
    messages = _forty_rounds() + [{'role': 'user', 'content': '它呢？'}]
    turn = _turn(messages)
    prior = turn.prior_turns()
    older = prior[0]
    left = 80 - (len(prior) - 1)                       # 80 earlier messages; the note is the one system line before them
    assert older == {'role': 'system', 'content':
                     '（更早的 %d 条对话消息因长度没有在这里展开；需要时用 recall_conversations 回查。）' % left}
    assert left > 0
    turns = prior[1:]
    assert all(m['role'] in {'user', 'assistant'} for m in turns)
    assert turns[-1] == messages[-2] and turns[-2] == messages[-3]     # the newest answer and question, whole
    event = next(e for e in turn.audit['truncation_events'] if e['site'] == 'prior_turns.older')
    assert event['dropped_messages'] == left


# --- group 7: memory and catalogue stay first, unchanged ----------------------------------------------

def test_memory_and_catalogue_stay_first_and_unchanged_when_the_older_note_is_added():
    memory = layers.MEMORY_NOTE + '\n- 用户关注 AMD'
    catalogue = layers.CATALOGUE_NOTE + '\n[]'
    messages = [{'role': 'user', 'content': memory}, {'role': 'user', 'content': catalogue}] + _forty_rounds() + \
               [{'role': 'user', 'content': '它呢？'}]
    prior = _turn(messages).prior_turns()
    assert prior[0] == {'role': 'system', 'content': memory}
    assert prior[1] == {'role': 'system', 'content': catalogue}
    assert prior[2]['role'] == 'system' and prior[2]['content'].startswith('（更早的 ')
