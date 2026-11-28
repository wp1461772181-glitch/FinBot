"""SW1B B1 (spec-sw1b §4.1, B01–B14): the closing completeness reminder.

Component tests build a Turn, read figure rows through the real financials code (figure_rows) and calculate for real.
The full-turn cases (B11, B12, B14) run run_direct_turn with a scripted decider and a fake query_financials executor.
No database is touched.
"""
import asyncio
import itertools
import json

import pytest

from app.agent_workflow.financials import figure_rows
from app.agent_workflow.state import AgentRuntimeContext
from sw1_filings import aapl_filings, msft_filings, new_symbol

SWITCH = 'FINBOT_SW1B_CLOSING_COMPLETE'
NOTE_MARK = '系统事实：用户点名的公司里'
ABSENCE_MARK = '系统事实：你的草稿说有资料没有取到'
UNREAD = {'form': '10-Q', 'filed_at': '2026-08-01', 'period': None, 'why': 'form_filter'}
GAP_SENTENCE = '{m} 只有年度数据，Q4 和 Q1 本轮未核算 [{fy}]；{a} 的 Q3 见 [{aq3}]。'
_ids = itertools.count(1)


# ---- helpers -------------------------------------------------------------------------------------------------------

def rows_of(symbol, filings):
    """The figure rows query_financials returns for one company's saved filings (the real row builder)."""
    rows = []
    for number, filing in enumerate(filings):
        rows += figure_rows({'id': f'{symbol}-{number}', 'symbol': symbol, 'form': filing['form'],
                             'accession_number': f'{symbol}-{number:04d}', 'filed_at': filing['filed'].isoformat(),
                             'content_source_url': f'https://www.sec.gov/{symbol}/{number}', 'content_financials': filing['figures']})
    return rows


def scope_of(symbols):
    return {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': list(symbols), 'days_back': None}


def entry(ordinal, symbol, label='FY2026 Q3', metric='revenue', span='quarter', end='2026-06-27', value='82,886 百万美元'):
    """One ledger line, as note_figures keeps it."""
    return {'ordinal': ordinal, 'symbol': symbol, 'metric': metric, 'metric_zh': '营业收入', 'period_span': span,
            'period_label_short': label, 'period_end': end, 'value_text': value, 'label': 'Revenue'}


def attempt(inputs, *, ok=True, result=None, unbound=None):
    """One calculate attempt, as note_calc keeps it. inputs: (source ordinal, value) pairs."""
    return {'ok': ok, 'inputs': [{'ordinal': o, 'value': str(v)} for o, v in inputs], 'result_ordinal': result,
            'error_code': None if ok else 'calculation_input_unbound', 'unbound': unbound}


def unbound(ordinal, requested, closest):
    return {'ordinal': ordinal, 'requested_value': requested, 'closest': closest, 'reason': 'value_not_in_source'}


def ordinal_of(turn, symbol, metric, label):
    return next(e['ordinal'] for e in turn.figure_ledger if e['symbol'] == symbol and e['metric'] == metric
                and e['period_label_short'] == label)


def cite(messages, symbol, metric, label):
    """The [n] the model was shown for one row: what it reads from the evidence it is given."""
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith('Accepted evidence DATA'):
            text = m['content']
            for observation in json.loads(text[text.index('[{'):]):
                for row in (observation.get('result') or {}).get('data') or []:
                    if isinstance(row, dict) and row.get('symbol') == symbol and row.get('metric') == metric \
                            and str(row.get('period_label') or '').split('（')[0] == label:
                        return int(row['citation'][1:-1])
    raise AssertionError(f'{symbol} {metric} {label} is not in the evidence shown')


def call(name, **args):
    return {'tool_calls': [{'id': f'call-{next(_ids)}', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}


def calls(*items):
    return {'tool_calls': [{'id': f'call-{next(_ids)}', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}
                           for name, args in items]}


def text(content):
    return {'content': content}


def scripted(steps, seen):
    """Steps are decisions, or callables that read the messages the model was shown and return one."""
    queue = list(steps)

    def decide(messages, tools):
        seen.append(messages)
        step = queue.pop(0) if queue else text('')
        return step(messages) if callable(step) else step
    return decide


def executor_for(rows_by_symbol, coverage=None):
    def run(name, args):
        assert name == 'query_financials', name
        outcome = {'ok': True, 'data': list(rows_by_symbol[args['symbol']]), 'source': 'fake'}
        if coverage and args['symbol'] in coverage:
            outcome['meta'] = {'coverage': coverage[args['symbol']]}
        return outcome
    return run


def run_turn(question, scope, steps, seen, rows_by_symbol, coverage=None):
    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope, decider=scripted(steps, seen),
                              executor=executor_for(rows_by_symbol, coverage))
    return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def reminders(seen, mark=NOTE_MARK):
    found = {id(m): m for messages in seen for m in messages if isinstance(m, dict) and m.get('role') == 'system'
             and mark in str(m.get('content') or '')}
    return list(found.values())


def coverage_with_unread(symbol):
    return {symbol: {'filters': {}, 'filings_read': [{'form': '10-K', 'filed_at': '2026-07-29', 'period': 'FY2026'}],
                     'not_read': [dict(UNREAD)], 'rows_left_out_by_limit': 0, 'periods_left_out': [], 'widened': []}}


@pytest.fixture(autouse=True)
def switches_default(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv('FINBOT_SW1B_SAMPLE_AGGREGATE', raising=False)


@pytest.fixture
def audits(monkeypatch):
    """Each finished turn's audit and Turn object: run_direct_turn returns neither."""
    seen, turns = [], []
    original = direct.Turn.finish

    def spy(self, *args, **kwargs):
        seen.append(dict(self.audit))
        turns.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(direct.Turn, 'finish', spy)
    return seen, turns


# The Q3#2 shape: two companies; MSFT's Q4 calculation fails on the scaled value; the draft says Q4 was not calculated.
M, A = new_symbol(), new_symbol()
Q3_DRAFT = '{m} 的 Q3 营收 38,398 百万美元 [{q3}]，Q4 和 Q1 本轮未核算。{a} 的 Q3 营收 94,000 百万美元 [{aq3}]。'


def q3_steps(drafts=None):
    """Read both companies, try MSFT's Q4 with the scaled value (fails), then draft the Q3#2 closing."""
    def read(messages):
        return calls(('query_financials', {'symbol': M, 'latest': True, 'limit': 40}),
                     ('query_financials', {'symbol': A, 'latest': True, 'limit': 40}))

    def failing(messages):
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '331.839', 'source_ordinal': cite(messages, M, 'revenue', 'FY2026')},
            {'name': 'b', 'value': '114.634', 'source_ordinal': cite(messages, M, 'revenue', 'FY2026 前三季度累计')}])

    def draft(messages):
        content = Q3_DRAFT.format(m=M, a=A, q3=cite(messages, M, 'revenue', 'FY2026 Q3'), aq3=cite(messages, A, 'revenue', 'FY2026 Q3'))
        if drafts is not None:
            drafts.append(content)
        return text(content)
    return [read, failing, draft]


def read_both():
    return {M: rows_of(M, msft_filings()), A: rows_of(A, aapl_filings())}


# ---- B01 / B02: what the ledger and the calculate record hold ------------------------------------------------------

# ---- B03–B10: the check itself, on a ledger and calculations set up for each case ---------------------------------

# ---- M1: the example quotes the source's own value; closest_in_source never reaches the reminder -------------------

# ---- B11, B12, B14: the closing in a full turn ---------------------------------------------------------------------

# ---- B13: sizes ----------------------------------------------------------------------------------------------------

