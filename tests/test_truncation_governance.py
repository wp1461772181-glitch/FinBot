"""Truncation governance: a checker or a model never reasons over silently cut text.

Presentation may truncate; verification and model decision-making may not, unless the cut is explicit
(and recorded in ``audit.truncation_events``).
"""
import json
from datetime import UTC, datetime

from app import observability
from app.agent_web_research import MAX_EXCERPT, _focus_source, extract_page
from app.agent_workflow import evidence, truncation
from app.agent_workflow.direct import Turn


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


def test_a_stored_citation_without_its_full_text_is_marked_partial():
    stored = evidence.persistable_citation({'ordinal': 1, 'quote': 'x', 'check_text': 'x' * 9000})
    assert 'check_text' not in stored and stored['evidence_incomplete'] is True
    plain = {'ordinal': 2, 'quote': 'y'}
    assert evidence.persistable_citation(plain) is plain
    sets = [{'id': 's', 'rows': [{'excerpt': 'a', '_evidence_text': 'a' * 9000}, {'excerpt': 'b'}]}]
    rows = evidence.persistable_result_sets(sets)[0]['rows']
    assert '_evidence_text' not in rows[0] and rows[0]['evidence_incomplete'] is True and rows[1] == {'excerpt': 'b'}


def _turn():
    turn = Turn.__new__(Turn)
    turn.audit = {}
    turn.feedback = []
    turn.sets = []
    return turn


def _observation(n, rows=3, size=3000):
    return {'name': 'web_research', 'arguments': {'query': f'q{n}'}, 'accepted_evidence': True,
            'result': {'ok': True, 'data': [{'citation': f'[{n * 10 + r}]', 'excerpt': 'x' * size} for r in range(rows)]}}


def test_the_model_evidence_payload_cuts_at_whole_sources_and_records_the_event():
    turn = _turn()
    accepted = [_observation(n) for n in range(1, 6)]          # 15 sources of ~3000 characters
    text = turn.evidence_payload(accepted, budget=20000)
    data = json.loads(text[text.index('[{"name"'):])             # whole, parseable structure: nothing cut mid-text
    kept_rows = [row for obs in data for row in obs['result']['data']]
    assert kept_rows and all(len(row['excerpt']) == 3000 for row in kept_rows)
    assert 'Left out for length' in text and '[11]' in text.split('Left out for length')[1].split('[{"name"')[0]
    assert kept_rows[-1]['citation'] == '[52]'                  # the newest source has priority
    events = turn.audit['truncation_events']
    assert len(events) == 1 and events[0]['site'] == 'tool_messages.accepted_evidence'
    assert events[0]['original_chars'] > 20000 > events[0]['kept_chars'] > 0
    assert events[0]['omitted_sources'] == 15 - len(kept_rows)


def test_no_event_when_everything_fits():
    turn = _turn()
    text = turn.evidence_payload([_observation(1, rows=1, size=100)], budget=20000)
    assert 'Left out' not in text and 'truncation_events' not in turn.audit


def test_status_and_catalogue_payloads_cut_whole_items():
    turn = _turn()
    turn.feedback = [{'name': f't{i}', 'error_code': 'zero_evidence', 'hint': 'h' * 900} for i in range(20)]
    status = turn.status_payload(budget=5000)
    kept = json.loads(status.split(': ', 1)[1])
    assert 0 < len(kept) < 20 and kept[-1]['name'] == 't19' and all(len(k['hint']) == 900 for k in kept)
    turn.sets = [{'id': f'set{i}', 'scope': {}, 'rows': [{'title': 't' * 50, 'url': 'u' * 100, 'excerpt': 'p' * 400} for _ in range(10)]}
                 for i in range(6)]
    catalogue = turn.catalogue_payload(budget=3000)
    sets = json.loads(catalogue.split(': ', 1)[1])
    assert 0 < len(sets) < 6 and sets[-1]['id'] == 'set5'
    assert {e['site'] for e in turn.audit['truncation_events']} == {
        'tool_messages.feedback', 'tool_messages.result_catalogue', 'tool_messages.result_catalogue.items'}


def test_memory_and_tool_result_cuts_are_at_item_boundaries():
    text, original, kept, dropped = truncation.cut_lines('\n'.join(f'line {i} ' + 'm' * 90 for i in range(100)), 1000)
    assert dropped > 0 and original > kept and all(line.endswith('m' * 90) for line in text.split('\n'))
    content = json.dumps({'ok': True, 'data': [{'excerpt': 'e' * 2000, 'n': i} for i in range(5)]})
    compact = json.loads(truncation.compact_tool_content(content, 6000))
    assert compact['truncated'] is True and compact['omitted_items'] == 5 - len(compact['data'])
    assert all(len(row['excerpt']) == 2000 for row in compact['data'])


def test_record_updates_one_event_per_site():
    audit = {}
    truncation.record(audit, 'a', 100, 50)
    truncation.record(audit, 'a', 120, 60)
    assert audit['truncation_events'] == [{'site': 'a', 'original_chars': 120, 'kept_chars': 60, 'count': 2}]
    assert truncation.record(audit, 'b', 10, 10) is None


class _Obs:
    def __init__(self):
        self.scores = {}

    def score_trace(self, name, value, data_type, comment=None):
        self.scores[name] = value


def test_event_count_reaches_the_trace_scores():
    obs = _Obs()
    observability.score_citation_audit(observability.Handle(obs), verified=2, unverified=1, truncation_events=3, insufficient=1)
    assert obs.scores == {'citation_verified': 2.0, 'citation_unverified': 1.0, 'truncation_events': 3.0, 'citation_insufficient': 1.0}
