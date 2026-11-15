"""SW1 §2.6: a closing draft that calls the library empty, while a coverage receipt lists filings this turn never read,
is shown those filings once and may keep its draft (spec T17–T21).

The executor is a scripted fake that returns receipts; no database is touched here.
"""
import asyncio
import itertools
import json

import pytest

from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

SWITCH = 'FINBOT_SW1_ABSENCE_RECHECK'
NOTE_MARK = '系统事实：你的草稿说有资料没有取到'
GAP_DRAFT = 'MSFT 只有年度数据，没有季度数据 [1]。'
PLAIN_DRAFT = 'MSFT 最新一期营收见 [1]。'
_ids = itertools.count(1)

ROW = {'source_id': 'f1', 'symbol': 'MSFT', 'form': '10-K', 'source_type': 'reported_figure', 'metric': 'revenue',
       'filed_at': '2026-07-29', 'title': 'MSFT 10-K 2026-07-29 · 营业收入 FY2026',
       'period_label': 'FY2026（2025-07-01 至 2026-06-30）', 'excerpt': '营业收入（Revenue）FY2026：331,839,000,000 USD。'}
QUARTER = {**ROW, 'source_id': 'f2', 'form': '10-Q', 'filed_at': '2026-04-29', 'period_label': 'FY2026 Q3（2026-01-01 至 2026-03-31，3 个月）',
           'excerpt': '营业收入（Revenue）FY2026 Q3：38,398,000,000 USD。'}


def receipt(not_read=(), periods_left_out=()):
    """A financial read's outcome, with the coverage receipt the tool now attaches."""
    coverage = {'filters': {'latest': True, 'limit': 8}, 'filings_read': [{'form': '10-K', 'filed_at': '2026-07-29', 'period': 'FY2026'}],
                'not_read': [dict(n) for n in not_read], 'rows_left_out_by_limit': len(periods_left_out),
                'periods_left_out': list(periods_left_out), 'widened': []}
    return {'ok': True, 'data': [dict(ROW)], 'source': 'fake', 'meta': {'coverage': coverage}}


def quarter_read():
    coverage = {'filters': {'latest': True, 'limit': 40}, 'filings_read': [{'form': '10-Q', 'filed_at': '2026-04-29', 'period': 'FY2026 Q3'}],
                'not_read': [], 'rows_left_out_by_limit': 0, 'periods_left_out': [], 'widened': []}
    return {'ok': True, 'data': [dict(QUARTER)], 'source': 'fake', 'meta': {'coverage': coverage}}


UNREAD_10Q = {'form': '10-Q', 'filed_at': '2026-04-29', 'period': None, 'why': 'form_filter'}


@pytest.fixture(autouse=True)
def switch_on(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


@pytest.fixture
def audits(monkeypatch):
    """The audit each turn ends with: run_direct_turn does not return it."""
    seen = []
    original = direct.Turn.finish

    def spy(self, *args, **kwargs):
        seen.append(dict(self.audit))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(direct.Turn, 'finish', spy)
    return seen


def call(name, **args):
    return {'tool_calls': [{'id': f'call-{next(_ids)}', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}


def text(content):
    return {'content': content}


def scripted(steps, seen):
    queue = list(steps)

    def decide(messages, tools):
        seen.append(messages)
        return queue.pop(0) if queue else text('')
    return decide


def run_turn(steps, outcomes, seen):
    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              classifier=lambda _: {'category': 'A', 'mode': 'financials', 'symbol': 'MSFT', 'symbols': ['MSFT'], 'days_back': None},
                              decider=scripted(steps, seen), executor=lambda name, args: outcomes.pop(0))
    return asyncio.run(direct.run_direct_turn('MSFT 最近一期营收是多少', ctx, emit=emit))


def notes(seen):
    """The reminders the model was shown, each counted once: the protocol carries one message through later steps."""
    found = {id(m): m for messages in seen for m in messages if isinstance(m, dict) and m.get('role') == 'system'
             and str(m.get('content') or '').startswith(NOTE_MARK)}
    return list(found.values())


def read_step(**extra):
    return call('query_financials', symbol='MSFT', metrics=['revenue'], latest=True, **extra)


def test_a_gap_draft_with_unread_filings_gets_one_look_and_the_next_read_settles_it(audits):
    seen = []
    run_turn([read_step(), text(GAP_DRAFT), read_step(limit=40), text(PLAIN_DRAFT)],
             [receipt(not_read=[UNREAD_10Q]), quarter_read()], seen)
    assert len(notes(seen)) == 1
    reminder = notes(seen)[0]['content']
    assert '10-Q 2026-04-29' in reminder and GAP_DRAFT in reminder
    assert audits[-1]['absence_recheck_noted'] is True and audits[-1]['absence_recheck_outcome'] == 'requeried'
    assert audits[-1]['absence_recheck_draft'] == GAP_DRAFT


def test_a_gap_draft_with_nothing_unread_is_not_questioned(audits):
    seen = []
    run_turn([read_step(), text(GAP_DRAFT)], [receipt(not_read=[])], seen)
    assert notes(seen) == [] and not audits[-1].get('absence_recheck_noted')


def test_an_unread_filing_is_not_questioned_when_the_draft_claims_no_gap(audits):
    seen = []
    run_turn([read_step(), text(PLAIN_DRAFT)], [receipt(not_read=[UNREAD_10Q])], seen)
    assert notes(seen) == [] and not audits[-1].get('absence_recheck_noted')


def test_the_switch_off_restores_the_plain_close(audits, monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    seen = []
    run_turn([read_step(), text(GAP_DRAFT)], [receipt(not_read=[UNREAD_10Q])], seen)
    assert notes(seen) == [] and not audits[-1].get('absence_recheck_noted')


def test_a_second_gap_draft_is_kept_without_a_second_look(audits):
    seen = []
    result = run_turn([read_step(), text(GAP_DRAFT), text(GAP_DRAFT)], [receipt(not_read=[UNREAD_10Q])], seen)
    assert len(notes(seen)) == 1                       # the note did not come a second time
    assert audits[-1]['absence_recheck_outcome'] == 'kept'
    assert result['status'] == 'succeeded' and '只有年度数据' in result['answer']


def test_unread_entries_listed_by_a_later_read_are_settled_and_old_ones_are_not_gaps():
    turn = direct.Turn.__new__(direct.Turn)
    turn.coverage_log = [
        {'name': 'query_financials', 'coverage': {'not_read': [UNREAD_10Q], 'periods_left_out': []},
         'read_filings': {('10-K', '2026-07-29')}, 'read_labels': set()},
        {'name': 'query_financials', 'coverage': {'not_read': [], 'periods_left_out': []},
         'read_filings': {('10-Q', '2026-04-29')}, 'read_labels': set()},
    ]
    assert turn.unread_gap() == []
    turn.coverage_log[1]['read_filings'] = set()
    assert turn.unread_gap() == ['10-Q 2026-04-29']
    turn.coverage_log = [
        {'name': 'query_financials', 'coverage': {'not_read': [{'form': '10-Q', 'filed_at': '2019-04-30', 'period': None, 'why': 'limit'}],
                                                  'periods_left_out': ['FY2018 Q1（2017-10-01 至 2017-12-31，3 个月）']},
         'read_filings': {('10-K', '2026-07-29')}, 'read_labels': set()},
    ]
    assert turn.unread_gap() == []


def test_a_period_left_out_by_limit_is_settled_by_a_later_read_of_that_label():
    turn = direct.Turn.__new__(direct.Turn)
    label = 'FY2026 Q1（2025-09-28 至 2025-12-27，3 个月）'
    turn.coverage_log = [
        {'name': 'query_financials', 'coverage': {'not_read': [], 'periods_left_out': [label]},
         'read_filings': {('10-K', '2026-11-03')}, 'read_labels': set()},
    ]
    assert turn.unread_gap() == [label]
    turn.coverage_log.append({'name': 'query_financials', 'coverage': {'not_read': [], 'periods_left_out': []},
                              'read_filings': {('10-Q', '2026-01-31')}, 'read_labels': {label}})
    assert turn.unread_gap() == []
