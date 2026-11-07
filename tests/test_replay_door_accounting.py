import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from scripts import claim_replay_185 as replay
from scripts import run_trap_pack as trap


def make_result(verdict, candidates):
    return SimpleNamespace(status='ok', verdict=verdict, subtype=None, quote_verified=verdict == 'contradiction',
                           reason='', quote='', latency_ms=0, error_code=None, attribution_candidates=candidates)


def run_item(monkeypatch, result):
    monkeypatch.setattr(replay, 'judge_claims', AsyncMock(return_value=result))
    monkeypatch.setattr(replay, 'review_attribution', AsyncMock(return_value={'status': 'ok', 'passed': True}))
    monkeypatch.setattr(replay, 'review_candidate', AsyncMock(return_value={'status': 'ok', 'passed': True}))
    item = {'turn': 'turn', 'idx': 0, 'gold': 'problem', 'gold_raw': 'problem', 'text': '', 'sources': []}
    return asyncio.run(replay.judge_item(item, {}, asyncio.Semaphore(1), 1))


def test_attribution_pass_is_counted_without_opening_door(monkeypatch):
    row = run_item(monkeypatch, make_result('supported', [{'text': 'figure'}]))
    assert row['door_open'] is False
    assert row['attribution_reviews'][0]['passed'] is True
    assert replay.summarize([row], 'none')['attribution_reviews_passed'] == 1
    row['class'] = 'T1'
    summary = trap.summarize([row])['T1']
    assert summary['door_open'] == 0
    assert summary['attribution_reviews_passed'] == 1


def test_contradiction_review_pass_still_opens_door(monkeypatch):
    row = run_item(monkeypatch, make_result('contradiction', []))
    assert row['door_open'] is True
    summary = replay.summarize([row], 'none')
    assert summary['problem_door_open'] == 1
    assert summary['attribution_reviews_passed'] == 0
