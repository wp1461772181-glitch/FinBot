"""Unit conversion is arithmetic on a cited value, not a new figure."""
import asyncio,json
import pytest
from fastapi import HTTPException
from app.agent_workflow.calculation import calculate
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

SOURCE=[{'ordinal':1,'source_type':'calculation','quote':'{"value": "50115000000.00"}'}]

def test_a_value_may_be_converted_to_billions_with_a_power_of_ten():
    result=calculate({'expression':'a/1000000000','inputs':[{'name':'a','value':'50115000000','source_ordinal':1}]},SOURCE)
    assert result['value']=='50.12'

def test_an_arbitrary_constant_is_still_refused():
    # F2 (checker-numbers brief): a literal up to 1000 with up to 4 decimals is allowed now (a*7 was refused);
    # anything larger or finer is still refused.
    for expression in ('a*1001','a*0.00001','a*7777'):
        with pytest.raises(ValueError):
            calculate({'expression':expression,'inputs':[{'name':'a','value':'50115000000','source_ordinal':1}]},SOURCE)

def test_a_provider_failure_mid_loop_answers_from_the_evidence_gathered():
    steps=iter([{'tool_calls':[{'id':'1','function':{'name':'query_stock_prices','arguments':json.dumps({'symbol':'AMD'})}}]}])
    def decide(messages,tools):
        try:return next(steps)
        except StopIteration:raise HTTPException(502,'provider_protocol_too_large')
    async def emit(_):pass
    ctx=AgentRuntimeContext('custom','test','dummy',classifier=lambda _:'D',decider=decide,answerer=lambda messages:'AMD 已保存收盘价 100 美元 [1]。',
        executor=lambda *_:{'ok':True,'data':[{'id':'p','symbol':'AMD','close':100}]})
    result=asyncio.run(direct.run_direct_turn('AMD 收盘价',ctx,emit=emit))
    assert result['status']=='succeeded' and result['answer'].startswith('AMD 已保存收盘价 100 美元 [1]')

def test_a_value_written_per_million_binds_and_its_result_may_be_restated_in_yi():
    from app.agent_workflow.evidence import unsupported_number_values
    figures=[{'ordinal':1,'source_type':'reported_figure','quote':'营业收入 FY2026：331,839,000,000 USD，约 3,318.39 亿美元，即 331,839 百万美元。'},
             {'ordinal':2,'source_type':'reported_figure','quote':'营业收入 FY2025：281,724,000,000 USD，约 2,817.24 亿美元，即 281,724 百万美元。'}]
    result=calculate({'expression':'a-b','inputs':[{'name':'a','value':'331839','source_ordinal':1},{'name':'b','value':'281724','source_ordinal':2}],'decimals':0},figures)
    assert result['value']=='50115'
    cited=figures+[{'ordinal':3,'source_type':'calculation','quote':json.dumps(result,ensure_ascii=False)}]
    assert unsupported_number_values('差额为 50,115 百万美元 [3]',cited)==[]
    assert unsupported_number_values('差额约 501.15 亿美元 [3]',cited)==[]
    assert unsupported_number_values('差额约 600 亿美元 [3]',cited)==[6e10]


# --- Yahoo's single-precision prices: 92.07 is stored as 92.06999969482422 -----------------------------------

PRICE=92.06999969482422

def _price_row(**extra):
    return {'id':'11111111-1111-4111-8111-111111111111','symbol':'INTC','trading_date':'2026-10-29','close':PRICE,'open':91.5,
            'source':'yahoo','fetched_at':'2026-10-30T01:00:00+00:00',**extra}

def test_rounded_price_binds():
    source=[{'ordinal':1,'source_type':'saved_price','quote':str(PRICE)}]
    def run(value):
        return calculate({'expression':'a','inputs':[{'name':'a','value':value,'source_ordinal':1}]},source)
    assert run('92.07')['value']=='92.07'
    for wrong in ('92.1','92.08'):
        with pytest.raises(ValueError,match='calculation_input_unbound'):run(wrong)

def test_price_quote_is_rounded():
    from app.agent_workflow.evidence import number_rows
    citations=[]
    number_rows('query_stock_prices',[_price_row()],citations,{'symbol':'INTC'})
    assert citations[0]['quote']=='92.07' and '92.0699' not in citations[0]['figures']
    assert '92.0699' not in str(citations[0]['fields'])
    # The saved price is still exactly what the restore check reads from the table.
    assert str(PRICE)!=citations[0]['quote']
    sets=[]
    number_rows('query_stock_prices',[{'source_type':'saved_price_set','set_id':'ps_1','symbol':'INTC','n':2,'row_ids':[],'parent_digest':'d',
                                       'start_date':'2026-10-29','end_date':'2026-10-30','first_close':PRICE,'last_close':65.76000213623047}],sets,{})
    assert sets[0]['figures']=='2026-10-29 close 92.07 2026-10-30 close 65.76'

def test_rounded_price_not_flagged():
    from app.agent_workflow.evidence import number_rows,unsupported_number_values
    citations=[]
    number_rows('query_stock_prices',[_price_row()],citations,{'symbol':'INTC'})
    assert unsupported_number_values('INTC 10-29 收盘 92.07 [1]',citations)==[]
    assert unsupported_number_values('INTC 10-29 收盘 92.5 [1]',citations)==[92.5]

def test_exact_figures_unchanged():
    from decimal import Decimal
    from app.agent_workflow.calculation import format_price,matches_source
    source=[{'ordinal':1,'source_type':'reported_figure','quote':'Revenue per share was 165.13 dollars.'}]
    assert calculate({'expression':'a','inputs':[{'name':'a','value':'165.13','source_ordinal':1}]},source)['value']=='165.13'
    for wrong in ('165.1','165.14','165'):
        with pytest.raises(ValueError,match='calculation_input_unbound'):
            calculate({'expression':'a','inputs':[{'name':'a','value':wrong,'source_ordinal':1}]},source)
    assert format_price(PRICE)=='92.07' and format_price(100.0)=='100' and format_price(65.76000213623047)=='65.76'
    assert matches_source(Decimal('92.07'),{Decimal(str(PRICE))}) and not matches_source(Decimal('92.1'),{Decimal(str(PRICE))})
