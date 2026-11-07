"""End-to-end checks for citation protocol v2 (issue_citation), driven through run_direct_turn with stub models.

Switch: FLEX_CITATION_PROTOCOL=on (default off).  The v1 path is covered by the existing citation tests.
"""
import asyncio
import json

import pytest

from app.agent_workflow import citation_issuance, direct
from app.agent_workflow.state import AgentRuntimeContext

PRICE_ROWS = [
    {'id': 'p1', 'symbol': 'AMD', 'close': 100, 'trading_date': '2026-10-20'},
    {'id': 'p2', 'symbol': 'AMD', 'close': 999, 'trading_date': '2026-10-19'},
]
ANSWER = 'AMD 收盘价为 100 美元。'


async def emit(_):
    pass


def call(name, **args):
    return {'tool_calls': [{'id': f'{name}-{len(json.dumps(args))}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}


def text(content):
    return {'content': content}


def run(steps, monkeypatch, question='AMD 收盘价', protocol='on'):
    monkeypatch.setenv('FLEX_CITATION_PROTOCOL', protocol)
    seen = []
    queue = iter(steps)

    def decide(messages, tools):
        seen.append({'messages': [dict(m) for m in messages], 'tools': [t['function']['name'] for t in tools]})
        return next(queue)

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: 'D', decider=decide,
                              executor=lambda *_: {'ok': True, 'data': PRICE_ROWS})
    result = asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))
    return result, seen


def test_v1_default_is_unchanged(monkeypatch):
    result, seen = run([call('query_stock_prices', symbol='AMD'), text(ANSWER + '[1]')], monkeypatch, protocol='off')
    assert 'issue_citation' not in seen[-1]['tools']
    assert 'citation_protocol' not in result and 'citation_nodes' not in result
    assert '[1]' in result['answer']


def test_normal_issuance_delivers_a_node_and_no_marker(monkeypatch):
    # (1) The model reads the price row, signs the quote, then writes the answer without markers.
    result, seen = run([call('query_stock_prices', symbol='AMD'),
                        call('issue_citation', source_ref='1', quote='close=100.0'),
                        text(ANSWER)], monkeypatch)
    assert 'issue_citation' in seen[1]['tools']
    assert result['citation_protocol'] == 'v2'
    assert len(result['citation_nodes']) == 1
    node = result['citation_nodes'][0]
    assert node['source_ref'] == '1' and node['quote'] == 'close=100.0' and node['anchor']['block_id'] == 'answer'
    assert '[' not in result['answer'] and '100 美元' in result['answer']
    assert result['status'] == 'succeeded'


def test_rejected_quote_receipt_lets_the_model_correct_in_the_same_turn(monkeypatch):
    # (2) A quote that is not in the snapshot is refused with a receipt; the corrected call is accepted.
    result, seen = run([call('query_stock_prices', symbol='AMD'),
                        call('issue_citation', source_ref='1', quote='888'),
                        call('issue_citation', source_ref='1', quote='close=100.0'),
                        text(ANSWER)], monkeypatch)
    refusal = [json.loads(m['content']) for s in seen for m in s['messages']
               if m.get('role') == 'tool' and 'quote_not_in_snapshot' in m.get('content', '')]
    assert refusal and refusal[0]['source_ref'] == '1' and refusal[0]['request'] == '888'
    assert 'close=100.0' in refusal[0]['window']
    assert len(result['citation_nodes']) == 1 and result['citation_nodes'][0]['quote'] == 'close=100.0'
    assert result['status'] == 'succeeded'


def test_malformed_tool_arguments_get_a_receipt_not_an_exception(monkeypatch):
    broken = {'tool_calls': [{'id': 'bad-1', 'function': {'name': 'issue_citation', 'arguments': '{"source_ref": '}}]}
    result, seen = run([call('query_stock_prices', symbol='AMD'), broken,
                        call('issue_citation', source_ref='1', quote='close=100.0'), text(ANSWER)], monkeypatch)
    receipt = [m['content'] for s in seen for m in s['messages'] if m.get('tool_call_id') == 'bad-1' and m.get('role') == 'tool']
    assert receipt and json.loads(receipt[0]) == {'ok': False, 'error': 'invalid_arguments'}
    assert len(result['citation_nodes']) == 1


def test_hand_written_marker_is_never_a_citation(monkeypatch):
    # (3) A model that types [1] without calling the tool gets body text with no citation node and no marker.
    result, _ = run([call('query_stock_prices', symbol='AMD'), text('AMD 收盘价为 100 美元[1]。')], monkeypatch)
    assert result['citation_protocol'] == 'v2'
    assert result['citation_nodes'] == []
    assert '[1]' not in result['answer'] and '100 美元' in result['answer']
    assert all('[' not in line['line'] for line in result['unverified_lines'] if isinstance(line, dict))


@pytest.mark.parametrize('failure', ['issue', 'construct'])
def test_issuer_failure_delivers_body_without_citation_components(monkeypatch, failure):
    # (4) The signing service fails (at construction or at issue): the body is delivered, no node, no marker.
    if failure == 'issue':
        def boom(self, item):
            raise RuntimeError('signing service down')
        monkeypatch.setattr(citation_issuance.CitationIssuer, 'issue', boom)
    else:
        def boom(sources):
            raise RuntimeError('signing service down')
        monkeypatch.setattr(citation_issuance, 'new_turn_issuer', boom)
    result, _ = run([call('query_stock_prices', symbol='AMD'),
                     call('issue_citation', source_ref='1', quote='close=100.0'),
                     text(ANSWER)], monkeypatch)
    assert result['citation_protocol'] == 'v2' and result['citation_nodes'] == []
    assert '100 美元' in result['answer'] and '[' not in result['answer']
    assert result['audit'].get('citation_issuer_error') == 'RuntimeError'


def test_issuer_refuses_quote_outside_snapshot_and_unknown_source():
    issuer = citation_issuance.new_turn_issuer({'1': 'Close 100 USD'})
    refused = citation_issuance.issue_for_turn(issuer, {'source_ref': '1', 'quote': 'Close 999'})
    assert refused['ok'] is False and refused['error'] == 'quote_not_in_snapshot'
    unknown = citation_issuance.issue_for_turn(issuer, {'source_ref': '7', 'quote': 'Close 100'})
    assert unknown['error'] == 'source_not_in_turn' and unknown['available_sources'][0]['source_ref'] == '1'
    assert citation_issuance.issue_for_turn(issuer, 'not-a-dict') == {'ok': False, 'error': 'invalid_arguments'}
    ambiguous = citation_issuance.new_turn_issuer({'1': 'close 100 and close 100 again'})
    hit = citation_issuance.issue_for_turn(ambiguous, {'source_ref': '1', 'quote': '100'})
    assert hit['error'] == 'quote_ambiguous' and len(hit['hits']) == 2 and hit['hits'][0]['window']
