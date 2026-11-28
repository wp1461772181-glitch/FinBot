"""What the first end-to-end run of owner writes (2026-10-19, real model) showed the user."""
import asyncio,json
import pytest
from app.agent_workflow import write_text
from app.agent_workflow.state import AgentRuntimeContext

async def emit(_):pass

QUEUE={'name':'query_research_queue','result':{'ok':True,'data':[{'symbols':['AAPL','MSFT','IBM']}],
       'source':'owner queue','as_of':'2026-10-19T09:28:13.123456+00:00'}}
REVENUE_ROW={'source_id':'f1','symbol':'MSFT','form':'10-K','source_type':'reported_figure','metric':'revenue',
    'title':'MSFT 10-K · 营业收入 FY2026','filed_at':'2026-07-29','excerpt':'营业收入（Revenue）FY2026：331,839,000,000 USD。'}
QUEUE_ADDED={'ok':True,'status':'complete','data':[{'ok':True,'data':[{'symbols':['AAPL','MSFT']}],'source':'owner queue'}]}
ADD_MSFT={'operations':[{'name':'add_to_research_queue','arguments':{'symbol':'MSFT'}}]}

def _turn(question,state=None,**context):
    return direct.Turn(question,AgentRuntimeContext('custom','test','dummy',**context),emit,[],state or {})


def test_execution_facts_name_the_operation_and_symbol_the_card_carried():
    assert write_text.execution_facts(QUEUE_ADDED,ADD_MSFT['operations'])==[{'action':'add_to_research_queue','symbol':'MSFT','ok':True}]

def _resuming(answer,executed):
    def execute(name,args):
        executed.append(name)
        return {'ok':True,'data':[dict(REVENUE_ROW)] if name=='query_financials' else []}
    state={'pending_request':{'original_question':'把 MSFT 加入研究队列，然后告诉我它最近一期营收','display':{'targets':[{'symbol':'MSFT'}]}},
           'previous_category':'D','previous_scope':{'symbol':'MSFT','metrics':['营业收入'],'requested_actions':['add_to_research_queue']}}
    return _turn('confirm:tok',state,decider=lambda *_:{'content':answer},executor=execute)

def _reporting(answer):
    turn=_turn('confirm:tok',{'pending_request':{'id':'req-1','reason':'write_confirmation','original_question':'把第二条保存到资料库',
        'display':{'targets':[{'symbol':'ORCL','title':'Oracle 新闻'}]}},'requested_pending_id':'req-1'})
    async def model(messages,tools,**kwargs):return {'content':answer}
    turn.model=model
    return turn

def _pressing(status,monkeypatch,pending=None):
    from app.agent_workflow import consent
    monkeypatch.setattr(consent,'lookup',lambda *_:{'id':'old','operations':[{'name':'add_to_research_queue','arguments':{'symbol':'INTC'}}],'display':{},'status':status})
    return asyncio.run(_turn('confirm:tok',{'pending_request':pending,'requested_pending_id':'00000000-0000-4000-8000-000000000001'},
                             identity_credential='owner').consent_reply())

