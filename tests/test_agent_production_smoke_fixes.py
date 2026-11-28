"""Behaviours the first production smoke of the fluent agent got wrong (2026-10-19, RAG on)."""
import asyncio,json,time
from app.agent_workflow.evidence import reviewed_answer,unsupported_number_values
from app.agent_workflow.state import AgentRuntimeContext

async def emit(_):pass

MARKUP=('<｜DSML｜ calls>\n<｜DSML｜ invoke name="use_result_set">\n'
        '<｜DSML｜ parameter name="positions" string="false">[1]</｜DSML｜ parameter>\n'
        '</｜DSML｜ invoke>\n</｜DSML｜ calls>')
FILINGS=[{'ordinal':1,'source_type':'official_filing','quote':'Our Internet address is www.microsoft.com.','title':'msft-20260630.htm','source_url':None},
         {'ordinal':2,'source_type':'official_filing','quote':'INCOME STATEMENTS','title':'0001193125-26-323660',
          'source_url':'https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm','published_at':'2026-07-29'}]
SEGMENTS=[{'ordinal':1,'source_type':'official_filing','quote':'(In millions) iPhone 54,252 44,582 Mac 10,352 8,046 Total net sales 109,417','title':'AAPL 10-Q'}]
TABLE=('苹果 10-Q 披露的分产品营收（百万美元）[1]：\n\n| 产品 | 本期 | 上年同期 |\n|---|---|---|\n'
       '| iPhone | 54,252 | 44,582 |\n| Mac | 10,352 | 8,046 |')


def test_digits_inside_a_link_the_evidence_shows_are_not_figures():
    row=('| 2026-07-29 | 10-K | 年度报告正文 msft-20260630.htm [1] | '
         'sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm [1] |')
    assert unsupported_number_values(row,FILINGS)==[]

def test_digits_inside_a_link_no_source_shows_are_still_checked():
    assert unsupported_number_values('详见 example.com/data/123456/report [2]。',FILINGS)==[123456.0]

def test_a_table_row_is_checked_against_the_sources_its_table_cites():
    kept,issues=reviewed_answer(TABLE,SEGMENTS,require_citations=True)
    assert issues==[] and '| Mac | 10,352 | 8,046 |' in kept

def test_a_table_row_stating_a_figure_its_sources_do_not_is_still_dropped():
    kept,issues=reviewed_answer(TABLE.replace('10,352','99,999'),SEGMENTS,require_citations=True)
    assert issues==['unsupported_numeric_claim'] and '99,999' not in kept and '| iPhone | 54,252 | 44,582 |' in kept

def test_a_heading_that_states_no_amount_needs_no_citation():
    text='## 作为替代：本轮可核验的苹果营收官方数字\n\n**单季营收（FY2026 Q3，2026-03-29 至 2026-06-27）**\n\n营收 109,417 百万美元 [1]。'
    assert reviewed_answer(text,SEGMENTS,require_citations=True)[1]==[]

def test_a_heading_that_states_an_amount_still_needs_its_source():
    assert reviewed_answer('## 营收 999 亿美元\n\n营收 109,417 百万美元 [1]。',SEGMENTS,require_citations=True)[1]

def test_a_list_item_keeps_its_sentences_that_passed():
    text='- 另有 999 亿美元的说法。营收为 109,417 百万美元 [1]。'
    kept,issues=reviewed_answer(text,SEGMENTS,require_citations=True)
    assert issues==['missing_citation'] and kept.startswith('- ') and '109,417 百万美元 [1]' in kept and '999' not in kept

def _turn(question='AMD 收盘价',**context):
    return direct.Turn(question,AgentRuntimeContext('custom','test','dummy',**context),emit,[],{})

def _capped(answers,closings):
    def decide(messages,tools):
        turn.started=time.monotonic()-100
        return {'tool_calls':[{'id':'1','function':{'name':'query_stock_prices','arguments':json.dumps({'symbol':'AMD'})}}]}
    def answer(messages):
        closings.append(messages);return answers[len(closings)-1]
    turn=_turn(classifier=lambda _:'D',decider=decide,answerer=answer,
               executor=lambda *_:{'ok':True,'data':[{'id':'p','symbol':'AMD','close':100}]})
    return turn

def test_a_date_written_with_spaces_is_a_date_not_three_figures():
    filing=[{'ordinal':1,'source_type':'official_filing','quote':'Quarterly report 10-Q','title':'MSFT 10-Q'}]
    assert unsupported_number_values('| 2026-01-28 | 10-Q | 截至 2025 年 12 月 31 日的季度报告 [1] |',filing)==[]
    assert unsupported_number_values('交易日为 2026 年 10 月 16 日，统计到 2025 年 12 月 [1]。',filing)==[]

def test_a_question_mark_inside_a_title_does_not_split_the_cited_line():
    text='1. **《Nvidia 与 Apple 股票：2026 年哪一只更值得买入？》（KuCoin，2026-10-18）** [1]'
    news=[{'ordinal':1,'source_type':'web','quote':'Nvidia vs Apple stock: which one to buy?','title':'Nvidia 与 Apple 股票：2026 年哪一只更值得买入？'}]
    kept,issues=reviewed_answer(text,news,require_citations=True)
    assert issues==[] and kept==text

def test_a_numbered_item_that_loses_a_sentence_keeps_a_clean_marker():
    kept,issues=reviewed_answer('1. 营收为 109,417 百万美元 [1]。另有 999 亿美元的说法。',SEGMENTS,require_citations=True)
    assert issues and kept=='1. 营收为 109,417 百万美元 [1]'
