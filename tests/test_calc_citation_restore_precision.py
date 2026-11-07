"""A calculation citation survives reopening the conversation when its recorded value agrees with the
recomputed one at the recorded value's own display precision; a real difference still expires it.

No database: the calculation branch of ``_restore_citations`` reads only the citations it is given, and the
source here is a ``market_quote`` (passed through without a lookup).  Run with ``--noconftest`` when the
disposable Postgres used by ``tests/conftest.py`` is unavailable.
"""
import pytest

from app.agent_chat_stream import _restore_citations
from app.agent_workflow.calculation import agrees_at_recorded_precision

SOURCE_QUOTE = ('TSLA table: 3218 deliveries, 1258.41 revenue, 391.05 margin, 19.50 change, '
                '1259.9 peak, 388.0 floor.')


def _source():
    return {'ordinal': 1, 'source_type': 'market_quote', 'quote': SOURCE_QUOTE, 'title': 'quote', 'section': ''}


def _calc(ordinal, expression, bound, recorded):
    """A calculation citation as the chat stored it: the expression, its bound inputs, and the recorded value."""
    inputs = [{'name': name, 'value': value, 'source_ordinal': 1} for name, value in bound.items()]
    return {'ordinal': ordinal, 'source_type': 'calculation', 'derived': True, 'title': '可复核计算',
            'quote': str(recorded),
            'calculation': {'expression': expression, 'inputs': inputs, 'value': recorded,
                            'parents': [1], 'derived': True}}


def _restored_type(expression, bound, recorded):
    restored = _restore_citations([_source(), _calc(2, expression, bound, recorded)], 'guest')
    return restored[1]['source_type']


# The four measured production samples (turn dab018fa): recorded at display precision, recomputed at full.
@pytest.mark.parametrize('expression,bound,recorded', [
    ('a', {'a': '3218'}, '3218'),          # 3218 vs 3218.00  (representation only)
    ('a', {'a': '1258.41'}, '1258.4'),     # 1258.4 vs 1258.41 (one-decimal display)
    ('a', {'a': '391.05'}, '391.1'),       # 391.1 vs 391.05 (half-up at one decimal)
    ('-a', {'a': '19.5'}, '-19.5'),        # -19.5 vs -19.50 (representation only)
])
def test_measured_equivalent_calculations_restore_live(expression, bound, recorded):
    assert _restored_type(expression, bound, recorded) == 'calculation'


# Real differences beyond the recorded precision must still expire the citation.
@pytest.mark.parametrize('expression,bound,recorded', [
    ('a', {'a': '1259.9'}, '1258.4'),      # 1258.4 vs 1259.9
    ('a', {'a': '388.0'}, '391.1'),        # 391.1 vs 388.0
])
def test_real_differences_still_expire_the_citation(expression, bound, recorded):
    assert _restored_type(expression, bound, recorded) == 'unavailable'


def test_forged_recorded_value_still_expires_when_inputs_are_unchanged():
    # Same inputs, recorded value changed to a different figure: must not be accepted.
    assert _restored_type('a', {'a': '1258.41'}, '1258.5') == 'unavailable'


@pytest.mark.parametrize('recorded,recomputed,expected', [
    ('3218', '3218.00', True),
    ('-19.5', '-19.50', True),
    ('1258.4', '1258.41', True),
    ('391.1', '391.05', True),
    (3218, '3218.00', True),               # int recorded
    (1258.4, '1258.41', True),             # float recorded, no binary noise leaks in
    ('1258.4', '1259.9', False),
    ('391.1', '388.0', False),
    ('1258.4', '1258.35', True),           # half-up at the recorded one decimal
    ('1258.4', '1258.34', False),          # rounds to 1258.3
    ('0.5', '0.4', False),
    (None, '3218.00', False),              # recorded value missing
    ('3218', None, False),                 # recompute missing
    ('not-a-number', '3218.00', False),
    (True, '1.00', False),                 # a bool is not a figure
])
def test_precision_agreement_rule(recorded, recomputed, expected):
    assert agrees_at_recorded_precision(recomputed, recorded) is expected
