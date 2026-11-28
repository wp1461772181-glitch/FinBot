import asyncio,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime,timedelta
import pytest
from sqlalchemy import select
from app.database import Base,engine,SessionLocal
from app.agent_workflow import consent, tools, web_sources
from app.agent_workflow.models import AgentConsent,AgentWebSource
from app.agent_workflow.state import AgentRuntimeContext

@pytest.fixture
def owner(monkeypatch,disposable_database):
    Base.metadata.create_all(engine)
    for m in (consent,tools):monkeypatch.setattr(m,'owner_credential_matches',lambda c:c=='v4-owner')
    from app.agent_chat_store import owner_hash
    return AgentRuntimeContext('custom','test','dummy',owner_hash=owner_hash('v4-owner'),identity_credential='v4-owner',conversation_id=str(uuid.uuid4()))

async def emit(_):pass

def request(owner,name='initialize_prices',args=None):
    turn=Turn('看看AMD',owner,emit,[],{})
    turn.route='D';turn.scope={'symbol':'AMD'}
    if args and args.get('url'):turn.sets=[{'id':'seen-web','owner':owner.owner_hash,'conversation':owner.conversation_id,'scope':{'symbol':'AMD'},'tool':'web_research','rows':[{'url':args['url'],'title':'AMD update'}]}]
    outcome=asyncio.run(turn.request_action({'tool':name,'arguments':args or {'symbol':'AMD'},'reason':'可补齐缺少的历史数据'}))
    return turn,outcome

def confirm(owner,card,word=None):
    return asyncio.run(run_direct_turn(word or card['choices'][0]['value'],owner,emit=emit,state={'pending_request':card,'requested_pending_id':card['id']}))

def test_caller_cannot_assert_confirmation_without_capability(owner):
    effects=[]
    from dataclasses import replace
    context=replace(owner,executor=lambda *a:effects.append(a) or {'ok':True})
    try:result=asyncio.run(tools.invoke('add_to_research_queue',{'symbol':'AMD'},context,confirmed=True))
    except TypeError:result={'ok':False}
    assert not result['ok'] and not effects

