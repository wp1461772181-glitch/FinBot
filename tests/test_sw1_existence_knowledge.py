"""SW1 §6 (spec item 5, Q22, FINBOT_SW1_EXISTENCE_KNOWLEDGE): a draft the system replaces is given back to the model, and a
labelled general-knowledge sentence about existence may stay.  Spec §8.2 T36–T40; the end-to-end E04 and E05 are in
tests/test_sw1_e2e.py.

Helpers follow tests/test_fp9_compound_empty.py.  Every model here is a scripted fake: the loop's decisions come from
``scripted``, the refusal verdict from a monkeypatched ``decision_request``.  The search tools return nothing (EMPTY), so no
test reaches the network.
"""
import asyncio
import itertools
import json

import pytest

from app.agent_workflow import direct, entities
from app.agent_workflow.state import AgentRuntimeContext
from app.database import engine
from app.knowledge.models import LowConfidenceQuestion

SWITCH = 'FINBOT_SW1_EXISTENCE_KNOWLEDGE'
NOTE_MARK = '系统事实：本轮你查询的来源都没有取得可用资料'
NUDGE_MARK = '系统事实：本轮你尚未调用任何工具'
NEWS_CATEGORY = '新闻与网页'          # web_research's category; load_hint exposes it from the first call
DRAFT = '据我所知，Twitter 已于 2022 年被私有化，之后不再披露季度财报，这同样是背景判断。'
FIXED_NOTICE = '没有可核验资料，无法确认本次请求中的事实。'
EXCEPTION = '（公司是否上市、是否仍公开披露这类背景常识除外，写出时标明是一般知识）'
_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def switch_default(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


@pytest.fixture(autouse=True)
def honest_refusal(monkeypatch):
    refusal, _ = refusal_model(FIXED_NOTICE)
    monkeypatch.setattr(direct, 'decision_request', refusal)


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


def refusal_model(reply, seen=None):
    """Answers only the refusal prompt.  Its messages are recorded in ``seen`` when given."""
    async def fake(provider, model, key, messages, schemas, base_url=None):
        if 'gathered no usable evidence' not in str(messages[0].get('content')):
            return {}, {'role': 'assistant', 'content': ''}
        if seen is not None:
            seen.append(messages)
        decision = {'useful': False, 'reply': reply, 'reason': '缺少日期或股票代码', 'route': 'insufficient_evidence'}
        return {}, {'role': 'assistant', 'content': json.dumps(decision, ensure_ascii=False)}
    return fake, seen


def refusal_facts(refusal_seen):
    """The refusal's facts message, parsed, and its system prompt."""
    system, user = refusal_seen[0][0], refusal_seen[0][1]
    return json.loads(user['content'][len('facts: '):]), system['content']


def note_messages(seen):
    return [m for messages in seen for m in messages
            if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(NOTE_MARK)]


def run(question, ctx):
    return asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))


def instruction_text():
    turn = direct.Turn('q', AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='guest'), emit, [], {})
    return turn.tool_messages(False)[0]['content']


EMPTY = lambda n, a: {'ok': True, 'data': []}


def two_empty_then(*closing):
    # The two searches must differ after validation (validate fills in limit=5, so a second call with limit=5 would be a
    # replay, not a second search).
    return [call('query_stock_prices', symbol='AMD'), call('query_stock_prices', symbol='AMD', days=30), *[text(c) for c in closing]]


# T36: the compound note carries the draft and the existence limit; the D-F2 sentence stays.

def test_t36_the_note_gives_back_the_draft_and_the_existence_limit():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(two_empty_then(DRAFT, ''), seen), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    notes = note_messages(seen)
    assert len(notes) == 1
    note = notes[0]['content']
    assert DRAFT in note                                   # the draft comes back verbatim
    assert '一般知识' in note and '未经本轮资料核实' in note
    assert '不要断言这个信息不存在。' in note              # the D-F2 sentence is kept as it was
    assert result['audit']['compound_empty_draft'] == DRAFT


def test_t36_switch_off_the_note_is_the_constant_unchanged(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(two_empty_then(DRAFT, ''), seen), executor=EMPTY)
    run('AMD 收盘价', ctx)
    note = note_messages(seen)[0]['content']
    searched = note[len(NOTE_MARK) + 1:note.index('。其中没有公开网页检索。')]
    assert note == direct.COMPOUND_EMPTY_NOTE.format(searched=searched)
    assert DRAFT not in note and '一般知识' not in note


# T37: a draft longer than 1200 characters is quoted up to 1200 with a note; the audit keeps 2000.

def test_t37_a_long_draft_is_quoted_up_to_1200_characters_and_audited_at_2000():
    long_draft = 'AMD 收盘价为 100 美元。' + '填' * 3000 + 'TAILEND'
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(two_empty_then(long_draft, ''), seen), executor=EMPTY)
    result = run('AMD 收盘价', ctx)
    note = note_messages(seen)[0]['content']
    assert long_draft[:1200] + '（草稿后半已省略）' in note
    assert 'TAILEND' not in note
    assert result['audit']['compound_empty_draft'] == long_draft[:2000]


# T38: a refusal after a draft is handed the draft as facts.model_draft, and the prompt allows one labelled sentence.

def test_t38_a_refusal_after_a_draft_gets_the_draft_and_the_existence_clause(monkeypatch):
    refusal, refusal_seen = refusal_model(FIXED_NOTICE, seen=[])
    monkeypatch.setattr(direct, 'decision_request', refusal)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(two_empty_then(DRAFT, ''), []), executor=EMPTY)
    run('AMD 收盘价', ctx)
    facts, system = refusal_facts(refusal_seen)
    assert facts['model_draft'] == DRAFT
    assert "(model_draft is the model's own earlier draft" in system
    assert 'Never say or imply that the information does not exist' in system
    assert 'model_draft states, labelled as general knowledge' in system


def test_t38_switch_off_the_refusal_gets_no_draft_and_the_prompt_is_as_before(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    refusal, refusal_seen = refusal_model(FIXED_NOTICE, seen=[])
    monkeypatch.setattr(direct, 'decision_request', refusal)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none', load_hint=[NEWS_CATEGORY]),
                              decider=scripted(two_empty_then(DRAFT, ''), []), executor=EMPTY)
    run('AMD 收盘价', ctx)
    facts, system = refusal_facts(refusal_seen)
    assert 'model_draft' not in facts and 'searched' in facts        # the FP9 facts are unchanged
    assert 'model_draft' not in system and 'model_draft states' not in system
    assert 'Never say or imply that the information does not exist' in system


# T39: INSTRUCTION carries the existence sentence beside the coverage sentence; off, it is not there.

def test_t39_instruction_allows_a_labelled_general_knowledge_answer_on_existence_questions():
    text_ = instruction_text()
    assert '公司是否上市、是否还向 SEC 报送某类文件这类存在性问题，可以用一般知识回答，标明“一般知识，未经本轮资料核实”，不标 [n]；库里查不到本身不能证明不存在。' in text_
    assert '不要说成库里没有' in text_                      # the S1 coverage sentence is still there
    assert len(text_) <= int(4505 * 0.7)


def test_t39_switch_off_the_instruction_has_no_existence_sentence(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    text_ = instruction_text()
    assert '库里查不到本身不能证明不存在' not in text_
    assert '不要说成库里没有' in text_


# T40: the no-tool nudge keeps the exception for background facts; off, it is the old text.

def test_t40_the_nudge_names_the_general_knowledge_exception_when_on():
    seen = []
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=classify(mode='none'),
                              decider=scripted([text('AMD 收盘价为 100 美元。'), text('')], seen), executor=EMPTY)
    run('AMD 收盘价', ctx)
    nudges = [m['content'] for messages in seen for m in messages
              if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(NUDGE_MARK)]
    assert len(nudges) == 1 and EXCEPTION in nudges[0]


def test_t40_switch_off_the_nudge_is_the_old_text(monkeypatch):
    monkeypatch.setenv(SWITCH, 'off')
    assert direct.nudge_note('query_financials') == direct.NUDGE_NOTE.format(tools='query_financials')
    assert EXCEPTION not in direct.nudge_note('query_financials')
