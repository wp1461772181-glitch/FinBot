import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.agent_chat_stream import _failure_notice
from app.agent_workflow import consent, direct
from app.agent_workflow.models import AgentConsent
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine
from app.knowledge.remote import KnowledgeOffline


NOTICES = {
    'chat_context_too_large': '这一轮没有完成：对话上下文超过了当前模型能处理的长度。再发一次不会解决；可以先发送「/压缩」压缩这条对话，或开一个新对话再问。',
    'pending_request_expired': '这张卡片已经过期，没有执行任何操作。请把你的选择直接打字发给我，或重新提出请求。',
    'pending_request_mismatch': '这张卡片已经不是当前待处理的那一张，没有执行任何操作。请按最新的卡片操作，或重新提出请求。',
    'task_token_cap': '这次任务的用量达到了为它设定的上限，已停止。原样重跑结果相同；可以缩小任务范围后再试。',
    'workflow_incomplete': '这一轮在生成过程中意外中断，没有生成回答。可以再发一次。',
    'provider_protocol_invalid': '模型服务这次返回的内容无法使用，本轮没有完成。可以再发一次；连续出现时请稍后再试。',
}


@pytest.mark.parametrize('code,expected', NOTICES.items())
def test_registered_failure_notice(code, expected):
    notice = _failure_notice(HTTPException(502, code))
    assert notice == expected and code not in notice


@pytest.mark.parametrize('code', ['chat_context_too_large', 'task_token_cap'])
def test_retry_does_not_claim_to_fix_limits(code):
    assert '请再发一次' not in _failure_notice(HTTPException(502, code))


def test_unknown_failure_fallback():
    notice = _failure_notice(HTTPException(502, 'unknown_failure'))
    assert notice == '这一轮没有完成，没有生成回答。可以再发一次；如果连续出现，请稍后再试或换个问法。'
    assert '没有完成' in notice


def test_knowledge_offline_copy():
    assert KnowledgeOffline.hint == '知识库检索服务当前不可用，本轮请不依赖知识库继续回答。'
    assert 'Mac' not in KnowledgeOffline.hint
    assert KnowledgeOffline.code == 'knowledge_offline'


async def emit(_):
    pass


def expired_card():
    return {'id': 'clarify-1', 'reason': 'missing_information', 'question': '选哪一项？',
            'expires_at': (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            'choices': [{'label': '微软', 'value': 'reply:微软'}]}


def test_expired_clarification_reply_continues(monkeypatch):
    monkeypatch.delenv('FINBOT_FP4_EXPIRED_CARD_REPLY', raising=False)
    seen = []
    def resolver(payload):
        seen.append(payload['question'])
        return {'relationship': 'new', 'canonical_question': payload['question']}
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', resolver=resolver,
                              classifier=lambda _: {'category': 'D'}, decider=lambda *_: {'content': '好的。'})
    card = expired_card()
    result = asyncio.run(direct.run_direct_turn('reply:微软', ctx, emit=emit,
                         state={'pending_request': card, 'requested_pending_id': card['id']}))
    assert result['audit']['pending_request_expired_reply'] is True
    assert result.get('reason') != 'pending_request_expired'
    assert seen == ['微软']


@pytest.mark.parametrize('value,flag', [('reply:微软', 'off'), ('微软', 'on')])
def test_expired_clarification_other_cases_still_raise(monkeypatch, value, flag):
    monkeypatch.setenv('FINBOT_FP4_EXPIRED_CARD_REPLY', flag)
    card = expired_card()
    turn = direct.Turn(value, AgentRuntimeContext('custom', 'test', 'dummy'), emit, [],
                       {'pending_request': card, 'requested_pending_id': card['id']})
    with pytest.raises(ValueError, match='^pending_request_expired$'):
        asyncio.run(turn.consent_reply())


def test_expired_write_card_still_rejected(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConsent.__table__])
    monkeypatch.setattr(consent, 'owner_credential_matches', lambda c: c == 'owner')
    monkeypatch.setenv('FINBOT_FP4_EXPIRED_CARD_REPLY', 'on')
    operations = [{'name': 'index', 'arguments': {}}]
    card = consent.propose('owner', 'conversation', operations, {})
    card['reason'] = 'write_confirmation'
    with SessionLocal() as db:
        row = db.get(AgentConsent, uuid.UUID(card['id']))
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    card['expires_at'] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='owner', conversation_id='conversation')
    turn = direct.Turn(card['choices'][0]['value'], ctx, emit, [],
                       {'pending_request': card, 'requested_pending_id': card['id']})
    with pytest.raises(consent.ConsentError, match='confirmation_expired'):
        asyncio.run(turn.consent_reply())
    assert 'pending_request_expired_reply' not in turn.audit
