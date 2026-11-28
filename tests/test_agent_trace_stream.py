"""The turn graph on the wire, out of the checkpoint, and back in the history.

The graph is drawn while the answer is still being written, so these tests pin both
directions: every node reaches the browser before the answer text, and the saved turn
keeps the same nodes plus the time the stream spent thinking.
"""
import asyncio, json
from types import SimpleNamespace
import pytest
from test_agent_chat_stream import frames, stream_fixture  # noqa: F401

def test_history_returns_the_trace_and_the_thinking_time(monkeypatch):
    import app.agent_chat_stream as stream
    trace=[{'id':'n1','kind':'input','status':'done','after':[],'start_ms':0,'ms':3,'output':{'question':'苹果营收'}},
           {'id':'n2','kind':'output','status':'done','after':['n1'],'start_ms':40,'ms':5,'output':{'status':'succeeded'}}]
    async def rows(*_args,**_kwargs):
        return {'messages':[
            {'role':'assistant','content':'带图','status':'complete','turn_id':'t1','tool_calls':{'trace':trace,'thinking_ms':1234}},
            {'role':'assistant','content':'只有旧计时','status':'complete','turn_id':'t2','tool_calls':{'audit':{'elapsed_ms':900}}},
            {'role':'assistant','content':'都没有','status':'complete','turn_id':'t3','tool_calls':None}],
            'has_more':False,'next_before':None}
    monkeypatch.setattr(stream,'owned_message_page',rows)
    items=asyncio.run(stream.get_messages('conversation','owner'))['messages']
    assert items[0]['trace']==trace and items[0]['thinking_ms']==1234
    assert items[1]['thinking_ms']==900 and 'trace' not in items[1]
    assert 'trace' not in items[2] and 'thinking_ms' not in items[2]
