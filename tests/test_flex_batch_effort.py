import asyncio
import json
from types import SimpleNamespace

from app.agent_workflow import flex_number_review as f


def test_batches_keep_same_line_and_stable_ids():
    ps = f.positions('1 plus 2 equals 3\n4\n5\n6')
    assert [[p['id'] for p in b] for b in f._batches(ps)] == [[0, 1, 2], [3, 4, 5]]
    assert [len(b) for b in f._batches(f.positions('1, 2, 3, 4, 5, 6, 7'))] == [3, 3, 1]
    assert [len(b) for b in f._batches(f.positions('1 + 2 + 3 + 4 = 10'))] == [5]


def test_failed_batch_does_not_erase_completed_batch_and_network_retries_low():
    calls = []
    async def call(model, system, user, *, reasoning_effort):
        req = json.loads(user)
        calls.append((reasoning_effort, [p['id'] for p in req['positions']]))
        if req['positions'][0]['id'] >= 3:
            raise RuntimeError('offline')
        return {}, {'content': json.dumps({'results': [{'id': p['id'], 'responsibility': 'current', 'binding': 'insufficient'} for p in req['positions']], 'pairs': []})}
    out = asyncio.run(f.review_offline('1\n2\n3\n4', {}, {}, call=call))
    assert calls == [('low', [0, 1, 2]), ('low', [3]), ('low', [3])]
    assert [r['reason'] for r in out['results']] == ['insufficient_material'] * 3 + ['no_answer']


def test_escalates_only_eligible_positions_with_receipt_once():
    calls = []
    async def call(model, system, user, *, reasoning_effort):
        req = json.loads(user); calls.append((reasoning_effort, req))
        if len(calls) == 1:
            results = [{'id': 0, 'responsibility': 'current', 'binding': 'direct', 'quote': 'invented', 'source_ref': '1'},
                       {'id': 1, 'responsibility': 'current', 'binding': 'insufficient'},
                       {'id': 2, 'responsibility': 'current', 'binding': 'none', 'evidence_likely': True}]
        else:
            results = [{'id': p['id'], 'responsibility': 'current', 'binding': 'insufficient'} for p in req['positions']]
        return {}, {'content': json.dumps({'results': results, 'pairs': []})}
    out = asyncio.run(f.review_offline('1 2 3', {'1': 'source'}, {}, call=call))
    assert [c[0] for c in calls] == ['low', 'high']
    assert [p['id'] for p in calls[1][1]['positions']] == [0, 2]
    assert [r['reason'] for r in calls[1][1]['receipt']] == ['quote_unverified', 'evidence_likely_relation_unestablished']
    assert len(out['results']) == 3


def test_independent_full_call_budget_and_deadline_keeps_completed(monkeypatch):
    waits = []
    real_wait_for = asyncio.wait_for
    ticks = iter([0, 0, 301, 301])
    monkeypatch.setattr(f, 'time', SimpleNamespace(monotonic=lambda: next(ticks, 301)))
    async def wait_for(awaitable, timeout):
        waits.append(timeout)
        return await real_wait_for(awaitable, 1)
    monkeypatch.setattr(f.asyncio, 'wait_for', wait_for)
    async def call(model, system, user, *, reasoning_effort):
        req = json.loads(user)
        return {}, {'content': json.dumps({'results': [{'id': p['id'], 'responsibility': 'current', 'binding': 'insufficient'} for p in req['positions']], 'pairs': []})}
    out = asyncio.run(f.review_offline('1\n2\n3\n4', {}, {}, call=call))
    assert waits == [60.0]
    assert [r['reason'] for r in out['results']] == ['insufficient_material'] * 3 + ['no_answer']
