"""FP0 slice b (WP0 steps 6, 7, 11): the judge's code flags read audit.legacy_review, the judge keeps
judging past its report target, and the citation scores say when they came from the legacy check."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent_workflow.claim_judge import JudgeResult
from app.agent_workflow.claim_shadow import (
    _TASKS,
    _extract_code_flags,
    maybe_schedule,
    reset_state,
    set_test_judge_fn,
    set_test_resolve_fn,
)

REJECTED = {'line': 'AMD 开盘价为 999 美元 [1]。', 'reason': 'unsupported_numeric_claim', 'numbers': ['999']}
HINT = {'line': '公司 CEO 已辞职 [1]。', 'reason': 'event_not_in_source', 'numbers': [], 'ordinal': 1, 'snippet': 'x'}
POLARITY = {'count': 1, 'items': [{'line': '收入下降 [1]。'}]}
EVENT = {'count': 1, 'items': [{'line': '公司 CEO 已辞职 [1]。'}]}
EXPECTED = {'polarity_conflict': [], 'event_not_in_source': [], 'answer_issues': ['unsupported_numeric_claim'],
            'unverified_lines': 2}


def _baseline_shape():
    """A row as the pre-S0 finish stored it: the verdicts at the top of the audit and in the visible list."""
    return {'unverified_lines': [dict(REJECTED), dict(HINT)],
            'audit': {'answer_issues': ['unsupported_numeric_claim'], 'insufficient_evidence_lines': 1,
                      'polarity_conflict': dict(POLARITY), 'event_not_in_source': dict(EVENT)}}


def _s0_shape():
    """The same verdicts as the S0 finish writes them: under audit.legacy_review, with the visible list empty."""
    return {'unverified_lines': [],
            'audit': {'legacy_review': {'version': 'legacy-v1', 'issues': ['unsupported_numeric_claim'],
                                        'rejected_lines': [{'line': REJECTED['line'], 'reason': REJECTED['reason']}],
                                        'unverified_lines': [dict(REJECTED)], 'hints': [dict(HINT)],
                                        'insufficient_evidence_lines': 1, 'scope': {},
                                        'polarity_conflict': dict(POLARITY), 'event_not_in_source': dict(EVENT)}}}


def test_s0_shape_gives_the_same_code_flags_as_the_baseline_shape():
    assert _extract_code_flags(_s0_shape()) == _extract_code_flags(_baseline_shape()) == EXPECTED


def test_list_shaped_polarity_and_event_items_read_the_same_from_either_shape():
    polarity = [{'sentence': '收入下降 [1]。'}]
    event = ['公司 CEO 已辞职']
    base = _baseline_shape()
    base['audit']['polarity_conflict'] = list(polarity)
    base['audit']['event_not_in_source'] = list(event)
    s0 = _s0_shape()
    s0['audit']['legacy_review']['polarity_conflict'] = list(polarity)
    s0['audit']['legacy_review']['event_not_in_source'] = list(event)
    flags = _extract_code_flags(s0)
    assert flags == _extract_code_flags(base)
    assert flags['polarity_conflict'] == ['收入下降 [1]。'] and flags['event_not_in_source'] == ['公司 CEO 已辞职']


def test_a_row_without_legacy_review_falls_back_to_the_top_level_keys():
    assert _extract_code_flags(_baseline_shape()) == EXPECTED


def test_legacy_review_wins_over_stale_top_level_keys():
    row = _s0_shape()
    row['audit']['answer_issues'] = ['stale_top_level']
    row['audit']['unverified_lines'] = ['stale', 'stale', 'stale']
    assert _extract_code_flags(row) == EXPECTED


@pytest.mark.parametrize('row', [{}, {'audit': None}, {'audit': {}}, {'audit': {'legacy_review': None}},
                                 {'audit': {'legacy_review': {}}}])
def test_neither_source_present_gives_empty_flags_without_error(row):
    assert _extract_code_flags(row) == {'polarity_conflict': [], 'event_not_in_source': [],
                                        'answer_issues': [], 'unverified_lines': 0}


def test_a_hint_on_a_sentence_already_listed_is_not_counted_twice():
    row = _s0_shape()
    legacy = row['audit']['legacy_review']
    legacy['hints'] = [dict(REJECTED), dict(HINT), dict(HINT)]
    assert _extract_code_flags(row)['unverified_lines'] == 2


# ---- WP0 step 7: the judge keeps judging past its report target ---------------------------------


@pytest.fixture
def shadow_env(monkeypatch, tmp_path):
    reset_state()
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_TARGET_TURNS", "1")
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)
    set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash",
                                                "api_key": "fake"}))
    yield tmp_path
    reset_state()


def _turn(n):
    return {"turn_id": f"t{n}", "answer": f"公司第{n}季度营收增长 [1]。",
            "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}],
            "status": "succeeded"}


def test_reaching_the_target_writes_one_marker_and_judging_goes_on(shadow_env):
    async def _run():
        judge = AsyncMock(return_value=JudgeResult(status="ok", verdict="supported"))
        set_test_judge_fn(judge)
        for n in range(3):
            maybe_schedule(_turn(n), MagicMock(unattended=False), {})
            await asyncio.gather(*list(_TASKS))

        records = [json.loads(line) for path in shadow_env.glob("*.jsonl")
                   for line in path.read_text(encoding="utf-8").splitlines()]
        # Every turn is judged, including the ones past the target.
        assert judge.await_count == 3
        # The marker is written once, and it carries the target and the counted turns at that point.
        markers = [r for r in records if r["outcome"] == "experiment_target_reached"]
        assert len(markers) == 1
        assert markers[0]["target_turns"] == 1 and markers[0]["counted_turns"] == 1
        assert markers[0]["counted"] is False
        # Counting continues past the target.
        assert sum(1 for r in records if r["counted"] is True) == 3
        # The target path never produces a STOP file.
        assert not (shadow_env / "STOP").exists()

    asyncio.run(_run())


# ---- WP0 step 11: the citation scores read legacy_review and say so ----------------------------

from app import observability  # noqa: E402
from app.agent_workflow.direct import run_direct_turn  # noqa: E402
from app.agent_workflow.state import AgentRuntimeContext  # noqa: E402


@pytest.fixture
def traced(monkeypatch):
    recorded = {'scores': [], 'metadata': []}
    sentinel = object()
    monkeypatch.setattr(observability, 'start_turn', lambda **_kwargs: sentinel)
    monkeypatch.setattr(observability, 'score',
                        lambda trace, name, value, *, comment=None: recorded['scores'].append((name, value, comment)))
    monkeypatch.setattr(observability, 'end_trace',
                        lambda trace, *, output=None, metadata=None, error=None: recorded['metadata'].append(metadata))
    return recorded


async def _emit(_event):
    return None


def _priced_turn(answer):
    """A route D turn that reads one price row and answers with the given text."""
    steps = iter([{'tool_calls': [{'id': 'price', 'function': {'name': 'query_stock_prices', 'arguments': '{"symbol":"AMD"}'}}]},
                  {'content': answer}])
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: 'D', decider=lambda *_: next(steps),
                              executor=lambda *_: {'ok': True, 'data': [{'id': 'p', 'symbol': 'AMD', 'close': 100}]})
    return asyncio.run(run_direct_turn('AMD 收盘价', ctx, emit=_emit))


def test_legacy_sourced_scores_are_marked_legacy_and_code_side_counts_still_come(traced):
    result = _priced_turn('AMD 收盘价为 999 美元 [1]。')
    legacy = result['audit']['legacy_review']
    names = {name for name, _value, _comment in traced['scores']}
    # The code-side counts are still produced.
    assert {'citation_verified', 'citation_unverified'} <= names
    verified = next(value for name, value, _c in traced['scores'] if name == 'citation_verified')
    assert verified == len(result['citations'])
    # The unverified count is the one the legacy check gave.
    flagged = [item for item in legacy['unverified_lines'] if item.get('reason') not in {'polarity_conflict', 'event_not_in_source',
                                                                                       'number_read_from_source', 'number_computed'}]
    expected = len(flagged) or len(legacy['issues'])
    unverified = next(value for name, value, _c in traced['scores'] if name == 'citation_unverified')
    assert unverified == expected
    # The legacy marker is on the scores' trace: a score with the comment, and the trace metadata.
    assert ('legacy_review', 1, 'legacy=True') in traced['scores']
    assert traced['metadata'][-1].get('legacy') is True


def test_a_turn_without_legacy_review_has_no_legacy_marker(traced, monkeypatch):
    steps = iter([{'content': '你好，我可以帮你查看公司资料。'}])
    ctx = AgentRuntimeContext('custom', 'test', 'dummy', classifier=lambda _: 'B', decider=lambda *_: next(steps))
    result = asyncio.run(run_direct_turn('你好', ctx, emit=_emit))
    assert 'legacy_review' not in result['audit']
    names = {name for name, _value, _comment in traced['scores']}
    assert 'citation_verified' in names
    assert ('legacy_review', 1, 'legacy=True') not in traced['scores']
    assert 'legacy' not in traced['metadata'][-1]
