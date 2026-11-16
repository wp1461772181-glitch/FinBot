"""FP13-E5 (ruling-fp13-e5-fix.md section 3, pins K1-K13).

S1 (FINBOT_FP13E5_RESOLVER_UNFINISHED): the resolver prompt says what an unfinished earlier request in the history is.
S2 (FINBOT_FP13E5_UNFINISHED_FACT): when a rewrite comes back to such a request and the user's own words do not, the
answering model is given that fact as a hint. Nothing is changed, deleted or blocked by either slice.
"""
import hashlib
from pathlib import Path

import pytest

from app.agent_workflow import direct
from app.agent_workflow.direct import REFERENCE_PROMPT, resolver_prompt

S1 = 'FINBOT_FP13E5_RESOLVER_UNFINISHED'
S2 = 'FINBOT_FP13E5_UNFINISHED_FACT'
SW1 = 'FINBOT_SW1_RESOLVER_RULES'
BASE = '8640abf'      # the commit this package is cut from

# sha256 of the UTF-8 text, measured on the unmodified direct.py at 8640abf before any FP13-E5 edit.
BASE_REFERENCE_PROMPT_SHA = '25036339441a2744e2338dc00a8cdb9cc39d2337471087a7c13c90ff2f3885da'
BASE_RESOLVER_PROMPT_SW1_ON_SHA = 'e0e37bedc3bc3671baa167ecf23180b61ab246bb3cf43fae7bfad93a3ed8ae48'
BASE_RESOLVER_PROMPT_SW1_OFF_SHA = '25036339441a2744e2338dc00a8cdb9cc39d2337471087a7c13c90ff2f3885da'

# The anchor sentence of REFERENCE_PROMPT that S1 is inserted after (ruling 3.1).
S1_ANCHOR = 'canonical_question 始终用用户的口吻复述用户这一轮的请求（问题或指令），绝不是反问用户，也不请用户确认。'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@pytest.fixture(autouse=True)
def flags_at_their_defaults(monkeypatch):
    for name in (S1, S2, SW1, 'FINBOT_FP1_ORIGINAL_WORDS', 'FINBOT_FP3_UNFINISHED_TURNS'):
        monkeypatch.delenv(name, raising=False)


# ---- S1: resolver prompt ------------------------------------------------------------------------

def test_k1_default_on_puts_the_unfinished_rule_once_right_after_its_anchor():
    rule = direct.RESOLVER_UNFINISHED_TEXT
    prompt = resolver_prompt()
    assert REFERENCE_PROMPT.count(S1_ANCHOR) == 1
    assert prompt.count(rule) == 1
    assert (S1_ANCHOR + rule) in prompt


@pytest.mark.parametrize('sw1', ['on', 'off'])
def test_k1_holds_with_the_sw1_rules_on_and_off(monkeypatch, sw1):
    monkeypatch.setenv(S1, 'on')
    monkeypatch.setenv(SW1, sw1)
    prompt = resolver_prompt()
    assert prompt.count(direct.RESOLVER_UNFINISHED_TEXT) == 1
    assert (S1_ANCHOR + direct.RESOLVER_UNFINISHED_TEXT) in prompt
    assert (direct.RESOLVER_RULE_TEXT in prompt) is (sw1 == 'on')


@pytest.mark.parametrize('sw1,expected', [('on', BASE_RESOLVER_PROMPT_SW1_ON_SHA),
                                         ('off', BASE_RESOLVER_PROMPT_SW1_OFF_SHA)])
def test_k2_switch_off_is_byte_identical_to_8640abf(monkeypatch, sw1, expected):
    monkeypatch.setenv(S1, 'off')
    monkeypatch.setenv(SW1, sw1)
    prompt = resolver_prompt()
    assert sha(prompt) == expected, f'resolver_prompt() differs from {BASE} with SW1={sw1}'
    assert '对话里后面跟着' not in prompt


def test_k3_reference_prompt_constant_is_unchanged():
    assert sha(REFERENCE_PROMPT) == BASE_REFERENCE_PROMPT_SHA
