"""A model that writes an empty nullable field as the string "null" is classified, not rejected.

Real muse-ember arguments (2026-11-13 diagnosis): days_back/form/period come back as the *string* "null".
Only the empty spellings are normalised; the validation itself is not relaxed.
"""
import asyncio
import json

import pytest

from app.agent_chat_stream import _failure_notice
from app.agent_workflow import direct
from app.agent_workflow.routing import parse_route, safe_parse_route
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


def test_real_ember_sample_is_accepted_and_empties_become_none():
    route, _ = safe_parse_route(json.dumps(EMBER_SAMPLE))
    assert route.days_back is None and route.form is None and route.period is None
    assert route.symbols == ['NVDA', 'AMD', 'INTC'] and route.symbol == 'NVDA'
    assert route.metrics == ['毛利率'] and route.mode == 'financials'


@pytest.mark.parametrize('field', ['days_back', 'form', 'period', 'symbol'])
@pytest.mark.parametrize('spelling', ['null', 'NULL', 'Null', ' null ', 'None', 'none', 'N/A', 'n/a', '', '   '])
def test_empty_spellings_become_none(field, spelling):
    assert getattr(parse_route(base(**{field: spelling})), field) is None


def test_string_null_symbol_is_not_promoted_to_a_ticker():
    route = parse_route(base(symbol='null'))
    assert route.symbol is None and route.symbols == []


def test_real_values_pass_unchanged():
    route = parse_route(base(days_back=7, form='10-Q', period='2025Q3', symbol='MU'))
    assert (route.days_back, route.form, route.period, route.symbol) == (7, '10-Q', '2025Q3', 'MU')


@pytest.mark.parametrize('over', [{'days_back': 'abc'}, {'days_back': 'nulll'}, {'form': '10-Z'}, {'form': 'nulll'}])
def test_invalid_values_are_still_rejected(over):
    with pytest.raises(ValueError):
        parse_route(base(**over))


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


def test_retry_prompt_names_failed_field_and_demands_json_null(monkeypatch):
    bad = {**EMBER_SAMPLE, 'form': '10-Z'}
    result, seen = run_turn(monkeypatch, [bad, bad])
    retry = seen[1][-1]['content']
    assert seen[1][-1]['role'] == 'system'
    assert 'form' in retry and 'JSON null' in retry and 'string "null"' in retry
    assert 'leave unspecified' not in retry  # the wording that taught ember to write "null"
    assert '10-Z' not in retry  # field and reason only, never echo the model's value back as text


def test_second_failure_records_classification_error_and_own_reason(monkeypatch):
    bad = {**EMBER_SAMPLE, 'form': '10-Z', 'days_back': 'abc'}
    result, _ = run_turn(monkeypatch, [bad, bad])
    assert result['status'] == 'failed' and result['reason'] == 'classification_invalid'
    error = result['audit']['classification_error']
    assert 'form' in error and 'days_back' in error and 'str' in error
    assert '\n' not in error and 'pydantic' not in error.lower() and '10-Z' not in error
    assert '无法使用' not in result['answer']


def test_ember_string_null_turn_no_longer_fails_classification(monkeypatch):
    result, seen = run_turn(monkeypatch, [EMBER_SAMPLE, {'content': 'x'}])
    assert result['audit'].get('classification_retries') is None  # first attempt classified
    assert result.get('reason') != 'classification_invalid'


def test_other_failure_reasons_are_untouched(monkeypatch):
    result, _ = run_turn(monkeypatch, [ValueError('provider_protocol_invalid')] * 2)
    assert result['reason'] == 'provider_protocol_invalid'
    result, _ = run_turn(monkeypatch, [ValueError('task_token_cap')] * 2)
    assert result['reason'] == 'task_token_cap'
    assert 'classification_error' not in result['audit']


def test_failure_notice_for_classification_invalid_is_honest():
    notice = _failure_notice(HTTPException(502, 'classification_invalid'))
    assert '无法使用' not in notice and '模型服务' not in notice
    assert notice != _failure_notice(HTTPException(502, 'unknown_failure'))
    assert '再发一次' in notice
