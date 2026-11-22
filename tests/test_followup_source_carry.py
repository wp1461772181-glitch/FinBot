"""FINBOT_FOLLOWUP_SOURCE_CARRY: a follow-up that builds on earlier answers gets their sources bound and read back."""
import asyncio
import json

import pytest

from app.agent_workflow import direct
from app.agent_workflow.direct import HISTORY_BINDING_LIMIT, Reference, Turn, resolver_prompt
from app.agent_workflow.state import AgentRuntimeContext

SWITCH = 'FINBOT_FOLLOWUP_SOURCE_CARRY'


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


def src(n, available=True, **extra):
    return {'ordinal': n, 'title': f'来源{n}', 'source_type': 'official_filing', 'available': available, **extra}


# The production turn: answer 1 reported the 8-K press release [1] plus other sources and derived calculations.
ONLINE = (
    {'turn_id': 'latest', 'answers_back': 1, 'opening': '英伟达第三季度业绩', 'sources': [
        src(3), src(1, title='8-K 业绩新闻稿'), src(2), src(4, derived=True, parents=[1, 2]), src(5, False), src(6, derived=True, parents=[3])]},
    {'turn_id': 'older', 'answers_back': 2, 'opening': '更早的回答', 'sources': [src(1), src(2)]},
    {'turn_id': 'empty', 'answers_back': 3, 'opening': '没有来源的回答', 'sources': []},
)


def make_turn(resolver, catalogue=ONLINE, question='从交出的成绩单来看，这份财报是好还是不好呢？'):
    context = AgentRuntimeContext('p', 'm', 'k', conversation_id='c', resolver=resolver, history_citation_catalogue=catalogue)

    async def emit(_):
        pass
    return Turn(question, context, emit, [{'role': 'user', 'content': '拉取最新英伟达财报'}, {'role': 'assistant', 'content': '第三季度……[1]'}], {})


def resolving(**fields):
    async def resolver(_):
        return {'relationship': 'followup', 'canonical_question': '判断这份财报好不好', **fields}
    return resolver


def run_reference(turn):
    asyncio.run(turn.reference())
    return turn


def keys(turn):
    return [(b['turn_id'], b['ordinal']) for b in turn.bound_history_citations]


def test_follow_up_binds_the_answer_sources_in_ordinal_order_without_derived_or_unavailable():
    turn = run_reference(make_turn(resolving(builds_on_answers=[1])))
    assert keys(turn) == [('latest', 1), ('latest', 2), ('latest', 3)]
    assert all(b['derived'] is False and b['parents'] == [] for b in turn.bound_history_citations)
    assert turn.audit['followup_source_carry'] == {'answers': [1], 'bound': 3, 'left_out': 0, 'skipped_answers': []}
    assert turn.pending is None


def test_recall_reads_them_as_this_turns_evidence_and_skips_the_automatic_prefetch(monkeypatch):
    turn = run_reference(make_turn(resolving(builds_on_answers=[1])))
    turn.route = 'A'
    turn.scope = {'mode': 'financials', 'symbol': 'NVDA', 'metrics': ['revenue']}
    calls = []

    async def execute(name, args, page_chars=None):
        calls.append((name, args.get('ordinal')))
        return {'ok': True, 'data': [{'ordinal': args['ordinal'], 'quote': f'原文{args["ordinal"]}', 'chars_total': 10}]}

    def accept(name, args, outcome):
        turn.citations.append({'ordinal': len(turn.citations) + 1, 'title': f'来源{args["ordinal"]}', 'source_type': 'history_citation'})
        turn.last_accepted = {'ok': True, 'data': outcome['data']}
    seen_hint = {}

    async def decision():
        text = next(m['content'] for m in turn.tool_messages() if m['role'] == 'system' and '"resolved_question"' in m['content'])
        seen_hint.update(json.loads(text[text.index('{'):]))
        return {'content': '这份财报整体不错。'}

    async def publish(*_):
        pass

    async def finish(_):
        return {'status': 'succeeded'}
    monkeypatch.setattr(turn, 'execute_read', execute)
    monkeypatch.setattr(turn, 'accept', accept)
    monkeypatch.setattr(turn, 'publish_result', publish)
    monkeypatch.setattr(turn, 'decision', decision)
    monkeypatch.setattr(turn, 'finish_answer', finish)
    asyncio.run(turn.agent_loop())
    assert calls == [('read_history_citation', 1), ('read_history_citation', 2), ('read_history_citation', 3)]
    recall = turn.audit['history_citation_recall']
    assert recall['bound'] == 3 and recall['read_ok'] == 3 and recall['unread'] == 0
    assert turn.audit['retrieval_gate'] == 'history_citation_recalled'
    # the model is told where the evidence came from
    note = seen_hint['carried_sources_note']
    assert '重新读进本轮' in note and '[1] 来源1' in note


def test_empty_builds_on_changes_nothing():
    turn = run_reference(make_turn(resolving(builds_on_answers=[])))
    assert turn.bound_history_citations == [] and 'followup_source_carry' not in turn.audit
    turn = run_reference(make_turn(resolving()))
    assert turn.bound_history_citations == [] and 'followup_source_carry' not in turn.audit and turn.carry_note is None


def test_named_binding_merges_with_carry_within_the_limit_and_named_comes_first():
    cat = ({'turn_id': 'latest', 'answers_back': 1, 'opening': 'a', 'sources': [src(1), src(2), src(3)]},
           {'turn_id': 'older', 'answers_back': 2, 'opening': 'b', 'sources': [src(7)]})
    turn = run_reference(make_turn(resolving(history_citations=[{'answers_back': 2, 'ordinal': 7}], builds_on_answers=[1]), cat))
    assert keys(turn) == [('older', 7), ('latest', 1), ('latest', 2), ('latest', 3)]
    assert turn.audit['followup_source_carry']['bound'] == 3


def test_a_handle_bound_by_name_is_not_bound_again_and_the_cap_holds():
    many = ({'turn_id': 'latest', 'answers_back': 1, 'opening': 'a', 'sources': [src(n) for n in range(1, 5)]},
            {'turn_id': 'older', 'answers_back': 2, 'opening': 'b', 'sources': [src(n) for n in range(1, 9)]})
    turn = run_reference(make_turn(resolving(history_citations=[{'answers_back': 2, 'ordinal': 5}], builds_on_answers=[1, 2, 1]), many))
    got = keys(turn)
    # the named answer fills the 6 slots (5 first, then 1,2,3,4,6); 7 and 8 were capped there, the carry finds answer 1's four handles and 7, 8 again, none fits
    assert got[0] == ('older', 5) and len(got) == len(set(got)) == HISTORY_BINDING_LIMIT
    assert turn.audit['history_citation_capped'] == 2
    carry = turn.audit['followup_source_carry']
    assert carry['answers'] == [1, 2, 1] and carry['bound'] == 0 and carry['left_out'] == 6


def test_over_the_limit_counts_what_was_left_out():
    cat = ({'turn_id': 'latest', 'answers_back': 1, 'opening': 'a', 'sources': [src(n) for n in range(1, 5)]},
           {'turn_id': 'older', 'answers_back': 2, 'opening': 'b', 'sources': [src(n) for n in range(1, 5)]})
    turn = run_reference(make_turn(resolving(builds_on_answers=[1, 2]), cat))
    assert len(turn.bound_history_citations) == HISTORY_BINDING_LIMIT
    assert turn.audit['followup_source_carry'] == {'answers': [1, 2], 'bound': 6, 'left_out': 2, 'skipped_answers': []}


def test_unknown_or_sourceless_answers_are_skipped_and_recorded():
    turn = run_reference(make_turn(resolving(builds_on_answers=[9, 3, 1])))
    assert keys(turn) == [('latest', 1), ('latest', 2), ('latest', 3)]
    assert turn.audit['followup_source_carry']['skipped_answers'] == [
        {'answers_back': 9, 'reason': 'not_in_catalogue'}, {'answers_back': 3, 'reason': 'no_available_sources'}]
    only_bad = run_reference(make_turn(resolving(builds_on_answers=[9])))
    assert only_bad.bound_history_citations == [] and only_bad.carry_note is None and only_bad.pending is None


def test_clarify_with_builds_on_is_rejected_like_a_clarification_that_binds_sources():
    seen = []

    async def resolver(payload):
        seen.append(payload.get('correction'))
        if len(seen) == 1:
            return {'relationship': 'clarify', 'clarification_answers': [1], 'builds_on_answers': [1]}
        return {'relationship': 'followup', 'canonical_question': '好不好', 'builds_on_answers': [1]}
    turn = run_reference(make_turn(resolver))
    assert seen[0] is None and seen[1]['error'] == 'clarification_cannot_bind_sources'
    assert 'builds_on_answers must be empty' in seen[1]['instruction']
    assert turn.audit['resolver_retries'] == 1 and keys(turn) == [('latest', 1), ('latest', 2), ('latest', 3)]


def test_a_failed_attempt_leaves_no_half_binding():
    async def resolver(_):
        return {'relationship': 'followup', 'canonical_question': 'x', 'builds_on_answers': [1],
                'referents': [{'text': '不存在的条目', 'kind': 'x', 'item_id': 'nope'}]}
    turn = run_reference(make_turn(resolver))
    assert turn.bound_history_citations == [] and 'followup_source_carry' not in turn.audit and turn.carry_note is None
    assert turn.resolver_failed is True


def test_a_binding_from_a_rejected_first_attempt_is_cleared_before_the_retry():
    calls = []

    async def resolver(payload):
        calls.append(payload.get('correction'))
        if len(calls) == 1:
            return {'relationship': 'followup', 'canonical_question': 'x', 'builds_on_answers': [1],
                    'referents': [{'text': '没有的', 'kind': 'x', 'item_id': 'nope'}]}
        return {'relationship': 'followup', 'canonical_question': 'x'}
    turn = run_reference(make_turn(resolver))
    assert len(calls) == 2 and turn.bound_history_citations == [] and 'followup_source_carry' not in turn.audit


def test_switch_off_removes_the_field_and_the_text_and_binds_nothing(monkeypatch):
    assert 'builds_on_answers' in json.dumps(direct.REFERENCE_SCHEMA_CARRY)
    assert 'builds_on_answers' not in json.dumps(direct.REFERENCE_SCHEMA)
    assert 'builds_on_answers' not in Reference.model_json_schema()['properties']
    on_prompt = resolver_prompt()
    assert on_prompt.endswith(direct.CARRY_PROMPT_TEXT)
    monkeypatch.setenv(SWITCH, 'off')
    off_prompt = resolver_prompt()
    assert 'builds_on_answers' not in off_prompt and on_prompt == off_prompt + direct.CARRY_PROMPT_TEXT
    # off: validated as before, so a stray builds_on_answers fails the attempt (extra='forbid') exactly as it did.
    turn = run_reference(make_turn(resolving(builds_on_answers=[1])))
    assert turn.bound_history_citations == [] and turn.resolver_failed is True and 'followup_source_carry' not in turn.audit
    ok = run_reference(make_turn(resolving()))
    assert ok.bound_history_citations == [] and not getattr(ok, 'resolver_failed', False)


def test_the_model_call_gets_the_schema_and_prompt_for_the_switch(monkeypatch):
    sent = []

    async def model(messages, tools):
        sent.append((messages[0]['content'], tools))
        return {'content': json.dumps({'relationship': 'followup', 'canonical_question': 'x'})}
    for value, expected in (('on', True), ('off', False)):
        monkeypatch.setenv(SWITCH, value)
        context = AgentRuntimeContext('p', 'm', 'k', conversation_id='c', history_citation_catalogue=ONLINE)

        async def emit(_):
            pass
        turn = Turn('这份好不好', context, emit, [{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'a'}], {})
        turn.model = model
        asyncio.run(turn.reference())
        prompt, tools = sent[-1]
        assert ('builds_on_answers' in json.dumps(tools)) is expected and ('builds_on_answers' in prompt) is expected
