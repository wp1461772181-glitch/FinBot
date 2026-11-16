"""SW1D end to end (spec-sw1d §7.2 E1, E1b, E2, E2-off, E3) and the database-backed unit cases U7, U7b, U8 (§7.1).

E1, E1b, E3, U7, U7b and U8 run the real query_financials tool over seeded filings (the test database); only the model's
decisions are scripted. E2 and E2-off run the real stream parser and the real decision loop: only the model's request is
replaced by a function that writes the step's SSE bytes and sends them through provider._post over a MockTransport.
"""
import asyncio
import json
import time

import httpx

import app.agent_chat_provider as provider
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings, drop, msft_filings, new_symbol, nvda_filings, seed
from test_agent_chat_provider import Chunks
from test_sw1b_closing_complete import calls, cite, scripted, text
from test_sw1d_toolcall_cap import SWITCH, audits, sse_text, sse_tool_calls, switches_default  # noqa: F401  (fixtures)

ORIGINAL_CLIENT = httpx.AsyncClient
# Fixture rows per company, as query_financials shows them: (metric, period label, value in millions).
ROWS = {
    'aapl': [('revenue', 'FY2026 Q3', '94000'), ('revenue', 'FY2025 Q3', '85777'), ('revenue', 'FY2026 前三季度累计', '364357'),
             ('revenue', 'FY2025 前三季度累计', '310000'), ('revenue', 'FY2026 Q2', '111000'), ('revenue', 'FY2026 Q1', '143000'),
             ('revenue', 'FY2026', '478834')],
    'msft': [('revenue', 'FY2026 Q3', '38398'), ('revenue', 'FY2026 前三季度累计', '114634'), ('revenue', 'FY2026 Q2', '76441'),
             ('revenue', 'FY2026 Q1', '77700'), ('revenue', 'FY2026', '331839'), ('revenue', 'FY2025', '281724')],
    'nvda': [('revenue', 'FY2026 Q3', '57000'), ('revenue', 'FY2026 Q4', '68000'), ('revenue', 'FY2027 Q1', '44000'),
             ('revenue', 'FY2027 Q2', '46000')],
}
EXPRESSIONS = ('a-b', '(a-b)/b*100')


def pairs(companies=('aapl', 'msft', 'nvda')):
    """Adjacent pairs of each company's rows, interleaved across companies: (company, row a, row b)."""
    per = {k: [(ROWS[k][i], ROWS[k][i + 1]) for i in range(len(ROWS[k]) - 1)] for k in companies}
    out = []
    for i in range(max(len(v) for v in per.values())):
        for k in companies:
            if i < len(per[k]):
                out.append((k, *per[k][i]))
    return out


def shown(messages, symbol, metric, label):
    """Whether the evidence the model is shown holds this row (cite finds it), so a calculation can bind to it."""
    try:
        cite(messages, symbol, metric, label)
        return True
    except AssertionError:
        return False


def calc_calls(messages, tickers, count, *, companies=('aapl', 'msft', 'nvda'), offset=0):
    """``count`` distinct calculate calls over pairs of rows the evidence shows (a row the budget left out cannot be cited).
    The signature varies by pair, expression and decimals, so no two are the same call (a repeat would be a replay, not new
    work). tickers: company key -> symbol."""
    options = [p for p in pairs(companies)
               if shown(messages, tickers[p[0]], p[1][0], p[1][1]) and shown(messages, tickers[p[0]], p[2][0], p[2][1])]
    items = []
    for k in range(offset, offset + count):
        company, a, b = options[k % len(options)]
        expression = EXPRESSIONS[(k // len(options)) % 2]
        decimals = (k // (len(options) * 2)) % 9
        symbol = tickers[company]
        items.append(('calculate', {'expression': expression, 'decimals': decimals, 'inputs': [
            {'name': 'a', 'value': a[2], 'source_ordinal': cite(messages, symbol, a[0], a[1])},
            {'name': 'b', 'value': b[2], 'source_ordinal': cite(messages, symbol, b[0], b[1])}]}))
    return calls(*items)


def items_of(decision):
    """(name, args) pairs of a scripted decision, for sending the same calls again."""
    return [(c['function']['name'], json.loads(c['function']['arguments'])) for c in decision['tool_calls']]


def evidence_text(messages):
    return next((m['content'] for m in reversed(messages) if isinstance(m, dict)
                 and str(m.get('content') or '').startswith('Accepted evidence DATA')), '')


def calc_cites(messages):
    """The [n] numbers of the calculate results the model is shown, in order."""
    shown = evidence_text(messages)
    if not shown:
        return []
    return [int(o['result']['data'][0]['citation'][1:-1]) for o in json.loads(shown[shown.index('[{'):])
            if o.get('name') == 'calculate']


def tool_replies(protocol):
    """Every tool reply in the protocol, parsed, in order."""
    return [json.loads(m['content']) for m in protocol if m.get('role') == 'tool']


def batch_ids(protocol, index):
    """The tool_call ids of the index-th assistant tool-call message in the protocol."""
    batches = [m for m in protocol if m.get('role') == 'assistant' and m.get('tool_calls')]
    return [c['id'] for c in batches[index]['tool_calls']]


def three_companies():
    tickers = {'aapl': new_symbol(), 'msft': new_symbol(), 'nvda': new_symbol()}
    ids = (seed(tickers['aapl'], aapl_filings()) + seed(tickers['msft'], msft_filings())
           + seed(tickers['nvda'], nvda_filings()))
    return tickers, ids


def question_of(tickers):
    """Names the seeded tickers, so the resolver has no referent to ask about."""
    return f"{tickers['aapl']} {tickers['msft']} {tickers['nvda']} 最近营收与同比"


def scope_of(tickers, companies=None):
    symbols = list(tickers.values()) if companies is None else [tickers[k] for k in companies]
    return {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': symbols, 'days_back': None}


def reads(tickers):
    return calls(*[('query_financials', {'symbol': s, 'latest': True, 'limit': 40}) for s in tickers.values()])


def run_turn(question, scope, steps, seen, *, emit_log=None):
    """A turn whose decisions are the scripted steps (each may read the messages it is shown)."""
    async def emit(event):
        if emit_log is not None:
            emit_log.append((time.monotonic(), event))
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope, decider=scripted(steps, seen))
    with research_context('sw1d-e2e-test', cutoff=CUTOFF):
        return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


# ---- E1: twenty calls in one step, all run --------------------------------------------------------------------------

def test_e1_twenty_calls_in_one_step_all_run_and_all_are_cited(audits):
    tickers, ids = three_companies()
    emit_log, seen = [], []
    try:
        steps = [reads(tickers),
                 lambda messages: calc_calls(messages, tickers, 20),
                 lambda messages: text('计算结果见 ' + ' '.join(f'[{n}]' for n in calc_cites(messages)[:3]) + '。')]
        result = run_turn(question_of(tickers), scope_of(tickers), steps, seen, emit_log=emit_log)
        turn = audits[-1]
        assert result['status'] == 'succeeded'
        replies = tool_replies(turn.protocol)[-20:]
        assert all(r.get('ok') is True and r.get('error_code') != 'step_call_cap' for r in replies)
        assert turn.audit['max_step_calls'] == 20
        assert 'step_calls_deferred' not in turn.audit and 'step_call_deferrals' not in turn.audit
        assert 'provider_retries' not in turn.audit and 'provider_failure' not in turn.audit
        # Each of the twenty is a calculation citation on the turn, and each number is in what the third decision was shown.
        calc_ordinals = {c['ordinal'] for c in turn.citations if c.get('source_type') == 'calculation'}
        cited = [int(r['data'][0]['citation'][1:-1]) for r in replies]
        assert len(set(cited)) == 20 and set(cited) <= calc_ordinals
        visible = json.dumps(seen[2], ensure_ascii=False)
        assert all(f'[{n}]' in visible for n in cited)
        # Wall-clock time of the twenty calls, from the request to the last result (recorded in the report).
        ids_of_step = set(batch_ids(turn.protocol, 1))
        start = next(t for t, e in emit_log if e.get('event') == 'assistant_tool_request' and len(e['protocol']['calls']) == 20)
        last = max(t for t, e in emit_log if e.get('event') == 'tool_result' and e['call_id'] in ids_of_step)
        print('E1 twenty-call step seconds:', round(last - start, 3))
    finally:
        drop(ids)


# ---- E1b and E3: forty calls, the tail deferred and re-sent --------------------------------------------------------

def run_e1b():
    tickers, ids = three_companies()
    seen, state = [], {}

    def forty(messages):
        decision = calc_calls(messages, tickers, 40)
        state['sent'] = items_of(decision)
        return decision

    def resend_tail(messages):
        state['step3'] = messages
        return calls(*state['sent'][32:40])

    def close(messages):
        state['final'] = messages
        return text('结果见 ' + ' '.join(f'[{n}]' for n in calc_cites(messages)[-4:]) + '。')
    try:
        steps = [reads(tickers), forty, resend_tail, close]
        return run_turn(question_of(tickers), scope_of(tickers), steps, seen), state
    finally:
        drop(ids)


def test_e1b_forty_calls_run_thirty_two_then_the_eight_the_model_resends(audits):
    result, state = run_e1b()
    turn = audits[-1]
    assert result['status'] == 'succeeded'
    assert turn.audit['max_step_calls'] == 40
    assert turn.audit['step_calls_deferred'] == 8
    assert turn.audit['step_call_deferrals'] == [{'step': 2, 'sent': 40, 'run': 32}]
    # The third decision was shown the eight replies, by position 33..40.
    replies = [r for r in tool_replies(state['step3']) if r.get('error_code') == 'step_call_cap']
    assert [r['call_position'] for r in replies] == list(range(33, 41))
    assert len([o for o in turn.observations if o['name'] == 'calculate']) == 40   # 32 in step 2, the 8 re-sent in step 3


def test_e3_the_ledger_and_the_evidence_hold_only_the_calls_that_ran(audits):
    _, state = run_e1b()
    turn = audits[-1]
    assert len(turn.calc_attempts) == 40                 # one attempt per call that ran; no attempt for a deferred reply
    assert all(a.get('error_code') != 'step_call_cap' for a in turn.calc_attempts)
    # The ledger is the evidence and the omitted-readings text, both system messages of the last decision. Neither names a
    # deferred reply. (The protocol's tool replies do carry them: those are the record of the step, not the ledger.)
    ledger = json.dumps([m['content'] for m in state['final'] if isinstance(m, dict) and m.get('role') == 'system'], ensure_ascii=False)
    assert 'step_call_cap' not in ledger and 'Not run' not in ledger


# ---- U7 / U7b / U8: the cap at the unit level, on the seeded filings ----------------------------------------------

def msft_calls(messages, tickers, count, offset=0):
    return calc_calls(messages, tickers, count, companies=('msft',), offset=offset)


def test_u7_a_step_past_the_cap_runs_thirty_two_and_answers_the_rest(audits):
    from app.agent_tool_catalog import validate
    tickers, ids = three_companies()
    seen, emitted, state = [], [], {}

    def forty(messages):
        decision = msft_calls(messages, tickers, 40)
        state['sent'] = items_of(decision)
        return decision
    try:
        steps = [reads(tickers), forty, lambda messages: text('结果已取得。')]
        result = run_turn(question_of(tickers), scope_of(tickers), steps, seen, emit_log=emitted)
        turn = audits[-1]
        assert result['status'] == 'succeeded'
        assert turn.audit['max_step_calls'] == 40
        assert turn.audit['step_call_cap'] == 32
        assert turn.audit['step_calls_deferred'] == 8
        # Step 2 is the second decision (step 1 is the three reads), so the deferral is recorded at step 2 (K7).
        assert turn.audit['step_call_deferrals'] == [{'step': 2, 'sent': 40, 'run': 32}]
        # The batch: the assistant message carries all forty; the last eight tool replies are the cap's, in position order.
        batch = [m for m in turn.protocol if m.get('role') == 'assistant' and len(m.get('tool_calls') or []) == 40]
        assert len(batch) == 1
        tail = tool_replies(turn.protocol)[-8:]
        assert [r['call_position'] for r in tail] == list(range(33, 41))
        for position, reply in zip(range(33, 41), tail):
            assert reply == {'ok': False, 'error_code': 'step_call_cap', 'executed': False, 'call_position': position,
                             'calls_in_step': 40, 'step_call_cap': 32,
                             'note': f'Not run: one step runs the first 32 calls and this was call {position} of 40. It can be sent again in a later step.'}
        # Each of the eight deferred calls got its reply as a tool_result event, under its own call id.
        deferred_ids = batch_ids(turn.protocol, 1)[32:40]
        events = {e['call_id']: e['result'] for _, e in emitted if e.get('event') == 'tool_result' and e['call_id'] in deferred_ids}
        assert list(events) == deferred_ids and all(events[i] == r for i, r in zip(deferred_ids, tail))
        # Only the calls that ran are counted, seen and observed: three reads and thirty-two calculations.
        assert turn.audit['tool_calls'] == 3 + 32
        assert len(turn.observations) == 3 + 32
        # The eight deferred signatures are not among the seen ones (validated arguments, as the loop records them).
        deferred = [sig for sig in (json.dumps([name, validate(name, args)], sort_keys=True, ensure_ascii=False)
                                    for name, args in state['sent'][32:40])]
        assert len(deferred) == 8 and not set(deferred) & set(turn.seen)
        assert len(turn.seen) == 3 + 32
    finally:
        drop(ids)


def test_u8_the_eight_deferred_calls_run_when_the_model_sends_them_again(audits):
    tickers, ids = three_companies()
    seen, state = [], {}

    def forty(messages):
        decision = msft_calls(messages, tickers, 40)
        state['sent'] = items_of(decision)
        return decision

    def resend(messages):
        return calls(*state['sent'][32:40])

    def close(messages):
        state['final'] = messages
        return text('结果见 ' + ' '.join(f'[{n}]' for n in calc_cites(messages)[-8:]) + '。')
    try:
        # A second closing answer follows the first: the SW1B completeness check may send one reminder (the reads of AAPL and
        # NVDA are not in this answer), and the revised answer is the one kept.
        result = run_turn(question_of(tickers), scope_of(tickers), [reads(tickers), forty, resend, close, close], seen)
        turn = audits[-1]
        assert result['status'] == 'succeeded'
        resent = tool_replies(turn.protocol)[-8:]
        assert all(r.get('ok') is True and r.get('error_code') != 'step_call_cap' and not r.get('reused') for r in resent)
        assert 'replayed_calls' not in turn.audit
        cited = calc_cites(state['final'])[-8:]
        assert len(cited) == 8 and all(f'[{n}]' in result['answer'] for n in cited)
    finally:
        drop(ids)


def test_u7b_a_mixed_tail_is_deferred_whole_and_the_tail_read_is_sent_again_and_observed(audits):
    tickers, ids = three_companies()
    seen, state = [], {}
    tail_read = ('query_financials', {'symbol': tickers['nvda'], 'latest': True, 'limit': 3})

    def mixed(messages):
        head = items_of(msft_calls(messages, tickers, 30))                 # positions 1-30: calculate
        tail_calc = items_of(msft_calls(messages, tickers, 1, offset=39))[0]
        state['tail'] = [tail_read, tail_calc]                              # positions 33 and 34: deferred
        return calls(*head, ('load_tools', {'categories': ['行情']}),       # 31
                     ('query_financials', {'symbol': tickers['nvda'], 'latest': True, 'limit': 2}),   # 32, runs
                     tail_read, tail_calc)

    def resend(messages):
        state['step3'] = messages
        return calls(*state['tail'])

    try:
        steps = [reads(tickers), mixed, resend, lambda messages: text('结果已取得。')]
        result = run_turn(question_of(tickers), scope_of(tickers), steps, seen)
        turn = audits[-1]
        assert result['status'] == 'succeeded'
        assert turn.audit['step_call_deferrals'] == [{'step': 2, 'sent': 34, 'run': 32}]
        assert turn.audit['step_calls_deferred'] == 2
        # Positions 33 and 34 were replied to with the cap's fact, and nothing was recorded for them.
        replies = [r for r in tool_replies(state['step3']) if r.get('error_code') == 'step_call_cap']
        assert [r['call_position'] for r in replies] == [33, 34]
        # The reads observed: the three of step 1, the one that ran in step 2 (limit 2), then the deferred read once re-sent (limit 3).
        observed = [o['arguments'].get('limit') for o in turn.observations if o['name'] == 'query_financials']
        assert observed == [40, 40, 40, 2, 3]
        # The three reads of step 1, the 32 that ran in step 2 (30 calculations, load_tools, one read) and the two re-sent in step 3.
        assert len(turn.seen) == 3 + 32 + 2
        assert all(r.get('ok') is True for r in tool_replies(turn.protocol)[-2:])
    finally:
        drop(ids)


# ---- E2 and E2-off: the real parser and the real loop, with the model's bytes written by the test -------------------

def stream_transport(monkeypatch, queue):
    """One MockTransport for the whole turn (the decision session keeps one client): each request returns the next queued stream."""
    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(queue.pop(0)))
    monkeypatch.setattr(provider.httpx, 'AsyncClient', lambda **kw: ORIGINAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def stream_model(steps, queue, requests):
    """Stands in for decision_request. A request with tool schemas is a decision: its step is chosen by how many tool-call
    batches the messages already hold, so a retry of the same request gets the same step. A request without schemas is the
    closing answer. The step's SSE bytes are queued and read through the real provider._post."""
    async def decide(provider_name, model, api_key, messages, schemas, base_url=None, **kw):
        requests.append(schemas)
        if not schemas:
            queue.append(sse_text('已取得的资料如上。'))
        else:
            done = sum(1 for m in messages if isinstance(m, dict) and m.get('role') == 'assistant' and m.get('tool_calls'))
            step = steps[done] if done < len(steps) else text('')
            decision = step(messages) if callable(step) else step
            if decision.get('tool_calls'):
                queue.append(sse_tool_calls(items_of(decision), split=True, interleave=True))
            else:
                queue.append(sse_text(decision.get('content') or ''))
        return await provider._post('deepseek', 'test-key', {'model': model, 'messages': messages, 'stream': True})
    return decide


def run_stream_turn(monkeypatch, tickers, steps):
    queue, requests = [], []
    stream_transport(monkeypatch, queue)
    monkeypatch.setattr(direct, 'decision_request', stream_model(steps, queue, requests))
    scope = scope_of(tickers)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope)

    async def emit(_):
        pass
    with research_context('sw1d-e2e-stream', cutoff=CUTOFF):
        result = asyncio.run(direct.run_direct_turn(question_of(tickers), ctx, emit=emit))
    return result, requests


def e2_steps(tickers):
    return [reads(tickers),
            lambda messages: calc_calls(messages, tickers, 20),
            lambda messages: text('计算结果见 ' + ' '.join(f'[{n}]' for n in calc_cites(messages)[:3]) + '。')]


def test_e2_the_real_parser_and_loop_run_twenty_calls_from_one_stream(audits, monkeypatch):
    tickers, ids = three_companies()
    try:
        result, requests = run_stream_turn(monkeypatch, tickers, e2_steps(tickers))
        turn = audits[-1]
        assert result['status'] == 'succeeded'
        assert all(r.get('ok') is True for r in tool_replies(turn.protocol)[-20:])
        assert turn.audit['max_step_calls'] == 20
        assert 'provider_retries' not in turn.audit
        assert len(requests) == turn.audit['model_calls']       # one request per model call: nothing was retried
    finally:
        drop(ids)


def test_e2_off_the_same_stream_is_refused_at_index_twelve_and_nothing_runs(audits, monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    tickers, ids = three_companies()
    try:
        result, requests = run_stream_turn(monkeypatch, tickers, e2_steps(tickers))
        turn = audits[-1]
        assert turn.audit['provider_retries'] == 1
        assert turn.audit['provider_failure'] == 'provider_incompatible_response'
        assert not any(o['name'] == 'calculate' for o in turn.observations)   # the twenty never ran
        assert len(requests) == turn.audit['model_calls'] + turn.audit['provider_retries']
    finally:
        drop(ids)
