"""Behavior at the native-model boundary, not claims about model accuracy."""
import asyncio,json
import pytest
from app.agent_workflow.state import AgentRuntimeContext

LIST='1. 远期（Forward）\n2. 期货（Futures）\n3. 期权（Option）\n4. 互换（Swap）'
HISTORY=[{'role':'user','content':'金融衍生品包括哪些？简单列举几个说明一下'}, {'role':'assistant','content':LIST}]

def run(question,*,category='B',resolver=None,answers=(),messages=None,scope=None):
    answers=iter(answers);requests=[]
    async def answerer(payload):
        requests.append(payload)
        value=next(answers,'')
        if isinstance(value,Exception):raise value
        return value
    async def execute(*_):raise AssertionError('Concept answer must not execute business tools')
    context=AgentRuntimeContext('custom','test','dummy',resolver=resolver,
        intent_recognizer=lambda _:{'category':category,'days_back':None,**(scope or {})},answerer=answerer,executor=execute)
    async def emit(_):pass
    result=asyncio.run(run_direct_turn(question,context,emit=emit,messages=messages))
    return result,requests

def test_historical_mention_is_descriptive_but_source_text_still_must_be_exact():
    from app.agent_workflow.references import Referent,validate_referents
    refs=[Referent(mention='美光的新闻',text='帮我搜两条美光的新闻',source='user_history')]
    result=validate_referents(refs,'它的最新新闻呢',[{'role':'user','content':'帮我搜两条美光的新闻'}],[])
    assert result[0]['text']=='帮我搜两条美光的新闻'

