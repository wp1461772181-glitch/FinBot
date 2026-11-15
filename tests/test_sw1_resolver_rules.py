"""SW1 items 2 and 3, resolver side (spec §8.2 T30–T35, §8.3 E03).

The two resolver prompts gain a period rule and a premise rule behind FINBOT_SW1_RESOLVER_RULES; a rewrite that pins a
quarter still in progress, when the user's own words named none, leaves the model a period_note and clears the period.
The original prompt texts are pinned in tests/fixtures/sw1_prompts_v0.json (extracted from d2e502c).
"""
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.agent_workflow import direct
from app.agent_workflow.direct import (CLASSIFY_PROMPT, REFERENCE_PROMPT, RESOLVER_RULE_TEXT, classify_prompt, resolver_prompt,
                                      unfinished_period)
from app.agent_workflow.state import AgentRuntimeContext

V0 = json.loads((Path(__file__).parent / 'fixtures' / 'sw1_prompts_v0.json').read_text(encoding='utf-8'))
SWITCH = 'FINBOT_SW1_RESOLVER_RULES'
PERIOD_RULE = '最近一个已披露的季度'
PREMISE_RULE = '用户所说的'
PREMISE_CLASSIFY = 'A form the user mentions only while describing a document they assume exists'
ANCHOR = 'Keep data-dependent wording such as "最新一期" or "最近一期" as it is; never guess a specific period. '


@pytest.fixture(autouse=True)
def switch_on(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


def current_quarter():
    """The calendar quarter in progress today (Asia/Kuala_Lumpur, as the rule reads it), its first and last day."""
    today = datetime.now(direct.KL_TZ).date()
    first_month = 3 * ((today.month - 1) // 3) + 1
    start = date(today.year, first_month, 1)
    following = date(today.year + (first_month + 3 > 12), (first_month + 2) % 12 + 1, 1)
    return start, following - timedelta(days=1), today


def test_the_resolver_prompt_gets_the_period_and_premise_rules_when_on():  # T30 on
    prompt = resolver_prompt()
    assert PERIOD_RULE in prompt and PREMISE_RULE in prompt
    # The rules follow the existing data-dependent sentence, and nothing else of the original text moves.
    assert prompt == V0['REFERENCE_PROMPT'].replace(ANCHOR, ANCHOR + RESOLVER_RULE_TEXT, 1)


def test_the_resolver_prompt_is_the_original_text_when_off(monkeypatch):  # T30 off
    monkeypatch.setenv(SWITCH, 'off')
    assert resolver_prompt() == V0['REFERENCE_PROMPT'] == REFERENCE_PROMPT


def test_the_classifier_prompt_gets_the_premise_sentence_when_on_and_is_original_when_off(monkeypatch):  # T35
    assert PREMISE_CLASSIFY in classify_prompt()
    assert classify_prompt().startswith(V0['CLASSIFY_PROMPT'])
    monkeypatch.setenv(SWITCH, 'off')
    assert classify_prompt() == V0['CLASSIFY_PROMPT'] == CLASSIFY_PROMPT


def test_the_constants_themselves_are_the_original_texts():
    assert REFERENCE_PROMPT == V0['REFERENCE_PROMPT']
    assert CLASSIFY_PROMPT == V0['CLASSIFY_PROMPT']


def test_an_unfinished_quarter_the_user_did_not_name_is_flagged():  # T31 unit
    start, end, today = current_quarter()
    canonical = f'半导体行业 {start.isoformat()} 至 {end.isoformat()} 营收增速'
    assert unfinished_period(canonical, '半导体行业这季营收增速', today) == {
        'start': start.isoformat(), 'end': end.isoformat(), 'today': today.isoformat()}


def test_a_quarter_the_user_named_is_not_flagged():  # T32
    canonical = '半导体行业 2026-10-01 至 2026-12-31 营收预期'
    assert unfinished_period(canonical, '2026 年第四季度半导体营收预期', date(2026, 11, 15)) is None


def test_a_quarter_already_ended_is_not_flagged():  # T33
    canonical = '半导体行业 2026-07-01 至 2026-09-30 营收增速'
    assert unfinished_period(canonical, '半导体行业上季营收增速', date(2026, 11, 15)) is None


def test_a_date_the_user_wrote_is_not_flagged():
    canonical = '半导体行业 2026-10-01 至 2026-12-31 营收增速'
    assert unfinished_period(canonical, '2026-10-01 起的半导体营收增速', date(2026, 11, 15)) is None


def refusal_model(messages, *_args, **_kwargs):
    """Only the refusal prompt is answered; the other model calls get an empty reply."""
    return {}, {'role': 'assistant', 'content': ''}


async def no_model(provider, model, key, messages, schemas, base_url=None, **_kwargs):
    return refusal_model(messages)


def run_pinned_turn(monkeypatch, question, canonical, period):
    """A route A turn whose resolver rewrote a deictic quarter into the calendar quarter in progress."""
    monkeypatch.setattr(direct, 'decision_request', no_model)
    seen, audits = [], []
    original = direct.Turn.finish

    def spy(self, *args, **kwargs):
        audits.append(dict(self.audit))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(direct.Turn, 'finish', spy)

    def decide(messages, tools):
        seen.append(messages)
        return {'content': ''}

    async def emit(_):
        pass
    ctx = AgentRuntimeContext('custom', 'test', 'dummy',
                              classifier=lambda _: {'category': 'A', 'mode': 'none', 'period': period, 'days_back': None},
                              resolver=lambda payload: {'relationship': 'new', 'canonical_question': canonical},
                              decider=decide, executor=lambda name, args: {'ok': True, 'data': []})
    asyncio.run(direct.run_direct_turn(question, ctx, emit=emit))
    return seen, audits


def period_notes(seen):
    """The understanding hints the model was shown, read back as JSON."""
    notes = []
    for messages in seen:
        for m in messages:
            if isinstance(m, dict) and m.get('role') == 'system' and str(m.get('content') or '').startswith(direct.UNDERSTANDING_NOTE):
                notes.append(json.loads(str(m['content'])[len(direct.UNDERSTANDING_NOTE):]))
    return notes


def test_a_rewrite_pinned_to_the_quarter_in_progress_gets_a_note_and_loses_its_period(monkeypatch):  # T31, E03
    start, end, _ = current_quarter()
    canonical = f'半导体行业 {start.isoformat()} 至 {end.isoformat()} 营收增速'
    period = f'{start.isoformat()} 至 {end.isoformat()}'
    seen, audits = run_pinned_turn(monkeypatch, '半导体行业这季营收增速', canonical, period)
    assert audits[-1]['resolver_period_unfinished']['end'] == end.isoformat()
    assert audits[-1].get('scope_period_cleared') is True
    hints = period_notes(seen)
    assert hints and 'period_note' in hints[0]
    assert end.isoformat() in hints[0]['period_note'] and '还没有结束' in hints[0]['period_note']


def test_the_period_note_is_absent_when_the_switch_is_off(monkeypatch):  # T34
    monkeypatch.setenv(SWITCH, 'off')
    start, end, _ = current_quarter()
    canonical = f'半导体行业 {start.isoformat()} 至 {end.isoformat()} 营收增速'
    seen, audits = run_pinned_turn(monkeypatch, '半导体行业这季营收增速', canonical, f'{start.isoformat()} 至 {end.isoformat()}')
    assert 'resolver_period_unfinished' not in audits[-1] and not audits[-1].get('scope_period_cleared')
    assert all('period_note' not in hint for hint in period_notes(seen))
