"""FP7 step 1: a number glued to a letter suffix is read whole or not at all (never shortened)."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app import agent_context_summary
from app.agent_workflow import claim_numeric, evidence, semantic, unverified
from app.agent_workflow.calculation import source_numbers
from app.agent_workflow.semantic import _FIGURE, figure_tokens, figure_values

WHOLE = 'FINBOT_FP7_WHOLE_TOKEN'


@pytest.fixture(autouse=True)
def _whole_token_on(monkeypatch):
    monkeypatch.delenv(WHOLE, raising=False)


def _old(text):
    """What the pre-FP7 reader gave (the switch off reproduces it exactly)."""
    return _FIGURE.findall(text)


# Rows whose reading changes: (text, tokens, figure_values, source_numbers).
CHANGED = [
    ('401.21x', [('401.21', 'x')], {401.21}, {Decimal('401.21')}),
    ('345x', [('345', 'x')], {345.0}, {Decimal('345')}),
    ('12.5x', [('12.5', 'x')], {12.5}, {Decimal('12.5')}),
    ('0.5x', [('0.5', 'x')], {0.5}, {Decimal('0.5')}),
    ('2.5X', [('2.5', 'X')], {2.5}, {Decimal('2.5')}),
    ('10x-15x', [('10', 'x'), ('15', 'x')], {10.0, 15.0}, {Decimal('10'), Decimal('15')}),
    ('3x', [('3', 'x')], {3.0}, {Decimal('3')}),
    # 1920 is a year-shaped period token to PERIOD_TEXT, removed before the figure is read: the final value is 1080.
    ('1920x1080', [('1920', 'x'), ('1080', '')], {1080.0}, {Decimal('1080')}),
    # The period reader removes the whole "2025Q4" before any figure is read: the final value is empty.
    ('2025Q4', [('4', '')], set(), set()),
]

# Rows that now read nothing (the old reader read a shortened number from each).
NOTHING = ['1.2T', '35bps', '100bp', '8.5pct', '4.5pp', '1.2w', '24h', '15min', '15mm', '100USD', '13F', '20th']

# Rows that must read exactly as before (the switch-off reader is the old one, so equality is the assertion).
UNCHANGED = ['1.5B', '20k', '3M', '100亿', '3.5 billion', '$1.5bn', '191.71 亿',
             '10-Q', '8-K', '401(k)', 'Form 10K', 'USD100', 'A320', 'FY25', '1.2.3', '2025-11-07']

# Literal values for the unchanged rows the brief names (guards against a silent change to either reader).
UNCHANGED_VALUES = {
    '1.5B': {1.5e9}, '20k': {2e4}, '3M': {3e6}, '100亿': {1e10}, '3.5 billion': {3.5e9},
    '$1.5bn': {1.5e9}, '191.71 亿': {19171000000.0}, '10-Q': {10.0}, '8-K': {8.0}, '401(k)': {401.0},
    'Form 10K': {10000.0}, 'USD100': {100.0}, 'A320': {320.0}, 'FY25': set(), '1.2.3': {1.2, 3.0},
    # PERIOD_TEXT removes the year: FY25 is a period and 2025 is a year, so neither is a figure.
    '2025-11-07': {7.0, 11.0},
}


@pytest.mark.parametrize('text,tokens,values,numbers', CHANGED, ids=[row[0] for row in CHANGED])
def test_changed_rows_read_the_whole_token(text, tokens, values, numbers):
    assert figure_tokens(text) == tokens
    assert figure_values(text) == values
    assert source_numbers(text) == numbers


@pytest.mark.parametrize('text', NOTHING)
def test_glued_suffix_reads_nothing(text):
    assert figure_tokens(text) == []
    assert figure_values(text) == set()
    assert source_numbers(text) == set()


@pytest.mark.parametrize('text', UNCHANGED)
def test_unchanged_rows_read_exactly_as_before(text, monkeypatch):
    assert figure_tokens(text) == _old(text)
    assert source_numbers(text) == _with_switch(text, source_numbers, monkeypatch, whole=False)
    assert figure_values(text) == _with_switch(text, figure_values, monkeypatch, whole=False)
    assert figure_values(text) == UNCHANGED_VALUES[text]


def _with_switch(text, reader, monkeypatch, *, whole):
    monkeypatch.setenv(WHOLE, 'on' if whole else 'off')
    try:
        return reader(text)
    finally:
        monkeypatch.delenv(WHOLE, raising=False)


def test_switch_off_restores_the_old_shortened_reading(monkeypatch):
    """The rollback path: with the switch off, 401.21x reads 401.2 again, as it did before FP7."""
    monkeypatch.setenv(WHOLE, 'off')
    assert figure_tokens('401.21x') == _old('401.21x') == [('401.2', '')]
    assert figure_values('401.21x') == {401.2}
    assert source_numbers('401.21x') == {Decimal('401.2')}


def test_negatives_fixture_none_of_must_not_bind_is_read():
    """Each plain must_not_bind value is absent from the source numbers of the source clause.

    The fixture texts carry the claim too ("...; a claimed span instead says 99."), so a value
    can appear in the text as a claim.  The source is the clause before the first ';', and the
    value must not be read from it.  Entries tagged ``value@key`` (20@1, 7@A-2025) are binding-level
    negatives: the value does appear in the text for another source, so they are not asserted here.
    """
    path = Path(__file__).parent / 'fixtures' / 'calc_pack' / 'negatives.json'
    checked = 0
    for entry in json.loads(path.read_text()):
        source_clause = entry['text'].split(';')[0]
        numbers = source_numbers(source_clause)
        for token in entry['must_not_bind']:
            if '@' in token:
                continue
            assert Decimal(token) not in numbers, (source_clause, token)
            checked += 1
    assert checked == 13


# --- figure_values consumers -------------------------------------------------------------------
# The consumer text: a multiple, a decimal multiple, a 10-Q, an accession, and a percentage.
CONSUMER_TEXT = 'Operating ratio 401.21x and coverage 345x; 10-Q accession 0000320193-25-000079; yield2.19%.'
NEW_FIGURES = {401.21, 345.0, 10.0, 2.19}
OLD_FIGURES = {401.2, 34.0, 10.0, 2.19}


def _figures_seen(monkeypatch, patch_target, call, *, whole):
    """What figure_values returned inside one consumer call, with the whole-token switch on or off."""
    monkeypatch.setenv(WHOLE, 'on' if whole else 'off')
    real = semantic.figure_values
    seen = []

    def spy(text, *args, **kwargs):
        out = real(text, *args, **kwargs)
        seen.append(out)
        return out

    monkeypatch.setattr(patch_target, 'figure_values', spy)
    try:
        call()
    finally:
        monkeypatch.delenv(WHOLE, raising=False)
    return seen


def test_claim_numeric_reads_whole_multiples(monkeypatch):
    seen = _figures_seen(monkeypatch, claim_numeric,
                         lambda: claim_numeric.numbers_supported('401.21x and 345x', CONSUMER_TEXT), whole=True)
    assert seen and seen[0] == NEW_FIGURES
    old = _figures_seen(monkeypatch, claim_numeric,
                        lambda: claim_numeric.numbers_supported('401.21x and 345x', CONSUMER_TEXT), whole=False)
    assert old[0] == OLD_FIGURES


def test_unverified_holds_whole_multiples_and_not_the_shortened_ones():
    citations = [{'ordinal': 1, 'quote': CONSUMER_TEXT}]
    assert unverified._holders(401.21, citations) == [1]
    assert unverified._holders(345.0, citations) == [1]
    assert unverified._holders(401.2, citations) == []
    assert unverified._holders(34.0, citations) == []
    assert unverified._holders(10.0, citations) == [1]
    assert unverified._holders(2.19, citations) == [1]
    assert unverified._holders(79.0, citations) == []   # accession digits stay excluded
    assert unverified._holders(25.0, citations) == []


def test_evidence_user_figure_values_reads_whole_multiples(monkeypatch):
    monkeypatch.setenv(WHOLE, 'on')
    values = evidence.user_figure_values(CONSUMER_TEXT)
    assert {401.21, 345.0, 10.0, 2.19} <= values
    assert 401.2 not in values and 34.0 not in values
    assert 79.0 not in values and 25.0 not in values


def test_agent_context_summary_reads_whole_multiples(monkeypatch):
    seen = _figures_seen(monkeypatch, semantic,
                         lambda: agent_context_summary._summary_drift(CONSUMER_TEXT, CONSUMER_TEXT), whole=True)
    assert seen[0] == NEW_FIGURES
    old = _figures_seen(monkeypatch, semantic,
                        lambda: agent_context_summary._summary_drift(CONSUMER_TEXT, CONSUMER_TEXT), whole=False)
    assert old[0] == OLD_FIGURES
