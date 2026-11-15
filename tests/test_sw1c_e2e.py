"""SW1C end to end (spec-sw1c §6.2, E1–E4): run_direct_turn with a scripted decider over the real query_financials tool and the
test database. Symbols are random (new_symbol) as in test_sw1b_e2e; the cross-tree comparison (U6, K3) runs outside pytest.

Checks made inside a scripted step are recorded and asserted after the turn: a failing assertion inside the decider is not a test
failure by itself.
"""
import asyncio
import json
import re
from datetime import date, timedelta

import pytest

from app.agent_workflow import direct, evidence
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings, drop, figure, msft_filings, new_symbol, nvda_filings, p, seed
from test_sw1b_closing_complete import call, calls, cite, reminders, scripted, text

SWITCH = 'FINBOT_SW1C_OMITTED_DIGEST'
SWITCHES = (SWITCH, 'FINBOT_SW1B_CLOSING_COMPLETE', 'FINBOT_SW1B_SAMPLE_AGGREGATE', 'FINBOT_SW1_READ_WIDEN',
            'FINBOT_SW1_ABSENCE_RECHECK', 'FINBOT_SW1_FRESHNESS', 'FINBOT_SW1_EXISTENCE_KNOWLEDGE', 'FINBOT_SW1_RESOLVER_RULES')


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


# ---- helpers ----------------------------------------------------------------------------------------------------------

def present(messages, symbol, metric, label):
    try:
        cite(messages, symbol, metric, label)
        return True
    except AssertionError:
        return False


def last_calc_cite(messages):
    """The [n] of the latest calculate result the model was shown."""
    found = None
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith('Accepted evidence DATA'):
            for observation in json.loads(m['content'][m['content'].index('[{'):]):
                if observation.get('name') == 'calculate':
                    found = int(observation['result']['data'][0]['citation'][1:-1])
    return found


def data_symbols(messages):
    """The symbols of every row the DATA message shows."""
    symbols = set()
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith('Accepted evidence DATA'):
            for observation in json.loads(m['content'][m['content'].index('[{'):]):
                for row in (observation.get('result') or {}).get('data') or []:
                    if isinstance(row, dict) and row.get('symbol'):
                        symbols.add(row['symbol'])
    return symbols


def digest_of(messages):
    """The omitted-readings digest the model was shown, or None."""
    for m in messages:
        if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(direct.OMITTED_DIGEST_HEAD):
            return m['content']
    return None


def ledger_line(digest, ordinal):
    prefix = f'[{ordinal}] '
    return next(line for line in digest.split('\n') if line.startswith(prefix))


def ledger_value(digest, ordinal):
    """What the ledger gives for one number, as written: '331,839 百万美元' for a figure, '77,673.00' for a calculate result."""
    line = ledger_line(digest, ordinal)
    if '计算结果 ' in line:
        return line.split('计算结果 ', 1)[1].split('（')[0]
    return ' '.join(line.split(' ')[-2:])


def plain(value):
    """The number a calculate input takes from the ledger: no commas, no unit."""
    return value.replace(' 百万美元', '').replace(' USD', '').replace(',', '')


def run_turn_with(question, scope, steps, seen, tools_seen=None, answerer=None):
    async def emit(_):
        pass

    inner = scripted(steps, seen)                 # one queue for the whole turn

    def decider(messages, tools):
        if tools_seen is not None:
            tools_seen.append(len(tools or []))
        return inner(messages, tools)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope, decider=decider, answerer=answerer)
    with research_context('sw1c-e2e-test', cutoff=CUTOFF):
        return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def wide_filings(n):
    """n quarterly 10-Qs with one revenue quarter each: a company with enough rows to fill the evidence budget."""
    out, start = [], date(2021, 1, 1)
    for i in range(n):
        q_start = start + timedelta(days=91 * i)
        q_end = q_start + timedelta(days=89)
        out.append({'form': '10-Q', 'filed': q_end + timedelta(days=35),
                    'figures': [figure('revenue', 'Revenue', [p(q_start.isoformat(), q_end.isoformat(), (10 + i) * 10 ** 9,
                                                              q_start.year, f'Q{(q_start.month - 1) // 3 + 1}')])]})
    return out


def q3_two_scope(*symbols):
    return {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': list(symbols), 'days_back': None}


# ---- E1: the Q3#2 reproduction (K1 binding check, K2 no reminder) -----------------------------------------------------

def test_e1_the_omitted_numbers_bind_and_the_calculations_go_through(audits):
    aapl, msft, x1, x2, x3 = new_symbol(), new_symbol(), new_symbol(), new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    ids += seed(x1, nvda_filings()) + seed(x2, nvda_filings()) + seed(x3, nvda_filings())
    scope = q3_two_scope(aapl, msft, x1, x2, x3)
    xs = [x1, x2, x3]
    saved, checks = {}, {}

    def read_others(messages):
        return calls(*[('query_financials', {'symbol': x, 'latest': True, 'limit': 40}) for x in xs])

    def remember_first(messages):
        saved.update(fy=cite(messages, msft, 'revenue', 'FY2026'), nine=cite(messages, msft, 'revenue', 'FY2026 前三季度累计'),
                     aq3=cite(messages, aapl, 'revenue', 'FY2026 Q3'), mq3=cite(messages, msft, 'revenue', 'FY2026 Q3'))
        return read_others(messages)

    def first_calc(messages):
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '331839', 'source_ordinal': saved['fy']},
            {'name': 'b', 'value': '114634', 'source_ordinal': saved['nine']}])

    def ten_more_calcs(messages):
        # The x rows are still in the DATA here: record their numbers, then push the first reads out of the last ten.
        for x in xs:
            saved[x] = cite(messages, x, 'revenue', 'FY2026 Q3')
        saved['q4'] = last_calc_cite(messages)
        # Ten different differences (company x ordered pair of quarters): identical calls would count as no progress.
        quarters = {'FY2026 Q3': 57000, 'FY2026 Q4': 68000, 'FY2027 Q1': 44000, 'FY2027 Q2': 46000}
        ords = {(x, q): cite(messages, x, 'revenue', q) for x in xs for q in quarters}
        combos = [(x, a, b) for a in quarters for b in quarters if a != b for x in xs][:10]
        return calls(*[('calculate', {'expression': 'a-b', 'inputs': [
            {'name': 'a', 'value': str(quarters[a]), 'source_ordinal': ords[(x, a)]},
            {'name': 'b', 'value': str(quarters[b]), 'source_ordinal': ords[(x, b)]}]}) for x, a, b in combos])

    def premise(messages):
        checks['evicted'] = (not present(messages, msft, 'revenue', 'FY2026 Q3'), not present(messages, aapl, 'revenue', 'FY2026 Q3'))
        digest = digest_of(messages)
        if digest is None:
            return text('')
        fy, nine = plain(ledger_value(digest, saved['fy'])), plain(ledger_value(digest, saved['nine']))
        mq3 = plain(ledger_value(digest, saved['mq3']))
        return calls(
            ('calculate', {'expression': 'a-b', 'inputs': [
                {'name': 'a', 'value': fy, 'source_ordinal': saved['fy']},
                {'name': 'b', 'value': nine, 'source_ordinal': saved['nine']}]}),
            ('calculate', {'expression': '(a-b)/b*100', 'inputs': [
                {'name': 'a', 'value': plain(ledger_value(digest, saved['q4'])), 'source_ordinal': saved['q4']},
                {'name': 'b', 'value': mq3, 'source_ordinal': saved['mq3']}]}))

    def final(messages):
        digest = digest_of(messages)
        ends = [f'{msft} FY2026 Q3 营收 {ledger_value(digest, saved["mq3"])} [{saved["mq3"]}]，'
                f'Q4 {ledger_value(digest, saved["q4"])} [{saved["q4"]}]；'
                f'{aapl} FY2026 Q3 营收 {ledger_value(digest, saved["aq3"])} [{saved["aq3"]}]。']
        ends += [f'{x} FY2026 Q3 营收 {ledger_value(digest, saved[x])} [{saved[x]}]。' for x in xs]
        checks['final'] = ''.join(ends)
        return text(checks['final'])

    steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                   ('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40})),
             remember_first, first_calc, ten_more_calcs, premise, final]
    seen = []
    try:
        result = run_turn_with(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen)
        turn = audits[-1]
        audit = turn.audit
        assert result['status'] == 'succeeded'
        assert checks.get('evicted') == (True, True), checks.get('evicted')           # precondition: both first reads are out
        assert result['answer'] == checks['final']                                    # the scripted text, unchanged
        assert 'closing_complete_noted' not in audit and 'absence_recheck_noted' not in audit   # K2 precondition
        assert audit['scope']['counts']['marked_figures'] >= 3                         # the numbered sentences were written
        assert audit['omitted_digest']['symbols'][:2] == [aapl, msft]
        assert all(attempt['ok'] for attempt in turn.calc_attempts)                  # §3.2 (3): no calculation came back unbound
        # §3.2 (1), by the checker itself (K1): the answer's figures bind to the turn's citations, and the
        # sentences that cite the omitted numbers are not rejected or insufficient.
        from app.agent_workflow.evidence import insufficient_number_values, number_review, unsupported_number_values
        user = turn.user_stated_text()
        final_answer = result['answer']
        assert unsupported_number_values(final_answer, turn.citations, user_text=user) == []
        assert insufficient_number_values(final_answer, turn.citations, user_text=user) == []
        omitted = {saved['mq3'], saved['aq3'], saved['q4'], *(saved[x] for x in xs)}
        reviews = number_review(final_answer, turn.citations, user_text=user)
        checked = 0
        for passage, review in zip(evidence._passages(final_answer), reviews):
            if any(f'[{number}]' in passage for number in omitted):
                checked += 1
                assert review['rejected'] == [] and review['insufficient'] == [], passage
        assert checked >= 4                                                          # the five sentences that cite them were checked
    finally:
        drop(ids)


# ---- E2: the Q3#3 shape: a decision step that still has tools sees the ledger ------------------------------------------

def test_e2_a_decision_step_with_tools_left_sees_the_ledger_for_the_first_two_reads(audits):
    aapl, msft, x1, x2, x3 = new_symbol(), new_symbol(), new_symbol(), new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    ids += seed(x1, wide_filings(20)) + seed(x2, wide_filings(20)) + seed(x3, wide_filings(20))
    scope = q3_two_scope(aapl, msft, x1, x2, x3)
    seen, tools_seen = [], []
    steps = [calls(*[('query_financials', {'symbol': s, 'latest': True, 'limit': 40}) for s in (aapl, msft, x1, x2, x3)]),
             call('query_financials', symbol=x3, latest=True, limit=1),
             lambda messages: text('占位')]
    try:
        run_turn_with(f'{aapl} {msft} {x1} {x2} {x3} 最近一季营收', scope, steps, seen, tools_seen)
        turn = audits[-1]
        assert len(seen) >= 3 and tools_seen[2] > 0                                  # step 3 is a decision with tools
        step3 = seen[2]
        assert not {aapl, msft} & data_symbols(step3)                                # the first two reads are out of the DATA
        digest = digest_of(step3)
        assert digest is not None
        listed = {line.split(' ')[1] for line in digest.split('\n')[1:] if re.match(r'\[\d+\] ', line)}
        assert {aapl, msft} <= listed
        assert 'omitted_digest' in turn.audit
    finally:
        drop(ids)


# ---- E3: the closing step (no tools) carries the ledger too ------------------------------------------------------------

def test_e3_the_closing_step_gets_the_ledger_and_no_protocol(audits, monkeypatch):
    monkeypatch.setattr(direct, 'CLOSING_AFTER_SECONDS', 0)
    aapl, msft = new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    scope = q3_two_scope(aapl, msft)
    captured, seen = [], []
    steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                   *[('query_financials', {'symbol': aapl, 'latest': True, 'limit': k}) for k in range(1, 11)])]

    def capture(messages):
        captured.append(messages)
        return '收尾回答'
    try:
        run_turn_with(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen, answerer=capture)
        turn = audits[-1]
        assert turn.audit['stop_reason'] == 'soft_time_budget_closing'
        assert len(captured) == 1
        messages = captured[0]
        assert not any(isinstance(m, dict) and m.get('role') == 'tool' for m in messages)   # no protocol batches
        digest = digest_of(messages)
        assert digest is not None
        assert any(line.split(' ')[1] == msft for line in digest.split('\n')[1:] if re.match(r'\[\d+\] ', line))
    finally:
        drop(ids)


# ---- E4: the B1 C1 shape with and without the digest: the same reminder and the same steps --------------------------

def test_e4_the_reminder_and_the_steps_are_the_same_with_the_digest_on_or_off(audits, monkeypatch):
    aapl, msft = new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    scope = q3_two_scope(aapl, msft)

    def run(switch):
        monkeypatch.setenv(SWITCH, switch)
        saved, evicted, seen = {}, [], []

        def remember(messages):
            saved.update(fy=cite(messages, msft, 'revenue', 'FY2026'), nine=cite(messages, msft, 'revenue', 'FY2026 前三季度累计'),
                         aq3=cite(messages, aapl, 'revenue', 'FY2026 Q3'), mq3=cite(messages, msft, 'revenue', 'FY2026 Q3'))
            return calls(*[('query_financials', {'symbol': aapl, 'latest': True, 'limit': k}) for k in range(1, 11)])

        def premise(messages):
            evicted.append(not present(messages, msft, 'revenue', 'FY2026'))
            return call('calculate', expression='a-b', inputs=[
                {'name': 'a', 'value': '331.839', 'source_ordinal': saved['fy']},
                {'name': 'b', 'value': '114.634', 'source_ordinal': saved['nine']}])
        steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                       ('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40})),
                 remember,
                 premise,
                 lambda messages: text(f'{msft} 的 Q4 与 Q1 本轮未核算；Q3 见 [{saved["mq3"]}]，{aapl} 的 Q3 见 [{saved["aq3"]}]。'),
                 lambda messages: call('calculate', expression='a-b', inputs=[
                     {'name': 'a', 'value': '331839', 'source_ordinal': saved['fy']},
                     {'name': 'b', 'value': '114634', 'source_ordinal': saved['nine']}]),
                 lambda messages: text(f'{msft} 的 Q4 为 [{last_calc_cite(messages)}]。')]
        result = run_turn_with(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen)
        turn = audits[-1]
        keys = ('closing_complete_noted', 'closing_complete_merged', 'closing_complete_symbols', 'closing_complete_outcome',
                'closing_complete_draft')
        return {'status': result['status'], 'evicted': evicted,
                'notes': [m['content'] for m in reminders(seen)],
                'audit': {k: turn.audit.get(k) for k in keys},
                'calc_attempts': turn.calc_attempts,
                'digest_steps': [i for i, messages in enumerate(seen) if digest_of(messages) is not None]}
    try:
        on = run('on')
        off = run('off')
        assert on['evicted'] == [True] and off['evicted'] == [True]
        assert on['status'] == off['status'] == 'succeeded'
        assert on['notes'] == off['notes'] and len(on['notes']) == 1
        assert on['audit'] == off['audit']
        assert on['calc_attempts'] == off['calc_attempts']
        assert on['digest_steps'] and off['digest_steps'] == []
    finally:
        drop(ids)
