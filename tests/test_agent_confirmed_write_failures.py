"""A confirmed write must say what it wrote, and why it could not.

Regression: the owner confirmed four writes in production on 2026-10-19.  Three failed with a bare
``write_service_failed`` (a date-only ``published_at`` was read as naive, and a page that was mostly
images was rejected by the boilerplate gate without saying why), and the visible reply claimed the
card had never been minted.  The one success was reported as ``GOOGL（已完成）`` instead of the
article it saved.
"""
import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.agent_workflow import consent, tools
from app.agent_workflow.models import AgentConsent, AgentWebSource
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine
from app.knowledge.models import KnowledgeDocument, KnowledgeUploadOwner
from app.models import UploadedEvidence


def _runtime(conversation='confirmed-write'):
    return AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='owner',
                               owner_hash='o' * 64, conversation_id=conversation)


def _material(overrides=None):
    argument = {'symbol': 'GOOGL', 'title': 'AI的尽头是贷款（36氪转载）',
                'source_url': 'https://36kr.com/p/4024322436059265', 'published_at': '2026-10-14',
                'credibility_stars': 3, 'credibility_reason': '转载的行业评论。', 'impact_severity': 'medium',
                'content': '# AI的尽头是贷款\n\nAlphabet 的债务融资引发讨论。'}
    argument.update(overrides or {})
    return {'name': 'save_material_evidence', 'arguments': argument}


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConsent.__table__, UploadedEvidence.__table__,
                                             KnowledgeUploadOwner.__table__])
    monkeypatch.setattr(consent, 'owner_credential_matches', lambda credential: credential == 'owner')
    monkeypatch.setattr(tools, 'owner_credential_matches', lambda credential: credential == 'owner')
    return 'owner'


def test_a_date_only_publication_time_is_saved_as_utc(owner):
    operation = _material({'content': '# 材料\n\n' + uuid.uuid4().hex})
    digest = hashlib.sha256(operation['arguments']['content'].encode()).hexdigest()
    outcome = tools.execute_costly(operation, 'request.0', _runtime())

    assert outcome['ok'] is True and outcome['data'][0]['created'] is True
    with SessionLocal() as db:
        row = db.scalar(select(UploadedEvidence).where(UploadedEvidence.content_sha256 == digest))
        assert row is not None
        assert row.published_at == datetime(2026, 10, 14, tzinfo=UTC)
        assert row.observed_at.tzinfo is not None


def test_an_unparseable_publication_time_is_rejected_not_replaced_with_now(owner):
    operation = _material({'published_at': 'not-a-date', 'content': '# 材料\n\n' + uuid.uuid4().hex})
    content = operation['arguments']['content'].encode()
    conversation = 'unparseable-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '保存上传材料'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    result = consent.execute(owner, conversation, token, [operation],
                             lambda op, key: tools.execute_costly(op, key, _runtime(conversation)))

    outcome = result['data'][0]
    assert outcome['error_code'] == 'invalid_published_at'
    assert '日期' in outcome['reason'] and '缺少时区' not in outcome['reason']
    with SessionLocal() as db:
        assert db.scalar(select(UploadedEvidence).where(
            UploadedEvidence.content_sha256 == hashlib.sha256(content).hexdigest())) is None


def test_a_blocked_web_page_is_reported_as_such_not_as_a_write_service_failure(owner):
    operation = {'name': 'ingest_web_source', 'arguments': {'url': 'https://example.org/news'}, 'snapshot': {}}
    conversation = 'blocked-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '保存网页为来源'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    def handler(*_):
        raise ValueError('web_body_unavailable')

    outcome = consent.execute(owner, conversation, token, [operation], handler)['data'][0]
    assert outcome['error_code'] == 'page_fetch_blocked'
    assert '正文' in outcome['reason']
    assert 'web_body_unavailable' not in str(outcome)


def test_a_handler_exception_is_logged_with_operation_and_request_but_not_the_body(owner, caplog):
    caplog.set_level(logging.ERROR)
    operation = _material({'content': 'BODY-MARKER-' + uuid.uuid4().hex})
    conversation = 'logging-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '保存上传材料'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    def handler(*_):
        raise RuntimeError('service unavailable')

    consent.execute(owner, conversation, token, [operation], handler)

    records = [record for record in caplog.records if 'confirmed write failed' in record.getMessage()]
    assert records and operation['name'] in records[0].getMessage() and card['id'] in records[0].getMessage()
    assert records[0].exc_info and 'BODY-MARKER' not in caplog.text


def test_a_page_with_almost_no_text_keeps_its_own_rejection_reason():
    from app.agent_web_research import boilerplate_reason, is_boilerplate_page
    images = '![行情图](https://cdn.example.com/chart.png) ' * 12
    prose = '黄仁勋称AI市场震荡将会过去，Alphabet 与 CoreWeave 股价走弱。' * 3
    text = images + prose
    # The image markup still counts as links: 12 images and 90 characters of prose are a fragment,
    # not an article.  The reason must be the text-poor page, not a block page.
    assert is_boilerplate_page(text) is True
    assert boilerplate_reason(text) == 'page_without_text'


def test_a_block_page_keeps_the_fetch_blocked_reason():
    from app.agent_web_research import boilerplate_reason
    assert boilerplate_reason('Access denied. ' + '[menu](https://x.test/a) ' * 40) == 'page_fetch_blocked'


def test_a_text_poor_page_is_reported_as_page_without_text(owner):
    url = 'https://example.org/thin/' + uuid.uuid4().hex
    page = {'url': url, 'title': 'Alphabet 图片新闻',
            'excerpt': '![图](https://cdn.example.com/a.png) ' * 12 + 'Alphabet 股价走弱。' * 3,
            'published_at': '2026-10-17T12:00:00+00:00', 'fetched_at': datetime.now(UTC).isoformat(),
            'body_provenance': 'public_page_fetch'}
    from app.agent_workflow.web_sources import freeze_snapshot
    operation = {'name': 'ingest_web_source', 'arguments': {'url': url, 'symbol': 'GOOGL', 'company': 'Alphabet'},
                 'snapshot': freeze_snapshot(page), 'entity_aliases': []}
    conversation = 'thin-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '保存网页为来源'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    outcome = consent.execute(owner, conversation, token, [operation],
                              lambda op, key: tools.execute_costly(op, key, _runtime(conversation)))['data'][0]
    assert outcome['error_code'] == 'page_without_text'
    assert '只抓到很少的文字' in outcome['reason']
    assert 'web_body_unavailable' not in str(outcome)


def test_a_saved_web_source_returns_the_article_title_for_the_report(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentWebSource.__table__, KnowledgeDocument.__table__,
                                             UploadedEvidence.__table__, KnowledgeUploadOwner.__table__])
    monkeypatch.setattr(tools, 'owner_credential_matches', lambda credential: credential == 'owner')
    url = 'https://example.org/article/' + uuid.uuid4().hex
    page = {'url': url, 'title': 'Alphabet 的 AI 债务融资', 'excerpt': 'Alphabet 发行债券，市场关注其 AI 支出。',
            'published_at': '2026-10-14T04:07:04+00:00', 'fetched_at': datetime.now(UTC).isoformat(),
            'body_provenance': 'public_page_fetch'}
    from app.agent_workflow.web_sources import freeze_snapshot
    operation = {'name': 'ingest_web_source', 'arguments': {'url': url, 'symbol': 'GOOGL', 'company': 'Alphabet'},
                 'snapshot': freeze_snapshot(page), 'entity_aliases': []}

    outcome = tools.execute_costly(operation, 'request.0', _runtime())
    assert outcome['ok'] is True and outcome['status'] == 'created'
    assert outcome['title'] == 'Alphabet 的 AI 债务融资'


CARD = {'id': 'req-1', 'reason': 'write_confirmation', 'original_question': '保存这篇新闻',
        'display': {'title': '保存网页为来源', 'targets': [{'symbol': 'GOOGL', 'url': 'https://36kr.com/p/x'}]},
        'choices': [{'label': '同意', 'value': 'confirm:' + 't' * 40}]}
OPERATIONS = [{'name': 'ingest_web_source',
               'arguments': {'url': 'https://36kr.com/p/4024322436059265', 'symbol': 'GOOGL', 'company': 'Alphabet'},
               'snapshot': {'title': 'AI的尽头是贷款', 'url': 'https://36kr.com/p/4024322436059265'}}]


def test_only_a_unique_violation_is_reported_as_a_duplicate():
    from sqlalchemy.exc import IntegrityError

    class UniqueViolation(Exception):
        sqlstate = '23505'

    duplicate = consent.failure_outcome(IntegrityError('insert', {}, UniqueViolation()))
    broken = consent.failure_outcome(IntegrityError('insert', {}, Exception('not null')))
    assert duplicate['error_code'] == 'duplicate_source'
    assert broken['error_code'] == 'write_service_failed'


def test_the_generic_boilerplate_code_means_a_text_poor_page():
    assert consent.failure_outcome(ValueError('boilerplate_page'))['error_code'] == 'page_without_text'


def test_a_confirmed_price_outage_keeps_its_specific_code_through_consent(owner):
    from app.market_data import MarketDataError
    operation = {'name': 'initialize_prices', 'arguments': {'symbol': 'AMD', 'days': 366}}
    conversation = 'price-outage-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '初始化历史行情'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    def handler(*_):
        raise MarketDataError('Yahoo Finance request failed for AMD: HTTP Error 429: Too Many Requests')

    outcome = consent.execute(owner, conversation, token, [operation], handler)['data'][0]
    assert outcome['error_code'] == 'market_data_unavailable'
    assert '行情数据源' in outcome['reason']
    assert 'Yahoo' not in outcome['reason'] and '429' not in outcome['reason']


def test_a_confirmed_revision_rejection_keeps_its_specific_code_through_consent(owner):
    operation = {'name': 'revise_forecast',
                 'arguments': {'version_id': '11111111-1111-4111-8111-111111111111', 'source_refs': []}}
    conversation = 'revision-refused-' + uuid.uuid4().hex[:8]
    card = consent.propose(owner, conversation, [operation], {'title': '修正预测'})
    token = card['choices'][0]['value'].split(':', 1)[1]

    def handler(*_):
        raise ValueError('revision_source_symbol_mismatch')

    outcome = consent.execute(owner, conversation, token, [operation], handler)['data'][0]
    assert outcome['error_code'] == 'revision_source_symbol_mismatch'
    assert '不属于这个预测版本的股票' in outcome['reason']
    assert 'write_service_failed' not in str(outcome)