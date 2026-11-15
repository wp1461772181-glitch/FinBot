"""SW1B end to end (spec-sw1b §4.3 E01–E04, E01b): run_direct_turn with a scripted decider.

E01, E01b, E02 and E03 run the real query_financials tool over seeded filings (the test database); only the model's
decisions are scripted. E04 uses a fake executor with random codes (its companies are not in the database and it needs no figures).
"""
import asyncio
import json

import pytest

from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings, drop, msft_filings, new_symbol, seed
from test_sw1b_closing_complete import ABSENCE_MARK, call, calls, cite, reminders, rows_of, scripted, text

SWITCH = 'FINBOT_SW1B_CLOSING_COMPLETE'


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
            text_ = m['content']
            for observation in json.loads(text_[text_.index('[{'):]):
                if observation.get('name') == 'calculate':
                    found = int(observation['result']['data'][0]['citation'][1:-1])
    return found


def run_real(question, scope, steps, seen):
    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: scope, decider=scripted(steps, seen))
    with research_context('sw1b-e2e-test', cutoff=CUTOFF):
        return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


@pytest.fixture(autouse=True)
def switches_default(monkeypatch):
    for name in (SWITCH, 'FINBOT_SW1B_SAMPLE_AGGREGATE', 'FINBOT_SW1_READ_WIDEN', 'FINBOT_SW1_ABSENCE_RECHECK',
                 'FINBOT_SW1_FRESHNESS', 'FINBOT_SW1_EXISTENCE_KNOWLEDGE'):
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


def q3_draft(messages, msft, aapl, closing):
    return text(f'{msft} 的 Q3 营收 38,398 百万美元 [{cite(messages, msft, "revenue", "FY2026 Q3")}]，{closing}'
                f'{aapl} 的 Q3 营收 94,000 百万美元 [{cite(messages, aapl, "revenue", "FY2026 Q3")}]。')


def test_e01_the_q3_shape_gets_one_reminder_with_the_values_and_the_redo_binds(audits, monkeypatch):
    aapl, msft = new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [aapl, msft], 'days_back': None}

    def failing(messages):
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '331.839', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026')},
            {'name': 'b', 'value': '114.634', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026 前三季度累计')}])

    def redo(messages):
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '331839', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026')},
            {'name': 'b', 'value': '114634', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026 前三季度累计')}])

    seen = []
    try:
        steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                       ('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40})),
                 failing,
                 lambda messages: q3_draft(messages, msft, aapl, f'{msft} 的 Q4 和 Q1 本轮未核算；'),
                 redo,
                 lambda messages: text(f'{msft} 的 Q4 为 [{last_calc_cite(messages)}]，Q3 见上文。')]
        result = run_real(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen)
        assert result['status'] == 'succeeded'
        notes = reminders(seen)
        assert len(notes) == 1
        assert '331,839 百万美元' in notes[0]['content'] and '114,634 百万美元' in notes[0]['content']
        assert '最接近的是' not in notes[0]['content']
        audit = turns_last(audits).audit
        assert audit['closing_complete_outcome'] == 'requeried'
        assert [(item['symbol'], item['kind']) for item in audit['closing_complete_symbols']] == [(msft, 'unfinished_calc')]
        redone = turns_last(audits).calc_attempts[-1]
        assert redone['ok'] is True and [i['value'] for i in redone['inputs']] == ['331839', '114634']
    finally:
        drop(ids)


def turns_last(audits):
    return audits[-1]


def test_e01b_when_the_read_is_evicted_the_reminder_carries_the_values_and_the_redo_binds(audits):
    aapl, msft = new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [aapl, msft], 'days_back': None}
    saved, evicted = {}, []

    def remember(messages):
        saved.update(fy=cite(messages, msft, 'revenue', 'FY2026'), nine=cite(messages, msft, 'revenue', 'FY2026 前三季度累计'),
                     aq3=cite(messages, aapl, 'revenue', 'FY2026 Q3'), mq3=cite(messages, msft, 'revenue', 'FY2026 Q3'))
        # Ten more reads push the MSFT read out of the evidence the model is shown (more than ten observations).
        return calls(*[('query_financials', {'symbol': aapl, 'latest': True, 'limit': k}) for k in range(1, 11)])

    def premise(messages):
        evicted.append(not present(messages, msft, 'revenue', 'FY2026'))
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '331.839', 'source_ordinal': saved['fy']},
            {'name': 'b', 'value': '114.634', 'source_ordinal': saved['nine']}])

    seen = []
    try:
        steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                       ('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40})),
                 remember,
                 premise,
                 lambda messages: text(f'{msft} 的 Q4 与 Q1 本轮未核算；Q3 见 [{saved["mq3"]}]，{aapl} 的 Q3 见 [{saved["aq3"]}]。'),
                 lambda messages: call('calculate', expression='a-b', inputs=[
                     {'name': 'a', 'value': '331839', 'source_ordinal': saved['fy']},
                     {'name': 'b', 'value': '114634', 'source_ordinal': saved['nine']}]),
                 lambda messages: text(f'{msft} 的 Q4 为 [{last_calc_cite(messages)}]。')]
        result = run_real(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen)
        assert result['status'] == 'succeeded' and evicted == [True]
        notes = reminders(seen)
        assert len(notes) == 1 and '331,839 百万美元' in notes[0]['content'] and '114,634 百万美元' in notes[0]['content']
        assert '最接近的是' not in notes[0]['content']
        turn = turns_last(audits)
        assert turn.audit['closing_complete_outcome'] == 'requeried'
        assert turn.calc_attempts[-1]['ok'] is True
    finally:
        drop(ids)


def test_e02_a_read_that_is_fully_used_gets_no_reminder_and_the_same_steps_as_switch_off(audits, monkeypatch):
    def run(switch):
        monkeypatch.setenv(SWITCH, switch)
        aapl, msft = new_symbol(), new_symbol()
        ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
        scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [aapl, msft], 'days_back': None}

        def redo(messages):
            return call('calculate', expression='a-b', inputs=[
                {'name': 'a', 'value': '331839', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026')},
                {'name': 'b', 'value': '114634', 'source_ordinal': cite(messages, msft, 'revenue', 'FY2026 前三季度累计')}])
        seen = []
        try:
            steps = [calls(('query_financials', {'symbol': msft, 'latest': True, 'limit': 40}),
                           ('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40})),
                     redo,
                     lambda messages: text(f'{msft} 的 Q4 为 [{last_calc_cite(messages)}]；'
                                           f'{msft} 的 Q3 [{cite(messages, msft, "revenue", "FY2026 Q3")}]，'
                                           f'{aapl} 的 Q3 [{cite(messages, aapl, "revenue", "FY2026 Q3")}]。')]
            run_real(f'{aapl} 与 {msft} 最近一季营收', scope, steps, seen)
            return turns_last(audits).audit['decision_steps'], reminders(seen), turns_last(audits).audit
        finally:
            drop(ids)
    on_steps, on_notes, on_audit = run('on')
    off_steps, off_notes, _ = run('off')
    assert on_notes == [] and off_notes == []
    assert on_steps == off_steps
    assert 'closing_complete_noted' not in on_audit


def test_e03_a_single_company_redone_under_another_source_ordinal_with_the_same_value_gets_no_reminder(audits):
    aapl = new_symbol()
    ids = seed(aapl, aapl_filings())
    scope = {'category': 'A', 'mode': 'financials', 'symbol': aapl, 'symbols': [aapl], 'days_back': None}

    def wrong_ordinal(messages):
        # The nine-month figure written against the annual row: unbound; the Q3 input is right.
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '364357', 'source_ordinal': cite(messages, aapl, 'revenue', 'FY2026')},
            {'name': 'b', 'value': '94000', 'source_ordinal': cite(messages, aapl, 'revenue', 'FY2026 Q3')}])

    def right_ordinal(messages):
        return call('calculate', expression='a-b', inputs=[
            {'name': 'a', 'value': '364357', 'source_ordinal': cite(messages, aapl, 'revenue', 'FY2026 前三季度累计')},
            {'name': 'b', 'value': '94000', 'source_ordinal': cite(messages, aapl, 'revenue', 'FY2026 Q3')}])
    seen = []
    try:
        steps = [call('query_financials', symbol=aapl, latest=True, limit=40), wrong_ordinal, right_ordinal,
                 lambda messages: text(f'{aapl} 的 Q4 为 [{last_calc_cite(messages)}]；Q1 本轮未核算。')]
        result = run_real(f'{aapl} 最近一季营收', scope, steps, seen)
        assert result['status'] == 'succeeded'
        assert reminders(seen) == []
        assert 'closing_complete_noted' not in turns_last(audits).audit
    finally:
        drop(ids)


def test_e04_an_industry_question_with_no_named_company_gets_the_permission_and_no_reminder(audits):
    from test_sw1b_closing_complete import run_turn as run_fake
    intc, nvda, amd = new_symbol(), new_symbol(), new_symbol()
    scope = {'category': 'A', 'mode': 'financials', 'symbol': None, 'symbols': [], 'days_back': None}
    rows = {intc: rows_of(intc, aapl_filings()), nvda: rows_of(nvda, msft_filings()), amd: rows_of(amd, msft_filings())}
    seen = []
    steps = [calls(('query_financials', {'symbol': intc, 'latest': True, 'limit': 4}),
                   ('query_financials', {'symbol': nvda, 'latest': True, 'limit': 4}),
                   ('query_financials', {'symbol': amd, 'latest': True, 'limit': 4})),
             text('无法计算行业增速：库里没有覆盖整个行业的数。')]
    run_fake('半导体行业整体营收增速是多少', scope, steps, seen, rows)
    instruction = seen[0][0]['content']
    assert direct.SAMPLE_AGGREGATE_SENTENCE in instruction
    assert reminders(seen) == [] and reminders(seen, ABSENCE_MARK) == []
    assert 'closing_complete_noted' not in turns_last(audits).audit
