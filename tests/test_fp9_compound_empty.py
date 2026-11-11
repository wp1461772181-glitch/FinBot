"""FP9: a turn whose searches all came back empty says what it searched, and does not call the absence real.

Helpers follow tests/test_agent_notools_governance.py.  Every model here is a scripted fake: the loop's decisions
come from ``scripted``, the refusal verdict from a monkeypatched ``decision_request``, tool results from the
executor lambda.  No test reaches the network.
"""
import asyncio, itertools, json

import pytest

from app.agent_workflow import direct, entities
from app.agent_workflow.state import AgentRuntimeContext
from app.database import engine
from app.knowledge.models import LowConfidenceQuestion

SWITCH = 'FINBOT_FP9_COMPOUND_EMPTY'
NOTE_MARK = '系统事实：本轮你查询的来源都没有取得可用资料'
FIXED_NOTICE = '没有可核验资料，无法确认本次请求中的事实。'
NEWS_CATEGORY = '新闻与网页'          # web_research's category; a classifier load_hint exposes it from the first call
_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def switch_default(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


@pytest.fixture(autouse=True)
def honest_refusal(monkeypatch):
    """Default refusal model: an honest reply.  Tests that need another reply override it."""
    refusal_fake, _ = refusal_model('库里没有这一天的收盘记录，请确认日期或股票代码。')
    monkeypatch.setattr(direct, 'decision_request', refusal_fake)


@pytest.fixture(autouse=True)
def question_pool_table():
    """The app creates its tables at startup, which these tests do not run; the question pool is the one they read."""
    LowConfidenceQuestion.__table__.create(bind=engine, checkfirst=True)


@pytest.fixture(autouse=True)
def verified_tickers(monkeypatch):
    """Tickers are tied to companies by SEC records in production; the test database has none."""
    monkeypatch.setattr(entities, 'verified_pair', lambda company, symbol: True)
    monkeypatch.setattr(entities, 'resolve_ticker', lambda _: None)
    monkeypatch.setattr(entities, 'sec_title', lambda _: None)


async def emit(_):
    pass


def call(name, **args):
    return {'tool_calls': [{'id': f'call-{next(_ids)}', 'function': {'name': name, 'arguments': json.dumps(args)}}]}


def text(content):
    return {'content': content}


def classify(**scope):
    value = {'category': 'A', 'mode': 'none', **scope}
    return lambda _: value


def scripted(steps, seen):
    """Decisions in order; once they run out the model says nothing.  Each call's messages are recorded."""
    queue = list(steps)

    def decide(messages, tools):
        seen.append(messages)
        return queue.pop(0) if queue else text('')
    return decide


def refusal_model(reply, reason='缺少日期或股票代码'):
    seen = []

    async def fake(provider, model, key, messages, schemas, base_url=None):
        # Only the refusal prompt is answered; the resolver and the other model calls get an empty reply.
        if 'gathered no usable evidence' not in str(messages[0].get('content')):
            return {}, {'role': 'assistant', 'content': ''}
        seen.append(messages)
        decision = {'useful': False, 'reply': reply, 'reason': reason, 'route': 'insufficient_evidence'}
        return {}, {'role': 'assistant', 'content': json.dumps(decision, ensure_ascii=False)}
    return fake, seen


def unusable_refusal_model():
    seen = []

    async def fake(provider, model, key, messages, schemas, base_url=None):
        if 'gathered no usable evidence' not in str(messages[0].get('content')):
            return {}, {'role': 'assistant', 'content': ''}
        seen.append(messages)
        return {}, {'role': 'assistant', 'content': 'not json at all'}
    return fake, seen


def carries(messages, mark):
    return sum(1 for m in messages if isinstance(m, dict) and mark in str(m.get('content') or ''))


def note_messages(seen):
    return [m for messages in seen for m in messages
            if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(NOTE_MARK)]


def run(question, ctx):
    return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def capture_feedback(monkeypatch):
    """The turn's feedback as it stands after each accept.  The turn's result does not carry it."""
    snapshots = []
    original = direct.Turn.accept

    def spy(self, name, args, outcome):
        original(self, name, args, outcome)
        snapshots.append(list(self.feedback))
    monkeypatch.setattr(direct.Turn, 'accept', spy)
    return snapshots


EMPTY = lambda n, a: {'ok': True, 'data': []}

# A two-search turn that finds nothing, then a draft: the case the note is for.
TWO_EMPTY_THEN_DRAFT = lambda: [call('query_stock_prices', symbol='AMD'),
                                call('query_stock_prices', symbol='AMD', limit=5),
                                text('AMD 收盘价为 100 美元 [1]。')]


def facts_of(refusal_seen):
    return refusal_seen[0][1]['content']


# 1. accept: the empty branch keeps every rejection reason and the row count, and the old keys do not change.

def test_empty_branch_keeps_every_rejection_reason_and_the_row_count(monkeypatch):
    snapshots = capture_feedback(monkeypatch)
    rows = [{'id': 'r1', 'symbol': 'MSFT', 'close': 100, 'trading_date': '2026-11-04'},
            {'id': 'r2', 'symbol': 'MSFT', 'close': 101, 'trading_date': '2026-11-04'},
            {'id': 'r3', 'symbol': 'AMD', 'close': 102, 'trading_date': '2026-11-04', 'fetch_error': True}]
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], []),
                              executor=lambda n, a: {'ok': True, 'data': rows})
    run('AMD 收盘价', ctx)
    fb = snapshots[-1][-1]
    assert fb['name'] == 'query_stock_prices'
    assert fb['rejected'] == {'requested_entity_missing': 2, 'invalid_source_body': 1}
    assert fb['rows_returned'] == 3
    # The old keys are unchanged: the status, and the first reason as the error code.
    assert fb['status'] == 'no_matching_evidence' and fb['error_code'] == 'requested_entity_missing'
    assert fb['ok'] is True and fb['data'] == [] and fb['items'] == []
    assert 'tool_status' not in fb


# 2. accept: a tool's own not_found status is kept, with the window it applied.

def test_tool_status_and_applied_window_survive_into_the_scope(monkeypatch):
    snapshots = capture_feedback(monkeypatch)
    outcome = {'ok': True, 'data': [], 'status': 'not_found', 'meta': {'applied_window_days': 7}}
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], []),
                              executor=lambda n, a: outcome)
    run('AMD 收盘价', ctx)
    assert snapshots[-1][-1]['tool_status'] == 'not_found'
    item = next(i for i in direct.search_scope(snapshots[-1]) if i['tool'] == 'query_stock_prices')
    assert item['window_days'] == 7 and item['tool_status'] == 'not_found' and item['outcome'] == 'empty'


# 3. search_scope and public_search_state: the five states, and a web_research beyond the 12-entry cap still counts.

def test_public_search_states_and_the_scope_cap():
    failed = {'name': 'web_research', 'ok': False, 'error_code': 'provider_timeout'}
    empty = {'name': 'web_research', 'ok': True, 'data': [], 'items': [], 'status': 'no_matching_evidence',
             'error_code': 'zero_evidence', 'meta': {}}
    unreadable = {'name': 'web_research', 'ok': True, 'data': [], 'items': [], 'status': 'no_matching_evidence',
                  'error_code': 'invalid_source_body', 'rejected': {'invalid_source_body': 2}, 'rows_returned': 2}
    found = {'name': 'web_research', 'ok': True, 'data': [{'id': 'w1'}]}
    other = {'name': 'query_stock_prices', 'ok': True, 'data': [], 'items': [], 'status': 'no_matching_evidence',
             'error_code': 'zero_evidence'}
    assert direct.public_search_state([]) == 'not_run'
    assert direct.public_search_state([other]) == 'not_run'
    assert direct.public_search_state([failed]) == 'failed'
    assert direct.public_search_state([empty]) == 'empty'
    assert direct.public_search_state([unreadable]) == 'pages_unreadable'
    assert direct.public_search_state([found]) == 'found'
    # The last web_research is the one that counts.
    assert direct.public_search_state([empty, found]) == 'found'
    # The scope's output is capped at 12 entries, but the public-search state is read from every entry.
    assert len(direct.search_scope([other] * 13)) == 12
    assert direct.public_search_state([other] * 12 + [empty]) == 'empty'


# 4. the compound note: two empty searches and a draft -> the note, once, in the input after the draft.

def test_two_empty_searches_and_a_draft_get_one_note_before_the_next_decision():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [text('')], seen), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    assert len(note_messages(seen)) == 1
    assert sum(carries(m, NOTE_MARK) for m in seen) == 1
    assert carries(seen[2], NOTE_MARK) == 0              # not in the input that got the draft
    assert carries(seen[3], NOTE_MARK) == 1              # the input after the draft
    assert result['audit']['compound_empty_noted'] is True
    assert result['audit']['compound_empty_draft'].startswith('AMD 收盘价为 100 美元')


# 5. the note leads to a public search that finds a usable page: a normal answer, no refusal.

def test_a_public_search_after_the_note_with_a_usable_source_answers_normally(monkeypatch):
    refusal, refusal_seen = refusal_model('不应出现')
    monkeypatch.setattr(direct, 'decision_request', refusal)
    page = {'id': 'w1', 'source_type': 'web', 'url': 'https://example.com/amd', 'title': 'AMD 公开资料',
            'excerpt': 'AMD 公开资料提到其新的处理器产品线。', 'fetch_error': False}

    def executor(name, args):
        return {'ok': True, 'data': [page]} if name == 'web_research' else {'ok': True, 'data': []}
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [call('web_research', query='AMD 公开资料'),
                                                                        text('AMD 公开资料提到其新的处理器产品线 [1]。')], seen),
                              executor=executor)
    result = run('请查一下 AMD 的公开说法', ctx)
    assert result['status'] == 'succeeded'
    assert '处理器产品线' in result['answer']
    assert refusal_seen == []                            # the refusal verdict was never asked for
    assert len(note_messages(seen)) == 1


# 6. the note, then the model still calls no tool -> the refusal is told what was searched and that no public search ran.

def test_a_refusal_after_the_note_is_told_what_was_searched_and_that_no_public_search_ran(monkeypatch):
    refusal, refusal_seen = refusal_model(FIXED_NOTICE)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [text('仍然没有工具')], seen), executor=EMPTY)
    run('AMD 收盘价', ctx)
    assert len(note_messages(seen)) == 1                 # the note did not come a second time
    facts = facts_of(refusal_seen)
    assert '"public_search": "not_run"' in facts
    assert '"searched": [' in facts and '"tool": "query_stock_prices"' in facts and '"outcome": "empty"' in facts
    assert 'at most three sentences' in refusal_seen[0][0]['content']
    assert 'Never say or imply that the information does not exist' in refusal_seen[0][0]['content']


# 7. one empty search is not compound: no note.

def test_one_empty_search_gets_no_note():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], seen), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    assert note_messages(seen) == []
    assert result['audit'].get('compound_empty_noted') is None


# 8. a public search already ran and came back empty: no note, and the refusal says the search was empty.

def test_a_public_search_that_already_came_back_empty_gets_no_note(monkeypatch):
    refusal, refusal_seen = refusal_model(FIXED_NOTICE)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted([call('web_research', query='AMD 公开资料'),
                                                call('query_stock_prices', symbol='AMD'), text('x')], seen),
                              executor=EMPTY)
    result = run('请查一下 AMD 的公开说法', ctx)
    assert note_messages(seen) == []
    assert result['audit'].get('compound_empty_noted') is None
    assert '"public_search": "empty"' in facts_of(refusal_seen)


# 9. web_research is not among the exposed tools: no note.

def test_no_note_when_web_research_is_not_exposed():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [text('')], seen), executor=EMPTY)
    run('AMD 收盘价', ctx)
    assert note_messages(seen) == []


# 10. the verdict is unusable twice: the fixed sentence, then the searched line that names the missing public search.

def test_a_twice_unusable_verdict_names_the_search_scope_on_a_second_line(monkeypatch):
    fake, _ = unusable_refusal_model()
    monkeypatch.setattr(direct, 'decision_request', fake)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [text('')], []), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    first, second = result['answer'].split('\n', 1)
    assert first == FIXED_NOTICE
    assert second.startswith('本轮已查：') and '本轮没有做公开网页检索。' in second


# 11. the switch off: every change above is absent, and the refusal prompt keeps its old wording.

def test_switch_off_restores_the_prior_behaviour(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    snapshots = capture_feedback(monkeypatch)
    rows = [{'id': 'r1', 'symbol': 'MSFT', 'close': 100, 'trading_date': '2026-11-04'}]
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], []),
                              executor=lambda n, a: {'ok': True, 'data': rows})
    run('AMD 收盘价', ctx)
    assert 'rejected' not in snapshots[-1][-1] and 'rows_returned' not in snapshots[-1][-1]

    refusal, refusal_seen = refusal_model(FIXED_NOTICE)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted(TWO_EMPTY_THEN_DRAFT() + [text('仍然没有工具')], seen), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    assert note_messages(seen) == [] and result['audit'].get('compound_empty_noted') is None
    facts = facts_of(refusal_seen)
    assert '"searched"' not in facts and '"public_search"' not in facts
    assert 'at most two sentences' in refusal_seen[0][0]['content']
    assert 'at most three sentences' not in refusal_seen[0][0]['content']
