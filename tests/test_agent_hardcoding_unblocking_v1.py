import asyncio
import pytest
from app.agent_workflow.state import AgentRuntimeContext
from app.agent_workflow import consent
from app.database import Base, engine
from app.agent_workflow.models import AgentConsent
from app import agent_context

@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConsent.__table__])
    monkeypatch.setattr(consent, 'owner_credential_matches', lambda c: c == 'owner')
    return 'owner'

def test_traditional_chinese_is_not_forced_to_simplified():
    from app.agent_workflow.language import format_answer
    text = "這是一份關於台積電的繁體中文分析報告。"
    res = format_answer(text, "請用繁體中文回答", [])
    assert res == text, "Should respect user's explicit request for Traditional Chinese"

def test_authorization_negation_allows_affirmative_request_in_same_sentence():
    from app.agent_workflow.authorization import vetoed
    assert not vetoed('analyze', '不要分析旧报告，分析新报告')
    assert not vetoed('ingest_web_source', '不要解释怎么保存，直接保存')

def test_is_challenge_page_does_not_discard_long_articles():
    from app.agent_web_research import is_challenge_page
    article = "A comprehensive analysis on cybersecurity. The website uses captcha mechanisms to prevent robot check. " * 30
    assert not is_challenge_page(article)


def test_assistant_keep_chars_configured():
    """L2 dialogue history compression budget for assistant must be configured."""
    assert agent_context.ASSISTANT_KEEP_CHARS > 0

def test_conversational_explanations_without_citations_are_not_pruned():
    from app.agent_workflow.evidence import reviewed_passages
    answer = "确认后才会写入资料库；如只想保留其中一两条，可在卡片上只确认对应项。"
    accepted, issues = reviewed_passages(answer, [], require_citations=True)
    assert answer.rstrip('。') in accepted, "Conversational instructions should not be pruned as missing_citation"
    assert "missing_citation" not in issues

def test_unsupported_numbers_does_not_flag_durations_or_item_counts():
    from app.agent_workflow.evidence import unsupported_numbers
    passage = "我们在最近15天内分析了前3项公开声明[1]。"
    citations = [{'ordinal': 1, 'quote': 'Apple published its statements recently.', 'source_type': 'web'}]
    assert not unsupported_numbers(passage, citations), "Durations (15天) and counts (前3项) must not trigger unsupported_numeric_claim"

def test_event_features_recognize_natural_market_synonyms():
    from app.agent_workflow.evidence import unsupported_claims
    passage = "公司完成了对该初创企业的全资收购[1]。"
    citations = [{'ordinal': 1, 'quote': 'The company finalized the deal and takeover.', 'source_type': 'web'}]
    assert not unsupported_claims(passage, citations), "deal/takeover must support 收购"

def test_reference_binding_tolerates_token_level_paraphrase():
    from app.agent_workflow.references import validate_referents, Referent
    messages = [{'role': 'assistant', 'content': '1. TSMC quarterly revenue grew strongly'}]
    ref = Referent(mention='TSMC quarterly revenue', text='TSMC quarterly revenue grew', source='assistant_previous')
    verified = validate_referents([ref], '解读第一项', messages, [])
    assert len(verified) == 1
    assert 'TSMC' in verified[0]['text']
