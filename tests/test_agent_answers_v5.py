import asyncio
import pytest
from app.agent_workflow.state import AgentRuntimeContext

def turn():
    t=Turn('AMD 股价',AgentRuntimeContext('custom','test','dummy'),None,[],{})
    t.route='A'
    t.citations=[{'ordinal':1,'quote':'100','source_type':'saved_price','symbol':'AMD'}, {'ordinal':2,'quote':'80','source_type':'saved_price','symbol':'AMD'}]
    return t

def test_a_chinese_search_always_considers_model_written_variants(monkeypatch):
    """An English filing answers a Chinese metric under English wording only."""
    import asyncio
    from app import agent_tools
    calls = []

    async def fake_retrieve(symbol, keyword, limit, source_id=None):
        calls.append(keyword)
        return {'ok': True, 'data': [] if keyword != 'cloud revenue' else [{'id': 'c1'}], 'as_of': None}

    async def fake_variants(keyword):
        return [keyword, 'cloud revenue']

    monkeypatch.setattr('app.knowledge.query_understanding.query_variants', fake_variants)
    result = asyncio.run(agent_tools._expanded_retrieval(fake_retrieve, 'MSFT', '云业务收入', 3, None))
    assert 'cloud revenue' in calls and len(result['data']) == 1
