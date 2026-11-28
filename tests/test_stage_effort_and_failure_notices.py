"""FINBOT_STAGE_LOW_EFFORT (the steps before the answer think at low) and FINBOT_FAILURE_NOTICES (a failed turn says why)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.agent_chat_provider import ProviderFailure
from app.agent_chat_stream import _FAILURE_NOTICES, _failure_notice
from app.agent_workflow.state import AgentRuntimeContext

GENERIC = "这一轮没有完成，没有生成回答。可以再发一次；如果连续出现，请稍后再试或换个问法。"


async def emit(_):
    return None


def turn(effort, **kwargs):
    context = AgentRuntimeContext('anthropic', 'm', 'k', conversation_id='c', reasoning_effort=effort, **kwargs)
    return Turn('英伟达最新财报怎么样？', context, emit, [{'role': 'user', 'content': '英伟达最新财报怎么样？'}], {})


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


