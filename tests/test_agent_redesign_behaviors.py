"""Executable C1–C14 orchestration and service contracts. Model decisions are injected;
these tests do not claim to measure real-model classification accuracy or latency.
"""
import asyncio,copy,json,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
import pytest
from sqlalchemy import select
from app.agent_chat_store import owner_hash
from app.database import Base,engine,SessionLocal
from app.agent_chat_models import AgentResearchQueue
from app.agent_workflow.models import AgentConsent,AgentWebSource
from app.knowledge.models import KnowledgeDocument
pass  # (removed import of the old turn)
from app.agent_workflow.state import AgentRuntimeContext
from app.agent_workflow import consent, tools
from app.agent_tool_catalog import definitions,schemas

NOW=datetime.now(UTC)
@pytest.fixture(autouse=True)
def official_entity_metadata(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'AAPL','title':'APPLE INC'},{'ticker':'MU','title':'MICRON TECHNOLOGY INC'},{'ticker':'MSFT','title':'MICROSOFT CORP'}])
def page(company='Micron',days=1,n=1):return {'url':f'https://example.org/{company}/{n}','title':company+' news','excerpt':company+' released a new product.','published_at':(NOW-timedelta(days=days)).isoformat(),'fetched_at':NOW.isoformat(),'body_provenance':'public_page_fetch'}
def call(name,**args):return {'tool_calls':[{'id':uuid.uuid4().hex,'function':{'name':name,'arguments':json.dumps(args)}}]}

@pytest.fixture
def owned(monkeypatch,disposable_database):
    from app.knowledge.models import KnowledgeUploadOwner
    from app.models import UploadedEvidence
    Base.metadata.create_all(engine,tables=[AgentConsent.__table__,AgentWebSource.__table__,KnowledgeDocument.__table__,AgentResearchQueue.__table__,UploadedEvidence.__table__,KnowledgeUploadOwner.__table__])
    for module in (consent,tools):monkeypatch.setattr(module,'owner_credential_matches',lambda c:c=='owner')
    return 'owner'

async def turn(question,*,route='A',scope=None,steps=(),answers=None,owner=False,state=None,resolver=None,messages=None,pending=None,grants=()):
    calls=[];events=[];steps=iter(steps);values=copy.deepcopy(answers or {})
    async def execute(name,args):
        calls.append((name,args))
        value=values.get(name,{'ok':True,'data':[]})
        if callable(value):value=value(args)
        if isinstance(value,Exception):raise value
        return copy.deepcopy(value)
    async def decide(*_):return next(steps,{'content':'已完成，来源见 [1]。' if any(n=='web_research' for n,_ in calls) else '没有可核验资料。'})
    context=AgentRuntimeContext('custom','test','dummy',owner_hash=owner_hash('owner' if owner else 'guest'),conversation_id='c',identity_credential='owner' if owner else 'guest',
        classifier=lambda q:{'category':route,'mode':'rag' if route=='A' else 'none','requested_actions':list(grants),**{k:v for k,v in (scope or {}).items() if k!='answer'}},decider=decide,executor=execute,answerer=lambda *_:(scope or {}).get('answer') or '已完成：已返回证据；未完成：剩余请求。',resolver=resolver)
    async def emit(e):events.append(e)
    result=await run_direct_turn(question,context,emit=emit,state={**(state or {}),'requested_pending_id':pending},messages=messages)
    return result,calls,events,context

def run(*args,**kwargs):return asyncio.run(turn(*args,**kwargs))

def test_guest_tool_catalog_excludes_every_costly_tool():
    exposed={s['function']['name'] for s in schemas(owner=False)}
    assert all(p.name not in exposed for p in definitions().values() if p.level=='costly')
    assert all(p.args_schema and p.description and p.errors for p in definitions().values())

