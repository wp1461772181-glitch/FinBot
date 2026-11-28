"""The evidence gate follows the course's split: recall finds, the model judges.

A source that words the metric differently, or covers a different period, is still shown to the
model with a note.  A source about another company, a broken body, or one outside the freshness
window the user asked for is not shown at all.
"""
from __future__ import annotations

import asyncio
import json

from app.agent_workflow.evidence import SOFT_GATE_CHECKS, gate_row

APPLE = {'symbol': 'AAPL', 'title': 'AAPL 10-K', 'filed_at': '2025-10-31', 'report_period': 'FY2025',
         'excerpt': 'Apple Inc. reported net sales of $391,035 million. Gross margin was 46.2% '
                    'for the year ended September 27, 2025.'}


def test_a_differently_worded_metric_is_accepted_with_its_reservation():
    ok, reason = gate_row('苹果毛利率', APPLE, company='Apple', symbol='AAPL', metrics=['毛利率'], soft=True)
    assert ok and reason == 'soft:requested_metric_missing:毛利率'


def test_a_different_reporting_period_is_accepted_with_its_reservation():
    ok, reason = gate_row('苹果 FY2024 营收', APPLE, company='Apple', symbol='AAPL',
                          metrics=['revenue'], period='FY2024', soft=True)
    assert ok and reason == 'soft:requested_period_missing'


def test_the_wrong_company_stays_a_hard_stop():
    """Attributing one company's numbers to another is the error worth refusing."""
    other = {'symbol': 'MSFT', 'title': 'MSFT 10-K', 'excerpt': 'Microsoft reported revenue growth.'}
    ok, reason = gate_row('苹果营收', other, company='Apple', symbol='AAPL', metrics=['revenue'], soft=True)
    assert not ok and reason == 'requested_entity_missing'


def test_a_broken_body_stays_a_hard_stop():
    broken = {**APPLE, 'body_hash_valid': False}
    ok, reason = gate_row('苹果营收', broken, company='Apple', symbol='AAPL', metrics=['revenue'], soft=True)
    assert not ok and reason == 'invalid_source_body'


def test_an_explicit_freshness_window_stays_a_hard_filter():
    """The window is the user's own constraint, not a relevance judgement."""
    old = {'symbol': 'AAPL', 'title': 'old', 'excerpt': 'Apple revenue rose.',
           'published_at': '2025-01-01T00:00:00+00:00'}
    ok, reason = gate_row('苹果营收', old, company='Apple', symbol='AAPL', metrics=['revenue'],
                          days_back=7, soft=True)
    assert not ok and reason == 'requested_time_window_missing'


def test_only_wording_checks_are_soft():
    assert SOFT_GATE_CHECKS == {'requested_metric_missing', 'requested_period_missing', 'weak_question_coverage'}


