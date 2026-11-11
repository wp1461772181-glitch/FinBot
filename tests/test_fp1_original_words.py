"""FP1: the understanding hint carries the user's own words next to the rewrite.

The user message stays the rewrite. The original words travel only as one field of the
understanding hint, and only when they differ from the rewrite and are not a control value.
"""
import asyncio,json
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

async def emit(_):pass
HISTORY=[{'role':'user','content':'查 MSFT 最近一期年报的营业收入'},
         {'role':'assistant','content':'MSFT FY2026 营业收入为 331,839 百万美元 [1]。'}]
CANONICAL='MSFT 最近一期年报营业收入的同比变化'
NOTE_PHRASE='不要按原话重新推算'

def _capture():
    seen=[]
    def decide(messages,tools):seen.append(messages);return {'content':'好的。'}
    return seen,decide

def _run(question,resolver,*,history=HISTORY):
    seen,decide=_capture()
    ctx=AgentRuntimeContext('custom','test','dummy',resolver=resolver,classifier=lambda _:'D',decider=decide)
    result=asyncio.run(direct.run_direct_turn(question,ctx,emit=emit,messages=history))
    return result,seen[0]

def _rewrite(text,relationship='followup'):
    return lambda _:{'relationship':relationship,'canonical_question':text,'referents':[]}

def _users(messages):
    return [m['content'] for m in messages if m['role']=='user']

def _hint(messages):
    notes=[m['content'] for m in messages if m['role']=='system' and m['content'].startswith(direct.UNDERSTANDING_NOTE)]
    assert len(notes)==1
    return json.loads(notes[0][len(direct.UNDERSTANDING_NOTE):])

def test_a_followup_is_rewritten_and_its_words_travel_in_the_hint():
    _,messages=_run('它同比怎么样？',_rewrite(CANONICAL))
    hint=_hint(messages)
    assert hint['user_original_words']=='它同比怎么样？'
    assert NOTE_PHRASE in hint['original_words_note']
    assert _users(messages)[-1]==CANONICAL

def test_a_rewrite_that_is_rejected_leaves_neither_field_in_the_hint():
    result,messages=_run('它同比怎么样？',_rewrite('MSFT 2031 年报营业收入同比'))
    assert result['audit']['stages']['resolver']['validator']['rejected_reason']=='reference_period_unbound'
    hint=_hint(messages)
    assert 'user_original_words' not in hint and 'original_words_note' not in hint
    assert _users(messages)[-1]=='它同比怎么样？'

def test_switch_off_leaves_neither_field_in_the_hint(monkeypatch):
    monkeypatch.setenv('FINBOT_FP1_ORIGINAL_WORDS','off')
    _,messages=_run('它同比怎么样？',_rewrite(CANONICAL))
    hint=_hint(messages)
    assert 'user_original_words' not in hint and 'original_words_note' not in hint

def test_relative_time_keeps_the_rewritten_period_and_says_not_to_recompute():
    rewrite='微软 FY2025 营业收入'
    _,messages=_run('去年微软的营收是多少？',_rewrite(rewrite,relationship='new'),history=[])
    assert _users(messages)[-1]==rewrite
    assert NOTE_PHRASE in _hint(messages)['original_words_note']

def test_control_prefixed_words_leave_neither_field_in_the_hint():
    _,messages=_run('confirm:它同比怎么样？',_rewrite(CANONICAL))
    hint=_hint(messages)
    assert 'user_original_words' not in hint and 'original_words_note' not in hint

def test_long_original_words_are_capped_at_4000_and_recorded_as_truncation():
    result,messages=_run('x'*5000,_rewrite(CANONICAL))
    assert len(_hint(messages)['user_original_words'])==4000
    assert any(e['site']=='tool_messages.original_words' for e in result['audit']['truncation_events'])
