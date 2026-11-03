import asyncio
import pytest
from app.agent_workflow.direct import run_direct_turn
from app.agent_workflow.state import AgentRuntimeContext

@pytest.mark.parametrize('company,symbol,mention,accepted',[
 ('Intel','INTC','Intel',True),('Intel','MSFT','Intel',False),
 ('Micron','MU','美光',True),('Palantir','PLTR','凭空公司',False),
])
def test_verified_ticker_pair_and_literal_mention_bind_scope(monkeypatch,company,symbol,mention,accepted):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'INTC','title':'INTEL CORP'},{'ticker':'MU','title':'MICRON TECHNOLOGY INC'}])
    async def execute(*_):return {'ok':True,'data':[]}
    context=AgentRuntimeContext('custom','test','dummy',intent_recognizer=lambda _:{'category':'A','days_back':None,'symbol':symbol,'company':company,'company_mention':mention},executor=execute,decider=lambda *_:{'content':'没有可核验资料。'})
    async def emit(_):pass
    result=asyncio.run(run_direct_turn('查Intel和美光的营收',context,emit=emit))
    assert bool(result['pending_request'])!=accepted

def test_shared_first_word_does_not_verify_a_different_issuer(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'BNS','title':'BANK OF NOVA SCOTIA'},{'ticker':'BAC','title':'BANK OF AMERICA CORP'}])
    assert not entities.verified_pair('Bank of America','BNS')
    assert entities.verified_pair('Bank of America Corporation','BAC')

@pytest.mark.parametrize('company,symbol,mention,question,expected',[
 ('Advanced Micro Devices, Inc.','AMD','AMD','抓取AMD的SEC原文','AMD'),
 ('Micron Technology',None,'美光','查美光最近的新闻','MU'),
])
def test_literal_ticker_or_unique_official_issuer_does_not_force_company_card(monkeypatch,company,symbol,mention,question,expected):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:[{'ticker':'AMD','title':'ADVANCED MICRO DEVICES INC'},{'ticker':'MU','title':'MICRON TECHNOLOGY INC'}])
    async def execute(*_):return {'ok':True,'data':[]}
    context=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:{'category':'A','company':company,'symbol':symbol,'company_mention':mention},executor=execute,decider=lambda *_:{'content':'没有可核验资料。'})
    async def emit(_):pass
    result=asyncio.run(run_direct_turn(question,context,emit=emit))
    assert not result['pending_request'] and result['previous_scope']['symbol']==expected

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

def _run_gate(monkeypatch,scope,question,records):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities,'ticker_records',lambda:records)
    async def execute(*_):return {'ok':True,'data':[]}
    context=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:{'category':'A',**scope},executor=execute,decider=lambda *_:{'content':'没有可核验资料。'})
    async def emit(_):pass
    return asyncio.run(run_direct_turn(question,context,emit=emit))

def test_chinese_named_issuer_in_the_question_does_not_hit_the_card(monkeypatch):
    # '礼来' appears verbatim in the trusted question text, so the pair is
    # contained and passes without a card; the scope keeps the user's wording.
    result=_run_gate(monkeypatch,{'company':'礼来','symbol':'LLY','company_mention':'礼来'},LLY_QUESTION,
        [{'ticker':'LLY','title':'ELI LILLY & Co'},{'ticker':'MU','title':'MICRON TECHNOLOGY INC'}])
    assert not result['pending_request']
    assert result['previous_scope']['symbol']=='LLY'

def test_symbol_anchored_grounding_passes_a_chinese_named_issuer(monkeypatch):
    # '礼来制药公司' is not verbatim in the question, so containment fails and
    # the symbol-anchored path must ground the pair in the SEC-listed ticker
    # and canonicalise the stored company to the SEC title.
    result=_run_gate(monkeypatch,{'company':'礼来制药公司','symbol':'LLY','company_mention':'礼来'},LLY_QUESTION,
        [{'ticker':'LLY','title':'ELI LILLY & Co'},{'ticker':'MU','title':'MICRON TECHNOLOGY INC'}])
    assert not result['pending_request']
    assert result['previous_scope']['symbol']=='LLY' and result['previous_scope']['company']=='ELI LILLY & Co'

def test_symbol_anchored_grounding_still_rejects_a_symbol_sec_does_not_list(monkeypatch):
    result=_run_gate(monkeypatch,{'company':'礼来制药公司','symbol':'ZZZQ','company_mention':'礼来'},'礼来 ZZZQ 的营收是多少',[{'ticker':'LLY','title':'ELI LILLY & Co'}])
    assert result['pending_request']

def test_chinese_name_without_any_ticker_in_the_text_still_clarifies(monkeypatch):
    result=_run_gate(monkeypatch,{'company':'礼来制药公司','symbol':'LLY','company_mention':'礼来'},'礼来的营收是多少',[{'ticker':'LLY','title':'ELI LILLY & Co'}])
    assert result['pending_request']
