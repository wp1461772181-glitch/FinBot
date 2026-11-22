"""FINBOT_GATHER_LOW_EFFORT: evidence-gathering steps of the tool loop think at low; the answer is written at the bot's effort."""
import asyncio

import pytest

from app.agent_workflow.direct import Turn
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
        calls.append({'effort': stage_effort, 'tools': bool(tool_schemas)})
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
    assert calls == [{'effort': 'low', 'tools': True}, {'effort': None, 'tools': True}]
    assert t.audit['gather_effort'] == {'effort': 'low', 'steps': 1, 'answered_at_own': 1}


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
