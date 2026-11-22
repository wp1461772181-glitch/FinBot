"""FINBOT_GATHER_LOW_EFFORT: evidence-gathering steps of the tool loop think at low; the answer is written at the bot's effort."""
import asyncio

import pytest

from app.agent_workflow.direct import OWN_PASS_AGAIN_NOTE, OWN_PASS_FIRST_NOTE, Turn
from app.agent_workflow.state import AgentRuntimeContext


async def emit(_):
    return None


def turn(effort):
    context = AgentRuntimeContext('anthropic', 'm', 'k', conversation_id='c', reasoning_effort=effort)
    t = Turn('英伟达最新一季营收是多少？', context, emit, [{'role': 'user', 'content': '英伟达最新一季营收是多少？'}], {})
    t.route = 'A'
    return t


def script(monkeypatch, replies):
    """Turn.model replaced: each call takes the next scripted reply and records the effort it was asked at and the tools offered."""
    calls = []
    queue = list(replies)

    async def fake(self, messages, tool_schemas, *, protocol_retries=1, stage_effort=None):
        last = messages[-1].get('content') if messages else ''
        note = 'first' if last == OWN_PASS_FIRST_NOTE else 'again' if last == OWN_PASS_AGAIN_NOTE else None
        calls.append({'effort': stage_effort, 'tools': bool(tool_schemas), **({'note': note} if note else {})})
        return queue.pop(0)
    monkeypatch.setattr(Turn, 'model', fake)
    return calls


TOOL_CALL = {'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'query_financials', 'arguments': '{"symbol":"NVDA"}'}}]}
ANSWER = {'content': '营收 1,158.44 亿美元 [1]'}
DRAFT = {'content': '草稿'}


def test_a_step_that_asks_for_a_tool_is_taken_once_at_low(monkeypatch):
    calls = script(monkeypatch, [TOOL_CALL])
    t = turn('max')
    assert asyncio.run(t.decision()) is TOOL_CALL
    assert calls == [{'effort': 'low', 'tools': True}]
    assert t.audit['gather_effort'] == {'effort': 'low', 'steps': 1, 'answered_at_own': 0}


def test_a_low_step_that_is_ready_to_answer_is_asked_again_at_the_bots_effort_with_tools_on_offer(monkeypatch):
    calls = script(monkeypatch, [DRAFT, ANSWER])
    t = turn('max')
    assert asyncio.run(t.decision()) is ANSWER          # the low draft is dropped
    assert calls == [{'effort': 'low', 'tools': True}, {'effort': None, 'tools': True, 'note': 'first'}]
    assert t.audit['gather_effort'] == {'effort': 'low', 'steps': 1, 'answered_at_own': 1, 'own_pass': 1}


def test_the_bots_own_pass_may_still_ask_for_more_evidence(monkeypatch):
    calls = script(monkeypatch, [DRAFT, TOOL_CALL])
    t = turn('xhigh')
    assert asyncio.run(t.decision()) is TOOL_CALL
    assert [c['effort'] for c in calls] == ['low', None]


@pytest.mark.parametrize('own', [None, 'none', 'minimal', 'low'])
def test_an_effort_not_above_low_or_unset_keeps_the_single_old_call(monkeypatch, own):
    calls = script(monkeypatch, [ANSWER])
    t = turn(own)
    assert asyncio.run(t.decision()) is ANSWER
    assert calls == [{'effort': None, 'tools': True}] and 'gather_effort' not in t.audit


def test_the_switch_off_keeps_the_single_old_call(monkeypatch):
    monkeypatch.setenv('FINBOT_GATHER_LOW_EFFORT', 'off')
    calls = script(monkeypatch, [ANSWER])
    t = turn('max')
    assert asyncio.run(t.decision()) is ANSWER
    assert calls == [{'effort': None, 'tools': True}] and 'gather_effort' not in t.audit


def test_the_closing_answer_is_always_at_the_bots_effort_and_without_tools(monkeypatch):
    calls = script(monkeypatch, [ANSWER])
    t = turn('max')
    assert asyncio.run(t.decision(closing=True)) is ANSWER
    assert calls == [{'effort': None, 'tools': False}] and 'gather_effort' not in t.audit


def test_after_the_own_pass_asked_for_more_the_next_steps_are_its_own_and_are_told_to_write(monkeypatch):
    """The production follow-up: low says ready, the own pass asks for more, and from then on no step goes back to low."""
    calls = script(monkeypatch, [TOOL_CALL, DRAFT, TOOL_CALL, ANSWER])
    t = turn('max')
    assert asyncio.run(t.decision()) is TOOL_CALL            # gathering, low
    assert asyncio.run(t.decision()) is TOOL_CALL            # low is ready; the own pass asks for everything it misses
    assert asyncio.run(t.decision()) is ANSWER               # straight to the own pass, told to write
    assert calls == [{'effort': 'low', 'tools': True},
                     {'effort': 'low', 'tools': True}, {'effort': None, 'tools': True, 'note': 'first'},
                     {'effort': None, 'tools': True, 'note': 'again'}]
    assert t.audit['gather_effort'] == {'effort': 'low', 'steps': 2, 'answered_at_own': 2, 'own_pass': 2, 'own_tool_rounds': 1}


def test_the_notes_are_only_on_the_own_pass_and_never_on_a_low_step_or_the_closing_call(monkeypatch):
    calls = script(monkeypatch, [TOOL_CALL, ANSWER])
    t = turn('high')
    asyncio.run(t.decision())
    asyncio.run(t.decision(closing=True))
    assert all('note' not in c for c in calls)


def test_a_recovery_round_after_an_own_pass_that_asked_for_nothing_gets_no_write_now_note(monkeypatch):
    """The own pass answered with no tool; the loop then appended its own recovery note (a nudge to use the tools) and came back.
    Nothing may be added after that note: the next own pass must be free to call the tools the nudge asks for."""
    calls = script(monkeypatch, [DRAFT, ANSWER, TOOL_CALL, ANSWER])
    t = turn('max')
    assert asyncio.run(t.decision()) is ANSWER                # low ready -> own pass answers (first note)
    t.protocol.append({'role': 'system', 'content': '请使用工具取证。'})   # what the loop's nudge does before `continue`
    assert asyncio.run(t.decision()) is TOOL_CALL             # own pass again, with no note of ours
    assert asyncio.run(t.decision()) is ANSWER                # it did ask for more: now it is told to write
    assert [c.get('note') for c in calls] == [None, 'first', None, 'again']
    assert [c['effort'] for c in calls] == ['low', None, None, None]
    assert 'own_asked_last' not in t.audit['gather_effort']
