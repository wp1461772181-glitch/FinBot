"""SW1D (spec-sw1d §7.1 U1–U13, §7.3 R3): the parser's stream guard, the per-step call cap, the replies past it, and the
batch-too-large code.

Stream cases call provider._post (or stream_answer) over a MockTransport, as test_agent_chat_provider.py does. Turn cases
call Turn.model or run_direct_turn with a scripted decider; the ones that need evidence read fixture rows through the
executor hook, so they need no database. The database-backed cases (U7, U7b, U8) live in test_sw1d_e2e.py.
"""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

import app.agent_chat_provider as provider
from app import agent_context as layers
from app.agent_chat_provider import ResponseCheckFailed, TOOL_CALL_STREAM_GUARD
from app.agent_workflow import direct, trace
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings
from test_agent_chat_provider import Chunks, transport
from test_sw1b_closing_complete import rows_of

SWITCH = 'FINBOT_SW1D_TOOLCALL_CAP'
SWITCHES = (SWITCH, 'FINBOT_SW1C_OMITTED_DIGEST', 'FINBOT_SW1B_CLOSING_COMPLETE', 'FINBOT_SW1B_SAMPLE_AGGREGATE',
            'FINBOT_SW1_READ_WIDEN', 'FINBOT_SW1_ABSENCE_RECHECK', 'FINBOT_SW1_FRESHNESS',
            'FINBOT_SW1_EXISTENCE_KNOWLEDGE', 'FINBOT_SW1_RESOLVER_RULES')
DONE = b'data: [DONE]\n\n'
CHECKS = {'utf8_decode', 'non_json_line', 'choice_shape', 'text_not_string', 'reasoning_details_shape', 'tool_calls_shape',
          'tool_part_shape', 'tool_index', 'tool_part_type', 'tool_function_shape', 'tool_field_not_string',
          'post_finish_delta', 'json_body', 'json_message_shape'}


@pytest.fixture(autouse=True)
def switches_default(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def audits(monkeypatch):
    turns = []
    original = direct.Turn.finish

    def spy(self, *args, **kwargs):
        turns.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(direct.Turn, 'finish', spy)
    return turns


# ---- synthetic SSE --------------------------------------------------------------------------------------------------

def data_line(event):
    return f'data: {json.dumps(event, ensure_ascii=False)}\n\n'.encode()


def sse_tool_calls(items, *, split=True, interleave=False, pieces=None, finish='tool_calls'):
    """items: [(name, args), ...]; call i has index i. split: the arguments come in two pieces (or pieces[i]), and the id and
    name ride on the first piece only. interleave: the pieces of different calls share one delta where they line up."""
    per_call = []
    for i, (name, args) in enumerate(items):
        raw = json.dumps(args, ensure_ascii=False)
        n = min((pieces or {}).get(i, 2 if split else 1), len(raw))
        cuts = [round(len(raw) * k / n) for k in range(n + 1)]
        frags = []
        for k in range(n):
            item = {'index': i, 'function': {'arguments': raw[cuts[k]:cuts[k + 1]]}}
            if k == 0:
                item.update(id=f'call_{i}', type='function')
                item['function']['name'] = name
            frags.append(item)
        per_call.append(frags)
    if interleave:
        deltas = [[f[k] for f in per_call if k < len(f)] for k in range(max(len(f) for f in per_call))]
    else:
        deltas = [[item] for f in per_call for item in f]
    events = [{'choices': [{'delta': {'tool_calls': d}, 'finish_reason': None}]} for d in deltas]
    events.append({'choices': [{'delta': {}, 'finish_reason': finish}]})
    return [data_line(e) for e in events] + [DONE]


def sse_text(content):
    events = [{'choices': [{'delta': {'content': content}, 'finish_reason': None}]},
              {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
    return [data_line(e) for e in events] + [DONE]


def event_of_index(lines, index):
    """1-based number of the data event (not [DONE]) whose tool_calls first names this index."""
    number = 0
    for line in lines:
        text = line.decode()
        if not text.startswith('data:') or '[DONE]' in text:
            continue
        number += 1
        for part in json.loads(text[5:])['choices'][0]['delta'].get('tool_calls') or []:
            if part.get('index') == index:
                return number
    raise AssertionError(f'no event names index {index}')


def stream_post(monkeypatch, lines, name='deepseek'):
    transport(monkeypatch, httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(lines)))
    return asyncio.run(provider._post(name, 'test-key', {'stream': True}))


def parsed(message):
    return [(c['id'], c['function']['name'], json.loads(c['function']['arguments'])) for c in message['tool_calls']]


def expected_calls(items):
    return [(f'call_{i}', name, args) for i, (name, args) in enumerate(items)]


def make_turn(window=0, question='公司营收', scope=None):
    async def emit(_):
        pass
    context = AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='guest', context_window=window)
    turn = direct.Turn(question, context, emit, [], {})
    turn.scope = dict(scope or {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [], 'days_back': None})
    turn.route = 'A'
    return turn


# ---- U1–U5: the parser -------------------------------------------------------------------------------------------

def test_u1_twelve_calls_are_the_same_with_the_switch_on_and_off(monkeypatch):
    items = [('calculate', {'n': i}) for i in range(12)]
    lines = sse_tool_calls(items, split=True, interleave=True)
    on_data, on_message = stream_post(monkeypatch, lines)
    monkeypatch.setenv(SWITCH, 'off')
    off_data, off_message = stream_post(monkeypatch, lines)
    assert json.dumps(on_data, sort_keys=True) == json.dumps(off_data, sort_keys=True)
    assert parsed(on_message) == expected_calls(items)


def test_u2_thirteen_calls_are_rejected_with_the_switch_off_and_accepted_with_it_on(monkeypatch):
    items = [('calculate', {'n': i}) for i in range(13)]
    lines = sse_tool_calls(items, split=True, interleave=True)
    monkeypatch.setenv(SWITCH, 'off')
    with pytest.raises(HTTPException) as error:
        stream_post(monkeypatch, lines)
    exc = error.value
    assert exc.status_code == 502 and exc.detail == 'provider_incompatible_response'
    assert exc.check == 'tool_index' and exc.tool_index == 12
    assert exc.event == event_of_index(lines, 12)
    monkeypatch.setenv(SWITCH, 'on')
    _, message = stream_post(monkeypatch, lines)
    assert parsed(message) == expected_calls(items)


@pytest.mark.parametrize('count', [20, 40, 128])
def test_u3_calls_up_to_the_stream_guard_are_all_accepted_in_order(monkeypatch, count):
    assert TOOL_CALL_STREAM_GUARD == 128            # spec §2.1: the parser's bound on index (0..127 accepted)
    items = [('calculate', {'n': i}) for i in range(count)]
    _, message = stream_post(monkeypatch, sse_tool_calls(items, split=True, interleave=True))
    assert parsed(message) == expected_calls(items)


def test_u4_past_the_stream_guard_is_a_finbot_limit_and_is_not_retried(monkeypatch, audits):
    items = [('calculate', {'n': i}) for i in range(129)]
    lines = sse_tool_calls(items, split=True, interleave=True)
    with pytest.raises(HTTPException) as error:
        stream_post(monkeypatch, lines)
    exc = error.value
    assert exc.status_code == 502 and exc.detail == 'tool_call_batch_too_large'
    assert exc.check == 'tool_index' and exc.tool_index == 128 and exc.event == event_of_index(lines, 128)
    # Through the turn: one request, no retry, and the check is recorded.
    attempts = []

    async def stub(*args, **kwargs):
        attempts.append(args)
        raise ResponseCheckFailed('tool_call_batch_too_large', 'tool_index', event=exc.event, tool_index=128)
    monkeypatch.setattr(direct, 'decision_request', stub)
    turn = make_turn()
    with pytest.raises(HTTPException):
        asyncio.run(turn.model([{'role': 'user', 'content': 'q'}], []))
    assert len(attempts) == 1
    assert 'provider_retries' not in turn.audit
    assert turn.audit['provider_checks'] == [{'code': 'tool_call_batch_too_large', 'check': 'tool_index',
                                             'event': exc.event, 'tool_index': 128, 'retried': False}]


def test_u5_a_mixed_step_keeps_every_call_whole_and_in_index_order(monkeypatch):
    items = [('query_financials', {'symbol': 'AAA', 'latest': True, 'limit': k}) for k in (1, 2, 3)]
    items += [('calculate', {'expression': 'a-b', 'decimals': k, 'inputs': [
        {'name': 'a', 'value': '5', 'source_ordinal': 1}, {'name': 'b', 'value': '2', 'source_ordinal': 2}]}) for k in range(15)]
    items += [('load_tools', {'categories': ['行情']})]
    _, message = stream_post(monkeypatch, sse_tool_calls(items, split=True, interleave=True, pieces={5: 5}))
    assert parsed(message) == expected_calls(items)


# ---- U6: the execution cap follows the window --------------------------------------------------------------------

@pytest.mark.parametrize('window,expected', [(0, 32), (200_000, 50), (1_000_000, 128), (32_000, 12), (4_000, 12)])
def test_u6_the_step_cap_is_the_window_formula_and_thirty_two_by_default(window, expected):
    turn = make_turn(window=window)
    running = layers.running_bytes_for_window(window) if window else layers.RUNNING_REQUEST_BYTES
    assert turn.step_call_cap() == min(128, max(12, running // 2 // 6000))
    # K10: the window-0 case is 32 only where RUNNING_REQUEST_BYTES is the 128k default (AGENT_MODEL_CONTEXT_WINDOW unset).
    if window or layers.RUNNING_REQUEST_BYTES == 384_000:
        assert turn.step_call_cap() == expected


# ---- U9–U10: the check codes -------------------------------------------------------------------------------------

def ev(delta=None, finish=None):
    choice = {'delta': delta if delta is not None else {}}
    if finish:
        choice['finish_reason'] = finish
    return data_line({'choices': [choice]})


# (case, stream lines or a JSON body, check, event number, which entry point)
MALFORMED = [
    ('utf8_decode', [b'data: \xff\xfe\n\n', DONE], 'utf8_decode', 1, 'stream'),
    ('non_json_line', [b'data: not-json\n\n', DONE], 'non_json_line', 1, 'stream'),
    ('choice_shape', [b'data: []\n\n', DONE], 'choice_shape', 1, 'stream'),
    ('text_not_string', [ev({'content': 5}), DONE], 'text_not_string', 1, 'stream'),
    ('reasoning_details_shape', [ev({'reasoning_details': 'x'}), DONE], 'reasoning_details_shape', 1, 'stream'),
    ('tool_calls_shape', [ev({'tool_calls': 'x'}), DONE], 'tool_calls_shape', 1, 'stream'),
    ('tool_part_shape', [ev({'tool_calls': [{'index': -1}]}), DONE], 'tool_part_shape', 1, 'stream'),
    ('tool_index', [ev({'tool_calls': [{'index': 12, 'id': 'c', 'function': {'name': 'x', 'arguments': '{}'}}]}), DONE],
     'tool_index', 1, 'stream'),
    ('tool_part_type', [ev({'tool_calls': [{'index': 0, 'type': 'x'}]}), DONE], 'tool_part_type', 1, 'stream'),
    ('tool_function_shape', [ev({'tool_calls': [{'index': 0, 'function': 'x'}]}), DONE], 'tool_function_shape', 1, 'stream'),
    ('tool_field_not_string', [ev({'tool_calls': [{'index': 0, 'function': {'name': 5}}]}), DONE], 'tool_field_not_string', 1, 'stream'),
    ('post_finish_delta', [ev({'content': 'a'}, 'stop'), ev({'content': 'b'}), DONE], 'post_finish_delta', 2, 'stream'),
    ('json_body', b'not json', 'json_body', None, 'json'),
    ('json_message_shape', b'{"choices":[{"message":"x","finish_reason":"stop"}]}', 'json_message_shape', None, 'json'),
    ('stream_answer post_finish_delta', [ev({'content': 'a'}, 'stop'), ev({'content': 'b'}), DONE], 'post_finish_delta', 2, 'answer'),
]


def run_malformed(monkeypatch, case):
    _, body, _, _, kind = case
    if kind == 'json':
        transport(monkeypatch, httpx.Response(200, headers={'content-type': 'application/json'}, stream=Chunks([body])))
        return asyncio.run(provider._post('deepseek', 'test-key', {}))
    transport(monkeypatch, httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(body)))
    if kind == 'answer':
        async def drain():
            async for _ in provider.stream_answer('deepseek', 'deepseek-chat', 'test-key', []):
                pass
        return asyncio.run(drain())
    return asyncio.run(provider._post('deepseek', 'test-key', {'stream': True}))


@pytest.mark.parametrize('case', MALFORMED, ids=[c[0] for c in MALFORMED])
def test_u9_each_check_keeps_its_code_status_and_position_and_never_the_text(monkeypatch, case):
    name, _, check, event, _ = case
    monkeypatch.setenv(SWITCH, 'off')
    with pytest.raises(HTTPException) as error:
        run_malformed(monkeypatch, case)
    exc = error.value
    assert isinstance(exc, HTTPException) and exc.status_code == 502
    assert exc.detail == 'provider_incompatible_response'
    assert exc.check == check and exc.check in CHECKS
    if event is not None:
        assert exc.event == event
    assert set(vars(exc)) - {'status_code', 'detail', 'headers'} <= {'check', 'event', 'tool_index'}


@pytest.mark.parametrize('case', [c for c in MALFORMED if c[0] != 'tool_index'], ids=[c[0] for c in MALFORMED if c[0] != 'tool_index'])
def test_u9_on_keeps_the_same_detail_for_every_check_but_the_tool_index_one(monkeypatch, case):
    with pytest.raises(HTTPException) as error:
        run_malformed(monkeypatch, case)
    assert error.value.detail == 'provider_incompatible_response'


def error_labels(monkeypatch):
    labels = []

    def record(generation, **kw):
        if 'error' in kw:
            labels.append(kw['error'])
    monkeypatch.setattr(direct.observability, 'end_generation', record)
    return labels


def test_u10_a_failed_check_is_recorded_and_its_retry_is_too_and_the_label_names_the_check(monkeypatch):
    seen_labels = error_labels(monkeypatch)
    # One failure, then success on the retry.  decision_request returns (response, message), as provider._post does.
    responses = [ResponseCheckFailed('provider_incompatible_response', 'post_finish_delta', event=7),
                 ({'usage': {'total_tokens': 3}}, {'role': 'assistant', 'content': 'ok'})]

    async def stub(*args, **kwargs):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    monkeypatch.setattr(direct, 'decision_request', stub)
    turn = make_turn()
    message = asyncio.run(turn.model([{'role': 'user', 'content': 'q'}], []))
    assert message['content'] == 'ok'
    assert turn.audit['provider_retries'] == 1
    assert turn.audit['provider_checks'] == [{'code': 'provider_incompatible_response', 'check': 'post_finish_delta',
                                             'event': 7, 'retried': True}]
    assert seen_labels == []   # the call succeeded: no error label

    # Both attempts fail: two records, and the error label names the check.
    responses[:] = [ResponseCheckFailed('provider_incompatible_response', 'post_finish_delta', event=7),
                    ResponseCheckFailed('provider_incompatible_response', 'post_finish_delta', event=7)]
    turn = make_turn()
    with pytest.raises(HTTPException):
        asyncio.run(turn.model([{'role': 'user', 'content': 'q'}], []))
    assert [c['retried'] for c in turn.audit['provider_checks']] == [True, False]
    assert seen_labels[-1] == 'provider_incompatible_response:post_finish_delta'


def test_u10_with_the_switch_off_there_are_no_records_and_the_error_is_only_the_code(monkeypatch):
    seen_labels = error_labels(monkeypatch)
    monkeypatch.setenv(SWITCH, 'off')

    async def stub(*args, **kwargs):
        raise ResponseCheckFailed('provider_incompatible_response', 'post_finish_delta', event=7)
    monkeypatch.setattr(direct, 'decision_request', stub)
    turn = make_turn()
    with pytest.raises(HTTPException):
        asyncio.run(turn.model([{'role': 'user', 'content': 'q'}], []))
    assert 'provider_checks' not in turn.audit and turn.audit.get('provider_retries') == 1
    assert seen_labels[-1] == 'provider_incompatible_response'


# ---- U11–U13: the decider batch, the trace, and off ----------------------------------------------------------------

def run_with_decider(question, scope, steps, seen, *, executor=None, answer='已取得的资料显示 [1]。'):
    """A turn with a scripted decider. The closing answer is given by an answerer, so no model is ever called."""
    from test_sw1b_closing_complete import scripted

    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope, decider=scripted(steps, seen),
                              answerer=lambda messages: answer, executor=executor)
    with research_context('sw1d-unit-test', cutoff=CUTOFF):
        return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def fixture_executor(rows_by_symbol, *, distinct=False):
    """query_financials from fixture rows. distinct: each read's rows carry their own id and source_url, so that reads of one
    company are new evidence and not repeated evidence (the turn's no_progress guard hashes those keys)."""
    def run(name, args):
        assert name == 'query_financials', name
        rows = list(rows_by_symbol[args['symbol']])
        if distinct:
            tag = f"{args['symbol']}-read-{args.get('limit')}"
            rows = [{**row, 'id': f'{tag}-{i}', 'source_url': f'https://www.sec.gov/{tag}/{i}'} for i, row in enumerate(rows)]
        return {'ok': True, 'data': rows, 'source': 'fake'}
    return run


def batch(count, name='calculate'):
    """A decision with ``count`` calculate calls (arguments only need to parse: the batch is refused or deferred before any runs)."""
    return {'tool_calls': [{'id': f'batch-{count}-{i}', 'function': {'name': name, 'arguments': json.dumps(
        {'expression': 'a-b', 'inputs': [{'name': 'a', 'value': '5', 'source_ordinal': 1},
                                         {'name': 'b', 'value': '2', 'source_ordinal': 2}], 'decimals': i % 9},
         ensure_ascii=False)}} for i in range(count)]}


def test_u11_a_batch_past_the_guard_with_evidence_closes_on_the_evidence_with_the_note(audits):
    from sw1_filings import new_symbol
    from test_sw1b_closing_complete import call, text
    symbol = new_symbol()
    rows = {symbol: rows_of(symbol, aapl_filings())}
    scope = {'category': 'A', 'mode': 'financials', 'symbol': symbol, 'symbols': [symbol], 'days_back': None}
    seen = []
    steps = [call('query_financials', symbol=symbol, latest=True, limit=4), batch(129)]
    result = run_with_decider(f'{symbol} 营收', scope, steps, seen, executor=fixture_executor(rows))
    assert result['status'] == 'succeeded'
    assert result['answer'].endswith('（模型这一步一次发出的工具调用超过了系统单次能接收的上限，本轮基于已取得的资料作答。）')
    turn = audits[-1]
    assert not any(m.get('role') == 'assistant' and len(m.get('tool_calls') or []) == 129 for m in turn.protocol)
    assert turn.audit.get('provider_failure') is None  # the decider path sets the stop, not a provider failure


def test_u11_a_batch_past_the_guard_with_no_evidence_fails_with_the_note(audits):
    from sw1_filings import new_symbol
    symbol = new_symbol()
    scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [], 'days_back': None}
    seen = []
    result = run_with_decider('一个问题', scope, [batch(129)], seen)
    assert result['status'] == 'failed'
    assert result['answer'].startswith('模型这一步一次发出的工具调用超过了系统单次能接收的上限，已停止。')


def test_u12_a_deferred_call_shows_as_a_warning_and_other_failures_stay_failed():
    assert trace.tool_output({'ok': False, 'error_code': 'step_call_cap'})[0] == 'warn'
    assert trace.tool_output({'ok': False, 'error_code': 'x'})[0] == 'failed'


def test_u13_with_the_switch_off_a_thirteen_call_step_is_still_protocol_invalid(audits, monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [], 'days_back': None}
    seen = []
    result = run_with_decider('一个问题', scope, [batch(13)], seen)
    assert result['reason'] == 'provider_protocol_invalid'
    audit = audits[-1].audit
    assert not any(k in audit for k in ('max_step_calls', 'step_call_cap', 'step_calls_deferred', 'step_call_deferrals', 'provider_checks'))


# ---- R3: the basis of the cap, measured ---------------------------------------------------------------------------

def padded_rows(symbol, filings, size):
    """Real figure rows, repeated until one result is about ``size`` bytes."""
    base = rows_of(symbol, filings)
    rows = []
    while len(json.dumps(rows, ensure_ascii=False).encode()) < size:
        rows += base
    return rows


DIGEST_HEAD = '以下是本轮已读、因篇幅不在上面 DATA 里的数'


def measure_full_batch(audits, monkeypatch, count, *, cap=None):
    """One step of ``count`` full-size reads (about 64 KB each), then a closing text. Returns the numbers R3 reports: the
    request the model is sent at the second decision (the protocol and the evidence block as tool_messages builds them),
    and the protocol alone against the protocol half-guard."""
    from app.agent_tool_catalog import schemas
    from sw1_filings import new_symbol
    if cap is not None:
        monkeypatch.setattr(direct.Turn, 'step_call_cap', lambda self: cap)
    symbol = new_symbol()
    rows = {symbol: padded_rows(symbol, aapl_filings(), 64_000)}
    scope = {'category': 'A', 'mode': 'financials', 'symbol': symbol, 'symbols': [symbol], 'days_back': None}
    seen = []
    steps = [batch_of_reads(symbol, count), {'content': '完成。'}]
    run_with_decider(f'{symbol} 营收', scope, steps, seen, executor=fixture_executor(rows, distinct=True))
    turn = audits[-1]
    messages = seen[1]
    evidence = next(m['content'] for m in messages if isinstance(m, dict) and str(m.get('content') or '').startswith('Accepted evidence DATA'))
    digest = any(isinstance(m, dict) and DIGEST_HEAD in str(m.get('content') or '') for m in messages)
    request = len(json.dumps(messages, ensure_ascii=False).encode()) + len(json.dumps(schemas(owner=True)).encode())
    protocol = len(json.dumps(turn.protocol, ensure_ascii=False).encode())
    half = turn._running_bytes() // 2
    return {'count': count, 'evidence_chars': len(evidence), 'digest': digest, 'request_bytes': request,
            'running': turn._running_bytes(), 'protocol_bytes': protocol, 'half': half,
            'ratio': round(protocol / half, 3), 'executed': turn.audit.get('tool_calls')}


def test_r3_thirty_two_full_results_fill_the_evidence_and_the_request_stays_under_the_guard(audits, monkeypatch):
    numbers = measure_full_batch(audits, monkeypatch, 32)
    print('R3', numbers)
    assert numbers['executed'] == 32
    assert numbers['evidence_chars'] > 20_000 and numbers['digest']        # evidence filled to its budget, with the SW1C ledger
    assert numbers['request_bytes'] < numbers['running']


def test_r3_report_only_thirty_three_full_results(audits, monkeypatch):
    # Report only (spec §7.3): the same step with the cap lifted to 33, to show how much room the guard leaves.
    numbers = measure_full_batch(audits, monkeypatch, 33, cap=33)
    print('R3-33', numbers)


def batch_of_reads(symbol, count):
    from test_sw1b_closing_complete import calls
    return calls(*[('query_financials', {'symbol': symbol, 'latest': True, 'limit': k}) for k in range(1, count + 1)])
