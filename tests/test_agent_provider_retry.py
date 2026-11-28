"""A provider hiccup costs one retry of that call, not the turn."""
import asyncio
import pytest
from fastapi import HTTPException
from app.agent_workflow.state import AgentRuntimeContext
from app.agent_chat_provider import _merge_delta

async def emit(_):pass

def test_a_long_chinese_reasoning_is_accepted_up_to_the_memory_guard():
    message={'role':'assistant','content':''};calls={}
    _merge_delta(message,calls,{'reasoning_content':'想'*100_000})
    assert len(message['reasoning_content'])==100_000
    with pytest.raises(HTTPException):_merge_delta(message,calls,{'reasoning_content':'想'*600_000})

def test_a_large_tool_result_keeps_the_rows_that_fit():
    from app.agent_chat_stream import bounded_tool_result
    # Rows sized so the kept rows fill the limit to within the result's own extra keys.
    rows=[{'id':str(i),'excerpt':'x'*6144} for i in range(11)]
    bounded=bounded_tool_result({'ok':True,'data':rows,'source':'saved'})
    assert bounded['ok'] and bounded['data'] and bounded['truncated']
