"""Truncation governance: a checker or a model never reasons over silently cut text.

Presentation may truncate; verification and model decision-making may not, unless the cut is explicit
(and recorded in ``audit.truncation_events``).
"""
import json
from datetime import UTC, datetime

from app import observability
from app.agent_web_research import MAX_EXCERPT, _focus_source, extract_page
from app.agent_workflow import evidence
pass  # (removed import of the old turn)


def _long_page():
    """A page whose figures sit at ~6k and ~30k characters: far beyond the 5000-character excerpt."""
    filler = 'The market moved sideways while analysts debated the outlook for the sector. '
    parts = ['<p>Alpha Corp is a large company.</p>']
    parts += [f'<p>{filler}</p>' for _ in range(85)]
    parts.append('<p>Alpha Corp reported quarterly revenue of $12.3 billion.</p>')
    parts += [f'<p>{filler}</p>' for _ in range(330)]
    parts.append('<p>Alpha Corp segment profit was $4.56 billion for the quarter.</p>')
    return '<html><head><title>Alpha results</title></head><body>' + ''.join(parts) + '</body></html>'


def _web_row(query=None):
    page = extract_page(_long_page(), 'https://example.com/alpha', datetime.now(UTC))
    page['source_type'] = 'web'
    if query:
        _focus_source(page, query, 'Alpha Corp')
    return page


def test_figures_far_beyond_the_excerpt_verify_against_the_cited_page():
    page = _web_row()
    whole = page['_evidence_text']
    assert len(page['excerpt']) <= MAX_EXCERPT and len(whole) > 30000
    assert 6000 < whole.index('$12.3 billion') < 7500 and whole.index('$4.56 billion') > 29000
    citations = []
    evidence.number_rows('web_research', [page], citations)
    cite = citations[0]
    assert len(cite['quote']) <= evidence.QUOTE_DISPLAY_CHARS      # what is shown stays an excerpt
    assert cite['check_text'] == whole and not cite['evidence_incomplete']
    answer = 'Alpha Corp 季度营收 123 亿美元，分部利润 45.6 亿美元 [1]。'
    assert evidence.unsupported_number_values(answer, citations) == []
    assert evidence.insufficient_number_values(answer, citations) == []
    _kept, issues = evidence.reviewed_answer(answer, citations)
    assert issues == []
    # A figure the page does not state is still refused.
    assert evidence.unsupported_number_values('Alpha Corp 季度营收 999 亿美元 [1]。', citations) == [999e8]


def test_a_focused_excerpt_of_a_long_page_is_chosen_from_the_whole_page():
    page = _web_row('Alpha Corp quarterly revenue')
    assert '$12.3 billion' in page['excerpt']       # the sentence 6k characters in is what the model is shown
    assert page['truncated'] is True and len(page['_evidence_text']) > 30000
    citations = []
    evidence.number_rows('web_research', [page], citations)
    assert evidence.unsupported_number_values('Alpha Corp 分部利润 45.6 亿美元 [1]。', citations) == []


def _row(**extra):
    return {'title': 'Lilly Q3', 'url': 'https://example.com/lly', 'source_type': 'web',
            'excerpt': 'Lilly reported Q3 revenue of $24.4 billion.', 'fetched_at': '2026-11-03T00:00:00+00:00', **extra}


def test_a_figure_missing_from_a_truncated_source_is_insufficient_not_unsupported():
    claim = 'Mounjaro 营收 107 亿美元 [1]。'
    partial = []
    evidence.number_rows('web_research', [_row(truncated=True)], partial)
    assert partial[0]['evidence_incomplete'] is True
    assert evidence.number_check(claim, partial) == ([], [107e8])
    assert evidence.unsupported_number_values(claim, partial) == []
    assert evidence.unsupported_numbers(claim, partial) is False and evidence.insufficient_numbers(claim, partial) is True
    _kept, issues = evidence.reviewed_answer(claim, partial)
    assert issues == ['insufficient_numeric_evidence']

    complete = []
    evidence.number_rows('web_research', [_row(truncated=False)], complete)
    assert complete[0]['evidence_incomplete'] is False
    assert evidence.number_check(claim, complete) == ([107e8], [])
    _kept, issues = evidence.reviewed_answer(claim, complete)
    assert issues == ['unsupported_numeric_claim']


def test_a_source_that_declares_itself_partial_makes_a_miss_insufficient():
    cites = []
    evidence.number_rows('search_knowledge', [_row(evidence_incomplete=True, truncated=False)], cites)
    # The declaration moves from the row onto the citation; the row the model sees keeps no flag.
    assert cites[0]['evidence_incomplete'] is True
    assert evidence.number_check('Mounjaro 营收 107 亿美元 [1]。', cites) == ([], [107e8])


def test_unsupported_wins_when_a_figure_is_missing_from_a_complete_and_a_partial_source():
    cites = [{'ordinal': 1, 'quote': 'Revenue was $1 billion.', 'evidence_incomplete': True},
             {'ordinal': 2, 'quote': 'Revenue was $2 billion.'}]
    unsupported, insufficient = evidence.number_check('营收 777 亿美元 [1][2]。', cites)
    assert unsupported == [777e8] and insufficient == []


def test_a_stored_citation_keeps_its_full_checking_text_up_to_the_cap():
    """The full text is stored with the turn, so a later answer's figure can be checked against the source it cites.
    Text over the cap is not kept, and the citation says so; text under it is complete and is not marked."""
    cap = evidence.STORED_CHECK_TEXT_CHARS
    kept = evidence.persistable_citation({'ordinal': 1, 'quote': 'x', 'check_text': 'x' * 9000})
    assert kept['check_text'] == 'x' * 9000 and 'evidence_incomplete' not in kept
    at_cap = {'ordinal': 2, 'quote': 'y', 'check_text': 'y' * cap}
    assert evidence.persistable_citation(at_cap)['check_text'] == 'y' * cap
    over = evidence.persistable_citation({'ordinal': 3, 'quote': 'z', 'check_text': 'z' * (cap + 1)})
    assert 'check_text' not in over and over['evidence_incomplete'] is True and over['quote'] == 'z'
    plain = {'ordinal': 4, 'quote': 'w'}
    assert evidence.persistable_citation(plain) is plain
    sets = [{'id': 's', 'rows': [{'excerpt': 'a', '_evidence_text': 'a' * 9000}, {'excerpt': 'b'},
                                 {'excerpt': 'c', '_evidence_text': 'c' * (cap + 1)}]}]
    rows = evidence.persistable_result_sets(sets)[0]['rows']
    assert rows[0]['_evidence_text'] == 'a' * 9000 and 'evidence_incomplete' not in rows[0]
    assert rows[1] == {'excerpt': 'b'}
    assert '_evidence_text' not in rows[2] and rows[2]['evidence_incomplete'] is True


def test_the_legacy_web_hydration_store_still_keeps_no_checking_text():
    """semantic.save_result_set has its own 64 KB cap and is not the turn record: it keeps the old stripping."""
    from app.agent_workflow.semantic import save_result_set
    citation = {'ordinal': 1, 'source_type': 'web', 'source_url': 'https://example.com/a', 'quote': 'Revenue rose 12%.',
                'title': 'A', 'observed_at': '2026-10-12T00:00:00+00:00', 'check_text': 'Revenue rose 12%. ' + 'x' * 100}
    row = {'url': 'https://example.com/a', 'excerpt': 'Revenue rose 12%.', 'body_provenance': 'verified_server_gate',
           'fetched_at': '2026-10-12T00:00:00+00:00', 'title': 'A'}
    saved = save_result_set([], {'ok': True, 'data': [row]}, [citation], owner='o', conversation='c', turn='t',
                            task='k', scope={})
    stored = saved[0]['items'][0]['citation']
    assert 'check_text' not in stored and stored['evidence_incomplete'] is True


def _turn():
    turn = Turn.__new__(Turn)
    turn.audit = {}
    turn.feedback = []
    turn.sets = []
    return turn


def _observation(n, rows=3, size=3000):
    return {'name': 'web_research', 'arguments': {'query': f'q{n}'}, 'accepted_evidence': True,
            'result': {'ok': True, 'data': [{'citation': f'[{n * 10 + r}]', 'excerpt': 'x' * size} for r in range(rows)]}}


class _Obs:
    def __init__(self):
        self.scores = {}

    def score_trace(self, name, value, data_type, comment=None):
        self.scores[name] = value


def test_event_count_reaches_the_trace_scores():
    obs = _Obs()
    observability.score_citation_audit(observability.Handle(obs), verified=2, unverified=1, truncation_events=3, insufficient=1)
    assert obs.scores == {'citation_verified': 2.0, 'citation_unverified': 1.0, 'truncation_events': 3.0, 'citation_insufficient': 1.0}
