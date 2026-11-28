"""The resolver writes the canonical question every turn, and every later stage reads it."""
import asyncio,json
from app.agent_workflow.state import AgentRuntimeContext
from app.freshness import requested_years

CANONICAL='微软（MSFT）2025 财年（截至 2025-06-30）的营业收入是多少？'
HISTORY=[{'role':'user','content':'先看一下微软（MSFT）最近一期年报的营收。'},
         {'role':'assistant','content':'微软（MSFT）FY2025 营业收入为 281,724 百万美元 [1]。'}]

async def emit(_):pass

def run(question,*,resolver,classifier,history=None):
    seen=[]
    def decide(messages,tools):seen.append(messages);return {'content':'好的。'}
    ctx=AgentRuntimeContext('custom','test','dummy',resolver=resolver,classifier=classifier,decider=decide)
    result=asyncio.run(direct.run_direct_turn(question,ctx,emit=emit,messages=history))
    return result,seen[0] if seen else []

def hint(messages):
    return next(m['content'] for m in messages if m['role']=='system' and m['content'].startswith('对当前问题的理解'))

def test_requested_years_reads_only_literal_years():
    assert requested_years('去年微软的营收')==set()
    assert requested_years('2025 财年')=={'2025'}

