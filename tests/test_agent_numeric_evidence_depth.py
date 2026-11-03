from app.agent_workflow import evidence

PAGE=('Lilly reported Q3 revenue of $24.4 billion. '+'Filler sentence about the market. '*30
      +'Zepbound sales were $5.3 billion and Mounjaro $10.7 billion.')


def _row(**extra):
    return {'title':'Lilly Q3','url':'https://example.com/lly','source_type':'web','truncated':True,
            'excerpt':'Lilly reported Q3 revenue of $24.4 billion.','fetched_at':'2026-11-03T00:00:00+00:00',**extra}


def test_hundred_million_claim_matches_a_billions_source_only_when_equal():
    cites=[{'ordinal':1,'quote':'Mounjaro sales reached $10.7 billion in the quarter.','source_type':'web'}]
    assert evidence.unsupported_number_values('Mounjaro 营收 107 亿美元 [1]',cites)==[]
    assert evidence.unsupported_number_values('Mounjaro 营收 108 亿美元 [1]',cites)==[108e8]


def test_figures_beyond_the_focused_excerpt_are_checked_against_the_cited_page():
    citations=[]
    accepted=evidence.number_rows('web_research',[_row(_evidence_text=PAGE)],citations)
    assert '_evidence_text' not in accepted[0]
    assert citations[0]['quote']==accepted[0]['excerpt']
    assert evidence.unsupported_number_values('Mounjaro 营收 107 亿美元，Zepbound 53 亿美元 [1]',citations)==[]
    # A number the page does not state is still refused.
    assert evidence.unsupported_number_values('Mounjaro 营收 109 亿美元 [1]',citations)==[109e8]


def test_without_the_page_text_a_truncated_source_leaves_the_figure_insufficient():
    # The row says it is a selection (truncated) and carries no page text: the figure may sit in the part
    # that was never stored, so it is 证据不完整, not an unsupported number.
    citations=[]
    evidence.number_rows('web_research',[_row()],citations)
    assert evidence.unsupported_number_values('Mounjaro 营收 107 亿美元 [1]',citations)==[]
    assert evidence.insufficient_number_values('Mounjaro 营收 107 亿美元 [1]',citations)==[107e8]


def test_without_the_page_text_a_complete_source_keeps_the_figure_unsupported():
    citations=[]
    evidence.number_rows('web_research',[_row(truncated=False)],citations)
    assert evidence.unsupported_number_values('Mounjaro 营收 107 亿美元 [1]',citations)==[107e8]
