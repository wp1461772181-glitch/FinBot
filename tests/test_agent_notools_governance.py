"""Governance of a model that answers without calling its tools (M1' refusal facts, M2 nudge, M2b empty
close, M3 price prefetch, M4 status line, and the observation fields).

Every model here is a scripted fake: the loop's decisions come from ``decider``, the refusal verdict from a
monkeypatched ``decision_request``, and tool results from ``executor``.  The clock is frozen at
2026-11-05 22:47 in Asia/Kuala_Lumpur, the incident's time.
"""
import asyncio, itertools, json
from datetime import UTC, date, datetime

import pytest

from app.agent_workflow import direct, entities
from app.agent_workflow.state import AgentRuntimeContext
from app.database import SessionLocal, engine
from app.knowledge.models import LowConfidenceQuestion

FIXED_NOW = datetime(2026, 11, 5, 14, 47, tzinfo=UTC)  # 2026-11-05 22:47 Asia/Kuala_Lumpur
NUDGE_MARK = '尚未调用任何工具'
EMPTY_CLOSE_MARK = '你上一步没有产出正文'
HONEST_REPLY = '库里没有这一天的收盘记录，请确认日期或股票代码。'
FIXED_NOTICE = '没有可核验资料，无法确认本次请求中的事实。'

_ids = itertools.count(1)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW if tz is None else FIXED_NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(direct, 'datetime', FrozenDatetime)


@pytest.fixture(autouse=True)
def honest_refusal(monkeypatch):
    """Default refusal model: an honest reply.  Tests that need another reply override it."""
    refusal_fake, _ = refusal_model(HONEST_REPLY)
    monkeypatch.setattr(direct, 'decision_request', refusal_fake)


@pytest.fixture(autouse=True)
def question_pool_table():
    """The app creates its tables at startup, which these tests do not run; the question pool is the one they read."""
    LowConfidenceQuestion.__table__.create(bind=engine, checkfirst=True)


@pytest.fixture(autouse=True)
def verified_tickers(monkeypatch):
    """Tesla and Apple are tied to their tickers by SEC ticker records in production; the test database has none."""
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
    value = {'category': 'A', 'mode': 'prices', **scope}
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


def carries(messages, mark):
    return sum(1 for m in messages if isinstance(m, dict) and mark in str(m.get('content') or ''))


def run(question, ctx):
    return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def price_rows(**closes):
    return {'ok': True, 'data': [{'id': f'p-{s}', 'symbol': s, 'close': c, 'trading_date': '2026-11-04'}
                                 for s, c in closes.items()]}


def recorded_reasons(question):
    with SessionLocal() as db:
        return [row.reason for row in db.query(LowConfidenceQuestion).filter(LowConfidenceQuestion.question == question)]


# --- M3: the incident replayed with a model that never calls a tool -------------------------------

def test_prefetched_close_lets_a_never_calling_model_answer_with_a_citation():
    executed = []

    def execute(name, args):
        executed.append((name, args))
        return price_rows(TSLA=385.19)
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='TSLA', symbols=['TSLA'], company='Tesla', company_mention='Tesla', metrics=['price']),
                              decider=scripted([text('TSLA 2026-11-04 收盘价为 385.19 美元 [1]。')], seen), executor=execute)
    result = run('昨天 Tesla 收盘价', ctx)
    assert result['status'] == 'succeeded'
    assert '385.19' in result['answer'] and '[1]' in result['answer']
    assert [(n, a['symbol']) for n, a in executed] == [('query_stock_prices', 'TSLA')]
    assert result['audit']['prefetch_hit'] is True
    assert result['audit']['first_decision_zero_tool'] is True
    assert len(seen) == 1


def test_double_symbol_prefetch_puts_both_closes_in_the_pool():
    executed = []

    def execute(name, args):
        executed.append(args['symbol'])
        return price_rows(**{args['symbol']: 100 if args['symbol'] == 'AMD' else 200})
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='AMD', symbols=['AMD', 'NVDA'], metrics=['price']),
                              decider=scripted([text('AMD 收盘价为 100 美元 [1]，NVDA 收盘价为 200 美元 [2]。')], []), executor=execute)
    result = run('持 AMD 200 股换 NVDA 能换多少股', ctx)
    assert executed == ['AMD', 'NVDA']
    assert result['status'] == 'succeeded' and '100 美元' in result['answer'] and '200 美元' in result['answer']
    assert result['audit']['prefetch_hit'] is True


def test_a_single_named_stock_is_prefetched_too():
    executed = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='AMD', metrics=['price']),
                              decider=scripted([text('AMD 收盘价为 100 美元 [1]。')], []),
                              executor=lambda n, a: executed.append(a['symbol']) or price_rows(AMD=100))
    result = run('AMD 收盘价', ctx)
    assert executed == ['AMD'] and result['audit']['prefetch_hit'] is True and result['status'] == 'succeeded'


@pytest.mark.parametrize('scope', [
    {},                                                         # no stock named: nothing to read
    {'symbol': 'A', 'symbols': ['A', 'B', 'C', 'D', 'E']},      # over the cap of four
])
def test_no_prefetch_without_a_named_stock_or_within_the_cap(scope):
    executed = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(**scope),
                              decider=scripted([text('没有可核验资料。')] * 2, []), executor=lambda n, a: executed.append(n) or price_rows())
    result = run('收盘价', ctx)
    assert 'query_stock_prices' not in executed
    assert result['audit'].get('prefetch_hit') is False


def test_non_price_and_out_of_scope_routes_are_untouched_by_prefetch():
    executed = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: {'category': 'C', 'mode': 'prices', 'symbols': ['AAPL'], 'symbol': 'AAPL'},
                              decider=scripted([], []), executor=lambda n, a: executed.append(n) or price_rows())
    run('帮我写个 Python 快排', ctx)
    assert executed == []


# --- M2: zero tools and zero evidence -> one nudge with facts ------------------------------------

def test_a_nudge_that_gets_a_tool_call_recovers_with_exactly_one_retry():
    seen = []
    executed = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([text('AMD 收盘价为 100 美元 [1]。'),
                                                call('query_stock_prices', symbol='AMD'),
                                                text('AMD 收盘价为 100 美元 [1]。')], seen),
                              executor=lambda n, a: executed.append(n) or price_rows(AMD=100))
    result = run('AMD 收盘价', ctx)
    assert result['status'] == 'succeeded' and '100 美元' in result['answer']
    assert executed == ['query_stock_prices']
    assert len(seen) == 3
    assert carries(seen[0], NUDGE_MARK) == 0
    assert carries(seen[1], NUDGE_MARK) == 1
    assert carries(seen[2], NUDGE_MARK) == 1          # the same single note, not a second one
    assert result['audit']['nudged'] is True and result['audit']['nudge_outcome'] == 'recovered'
    assert result['audit']['prefetch_hit'] is False


def test_status_line_states_facts_and_drops_the_choose_or_answer_wording():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([text('x'), text('y')], seen), executor=lambda n, a: price_rows())
    run('AMD 收盘价', ctx)
    instruction = seen[0][0]['content']
    assert '已调用工具 0 次' in instruction and '已接受证据 0 条' in instruction
    assert '选择工具或直接作答' not in instruction


# --- M2b: a blank close after evidence is asked once more ----------------------------------------

def test_blank_close_after_evidence_is_retried_once_and_recovers():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('   '), text('AMD 收盘价为 100 美元 [1]。')], seen),
                              executor=lambda n, a: price_rows(AMD=100))
    result = run('AMD 收盘价', ctx)
    assert result['status'] == 'succeeded' and '100 美元' in result['answer']
    assert len(seen) == 3 and carries(seen[2], EMPTY_CLOSE_MARK) == 1
    assert result['audit']['empty_close_retried'] is True and result['audit']['empty_close_outcome'] == 'recovered'


def test_blank_close_twice_after_evidence_gives_the_fixed_sentence_after_one_retry():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text(''), text('')], seen),
                              executor=lambda n, a: price_rows(AMD=100))
    result = run('AMD 收盘价', ctx)
    assert '没有生成可用的回答' in result['answer']
    assert sum(carries(m, EMPTY_CLOSE_MARK) for m in seen) == 1
    assert result['audit']['empty_close_outcome'] == 'failed'


def test_a_tool_call_between_two_blank_closes_does_not_count_as_recovery():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('  '),
                                                call('query_stock_prices', symbol='AMD', limit=5), text('')], seen),
                              executor=lambda n, a: price_rows(AMD=100))
    result = run('AMD 收盘价 重复', ctx)
    assert '没有生成可用的回答' in result['answer']
    assert len(seen) == 4                                    # one retry, then the fixed sentence: no second retry
    assert carries(seen[-1], EMPTY_CLOSE_MARK) == 1          # the note is in the protocol once, not added again
    assert result['audit']['empty_close_outcome'] == 'failed'


# --- M1': the refusal is written by the model, from facts ------------------------------------------

def test_silent_model_with_a_prefetch_miss_is_refused_from_facts_and_a_future_claim_is_voided(monkeypatch):
    refusal, refusal_seen = refusal_model('2026年11月4日尚未到来，因此无法给出收盘价。')
    monkeypatch.setattr(direct, 'decision_request', refusal)
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='AMD', metrics=['price']),
                              decider=scripted([text('AMD 收盘价为 100 美元 [1]。'), text('AMD 收盘价为 100 美元 [1]。')], seen),
                              executor=lambda n, a: {'ok': True, 'data': []})
    result = run('2026年11月4日 AMD 收盘价是多少', ctx)
    assert len(seen) == 2 and carries(seen[1], NUDGE_MARK) == 1
    assert len(refusal_seen) == 1
    facts = refusal_seen[0][1]['content']
    assert '2026-11-05' in facts and '"turn_state": "no_tool_called"' in facts
    assert '"relation_to_today": "past"' in facts
    assert '"tools_run_by_system": [{"name": "query_stock_prices", "status": "no_matching_evidence", "error_code": "zero_evidence"}]' in facts
    assert result['answer'].strip() == FIXED_NOTICE
    assert '尚未到来' not in result['answer']
    assert result['audit']['refusal']['reason'] == 'refusal_reason_rejected_future_claim'
    assert result['audit']['nudge_outcome'] == 'failed'
    assert 'AMD 收盘价为 100 美元' in result['audit']['discarded_draft']


def test_the_incident_phrasing_yesterday_is_resolved_and_a_future_claim_about_it_is_voided(monkeypatch):
    refusal, refusal_seen = refusal_model('2026年11月4日尚未到来，因此没有收盘价。')
    monkeypatch.setattr(direct, 'decision_request', refusal)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='TSLA', symbols=['TSLA'], company='Tesla', company_mention='Tesla', metrics=['price']),
                              decider=scripted([text('x'), text('y')], []), executor=lambda n, a: {'ok': True, 'data': []})
    result = run('昨天 Tesla 收盘价 核对', ctx)
    facts = refusal_seen[0][1]['content']
    assert '"written_as": "昨天"' in facts and '"date": "2026-11-04"' in facts
    assert result['answer'].strip() == FIXED_NOTICE
    assert result['audit']['refusal']['reason'] == 'refusal_reason_rejected_future_claim'


def test_an_honest_refusal_about_a_past_date_is_kept(monkeypatch):
    refusal, _ = refusal_model('2026年11月4日没有查到收盘记录，请确认日期或股票代码。')
    monkeypatch.setattr(direct, 'decision_request', refusal)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(symbol='AMD', metrics=['price']),
                              decider=scripted([text('x'), text('y')], []), executor=lambda n, a: {'ok': True, 'data': []})
    result = run('2026年11月4日 AMD 收盘价是多少', ctx)
    assert result['answer'].startswith(FIXED_NOTICE[:4])
    assert '没有查到收盘记录' in result['answer']
    assert result['audit']['refusal']['reason'] == '缺少日期或股票代码'


def test_a_refusal_with_no_tool_call_records_the_state_in_the_question_pool():
    question = '2026年11月4日 无人调用 收盘价'
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([text('x'), text('y')], []), executor=lambda n, a: price_rows())
    run(question, ctx)
    assert any(reason.startswith('no_tool_called:') for reason in recorded_reasons(question))


def test_a_tool_that_failed_is_named_as_tool_failed_with_its_error_code(monkeypatch):
    refusal, refusal_seen = refusal_model(HONEST_REPLY)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    question = '失败的收盘价查询 AMD'
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], []),
                              executor=lambda n, a: {'ok': False, 'error_code': 'upstream_timeout', 'data': []})
    result = run(question, ctx)
    facts = refusal_seen[0][1]['content']
    assert '"turn_state": "tool_failed"' in facts and 'upstream_timeout' in facts
    assert result['audit']['refusal_state'] == 'tool_failed'
    assert any(reason.startswith('tool_failed:') for reason in recorded_reasons(question))


def test_a_tool_that_found_nothing_is_named_as_searched_empty(monkeypatch):
    refusal, refusal_seen = refusal_model(HONEST_REPLY)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('x')], []),
                              executor=lambda n, a: {'ok': True, 'data': []})
    result = run('查空的收盘价 AMD', ctx)
    facts = refusal_seen[0][1]['content']
    assert '"turn_state": "searched_empty"' in facts and '"name": "query_stock_prices"' in facts
    assert result['audit']['refusal_state'] == 'searched_empty'


def test_a_long_reason_is_still_recorded_because_the_state_prefix_sits_inside_the_column_cap(monkeypatch):
    refusal, _ = refusal_model(HONEST_REPLY, reason='很长的缺失说明' * 30)
    monkeypatch.setattr(direct, 'decision_request', refusal)
    question = '超长原因的拒答 收盘价'
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([text('x'), text('y')], []), executor=lambda n, a: price_rows())
    result = run(question, ctx)
    reasons = recorded_reasons(question)
    assert reasons and all(len(r) <= 80 and r.startswith('no_tool_called:') for r in reasons)
    assert 'refusal_record_failed' not in result['audit']


def test_future_date_claims_are_only_caught_for_a_named_past_date():
    dates = direct.requested_dates('11月20日的收盘价', date(2026, 11, 5))
    assert dates == [{'date': '2026-11-20', 'relation_to_today': 'future', 'year_inferred': True}]
    assert direct.future_date_claim('11月20日尚未到来', dates) is False   # future relation: nothing to void


@pytest.mark.parametrize('reply,expected', [
    ('2026年11月4日尚未到来', True),
    ('2026-11-04 还没到', True),
    ('11月4日的数据将来才会有', True),
    ('2026年11月4日不是未来日期，库里没有记录', False),       # a negated claim is not a future claim
    ('2026年11月6日尚未到来', False),                          # a different date
    ('库里没有记录', False),
])
def test_future_claim_detection_is_limited_to_a_named_past_date(reply, expected):
    dates = direct.requested_dates('2026年11月4日 收盘价', date(2026, 11, 5))
    assert direct.future_date_claim(reply, dates) is expected


def test_requested_dates_reads_explicit_dates_and_infers_year_for_month_day():
    dates = direct.requested_dates('2026年11月4日和11月5日的收盘价', date(2026, 11, 5))
    assert dates == [
        {'date': '2026-11-04', 'relation_to_today': 'past', 'year_inferred': False},
        {'date': '2026-11-05', 'relation_to_today': 'today', 'year_inferred': True},
    ]


def test_relative_past_days_resolve_against_the_users_today():
    assert direct.requested_dates('昨天 Tesla 收盘价', date(2026, 11, 5)) == [
        {'date': '2026-11-04', 'relation_to_today': 'past', 'year_inferred': False, 'written_as': '昨天'}]


# --- observation fields ----------------------------------------------------------------------------

def test_observation_fields_are_present_with_their_defaults():
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([call('query_stock_prices', symbol='AMD'), text('AMD 收盘价为 100 美元 [1]。')], []),
                              executor=lambda n, a: price_rows(AMD=100))
    result = run('AMD 收盘价', ctx)
    audit = result['audit']
    assert audit['first_decision_zero_tool'] is False and audit['prefetch_hit'] is False
    assert audit['nudge_outcome'] is None and audit.get('discarded_draft') is None
