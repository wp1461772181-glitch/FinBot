"""A model that writes an empty nullable field as the string "null" is classified, not rejected.

Real muse-ember arguments (2026-11-13 diagnosis): days_back/form/period come back as the *string* "null".
Only the empty spellings are normalised; the validation itself is not relaxed.
"""
import asyncio
import json

import pytest

from app.agent_chat_stream import _failure_notice
from app.agent_workflow.state import AgentRuntimeContext
from fastapi import HTTPException

# Real ember sample (diagnosis report section 3, attempt 1).
EMBER_SAMPLE = {
    'category': 'A', 'company': 'NVIDIA', 'company_mention': 'NVDA', 'days_back': 'null',
    'explicit_task_change': False, 'financial_only': False, 'form': 'null', 'latest': False,
    'load_hint': ['财报与SEC'], 'max_results': 5, 'metrics': ['毛利率'], 'mode': 'financials',
    'period': 'null', 'query': 'NVDA 上个季度毛利率多少来着？', 'requested_actions': [],
    'symbol': 'NVDA', 'symbols': ['NVDA', 'AMD', 'INTC'], 'write_condition': 'none',
}


def base(**over):
    return {'category': 'A', 'days_back': None, **over}


# -- classify(): retry prompt, failure record, failure copy ------------------------------------------------

def run_turn(monkeypatch, replies):
    """Run a turn whose classification model returns `replies` in turn; returns (result, messages seen per call)."""
    seen, queue = [], list(replies)

    async def fake_model(self, messages, tool_schemas, **kw):
        seen.append([dict(m) for m in messages])
        self.audit['model_calls'] += 1
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return {'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'classify_request', 'arguments': json.dumps(item)}}]}

    monkeypatch.setattr(direct.Turn, 'model', fake_model)

    async def emit(_):
        pass

    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              resolver=lambda p: {'relationship': 'new', 'canonical_question': p['question']})
    result = asyncio.run(direct.run_direct_turn('NVDA 上季度毛利率？', ctx, emit=emit))
    return result, seen


def test_failure_notice_for_classification_invalid_is_honest():
    notice = _failure_notice(HTTPException(502, 'classification_invalid'))
    assert '无法使用' not in notice and '模型服务' not in notice
    assert notice != _failure_notice(HTTPException(502, 'unknown_failure'))
    assert '再发一次' in notice
