"""词表清理 (c): for an attended owner a granted write the user's words seem to negate still gets a card, with a
reminder quoting the negation; the model-suggestion path, guests and unattended runs keep the hard veto."""
import asyncio,json
import pytest
from app.agent_workflow import direct,consent
from app.agent_workflow.authorization import vetoed,vetoed_phrase
from app.agent_workflow.state import AgentRuntimeContext

def call(name,args):return {'tool_calls':[{'id':name,'function':{'name':name,'arguments':json.dumps(args)}}]}

def run(monkeypatch,question,*,steps=(),owner=True,actions=('add_to_research_queue',)):
    monkeypatch.setattr(direct,'owner_credential_matches',lambda _:owner)
    monkeypatch.setattr(consent,'owner_credential_matches',lambda _:owner)
    from app.database import Base,engine
    Base.metadata.create_all(engine)
    steps=iter(steps);writes=[]
    async def decide(messages,schemas):return next(steps,{'content':'好的。'})
    async def execute(name,args):
        if name=='add_to_research_queue':writes.append(name)
        return {'ok':True,'data':[]}
    ctx=AgentRuntimeContext('custom','test','dummy',identity_credential='test',conversation_id='c-veto',
        classifier=lambda _:{'category':'D','requested_actions':list(actions)},decider=decide,executor=execute)
    async def emit(_):pass
    return asyncio.run(direct.run_direct_turn(question,ctx,emit=emit)),writes

@pytest.mark.parametrize('question,quote',[('别忘了加入 AMD','别忘了加入 AMD'),("don't forget to add AMD to the queue","don't forget to add AMD to the queue")])
def test_a_granted_write_with_a_dont_forget_phrasing_makes_a_card_with_a_reminder(monkeypatch,question,quote):
    assert vetoed('add_to_research_queue',question) and vetoed_phrase('add_to_research_queue',question)==quote
    result,writes=run(monkeypatch,question,steps=[call('add_to_research_queue',{'symbol':'AMD'})])
    assert not writes
    assert result['audit']['write_outcome']=='proposed'
    pending=result['pending_request']
    assert pending and pending['reason']=='write_confirmation'
    assert quote in pending['display']['alternative'] and pending['display']['alternative'].startswith('提醒：')

def test_a_model_suggestion_the_user_negated_stays_refused(monkeypatch):
    monkeypatch.setattr(direct,'owner_credential_matches',lambda _:True)
    monkeypatch.setattr(consent,'owner_credential_matches',lambda _:True)
    from app.database import Base,engine
    Base.metadata.create_all(engine)
    async def emit(_):pass
    turn=direct.Turn('不要加入 AMD',AgentRuntimeContext('custom','test','dummy',identity_credential='test',conversation_id='c-veto2'),emit,[],{})
    result=asyncio.run(turn.request_action({'tool':'add_to_research_queue','arguments':{'symbol':'AMD'},'reason':'想加入'}))
    assert not result['ok'] and turn.audit['write_outcome']=='refused:write_negated' and turn.pending is None

def test_a_guest_whose_words_negate_the_write_is_still_refused(monkeypatch):
    result,writes=run(monkeypatch,'别加入 AMD',owner=False,steps=[call('add_to_research_queue',{'symbol':'AMD'})])
    assert not writes and result['pending_request'] is None
    assert result['audit']['write_outcome']=='refused:write_negated'

def test_an_unattended_run_is_not_downgraded():
    turn=direct.Turn('别忘了加入 AMD',AgentRuntimeContext('custom','test','dummy',identity_credential='test',unattended=True),lambda _:None,[],{})
    turn.owner=True;turn.granted_actions={'add_to_research_queue'}
    assert not turn.veto_downgraded('add_to_research_queue')

def test_remember_keeps_its_narrow_hard_refusal():
    turn=direct.Turn('不要记住这个',AgentRuntimeContext('custom','test','dummy',identity_credential='test'),lambda _:None,[],{})
    turn.owner=True;turn.granted_actions={'remember'}
    assert not turn.veto_downgraded('remember')
