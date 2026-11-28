import asyncio
import pytest
pass  # (removed import of the old turn)
from app.agent_workflow.state import AgentRuntimeContext

def test_shared_first_word_does_not_verify_a_different_issuer(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'BNS','title':'BANK OF NOVA SCOTIA'},{'ticker':'BAC','title':'BANK OF AMERICA CORP'}])
    assert not entities.verified_pair('Bank of America','BNS')
    assert entities.verified_pair('Bank of America Corporation','BAC')

def test_ambiguous_official_issuer_does_not_guess_ticker(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'GOOG','title':'ALPHABET INC'},{'ticker':'GOOGL','title':'ALPHABET INC'}])
    assert entities.resolve_ticker('Alphabet') is None

def test_exact_official_issuer_precedes_other_issuers_sharing_its_prefix(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'AAPL','title':'Apple Inc.'},{'ticker':'APLE','title':'Apple Hospitality REIT Inc.'}])
    assert entities.resolve_ticker('Apple Inc.')=='AAPL'
    assert entities.resolve_ticker('Apple Hospitality')=='APLE'


LLY_QUESTION='这句话的依据是什么：礼来 LLY 财报超预期，盘初涨 4% Q3 营收 244 亿美元，同比 +39%'

