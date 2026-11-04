import asyncio,json
import pytest
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

async def emit(_):pass
def call(name,**args):return {'tool_calls':[{'id':name,'function':{'name':name,'arguments':json.dumps(args)}}]}
# The repair returns a Markdown answer, as the model writes any answer; markers bind the sources.
def repair(text,citations=(1,)):return {'content':text+''.join('['+str(n)+']' for n in citations)}

PRICE_ROWS_WITH_HOLDERS=[
    {'id':'p1','symbol':'AMD','close':100,'trading_date':'2026-10-20'},
    {'id':'p2','symbol':'AMD','close':999,'trading_date':'2026-10-19'},
    {'id':'p3','symbol':'AMD','close':999,'trading_date':'2026-10-18'},
]
CITES_WITH_HOLDERS=[
    {'ordinal':1,'quote':'100','source_type':'saved_price'},
    {'ordinal':2,'quote':'999','source_type':'saved_price'},
    {'ordinal':3,'quote':'999','source_type':'saved_price'},
]

@pytest.mark.parametrize('replacement,reason',[
    (repair('AMD 收盘价为 100 美元'),None),
    (repair('AMD 收盘价为 888 美元'),'unsupported_numeric_claim'),
    (call('initialize_prices',symbol='AMD'),'unsupported_numeric_claim'),
    (repair('AMD 收盘价为 100 美元',(99,)),'invalid_citation'),
    (repair('AMD CEO 已辞职'),'unsupported_claim'),
    ({'content':'unstructured 100 dollars [1]'},None),
    (repair('AMD 收盘价为 100 美元 [99]'),'invalid_citation'),
    (repair('AMD 收盘价为 100 美元',(True,)),'missing_citation'),
    (repair('AMD 收盘价为 100 美元',(-1,)),'missing_citation'),
    (repair('AMD 收盘价为 100 美元',(0,)),'invalid_citation'),
])
def test_numeric_repair_is_single_tool_free_and_still_guarded(replacement,reason):
    # A repair reply that calls a tool is never executed; it gets one more tool-free try (the same
    # reply again here), so that case makes two repair calls instead of one.
    steps=iter([call('query_stock_prices',symbol='AMD'),{'content':'AMD 收盘价为 999 美元 [1]。'},replacement,replacement])
    retried=bool(replacement.get('tool_calls'))
    schemas=[];executed=[]
    def decide(messages,tools):schemas.append(tools);return next(steps)
    def execute(name,args):executed.append(name);return {'ok':True,'data':PRICE_ROWS_WITH_HOLDERS}
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=decide,executor=execute)
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    # The repair may only fix [n] markers: a reply that swaps the figure or the claim is not taken, the
    # drafted line stays (flagged) and nothing the reply invented reaches the answer.
    assert result['status']=='partially_succeeded' and result['reason']=='unsupported_numeric_claim'
    assert schemas[2:]==[[]]*(2 if retried else 1) and len(schemas)==(4 if retried else 3)
    assert result['audit']['answer_repair_count']==(2 if retried else 1)
    assert executed==['query_stock_prices'] and '999 美元' in result['answer'] and result['unverified_lines']
    assert '888' not in result['answer'] and 'CEO' not in result['answer']

def test_numeric_repair_continues_beyond_old_token_budget():
    calls=[]
    ctx=AgentRuntimeContext('custom','test','dummy',decider=lambda *_:calls.append(1) or repair('AMD 收盘价为100美元'))
    turn=direct.Turn('AMD 收盘价',ctx,emit,[],{})
    turn.route='A';turn.citations=list(CITES_WITH_HOLDERS)
    turn.observations=[{'accepted_evidence':True}];turn.audit['token_usage']=1_000_000
    result=asyncio.run(turn.finish_answer('AMD 收盘价为999美元[1]'))
    assert result['status']=='partially_succeeded' and calls==[1]
    assert result['audit']['answer_repair_count']==1 and '999' in result['answer']


def test_structured_repair_binds_each_sentence_and_rejects_a_second_bad_number():
    steps=iter([call('query_stock_prices',symbol='AMD'),{'content':'AMD 收盘价为999美元[1]。'},repair('AMD 收盘价为100美元。AMD 收盘价为888美元')])
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=lambda *_:next(steps),executor=lambda *_:{'ok':True,'data':PRICE_ROWS_WITH_HOLDERS})
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    # The unbound first sentence and the unsupported second one both stay out of the answer.
    assert result['reason'] in {'missing_citation','unsupported_numeric_claim'} and '888' not in result['answer'] and result['audit']['answer_repair_count']==1

def test_repair_never_retries_a_malformed_native_protocol(monkeypatch):
    calls=[]
    async def bad(*args,**kwargs):calls.append(1);return {'usage':{'total_tokens':1}},{'content':'<|tool_calls|>'}
    monkeypatch.setattr(direct,'decision_request',bad)
    turn=direct.Turn('AMD 收盘价',AgentRuntimeContext('custom','test','dummy'),emit,[],{})
    turn.route='A';turn.citations=list(CITES_WITH_HOLDERS)
    turn.observations=[{'name':'query_stock_prices','result':{'ok':True,'data':[{'close':100}]},'accepted_evidence':True}]
    result=asyncio.run(turn.finish_answer('AMD 收盘价为999美元[1]'))
    assert calls==[1] and result['reason']=='unsupported_numeric_claim' and turn.audit['model_calls']==1

def test_time_refinement_preserves_news_metric_scope_and_blocks_price_adapter():
    steps=iter([call('query_stock_prices',symbol='MU'),{'content':'没有可核验资料。'}]);executed=[]
    ctx=AgentRuntimeContext('custom','test','dummy',
        resolver=lambda _:{'relationship':'refinement','canonical_question':'Micron 最近15天新闻'},
        classifier=lambda _:{'category':'A','company':'Micron','symbol':'MU','metrics':[],'days_back':15},
        decider=lambda *_:next(steps),executor=lambda n,a:executed.append(n) or {'ok':True,'data':[]})
    result=asyncio.run(direct.run_direct_turn('我要最近的行情，也就是半个月之内的',ctx,emit=emit,
        messages=[{'role':'user','content':'Micron 最近新闻'}],state={'previous_scope':{'company':'Micron','symbol':'MU','metrics':[]}}))
    assert 'query_stock_prices' not in executed and result['previous_scope']['metrics']==[]
    assert result['audit']['preserved_task_scope'] is True

def test_time_refinement_of_a_price_task_still_allows_price_reads():
    ctx=AgentRuntimeContext('custom','test','dummy')
    turn=direct.Turn('近15天',ctx,emit,[],{});turn.refinement=True;turn.scope={'symbol':'MU','metrics':['price']}
    turn.ground_arguments('query_stock_prices',{'symbol':'MU'})

@pytest.mark.parametrize('question',['改成看过去15天股价','now show Micron stock price over 15 days'])
def test_explicit_task_switch_overrides_inconsistent_refinement(question):
    steps=iter([call('query_stock_prices',symbol='MU'),{'content':'MU 收盘价为100美元[1]。'}]);executed=[]
    ctx=AgentRuntimeContext('custom','test','dummy',
        resolver=lambda _:{'relationship':'refinement','canonical_question':question},
        classifier=lambda _:{'category':'A','mode':'prices','company':'Micron','symbol':'MU','metrics':['price'],'days_back':15,'explicit_task_change':True},
        decider=lambda *_:next(steps),executor=lambda n,a:executed.append(n) or {'ok':True,'data':[] if n=='search_knowledge' else [{'id':'p','symbol':'MU','close':100}]})
    result=asyncio.run(direct.run_direct_turn(question,ctx,emit=emit,messages=[{'role':'user','content':'Micron 最近新闻'}],state={'previous_scope':{'company':'Micron','symbol':'MU','metrics':[]}}))
    assert executed==['query_stock_prices'] and result['status']=='succeeded'
    assert result['audit']['explicit_task_switch'] and result['previous_scope']['metrics']==['price']

@pytest.mark.parametrize('question',['不要股价，只看最近15天新闻','do not show stock prices; only news in the last 15 days','股价这个词不要纳入检索','Do not include the word price in the search'])
def test_negative_or_metalinguistic_metric_mentions_cannot_override_conflicting_scope(question):
    executed=[]
    ctx=AgentRuntimeContext('custom','test','dummy',resolver=lambda _:{'relationship':'refinement','canonical_question':question},
        classifier=lambda _:{'category':'A','company':'Micron','symbol':'MU','metrics':['price'],'days_back':15},executor=lambda n,a:executed.append(n) or {'ok':True,'data':[]},decider=lambda *_:{'content':'没有可核验资料。'})
    result=asyncio.run(direct.run_direct_turn(question,ctx,emit=emit,messages=[{'role':'user','content':'Micron 最近新闻'}],state={'previous_scope':{'metrics':[],'company':'Micron','symbol':'MU'}}))
    assert 'query_stock_prices' not in executed and result['previous_scope']['metrics']==[]

@pytest.mark.parametrize('relationship',['new','followup'])
def test_explicit_task_switch_with_consistent_semantic_stages_reads_prices(relationship):
    steps=iter([call('query_stock_prices',symbol='MU'),{'content':'MU 收盘价为100美元[1]。'}]);executed=[]
    ctx=AgentRuntimeContext('custom','test','dummy',resolver=lambda _:{'relationship':relationship,'canonical_question':'Micron 过去15天股价'},
        classifier=lambda _:{'category':'A','mode':'prices','company':'Micron','symbol':'MU','metrics':['price'],'days_back':15},decider=lambda *_:next(steps),
        executor=lambda n,a:executed.append(n) or {'ok':True,'data':[] if n=='search_knowledge' else [{'id':'p','symbol':'MU','close':100}]})
    result=asyncio.run(direct.run_direct_turn('改成看 Micron 过去15天股价',ctx,emit=emit,messages=[{'role':'user','content':'Micron 最近新闻'}],state={'previous_scope':{'company':'Micron','symbol':'MU','metrics':[]}}))
    assert executed==['query_stock_prices'] and result['status']=='succeeded'


def test_repair_is_told_which_numbers_the_source_check_rejected():
    seen=[]
    steps=iter([call('query_stock_prices',symbol='AMD'),{'content':'AMD 收盘价为999美元[1]。'},repair('AMD 收盘价为100美元')])
    def decide(messages,tools):seen.append(json.dumps(messages,ensure_ascii=False,default=str));return next(steps)
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=decide,executor=lambda *_:{'ok':True,'data':PRICE_ROWS_WITH_HOLDERS})
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    assert result['status']=='partially_succeeded'
    repair_request=[m for m in json.loads(seen[-1]) if m.get('role')=='user'][-1]['content']
    assert '999' in repair_request and 'unsupported_numbers' in repair_request


def test_repair_names_the_source_that_holds_a_rejected_number():
    """Dropping a figure is the last resort; re-sourcing it keeps the answer."""
    seen=[]
    def decide(messages,tools):
        seen.append(json.dumps(messages,ensure_ascii=False,default=str))
        return repair('AMD 收盘价为 100 美元')
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=decide)
    turn=direct.Turn('AMD 营收',ctx,emit,[],{})
    turn.route='A';turn.observations=[{'accepted_evidence':True}]
    # The figure lives in the second source; the draft attached it to the first.
    turn.citations=[{'ordinal':1,'quote':'AMD 已保存收盘价 100','source_type':'saved_price'},
                    {'ordinal':2,'quote':'Total revenue 331,839 million','source_type':'official_filing'},
                    {'ordinal':3,'quote':'Revenue was 331,839 million (restated)','source_type':'official_filing'}]
    asyncio.run(turn.finish_answer('AMD 营收为 331,839 百万美元 [1]。'))
    payload=json.loads([m for m in json.loads(seen[0]) if m.get('role')=='user'][-1]['content'])
    assert payload['unsupported_numbers']==[331839000000.0]
    assert payload['rejected_numbers_appear_in']=={'331839000000.0':['2','3']}


def test_repair_accepts_a_fenced_markdown_answer():
    steps=iter([call('query_stock_prices',symbol='AMD'),{'content':'| 项目 | 数值 |\n|---|---|\n| AMD 收盘价 | 100 美元 |'},
                {'content':'```markdown\n| 项目 | 数值 |\n|---|---|\n| AMD 收盘价 | 100 美元 [1] |\n```'}])
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=lambda *_:next(steps),executor=lambda *_:{'ok':True,'data':[{'id':'p','symbol':'AMD','close':100}]})
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    assert result['status']=='succeeded' and '| AMD 收盘价 | 100 美元 [1] |' in result['answer']
    assert 'answer_repair_error' not in result['audit'] and '```' not in result['answer']

def test_repair_keeps_the_version_with_fewer_unsupported_lines():
    draft='- 收盘价 100 美元\n- 开盘价 998 美元 [1]\n- 最高价 997 美元 [1]\n- 成交量 200 [1]'
    better='- 收盘价 100 美元 [1]\n- 开盘价 998 美元 [1]'
    steps=iter([call('query_stock_prices',symbol='AMD'),{'content':draft},{'content':better},{'content':better}])
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=lambda *_:next(steps),executor=lambda *_:{'ok':True,'data':[{'id':'p','symbol':'AMD','close':100,'volume':200}]})
    result=asyncio.run(direct.run_direct_turn('AMD 行情',ctx,emit=emit))
    # The marker fix is taken; the lines the reply left out are not lost, they stay and are flagged.
    assert result['status']=='partially_succeeded' and '收盘价 100 美元 [1]' in result['answer']
    assert len(result['audit']['answer_issues'])==2 and '998' in result['answer'] and '997' in result['answer']

def test_a_failed_repair_call_is_recorded_with_its_cause():
    def steps():
        yield call('query_stock_prices',symbol='AMD');yield {'content':'AMD 收盘价为 999 美元 [1]。'}
        raise RuntimeError('provider down')
    it=steps()
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=lambda *_:next(it),executor=lambda *_:{'ok':True,'data':PRICE_ROWS_WITH_HOLDERS})
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    assert result['audit']['answer_repair_error']=='repair_unavailable:RuntimeError'

@pytest.mark.parametrize('replacement',['已打开 SEC 页面。','已打开 SEC 页面，事件时间为 2026-10-24 02:40 UTC。'])
def test_a_verified_browser_receipt_is_not_rewritten_by_the_repair(replacement):
    calls=[]
    ctx=AgentRuntimeContext('custom','test','dummy',decider=lambda *_:calls.append(1) or {'content':replacement})
    turn=direct.Turn('打开 SEC 页面。',ctx,emit,[],{})
    turn.route='D'
    turn.accept('open_page',{'page':'sec'},
        {'ok':True,'data':[{'client_action':{'action':'open_page','page':'sec'}}]})
    result=asyncio.run(turn.finish_answer('已打开 SEC 页面，事件时间为 2026-10-24 02:40 UTC。'))
    assert not calls
    # An unconfirmed timestamp is flagged, not deleted by the model.
    assert result['status']=='partially_succeeded' and '02:40' in result['answer'] and result['unverified_lines']


def test_a_failed_browser_action_does_not_supply_trusted_state_for_repair():
    calls=[]
    ctx=AgentRuntimeContext('custom','test','dummy',decider=lambda *_:calls.append(1) or {'content':'已打开 SEC 页面。'})
    turn=direct.Turn('打开 SEC 页面。',ctx,emit,[],{})
    turn.route='D';turn.accept('open_page',{'page':'sec'},{'ok':False,'error_code':'tool_failed'})
    result=asyncio.run(turn.finish_answer('已打开 SEC 页面，事件时间为 2026-10-24 02:40 UTC。'))
    assert not calls and result['status']=='partially_succeeded' and result['unverified_lines']


# ---- Task 7: the check annotates, it never deletes -------------------------------------------------

def _repair_turn(decide,citations,observations=None):
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=decide)
    turn=direct.Turn('电话会说了什么',ctx,emit,[],{})
    turn.route='A';turn.observations=observations or [{'accepted_evidence':True}];turn.citations=citations
    return turn

def _forty_three_sources():
    sources=[{'ordinal':n,'quote':'第 %d 条来源的背景材料，与资本开支无关。'%n*20,'source_type':'web','title':'来源 %d'%n} for n in range(1,44)]
    sources[0]['quote']+=' 历史增幅 45%。'
    sources[1]['quote']+=' 历史增幅 45%。'
    # The call transcript is source 38; the unique tail is past any 22,000-character truncation of the context.
    sources[37]['quote']='管理层在电话会上表示 2027 年资本开支将大幅上升。'+'补充说明。'*400+'TAIL-OF-SOURCE-38'
    return sources

def test_repair_sees_cited_source():
    """The rejected line cites [38]; the rewrite is shown [38]'s full quote, not the last ten sources cut to 22,000 characters."""
    seen=[]
    def decide(messages,tools):
        seen.append(json.dumps(messages,ensure_ascii=False,default=str));return {'content':'电话会说 2027 年资本开支大幅上升 [38]。'}
    turn=_repair_turn(decide,_forty_three_sources())
    asyncio.run(turn.finish_answer('电话会说 2027 年资本开支大幅上升 45% [38]。'))
    assert seen, 'the rejected line should have been sent for repair'
    request=[m for m in json.loads(seen[0]) if m.get('role')=='user'][-1]['content']
    assert 'TAIL-OF-SOURCE-38' in request and '管理层在电话会上表示' in request

def test_repair_keeps_lines():
    """A rewrite that drops a rejected sentence does not remove it: only [n] edits are taken from the rewrite."""
    draft='AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。'
    steps=iter([{'content':'AMD 收盘价为 100 美元 [1]。'}]*3)
    turn=_repair_turn(lambda *_:next(steps),[{'ordinal':1,'quote':'AMD 已保存收盘价 100','source_type':'saved_price'}])
    result=asyncio.run(turn.finish_answer(draft))
    assert '成交量为 999 万股' in result['answer'] and '收盘价为 100 美元' in result['answer']
    assert result['status']=='partially_succeeded'

def test_repair_remaps_a_citation_slip_without_the_model():
    draft='AMD 营收为 331,839 百万美元 [1]。'
    calls=[]
    turn=_repair_turn(lambda *_:calls.append(1) or {'content':draft},
        [{'ordinal':1,'quote':'AMD 已保存收盘价 100','source_type':'saved_price'},
         {'ordinal':2,'quote':'Total revenue 331,839 million','source_type':'official_filing'}])
    result=asyncio.run(turn.finish_answer(draft))
    assert not calls and result['status']=='succeeded' and '[2]' in result['answer'] and '[1]' not in result['answer']
    assert result['audit']['citation_remaps']

def test_unverified_lines_reported():
    draft='AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。'
    turn=_repair_turn(lambda *_:{'content':draft},[{'ordinal':1,'quote':'AMD 已保存收盘价 100','source_type':'saved_price'}])
    result=asyncio.run(turn.finish_answer(draft))
    lines=result['unverified_lines']
    assert len(lines)==1 and lines[0]['line'].startswith('AMD 成交量为 999 万股')
    assert lines[0]['reason']=='unsupported_numeric_claim' and '999' in ' '.join(lines[0]['numbers'])
    assert result['audit']['unverified_lines']==lines
