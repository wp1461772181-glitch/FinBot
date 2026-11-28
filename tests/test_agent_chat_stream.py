"""SSE and persistence acceptance against the production direct graph (controlled external I/O)."""
import asyncio,json
from contextlib import asynccontextmanager
from uuid import uuid4
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from starlette.requests import Request
from app.agent_chat_stream import StreamRequest
from app.agent_workflow.tools import invoke as REAL_TOOLS_INVOKE

@pytest.fixture
def stream_fixture(monkeypatch):
    import app.agent_chat_stream as stream
    import app.agent_chat_provider as provider
    from app.agent_workflow import tools
    import app.agent_workflow.checkpoints as checkpoints
    saver=InMemorySaver()
    @asynccontextmanager
    async def temporary_saver(_url):yield saver
    monkeypatch.setattr(checkpoints,'open_postgres_checkpointer',temporary_saver)
    stored=[]
    async def append(*args,**kwargs):stored.append((args,kwargs))
    async def empty(*args,**kwargs):return {'l1_rows':[]}
    async def yes(*args):return True
    async def create(*args):return str(uuid4())
    async def finish(*args):stored.append(((),{'finished':args[1]}))
    for name,value in [('verify_conversation',yes),('create_conversation',create),('append_message',append),('conversation_context',empty),('finish_conversation',finish)]:monkeypatch.setattr(stream,name,value)
    monkeypatch.setattr(stream,'_restore_citations',lambda items,*_:items)
    monkeypatch.setattr(stream,'_record_low_confidence',lambda *args:None)
    classification={'category':'A','symbol':'AAPL'};tool_results={};executed=[];requests=[];decisions=[]
    async def execute(name,args,context,**kwargs):
        executed.append((name,args))
        return tool_results.get(name,{'ok':True,'data':[] if name=='search_knowledge' else [{'id':str(uuid4()),'symbol':args.get('symbol'),'close':250,'trading_date':'2026-10-14','fetched_at':'2026-10-15T00:00:00Z'}],'source':'fixture'})
    monkeypatch.setattr(tools,'invoke',execute)
    async def decide(_provider,_model,_key,messages,schemas,base_url=None,**_ledger):
        requests.append((messages,schemas,base_url));names={s['function']['name'] for s in schemas}
        if 'resolve_reference' in names:
            payload=json.loads(messages[-1]['content']);return {},{'content':json.dumps({'relationship':'new','canonical_question':payload['question']})}
        if 'classify_request' in names:
            # Legacy fixture callers can still set intent; the test fixture translates it.
            category={'general':'B','unsupported_action':'C','system_action':'D','compound_research':'D'}.get(classification.get('intent'),classification.get('category','A'))
            value={'days_back':None,'category':category,'mode':classification.get('mode','rag' if category=='A' else 'none'),'symbol':classification.get('symbol')}
            return {},{'content':json.dumps(value)}
        if not schemas:return {},{'content':'First increment'}
        if decisions:return {'usage':{'total_tokens':5}},decisions.pop(0)
        if any(m.get('role')=='tool' for m in messages):return {},{'content':'First increment [1]'}
        return {},{'content':None,'tool_calls':[{'id':uuid4().hex,'function':{'name':'query_stock_prices','arguments':'{"symbol":"AAPL"}'}}]}
    monkeypatch.setattr(provider,'decision_request',decide)
    # The kernel's model call: a test that sends a turn sets its own (``tests.test_kernel_wiring.Wiring.model``); none reaches the network.
    async def no_model(*args,**kwargs):raise AssertionError('stream_fixture: set provider.stream_decision for a turn that calls the model')
    monkeypatch.setattr(provider,'stream_decision',no_model)
    async def send(message='show AAPL prices',cid=None,pending=None,label=None):
        payload=StreamRequest(provider='deepseek',model='deepseek-chat',api_key='abcdefgh',message=message,conversation_id=cid,pending_request_id=pending,display_message=label)
        request=Request({'type':'http','method':'POST','path':'/agent-chat/stream','headers':[]})
        response=await stream.stream_chat(payload,request,'x'*40)
        return ''.join([part async for part in response.body_iterator])
    return send,classification,tool_results,executed,stored,requests,decisions


def frames(wire):return [(block.splitlines()[0][7:],json.loads(block.splitlines()[1][6:])) for block in wire.strip().split('\n\n') if block.strip()]

def test_bad_tool_body_is_not_in_persisted_tool_or_answer_context(stream_fixture):
    send,_,results,_,stored,requests,_=stream_fixture
    results['query_stock_prices']={'ok':False,'data':[{'body':'REJECTED_PRIVATE_BODY'}],'error_code':'tool_failed'}
    asyncio.run(send())
    assert 'REJECTED_PRIVATE_BODY' not in json.dumps([stored,requests])


def test_legacy_watchlist_is_ignored():
    value=StreamRequest(provider='deepseek',model='test',api_key='abcdefgh',message='news',watchlist=['invalid/old'])
    assert 'watchlist' not in value.model_dump()


def test_bounded_tool_output_stays_valid_json():
    from app.agent_chat_stream import bounded_tool_result
    from app.agent_chat_stream import TOOL_RESULT_BYTES
    value=bounded_tool_result({'ok':True,'data':[{'excerpt':'中'*20000} for _ in range(30)]})
    assert isinstance(json.loads(json.dumps(value)),dict)
    assert 8000<len(json.dumps(value,ensure_ascii=False).encode())<=TOOL_RESULT_BYTES+4000


def test_exception_after_terminal_citation_keeps_raw_manifest_not_restore_placeholder(stream_fixture,monkeypatch):
    import app.agent_chat_stream as stream
    send,_,_,_,stored,_,_=stream_fixture
    original=[{'ordinal':4,'title':'Fixture','source_type':'official_filing','quote':'frozen quote','source_hash':'a'*64}]
    async def workflow(**_kwargs):
        yield {'event':'done','status':'succeeded','citations':original,'audit':{},'final_protocol':{}}
    monkeypatch.setattr(stream,'stream_workflow',workflow)
    monkeypatch.setattr(stream,'_restore_citations',lambda *_:[{'ordinal':4,'title':'Fixture','source_type':'unavailable','quote':''}])
    real_append=stream.append_message
    async def fail_first_success(_cid,_turn,role,content,**kwargs):
        if role=='assistant' and kwargs.get('status','complete')=='complete': raise RuntimeError('fixture_append_failure')
        await real_append(_cid,_turn,role,content,**kwargs)
    monkeypatch.setattr(stream,'append_message',fail_first_success)
    async def no_mark(*_): pass
    monkeypatch.setattr(stream,'mark_terminal_status',no_mark)
    events=frames(asyncio.run(send('verify saved citation')))
    assert any(event=='error' for event,_ in events)
    saved=next(kwargs['tool_calls']['citations'] for _,kwargs in stored
        if kwargs.get('status')=='failed' and kwargs.get('tool_calls',{}).get('citations'))
    assert saved==original and saved[0]['source_type']=='official_filing'


def test_the_realtime_stream_never_sends_an_unverified_frame_or_stores_one(stream_fixture, monkeypatch):
    """WP0 step 8 regression guard: even when the workflow hands over unverified lines, the stream sends no
    unverified_lines frame and stores none on the turn."""
    import app.agent_chat_stream as stream
    send,_,_,_,stored,_,_=stream_fixture
    async def workflow(**_kwargs):
        yield {"event":"delta","text":"AMD 收盘价为 100 美元 [1]。"}
        yield {"event":"done","status":"succeeded","reason":None,"final_protocol":{},"audit":{},"citations":[],
               "route":"A","trace":[],"unverified_lines":[{"line":"AMD 成交量为 999 万股 [1]。",
                                                          "reason":"unsupported_numeric_claim","numbers":["999 万"]}]}
    monkeypatch.setattr(stream,"stream_workflow",workflow)
    wire=asyncio.run(send())
    assert 'event: unverified_lines' not in wire and 'event: done' in wire
    assert not any(isinstance(kwargs.get('tool_calls'),dict) and 'unverified_lines' in kwargs['tool_calls'] for _,kwargs in stored)
