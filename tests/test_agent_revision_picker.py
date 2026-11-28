"""Revising a forecast through the agent: the user picks the materials, never the model.

Regression from 2026-10-20: asked to "修正这个快照", the agent chose three SEC filings itself, none
inside the revision window, and the card showed only "修正预测 · GOOGL".  Now the server lists the
materials the revision rule allows on a card the user ticks, and says plainly when there are none.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from app.agent_workflow import write_text
import pytest
from pydantic import ValidationError

from app.agent_tool_catalog import definitions
from app.agent_workflow import consent, tools, workspace_tools
from app.agent_workflow.models import AgentConsent
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine
from app.forecast_contract import future_xnys_sessions, latest_completed_xnys_session
from app.forecast_jobs import enqueue_job
from app.forecast_v2_models import ForecastVersionV2
from app.models import UploadedEvidence


from test_forecast_revision_candidates import forget_symbols


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(bind=engine)
    for module in (consent, tools, workspace_tools):
        monkeypatch.setattr(module, 'owner_credential_matches', lambda credential: credential == 'owner')
    yield 'owner'
    forget_symbols([f'RP{letter}' for letter in 'ABCDEFGH'])


def _context(conversation):
    return AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='owner',
                               owner_hash='o' * 64, conversation_id=conversation)


async def _quiet(_):
    pass


def _forecast(symbol, decided, *, target_end=None):
    with SessionLocal() as db:
        job = enqueue_job(db=db, symbol=symbol, kind='new', idempotency_key=f'picker-{uuid.uuid4()}')
        version = ForecastVersionV2(
            id=uuid.uuid4(), root_id=uuid.uuid4(), job_id=job.id, version_no=1, symbol=symbol,
            target_contract={'target_end_date': (target_end or future_xnys_sessions(latest_completed_xnys_session(datetime.now(UTC)), 20)[-1]).isoformat()},
            target_contract_hash='a' * 64, decision_at=decided, market_cutoff_at=decided - timedelta(minutes=5),
            price_input_manifest={}, evidence_version_manifest=[], feature_snapshot={},
            baseline_probabilities={'bearish': 0.2, 'neutral': 0.4, 'bullish': 0.4},
            joint_probabilities=None, model_status='research_only', model_manifest={}, trigger_type='manual',
        )
        version.root_id = version.id
        db.add(version); db.commit()
        return version.id


def _upload(symbol, title, published):
    with SessionLocal() as db:
        row = UploadedEvidence(
            symbol=symbol, title=title, source_url='https://news.example.test/' + uuid.uuid4().hex,
            published_at=published, observed_at=published + timedelta(hours=1), credibility_stars=4,
            credibility_reason='fixture', impact_severity='medium', filename='n.md',
            content_sha256=uuid.uuid4().hex.ljust(64, '0'), raw_content=b'x', content_text='x', status='unconfirmed')
        db.add(row); db.commit()
        return str(row.id)


def _turn(question, conversation, symbol, state=None):
    turn = direct.Turn(question, _context(conversation), _quiet, [], state or {})
    turn.route = 'D'
    turn.scope = {'symbol': symbol}
    turn.granted_actions = {'revise_forecast'}
    return turn


def test_the_model_cannot_name_revision_sources():
    schema = definitions()['revise_forecast'].args_schema
    assert set(schema.model_fields) == {'symbol', 'version_id', 'mentioned_sources'}
    with pytest.raises(ValidationError):
        schema.model_validate({'symbol': 'AAPL', 'source_refs': [
            {'source_type': 'official_filing', 'source_id': '11111111-1111-4111-8111-111111111111'}]})


def _card_with_two(owner_name, conversation):
    decided = datetime.now(UTC) - timedelta(days=6)
    _forecast('RPE', decided)
    first = _upload('RPE', '第一篇报道', decided + timedelta(days=1))
    second = _upload('RPE', '第二篇报道', decided + timedelta(days=2))
    turn = _turn('修正 RPE 的预测', conversation, 'RPE')
    asyncio.run(turn.propose('revise_forecast', {'symbol': 'RPE'}))
    return turn.pending, {'第一篇报道': first, '第二篇报道': second}


def _press(card, conversation, value, monkeypatch, sent):
    def execute_costly(operation, key, context):
        sent.append(operation)
        return {'ok': True, 'data': [{'job_id': str(uuid.uuid4()), 'status': 'queued', 'symbol': 'RPE',
                                      'action': 'revise_forecast'}]}
    monkeypatch.setattr(tools, 'execute_costly', execute_costly)
    turn = direct.Turn(value, _context(conversation), _quiet, [],
                       {'pending_request': card, 'requested_pending_id': card['id']})
    return asyncio.run(turn.consent_reply()), turn


def test_the_workspace_read_lists_the_same_candidates(owner):
    decided = datetime.now(UTC) - timedelta(days=6)
    _forecast('RPF', decided)
    inside = _upload('RPF', '窗口内报道', decided + timedelta(days=6))
    value = workspace_tools.revision_plan('RPF', None)
    assert value['status'] == 'ready'
    assert [c['source_id'] for c in value['candidates']] == [inside]


def test_named_materials_are_only_for_explaining():
    schema = definitions()['revise_forecast'].args_schema
    value = schema.model_validate({'symbol': 'AAPL', 'mentioned_sources': [
        {'source_type': 'official_filing', 'source_id': '11111111-1111-4111-8111-111111111111'}]})
    assert value.mentioned_sources[0].source_type == 'official_filing'
    assert 'never' in definitions()['revise_forecast'].description.lower()
