"""A card press and a typed reply recover the same question: the ``reply:`` prefix is transport, not words.

A button on a clarification card sends ``reply:<choice>``; typing the same choice sends ``<choice>``.  Both come
back with the card's ``pending_request_id``, so both must reach the resolver and the classifier as identical text.
Before the fix the press reached them as the literal ``reply:MSFT`` (``self.original`` kept the prefix).
"""
import asyncio
import json

from app.agent_workflow import direct, entities
from app.agent_workflow.state import AgentRuntimeContext

ENTITY_QUESTION = '最近有什么新闻？'
CLARIFY_QUESTION = '要看微软还是谷歌？'
HISTORY = [{'role': 'user', 'content': '先看一下微软（MSFT）和谷歌（GOOGL）最近一期年报的营收。'},
           {'role': 'assistant', 'content': '微软（MSFT）营收 281,724 百万美元 [1]；谷歌（GOOGL）营收 402,836 百万美元 [2]。'}]


async def emit(_):
    pass


def _first_turn_entity_card(monkeypatch):
    """The unbound-company confirmation card, produced by the real first turn (no ticker resolves)."""
    monkeypatch.setattr(entities, 'resolve_ticker', lambda _: None)
    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              resolver=lambda _: {'relationship': 'new', 'canonical_question': ENTITY_QUESTION},
                              intent_recognizer=lambda _: {'category': 'D', 'company': 'msft', 'symbol': 'MSFT'},
                              decider=lambda *_: {'content': '好的。'})
    result = asyncio.run(direct.run_direct_turn(ENTITY_QUESTION, ctx, emit=emit))
    assert result['status'] == 'waiting_for_input' and result['pending_request']['choices']
    return result['pending_request']


def _resolver_card():
    """The clarify card a resolver returns with choices (the same shape the web page and Telegram receive)."""
    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              resolver=lambda _: {'relationship': 'clarify', 'question': CLARIFY_QUESTION,
                                                  'choices': ['微软', '谷歌'], 'history_citations': []},
                              intent_recognizer=lambda _: {'category': 'D'},
                              decider=lambda *_: {'content': '好的。'})
    result = asyncio.run(direct.run_direct_turn('把它的营业利润列出来。', ctx, emit=emit, messages=HISTORY))
    assert result['status'] == 'waiting_for_input'
    assert [c['value'] for c in result['pending_request']['choices']] == ['reply:微软', 'reply:谷歌']
    return result['pending_request']


def _recover(card, value, *, relationship, canonical, company=None):
    """Answer the card with ``value``; return what the resolver and the classifier were given."""
    seen = {'resolver': [], 'classifier': []}

    def resolver(payload):
        seen['resolver'].append(payload)
        return {'relationship': relationship, 'canonical_question': canonical}

    def classifier(payload):
        seen['classifier'].append(payload)
        return {'category': 'D', **({'company': company, 'symbol': 'MSFT'} if company else {})}

    ctx = AgentRuntimeContext('custom', 'test', 'dummy', resolver=resolver, intent_recognizer=classifier,
                              decider=lambda *_: {'content': '好的。'})
    state = {'pending_request': card, 'requested_pending_id': card['id']}
    asyncio.run(direct.run_direct_turn(value, ctx, emit=emit, state=state, messages=HISTORY))
    assert seen['resolver'] and seen['classifier'], 'the press must reach the resolver and the classifier'
    return seen


def _assert_same_recovery(pressed, typed):
    p_resolver, t_resolver = pressed['resolver'][0], typed['resolver'][0]
    p_intent, t_intent = pressed['classifier'][0], typed['classifier'][0]
    assert p_resolver['question'] == t_resolver['question']
    assert p_intent['question'] == t_intent['question']
    assert p_intent['user_action_words'] == t_intent['user_action_words']
    for payload in (p_resolver, p_intent):
        assert 'reply:' not in json.dumps(payload, ensure_ascii=False)


def test_entity_card_press_and_typed_reply_reach_the_resolver_identically(monkeypatch):
    card = _first_turn_entity_card(monkeypatch)
    pressed = _recover(card, 'reply:MSFT', relationship='followup', canonical='MSFT 最近有什么新闻？', company='Microsoft Corporation')
    typed = _recover(card, 'MSFT', relationship='followup', canonical='MSFT 最近有什么新闻？', company='Microsoft Corporation')
    assert pressed['resolver'][0]['question'] == 'MSFT'
    _assert_same_recovery(pressed, typed)


def test_entity_card_press_with_a_new_relationship_does_not_leak_the_prefix(monkeypatch):
    card = _first_turn_entity_card(monkeypatch)
    pressed = _recover(card, 'reply:MSFT', relationship='new', canonical='MSFT 最近有什么新闻？', company='Microsoft Corporation')
    typed = _recover(card, 'MSFT', relationship='new', canonical='MSFT 最近有什么新闻？', company='Microsoft Corporation')
    _assert_same_recovery(pressed, typed)


def test_resolver_card_press_reaches_the_resolver_without_the_prefix():
    card = _resolver_card()
    pressed = _recover(card, 'reply:微软', relationship='followup', canonical='微软（MSFT）的营业利润是多少？')
    typed = _recover(card, '微软', relationship='followup', canonical='微软（MSFT）的营业利润是多少？')
    assert pressed['resolver'][0]['question'] == '微软'
    _assert_same_recovery(pressed, typed)


def test_resolver_card_press_with_a_new_relationship_does_not_leak_the_prefix():
    card = _resolver_card()
    pressed = _recover(card, 'reply:谷歌', relationship='new', canonical='谷歌（GOOGL）的营业利润是多少？')
    typed = _recover(card, '谷歌', relationship='new', canonical='谷歌（GOOGL）的营业利润是多少？')
    _assert_same_recovery(pressed, typed)
