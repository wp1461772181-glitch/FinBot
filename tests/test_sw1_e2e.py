"""SW1 end to end (spec §8.3 E01, E02, E06): a scripted decider drives a real turn over the seeded test database.

Tools are the real ones (no executor): the receipts, the widening and the reminder are all read from what the tools
actually return. Only the model's decisions are scripted.
"""
import asyncio
import itertools
import json

import pytest

from app import agent_web_research
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext
from app.knowledge.runtime import research_context
from sw1_filings import CUTOFF, aapl_filings, drop, msft_filings, new_symbol, seed

NOTE_MARK = '系统事实：你的草稿说有资料没有取到'
_ids = itertools.count(1)


def calls(*items):
    return {'tool_calls': [{'id': f'call-{next(_ids)}', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}
                           for name, args in items]}


def text(content):
    return {'content': content}


def scripted(steps, seen):
    queue = list(steps)

    def decide(messages, tools):
        seen.append(messages)
        return queue.pop(0) if queue else text('')
    return decide


def run_turn(question, classifier, steps, seen):
    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: classifier, decider=scripted(steps, seen))
    with research_context('sw1-e2e-test', cutoff=CUTOFF):
        return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def tool_bodies(seen):
    """Every tool message the model was shown, parsed; each one once."""
    found = {}
    for messages in seen:
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'tool':
                found.setdefault(id(m), json.loads(m['content']))
    return list(found.values())


def reminders(seen):
    found = {id(m): m for messages in seen for m in messages if isinstance(m, dict) and m.get('role') == 'system'
             and str(m.get('content') or '').startswith(NOTE_MARK)}
    return list(found.values())


@pytest.fixture
def audits(monkeypatch):
    seen = []
    original = direct.Turn.finish

    def spy(self, *args, **kwargs):
        seen.append(dict(self.audit))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(direct.Turn, 'finish', spy)
    return seen


@pytest.fixture(autouse=True)
def switches_default(monkeypatch):
    for name in ('FINBOT_SW1_READ_WIDEN', 'FINBOT_SW1_ABSENCE_RECHECK', 'FINBOT_SW1_FRESHNESS', 'FINBOT_SW1_EXISTENCE_KNOWLEDGE'):
        monkeypatch.delenv(name, raising=False)


def test_e01_a_truncated_read_gets_a_look_and_the_wider_read_fills_the_quarters(audits):  # Q3 shape
    aapl, msft = new_symbol(), new_symbol()
    ids = seed(aapl, aapl_filings()) + seed(msft, msft_filings())
    question = f'{aapl} 和 {msft} 最近的营收'
    scope = {'category': 'A', 'mode': 'financials', 'symbol': aapl, 'symbols': [aapl, msft], 'days_back': None}
    seen = []
    try:
        result = run_turn(question, scope, [
            calls(('query_financials', {'symbol': aapl, 'latest': True, 'limit': 8}),
                  ('query_financials', {'symbol': msft, 'latest': True, 'limit': 8})),
            text(f'{aapl} 和 {msft} 只有年度数据，没有季度数据。'),
            calls(('query_financials', {'symbol': aapl, 'latest': True, 'limit': 40}),
                  ('query_financials', {'symbol': msft, 'latest': True, 'limit': 40})),
            text(f'{aapl} 与 {msft} 的季度数据已在本轮取到。'),
        ], seen)
        first = [b for b in tool_bodies(seen) if b.get('meta') or 'coverage' in b]
        assert first and all('coverage' in b for b in first[:2])
        assert len(reminders(seen)) == 1
        assert audits[-1]['absence_recheck_outcome'] == 'requeried'
        assert result['status'] == 'succeeded'
    finally:
        drop(ids)


def test_e02_a_form_filter_that_hides_the_newest_filing_brings_it_in_marked(audits):  # Q2 shape
    aapl = new_symbol()
    ids = seed(aapl, aapl_filings())
    question = f'{aapl} 的服务收入与毛利率'
    scope = {'category': 'A', 'mode': 'financials', 'symbol': aapl, 'symbols': [aapl], 'metrics': ['服务收入', '毛利率'],
             'form': '10-Q', 'days_back': None}
    seen = []
    try:
        run_turn(question, scope, [
            calls(('query_financials', {'symbol': aapl, 'form': '10-Q', 'latest': True})),
            text(f'{aapl} 的毛利率数据已取到。'),
        ], seen)
        bodies = tool_bodies(seen)
        assert any('newer_other_form' in json.dumps(b, ensure_ascii=False) for b in bodies)
        widened = [row for b in bodies for row in b.get('data', []) if isinstance(row, dict) and row.get('widened') == 'newer_other_form']
        assert widened and all(row['form'] == '10-K' for row in widened)
    finally:
        drop(ids)


def test_e06_the_library_behind_its_rhythm_is_said_in_the_receipt(audits):  # Q1 shape
    msft = new_symbol()
    ids = seed(msft, msft_filings())
    question = f'{msft} 最新一季营收'
    scope = {'category': 'A', 'mode': 'financials', 'symbol': msft, 'symbols': [msft], 'metrics': ['营收'], 'days_back': None}
    seen = []
    try:
        run_turn(question, scope, [text(f'{msft} 的营收已在本轮取到。')], seen)
        # The figure pre-read is injected as evidence, not a model tool call, so the receipt is read from what the model saw.
        shown = ' '.join(str(m.get('content') or '') for messages in seen for m in messages if isinstance(m, dict))
        assert '"freshness"' in shown and '"overdue": true' in shown and 'FY2027 Q1' in shown
    finally:
        drop(ids)


# E04 and E05 (spec §8.3, Q22 shape).  The two searches come back empty from the real tools; the refusal model is the
# only fake, and it keeps a general-knowledge sentence only when the facts it is given carry the draft that said it.

DRAFT_PRIVATE = '据我所知，Twitter 已于 2022 年被私有化，之后不再披露季度财报，这同样是背景判断。'
PRIVATE_REPLY = 'Twitter 于 2022 年被私有化，此后不再公开季报（一般知识，未经本轮资料核实）。'
NEWS = '新闻与网页'
FINANCIAL = '财报与SEC'
COMPOUND_MARK = '系统事实：本轮你查询的来源都没有取得可用资料'   # FP9's note (NOTE_MARK above is the absence recheck's)


def refusal_reads_facts(monkeypatch, facts_seen):
    async def fake(provider, model, key, messages, schemas, base_url=None):
        if 'gathered no usable evidence' not in str(messages[0].get('content')):
            return {}, {'role': 'assistant', 'content': ''}
        facts = json.loads(messages[1]['content'][len('facts: '):])
        facts_seen.append(facts)
        reply = PRIVATE_REPLY if '私有化' in facts.get('model_draft', '') else '没有可核验资料。'
        decision = {'useful': False, 'reply': reply, 'reason': '缺少公司披露状态', 'route': 'insufficient_evidence'}
        return {}, {'role': 'assistant', 'content': json.dumps(decision, ensure_ascii=False)}
    monkeypatch.setattr(direct, 'decision_request', fake)


def test_e04_a_draft_naming_a_private_company_is_given_back_and_kept_through_the_refusal(monkeypatch):  # Q22 shape
    symbol = new_symbol()
    ids = seed(symbol, [])                      # no filings for this company: the two searches really come back empty
    facts_seen = []
    refusal_reads_facts(monkeypatch, facts_seen)
    question = f'{symbol} 的季度财报还在披露吗？'
    scope = {'category': 'A', 'mode': 'none', 'symbol': symbol, 'symbols': [symbol], 'load_hint': [NEWS, FINANCIAL], 'days_back': None}
    seen = []
    try:
        result = run_turn(question, scope, [
            calls(('query_financials', {'symbol': symbol, 'metrics': ['revenue']}),
                  ('query_sec_filings', {'symbol': symbol, 'form': '10-Q'})),
            text(DRAFT_PRIVATE),
            text(DRAFT_PRIVATE),
        ], seen)
    finally:
        drop(ids)
    notes = [m['content'] for messages in seen for m in messages
             if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(COMPOUND_MARK)]
    assert len(notes) == 1 and DRAFT_PRIVATE in notes[0]         # the draft came back with the note
    assert facts_seen[-1]['model_draft'] == DRAFT_PRIVATE         # and the refusal was handed it
    assert '私有化' in result['answer'] and '一般知识' in result['answer']
    assert result['audit']['compound_empty_noted'] is True


def test_e05_an_empty_web_search_after_the_note_still_hands_the_draft_to_the_refusal(monkeypatch):  # Q22 zero-evidence variant
    symbol = new_symbol()
    ids = seed(symbol, [])
    facts_seen = []
    refusal_reads_facts(monkeypatch, facts_seen)

    async def nothing_found(*args, **kwargs):
        return {'ok': True, 'data': [], 'source': 'public web research', 'as_of': None}
    monkeypatch.setattr(agent_web_research, '_research', nothing_found)   # the public search is stubbed: no network

    question = f'{symbol} 的季度财报还在披露吗？'
    scope = {'category': 'A', 'mode': 'none', 'symbol': symbol, 'symbols': [symbol], 'load_hint': [NEWS, FINANCIAL], 'days_back': None}
    seen = []
    try:
        result = run_turn(question, scope, [
            calls(('query_financials', {'symbol': symbol, 'metrics': ['revenue']}),
                  ('query_sec_filings', {'symbol': symbol, 'form': '10-Q'})),
            text(DRAFT_PRIVATE),
            calls(('web_research', {'query': f'{symbol} 是否仍披露季报'})),
            text(DRAFT_PRIVATE),
        ], seen)
    finally:
        drop(ids)
    assert facts_seen[-1]['public_search'] == 'empty'
    assert facts_seen[-1]['model_draft'] == DRAFT_PRIVATE
    assert '私有化' in result['answer'] and '一般知识' in result['answer']
    assert result['audit']['compound_empty_noted'] is True
