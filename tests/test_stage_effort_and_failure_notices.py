"""FINBOT_STAGE_LOW_EFFORT (the steps before the answer think at low) and FINBOT_FAILURE_NOTICES (a failed turn says why)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.agent_chat_provider import ProviderFailure
from app.agent_chat_stream import _FAILURE_NOTICES, _failure_notice
from app.agent_workflow import direct
from app.agent_workflow.direct import Turn
from app.agent_workflow.state import AgentRuntimeContext

GENERIC = "这一轮没有完成，没有生成回答。可以再发一次；如果连续出现，请稍后再试或换个问法。"


async def emit(_):
    return None


def turn(effort, **kwargs):
    context = AgentRuntimeContext('anthropic', 'm', 'k', conversation_id='c', reasoning_effort=effort, **kwargs)
    return Turn('英伟达最新财报怎么样？', context, emit, [{'role': 'user', 'content': '英伟达最新财报怎么样？'}], {})


@pytest.mark.parametrize('own', ['medium', 'high', 'xhigh', 'max'])
def test_a_bot_effort_above_low_makes_the_pre_answer_steps_think_at_low(own):
    t = turn(own)
    assert t.stage_effort() == 'low' and t.audit['stage_effort'] == 'low'


@pytest.mark.parametrize('own', [None, 'none', 'minimal', 'low', 'not-a-tier'])
def test_a_bot_effort_at_or_below_low_or_unset_is_left_alone(own):
    t = turn(own)
    assert t.stage_effort() is None and 'stage_effort' not in t.audit


def test_the_switch_off_never_overrides(monkeypatch):
    monkeypatch.setenv('FINBOT_STAGE_LOW_EFFORT', 'off')
    t = turn('max')
    assert t.stage_effort() is None and 'stage_effort' not in t.audit


def test_the_request_carries_the_stage_effort_only_when_one_is_given(monkeypatch):
    sent = []

    async def fake(provider, model, key, messages, schemas, base_url=None, **kwargs):
        sent.append(kwargs)
        return {}, {'content': 'ok'}
    monkeypatch.setattr(direct, 'decision_request', fake)
    t = turn('max')
    asyncio.run(t.provider_request([{'role': 'user', 'content': 'q'}], [], 'low'))
    asyncio.run(t.provider_request([{'role': 'user', 'content': 'q'}], []))
    assert sent == [{'reasoning_effort': 'low'}, {'reasoning_effort': 'max'}]
    plain = turn(None)
    asyncio.run(plain.provider_request([{'role': 'user', 'content': 'q'}], []))
    assert sent[-1] == {}


def test_resolving_and_classifying_ask_at_the_stage_effort_and_the_answer_does_not(monkeypatch):
    seen = []

    async def fake_model(self, messages, tool_schemas, *, protocol_retries=1, stage_effort=None):
        name = (tool_schemas[0].get('function') or {}).get('name') if tool_schemas else 'answer'
        seen.append((name, stage_effort))
        if name == 'resolve_reference':
            return {'content': '{"relationship":"new","canonical_question":"英伟达最新财报怎么样？"}'}
        if name == 'classify_request':
            return {'content': '{"category":"B","days_back":null}'}
        return {'content': '一般性解释'}
    monkeypatch.setattr(Turn, 'model', fake_model)
    # A second user message makes the turn a non-first one, so the resolver is not skipped.
    context = AgentRuntimeContext('anthropic', 'm', 'k', conversation_id='c', reasoning_effort='max')
    messages = [{'role': 'user', 'content': '苹果营收？'}, {'role': 'assistant', 'content': '营收 100'}, {'role': 'user', 'content': '英伟达最新财报怎么样？'}]
    t = Turn('英伟达最新财报怎么样？', context, emit, messages, {})

    async def run():
        await t.reference()
        await t.classify()
        await t.answer_b()
    asyncio.run(run())
    by_name = dict(seen)
    assert by_name['resolve_reference'] == 'low' and by_name['classify_request'] == 'low'
    assert by_name['answer'] is None


@pytest.mark.parametrize('code,status,shows_status,again', [
    ('provider_model_unavailable_or_invalid_request', 400, True, '原样再发不会成功'),
    ('provider_error', 503, True, '可以再发一次'),
    ('provider_incompatible_response', None, False, '可以再发一次'),
    ('provider_protocol_incompatible', 400, False, '原样再发通常结果相同'),
    ('provider_redirect_rejected', None, False, '设置 → 模型'),
])
def test_a_provider_failure_says_what_happened_and_whether_sending_again_helps(code, status, shows_status, again):
    notice = _failure_notice(ProviderFailure(code, stage='tool_decision', provider_status=status))
    assert notice != GENERIC and '本轮没有完成' in notice and again in notice and '{' not in notice
    assert (f'（上游返回 HTTP {status}）' in notice) is shows_status


def test_a_failure_without_a_status_shows_none_and_no_placeholder():
    notice = _failure_notice(HTTPException(502, 'provider_error'))
    assert notice != GENERIC and 'HTTP' not in notice and '{' not in notice


def test_the_switch_off_is_the_generic_sentence_again(monkeypatch):
    monkeypatch.setenv('FINBOT_FAILURE_NOTICES', 'off')
    for code in ('provider_error', 'provider_model_unavailable_or_invalid_request', 'provider_incompatible_response'):
        assert _failure_notice(ProviderFailure(code, stage='x', provider_status=500)) == GENERIC


def test_codes_that_already_had_a_notice_keep_it_and_unknown_codes_stay_generic():
    for code, text in _FAILURE_NOTICES.items():
        assert _failure_notice(HTTPException(502, code)) == text
    assert _failure_notice(HTTPException(502, 'something_else')) == GENERIC
    assert _failure_notice(RuntimeError('boom')) == GENERIC
