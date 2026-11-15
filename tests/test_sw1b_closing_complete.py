"""SW1B B1 (spec-sw1b §4.1, B01–B14): the closing completeness reminder.

Component tests build a Turn, read figure rows through the real financials code (figure_rows) and calculate for real.
The full-turn cases (B11, B12, B14) run run_direct_turn with a scripted decider and a fake query_financials executor.
No database is touched.
"""
import asyncio
import itertools
import json

import pytest

from app.agent_workflow import direct
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


def turn_for(scope, question='公司营收'):
    async def emit(_):
        pass
    context = AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='guest')
    turn = direct.Turn(question, context, emit, [], {})
    turn.scope = dict(scope)
    turn.route = 'A'
    return turn


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

def test_b01_a_financial_read_fills_the_ledger_and_a_price_read_does_not():
    turn = turn_for({'mode': 'financials', 'symbol': M, 'symbols': [M]}, question=f'{M} 营收')
    turn.accept('query_financials', {'symbol': M}, {'ok': True, 'data': rows_of(M, msft_filings())})
    ledger = turn.figure_ledger
    assert ledger and {'ordinal', 'symbol', 'metric', 'metric_zh', 'period_span', 'period_label_short', 'period_end',
                        'value_text', 'label'} <= set(ledger[0])
    assert {e['symbol'] for e in ledger} == {M} and {e['metric_zh'] for e in ledger} == {'营业收入'}
    assert {e['ordinal'] for e in ledger} <= {c['ordinal'] for c in turn.citations}
    fy = next(e for e in ledger if e['period_label_short'] == 'FY2026')
    assert fy['value_text'] == '331,839 百万美元' and fy['period_end'] == '2026-06-30'
    before = len(ledger)
    turn.accept('query_stock_prices', {'symbol': M}, {'ok': True, 'data': [
        {'source_type': 'saved_price', 'symbol': M, 'trading_date': '2026-11-10', 'close': 100.0}]})
    assert len(turn.figure_ledger) == before


def test_b02_an_unbound_and_a_successful_calculate_are_both_recorded():
    turn = turn_for({'mode': 'financials', 'symbol': M, 'symbols': [M]}, question=f'{M} 营收')
    turn.accept('query_financials', {'symbol': M}, {'ok': True, 'data': rows_of(M, msft_filings())})
    fy, nine = ordinal_of(turn, M, 'revenue', 'FY2026'), ordinal_of(turn, M, 'revenue', 'FY2026 前三季度累计')
    failed = asyncio.run(turn.execute_read('calculate', {'expression': 'a-b', 'inputs': [
        {'name': 'a', 'value': '331.839', 'source_ordinal': fy}, {'name': 'b', 'value': '114.634', 'source_ordinal': nine}]}))
    assert failed['ok'] is False and failed['error_code'] == 'calculation_input_unbound'
    first = turn.calc_attempts[0]
    assert first['ok'] is False and first['result_ordinal'] is None and first['error_code'] == 'calculation_input_unbound'
    assert first['inputs'][0] == {'ordinal': fy, 'value': '331.839'}
    assert first['unbound']['ordinal'] == fy and first['unbound']['requested_value'] == '331.839'
    assert first['unbound']['closest'] is not None
    ok = asyncio.run(turn.execute_read('calculate', {'expression': 'a-b', 'inputs': [
        {'name': 'a', 'value': '331839', 'source_ordinal': fy}, {'name': 'b', 'value': '114634', 'source_ordinal': nine}]}))
    assert ok['ok'] is True
    second = turn.calc_attempts[1]
    assert second['ok'] is True and second['error_code'] is None and second['unbound'] is None
    assert second['result_ordinal'] == len(turn.citations) and second['inputs'][1]['ordinal'] == nine


# ---- B03–B10: the check itself, on a ledger and calculations set up for each case ---------------------------------

def test_b03_a_failed_calculation_never_redone_is_named_with_its_ledger_rows():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(3, A, 'FY2026 前三季度累计', span='ytd', end='2026-06-27', value='364,357 百万美元'),
                          entry(9, M, 'FY2026', span='annual', end='2026-06-30', value='331,839 百万美元'),
                          entry(11, M), entry(13, M, 'FY2026 前三季度累计', span='ytd', end='2026-03-31', value='114,634 百万美元'),
                          entry(15, M, 'FY2026 Q2', end='2025-12-31', value='76,441 百万美元')]
    turn.calc_attempts = [attempt([(9, '331.839'), (13, '114.634')], ok=False, unbound=unbound(9, '331.839', '331839'))]
    draft = f'{M} 的 Q4 和 Q1 本轮未核算，Q3 见 [11]；{A} 营收见 [1]。'
    found = turn.closing_complete_check(draft)
    assert [(item['symbol'], list(item['kinds'])) for item in found] == [(M, ['unfinished_calc'])]
    ledger = turn.closing_ledger_text(found)
    assert M in ledger and '[9]' in ledger and '[13]' in ledger and '331839' in ledger and 'FY2026 Q3 [11]' in ledger
    assert turn.arm_closing_complete(found, draft, merged=False) == ledger
    assert turn.audit['closing_complete_symbols'] == [{'symbol': M, 'kind': 'unfinished_calc', 'ordinals': [9, 13]}]


def test_b04_a_later_success_with_the_same_source_numbers_is_not_named():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(9, M, 'FY2026', span='annual', end='2026-06-30'),
                          entry(11, M), entry(13, M, 'FY2026 前三季度累计', span='ytd', end='2026-03-31')]
    turn.calc_attempts = [attempt([(9, '331.839'), (13, '114.634')], ok=False, unbound=unbound(9, '331.839', '331839')),
                          attempt([(9, '331839'), (13, '114634')], ok=True, result=20)]
    assert turn.closing_complete_check(f'{M} 的 Q4 未核算 [11]，{A} 见 [1] 与 [20]。') == []


def test_b05_a_wrong_source_ordinal_redone_with_the_same_value_is_not_named():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(9, M, 'FY2026', span='annual', end='2026-06-30'), entry(11, M),
                          entry(13, M, 'FY2026 前三季度累计', span='ytd', end='2026-03-31')]
    turn.calc_attempts = [attempt([(13, '331839'), (11, '82886')], ok=False, unbound=unbound(13, '331839', '241832')),
                          attempt([(9, '331839'), (11, '82886')], ok=True, result=21)]
    assert turn.closing_complete_check(f'{M} Q4 未核算 [11]，{A} [1] [21]。') == []


def test_b06_the_order_of_success_and_failure_does_not_matter():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(9, M, 'FY2026', span='annual', end='2026-06-30'), entry(11, M),
                          entry(13, M, 'FY2026 前三季度累计', span='ytd', end='2026-03-31')]
    turn.calc_attempts = [attempt([(9, '331839')], ok=True, result=20),
                          attempt([(13, '331839')], ok=False, unbound=unbound(13, '331839', '241832'))]
    assert turn.closing_complete_check(f'{M} Q4 未核算 [11]，{A} [1] [20]。') == []


def test_b07_without_a_gap_phrase_the_draft_is_left_alone():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(9, M, 'FY2026', span='annual', end='2026-06-30'), entry(11, M)]
    turn.calc_attempts = [attempt([(9, '331.839'), (11, '82.886')], ok=False, unbound=unbound(9, '331.839', '331839'))]
    assert turn.closing_complete_check(f'{M} Q3 见 [11]，{A} 见 [1]。') == []


def test_b08_a_read_company_the_draft_never_uses_is_named_as_unused_rows():
    turn = turn_for(scope_of([A, M]))
    turn.figure_ledger = [entry(1, A), entry(3, A, 'FY2026 Q3', end='2026-06-27', value='94,000 百万美元'),
                          entry(11, M), entry(15, M, 'FY2026 Q2', end='2025-12-31', value='76,441 百万美元')]
    found = turn.closing_complete_check(f'{A} 的营收是 [1]，Q3 见 [3]。')
    assert [(item['symbol'], list(item['kinds'])) for item in found] == [(M, ['unused_rows'])]
    assert '草稿里没有用到这家公司的任何一条' in turn.closing_ledger_text(found)


def test_b09_a_single_company_is_not_checked_for_unused_rows():
    turn = turn_for(scope_of([M]))
    turn.figure_ledger = [entry(11, M), entry(15, M, 'FY2026 Q2', end='2025-12-31')]
    assert turn.closing_complete_check(f'{M} 的营收没有引用。') == []


def test_b10_a_question_with_no_named_company_is_never_checked():
    turn = turn_for(scope_of([]))
    turn.figure_ledger = [entry(1, A), entry(9, M, 'FY2026', span='annual', end='2026-06-30')]
    turn.calc_attempts = [attempt([(9, '331.839')], ok=False, unbound=unbound(9, '331.839', '331839'))]
    assert turn.closing_complete_check('行业增速本轮未核算。') == []


# ---- B11, B12, B14: the closing in a full turn ---------------------------------------------------------------------

def test_b11_a_second_closing_that_still_says_not_calculated_is_kept_without_another_reminder(audits):
    seen_audits, turns = audits
    seen = []
    result = run_turn(f'{A} 与 {M} 最近一季营收', scope_of([A, M]), q3_steps() + [text('已按草稿回答。')], seen, read_both())
    assert result['status'] == 'succeeded'
    notes = reminders(seen)
    assert len(notes) == 1 and notes[0]['content'].startswith(NOTE_MARK)
    audit = turns[-1].audit
    assert audit['closing_complete_outcome'] == 'kept' and audit['closing_complete_merged'] is False
    assert audit.get('absence_recheck_noted') is None


def test_b12_the_reminder_merges_with_the_absence_recheck_into_one_message_with_the_draft_once(audits):
    seen_audits, turns = audits
    seen, drafts = [], []
    padding = '甲' * 1500   # longer than SW1's 1200, shorter than 3000: the merged note quotes it whole (K3)
    steps = q3_steps()
    steps[2] = lambda messages: text(GAP_SENTENCE.format(m=M, a=A, fy=cite(messages, M, 'revenue', 'FY2026'),
                                                        aq3=cite(messages, A, 'revenue', 'FY2026 Q3')) + padding)
    steps.append(text('已按草稿回答。'))
    run_turn(f'{A} 与 {M} 最近一季营收', scope_of([A, M]), steps, seen, read_both(), coverage_with_unread(M))
    notes = reminders(seen, ABSENCE_MARK)
    assert len(notes) == 1 and notes[0]['content'].startswith(ABSENCE_MARK)
    content = notes[0]['content']
    assert NOTE_MARK in content and content.index(ABSENCE_MARK) < content.index(NOTE_MARK)
    assert content.count('只有年度数据，Q4 和 Q1 本轮未核算') == 1 and padding in content
    assert '10-Q 2026-08-01' in content
    audit = turns[-1].audit
    assert audit['absence_recheck_noted'] is True and audit['closing_complete_noted'] is True
    assert audit['closing_complete_merged'] is True
    assert audit['absence_recheck_outcome'] == 'kept' and audit['closing_complete_outcome'] == 'kept'


def test_b14_switch_off_restores_the_sw1_behaviour_word_for_word(audits, monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    seen_audits, turns = audits
    seen = []
    run_turn(f'{A} 与 {M} 最近一季营收', scope_of([A, M]), q3_steps() + [text('已按草稿回答。')], seen, read_both())
    assert reminders(seen) == []
    assert not [k for k in turns[-1].audit if k.startswith('closing_complete')]

    # Merged shape with the switch off: the SW1 note alone, its draft quoted at SW1's own 1200 characters.
    drafts = []
    padding = '甲' * 1500
    steps = q3_steps()

    def gap(messages):
        content = GAP_SENTENCE.format(m=M, a=A, fy=cite(messages, M, 'revenue', 'FY2026'),
                                      aq3=cite(messages, A, 'revenue', 'FY2026 Q3')) + padding
        drafts.append(content)
        return text(content)
    steps[2] = gap
    steps.append(text('已按草稿回答。'))
    seen = []
    run_turn(f'{A} 与 {M} 最近一季营收', scope_of([A, M]), steps, seen, read_both(), coverage_with_unread(M))
    notes = reminders(seen, ABSENCE_MARK)
    assert len(notes) == 1 and reminders(seen) == []
    assert notes[0]['content'] == direct.ABSENCE_RECHECK_NOTE.format(unread='10-Q 2026-08-01', draft=direct.draft_quote(drafts[0]))
    assert len(drafts[0]) > direct.DRAFT_QUOTE_LIMIT and '（草稿后半已省略）' in notes[0]['content']
    assert not [k for k in turns[-1].audit if k.startswith('closing_complete')]


# ---- B13: sizes ----------------------------------------------------------------------------------------------------

def test_b13_the_ledger_and_the_draft_stay_within_their_limits():
    turn = turn_for(scope_of([f'S{i}' for i in range(5)]))
    labels = [f'FY{2020 + y} Q{q}' for y in range(4) for q in range(1, 5)][:12]
    turn.figure_ledger = []
    for i in range(5):
        for k, label in enumerate(labels):
            end = f'{2020 + k // 4}-0{1 + k % 4}-28'
            turn.figure_ledger.append(entry(100 * i + k + 1, f'S{i}', label, end=end, value=f'{1000 + k:,} 百万美元'))
            turn.figure_ledger.append(entry(100 * i + k + 51, f'S{i}', label, metric='gross_profit', end=end, value=f'{5000 + k:,} 百万美元'))
    turn.calc_attempts = [attempt([(1, '1.0')], ok=False, unbound=unbound(1, '1.0', '1'))]
    draft = '未核算。' + ''.join(chr(0x4E00 + (i % 500)) for i in range(4000))
    found = turn.closing_complete_check(draft)
    assert len(found) == 5 and found[0]['kinds'].keys() == {'unfinished_calc', 'unused_rows'}
    ledger = turn.closing_ledger_text(found)
    assert len(ledger) <= direct.CLOSING_LEDGER_LIMIT and '（其余期间已省略）' in ledger
    note = direct.CLOSING_COMPLETE_NOTE.format(ledger=ledger, draft=direct.draft_quote(draft, direct.CLOSING_DRAFT_LIMIT))
    assert draft[:direct.CLOSING_DRAFT_LIMIT] in note and draft[:direct.CLOSING_DRAFT_LIMIT + 1] not in note
    assert '（草稿后半已省略）' in note
    turn.arm_closing_complete(found, draft, merged=False)
    assert len(turn.audit['closing_complete_draft']) == 2000


def test_the_reminder_states_only_what_holds_for_every_item():
    head = direct.CLOSING_COMPLETE_NOTE_BODY.split('\n', 1)[0]
    assert head == ('系统事实：用户点名的公司里，有的已读数没有用上，有的用来做的计算没成功、之后也没重算。'
                    '下面是这些公司本轮已读到的数，以及没做成的计算：')
    assert '有意不用的，照原样回答并写明原因即可' in direct.CLOSING_COMPLETE_NOTE
    assert '这些行若已不在你眼前的资料里，可以直接用上面的原值' in direct.CLOSING_COMPLETE_NOTE
    assert '你的草稿原文' not in direct.CLOSING_COMPLETE_NOTE_BODY and '你的草稿原文' in direct.CLOSING_COMPLETE_NOTE
