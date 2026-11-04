import pytest
from app.agent_workflow.evidence import gate_row,deterministic_confidence_gate

@pytest.mark.parametrize('claim,quote,blocked',[
 ('Tim Cook 离任[1]。','The achievement follows the departure of longtime chief executive Tim Cook.',False),
 ('Tim Cook 辞职[1]。','The departure of Tim Cook was announced.',False),
 ('Tim Cook 离任[1]。','Tim Cook resigned as chief executive.',False),
 ('Tim Cook 离任[1]。','Tim Cook has not resigned.',True),
 ('Tim Cook 没有离任[1]。','The departure of Tim Cook was announced.',True),
 ('John Ternus 上任 CEO[1]。','New chief executive John Ternus takes charge.',False),
 ('John Ternus 接任 CEO[1]。','New chief executive John Ternus takes charge.',False),
 ('John Ternus 被任命为 CEO[1]。','Chief executive John Ternus takes charge.',False),
 ('John Ternus 已经上任 CEO[1]。','John Ternus was appointed CEO and will take office next year.',False),
])
def test_departure_and_role_start_translations_keep_event_strength_and_polarity(claim,quote,blocked):
    # `blocked` now means "gets a polarity_conflict hint": polarity is no longer an unsupported verdict.
    from app.agent_workflow.evidence import polarity_conflicts,unsupported_claims
    cites=[{'ordinal':1,'quote':quote,'source_type':'web'}]
    assert bool(polarity_conflicts(claim,cites)) is blocked
    assert not unsupported_claims(claim,cites)

@pytest.mark.parametrize('amount,blocked',[('5万亿美元',False),('7万亿美元',True),('0.5万亿美元',True)])
def test_trillion_compound_chinese_units_are_checked_instead_of_ignored(amount,blocked):
    from app.agent_workflow.evidence import unsupported_numbers
    assert unsupported_numbers(amount+'[1]',[{'ordinal':1,'quote':'Apple reached US$5 trillion.'}]) is blocked

@pytest.mark.parametrize('quote,blocked',[('Apple 市值5萬億美元。',False),('Apple 市值7萬億美元。',True)])
def test_traditional_source_magnitudes_compare_without_changing_source_text(quote,blocked):
    from app.agent_workflow.evidence import unsupported_numbers
    citations=[{'ordinal':1,'quote':quote}]
    assert unsupported_numbers('Apple 市值5万亿美元[1]',citations) is blocked
    assert citations[0]['quote']==quote

@pytest.mark.parametrize('body',[
 'Apple FY2024 revenue was 10. Apple FY2025 profit was 20.',
 'Apple Q3 2024 revenue was 10. Apple Q1 2025 revenue was 20.',
 'Apple partners with Samsung. Samsung Q3 2025 revenue was 10.',
])
def test_company_period_and_metric_must_belong_to_same_claim(body):
    row={'source_type':'web','excerpt':body,'published_at':'2026-10-15T00:00:00Z'}
    assert gate_row('Apple Q3 2025 revenue',row,company='Apple',metrics=['revenue'],period='Q3 2025')[0] is False

@pytest.mark.parametrize('body',['Apple Q3 2025 revenue was 10.','Apple 2025 Q3 revenue was 10.','Apple 2025年第三季度 revenue was 10.'])
def test_equivalent_quarter_spellings_are_verified(body):
    assert gate_row('Apple Q3 2025 revenue',{'source_type':'web','excerpt':body},company='Apple',metrics=['revenue'],period='Q3 2025')[0]


def test_a_period_in_one_row_cannot_authorize_a_metric_in_another():
    assert not deterministic_confidence_gate('AAPL FY2025 revenue',{'ok':True,'data':[
        {'symbol':'AAPL','excerpt':'FY2025 earnings report'},
        {'symbol':'AAPL','excerpt':'FY2024 revenue is 10'},
    ]},verified_symbols=['AAPL'])[0]

@pytest.mark.parametrize('metric,row',[
 ('price',{'symbol':'AMD','close':100,'trading_date':'2026-10-15'}),
 ('date',{'symbol':'AMD','excerpt':'AMD annual report','filed_at':'2026-10-14'}),
 ('forecast',{'symbol':'AMD','probabilities':{'bearish':0.2,'neutral':0.3,'bullish':0.5}}),
])
def test_typed_fields_are_evidence_for_their_declared_metric(metric,row):
    assert gate_row('AMD',row,symbol='AMD',metrics=[metric])[0]

def test_exact_publication_window_rejects_eighth_day_and_future():
    from datetime import UTC,datetime,timedelta
    from app.freshness import published_within
    now=datetime(2026,10,15,12,tzinfo=UTC)
    assert published_within((now-timedelta(days=7)).isoformat(),7,now)
    assert not published_within((now-timedelta(days=7,seconds=1)).isoformat(),7,now)
    assert not published_within((now+timedelta(seconds=1)).isoformat(),7,now)

def test_saved_filing_cannot_use_filing_date_to_authorize_another_financial_year():
    row={'id':'saved','symbol':'AAPL','source_type':'official_filing','excerpt':'FY2024 revenue was 10. FY2025 profit was 20.','filed_at':'2025-01-01'}
    assert not gate_row('AAPL FY2025 revenue',row,symbol='AAPL',metrics=['revenue'],period='FY2025')[0]

@pytest.mark.parametrize('quote,claim',[
 ('Apple CEO did not resign.','Apple CEO resigned.[1]'),
 ('Apple did not acquire ExampleCo.','Apple acquired ExampleCo.[1]'),
 ('Apple CEO resigned.','Apple CEO did not resign.[1]'),
 ('苹果 CEO 并未离任。','苹果 CEO 已离任。[1]'),
 ('苹果没有收购 ExampleCo。','苹果已收购 ExampleCo。[1]'),
])
def test_cited_event_polarity_cannot_be_reversed(quote,claim):
    # A reversal against the cited source is shown with the source's own sentence; it is not an unsupported claim.
    from app.agent_workflow.evidence import polarity_conflicts,unsupported_claims
    cites=[{'ordinal':1,'source_type':'web','quote':quote}]
    hits=polarity_conflicts(claim,cites)
    assert len(hits)==1 and hits[0]['ordinal']==1 and hits[0]['snippet'] in quote
    assert not unsupported_claims(claim,cites)

@pytest.mark.parametrize('quote,claim',[
 ('Apple CEO did not resign.','苹果 CEO 没有辞职。[1]'),
 ('Apple appointed a new CFO.','苹果任命了新 CFO。[1]'),
 ('entered into a definitive agreement to purchase','宣布收购 [1]。'),
])
def test_supported_event_polarity_can_cross_languages(quote,claim):
    from app.agent_workflow.evidence import polarity_conflicts,unsupported_claims
    cites=[{'ordinal':1,'source_type':'web','quote':quote}]
    assert not polarity_conflicts(claim,cites)
    assert not unsupported_claims(claim,cites)

@pytest.mark.parametrize('claim',['AMD 收盘价 999 美元。AMD 收盘价 100 美元 [1]。','AMD CEO resigned. Price is 100 dollars [1].'])
def test_missing_marker_cannot_bypass_amount_or_event_validation(claim):
    from app.agent_workflow.evidence import reviewed_passages
    citations=[{'ordinal':1,'source_type':'saved_price','quote':'100'}]
    _, issues = reviewed_passages(claim, citations, require_citations=True)
    assert any(i in {'unsupported_numeric_claim', 'missing_citation', 'unsupported_claim'} for i in issues)


@pytest.mark.parametrize('quote,claim',[
 ('$54.2B','营收为 542 亿美元 [1]。'),
 ('$68.3B','净现金为 683 亿美元 [1]。'),
 ('$1.5M','收入为 150 万美元 [1]。'),
 ('$2.5K','金额为 2500 美元 [1]。'),
 ('$54,200M','营收为 $54.2B [1]。'),
 ('54.2 billion dollars','营收为 $54,200M [1]。'),
])
def test_financial_currency_suffixes_preserve_units_across_languages(quote,claim):
    from app.agent_workflow.evidence import unsupported_numbers
    assert not unsupported_numbers(claim,[{'ordinal':1,'source_type':'web','quote':quote}])


@pytest.mark.parametrize('claim',['营收为 $99B [1]。','营收为 54.2 万美元 [1]。','营收为 54.2 美元 [1]。'])
def test_currency_suffix_support_does_not_allow_a_changed_value_or_unit(claim):
    from app.agent_workflow.evidence import unsupported_numbers
    assert unsupported_numbers(claim,[{'ordinal':1,'source_type':'web','quote':'Revenue was $54.2B.'}])


def test_calendar_dates_and_citation_markdown_links_are_not_flagged_as_unsupported_numbers():
    from app.agent_workflow.evidence import unsupported_numbers
    passage = (
        '**Meta推出最新AI模型Muse Wonder**（2026-10-13，新浪财经）：'
        'Meta发布首款由自研芯片驱动的模型[2](https://wp1461772181-glitch.github.io/market-evidence-agent/#citation-2)。'
    )
    citations = [{
        'ordinal': 2,
        'source_type': 'web',
        'title': 'Meta推出最新AI模型Muse Wonder_新浪财经_新浪网',
        'source_url': 'https://finance.sina.com.cn/stock/usstock/c/2026-10-13/doc-iniuyxuz8302435.shtml',
        'published_at': '2026-10-12T17:08:53+00:00',
        'quote': 'Meta推出了其最新人工智能模型Muse Wonder，并称它是驱动数字助手的最先进选项。',
    }]
    assert not unsupported_numbers(passage, citations)
    # But a fake financial claim in the same passage must still be blocked:
    assert unsupported_numbers(passage + ' 营收为 999 亿美元[2]。', citations)


def test_pure_summary_without_numbers_does_not_trigger_missing_citation():
    from app.agent_workflow.evidence import factual_claim, reviewed_passages
    sentence = '因此毛利率改善是核心驱动力。'
    assert factual_claim(sentence) is False
    accepted, issues = reviewed_passages(sentence, [], require_citations=True)
    assert 'missing_citation' not in issues


def test_f12_acquisition_phrasing_and_polarity_reversal():
    from app.agent_workflow.evidence import polarity_conflicts, unsupported_claims
    cites = [{'ordinal': 1, 'quote': 'entered into a definitive agreement to purchase', 'source_type': 'web'}]
    assert not polarity_conflicts('宣布收购 [1]', cites)
    assert not unsupported_claims('宣布收购 [1]', cites)

    cites_neg = [{'ordinal': 1, 'quote': 'Company did not acquire ExampleCo.', 'source_type': 'web'}]
    assert polarity_conflicts('收购了 [1]', cites_neg)
    assert not unsupported_claims('收购了 [1]', cites_neg)


def test_8k_partial_storage_distinguishes_missing_part_from_contradiction():
    from app.agent_workflow.evidence import reviewed_passages
    partial_99_1 = [{
        'ordinal': 1,
        'source_type': 'official_filing',
        'saved_text': 'exhibit_99_1_only',
        'quote': 'Q3 revenue was $10 billion. Operating margin was 32%.',
    }]
    _, issues = reviewed_passages('公司同时宣布任命新任 CEO [1]。', partial_99_1, check_claims=True)
    assert 'source_part_not_stored' in issues
    assert 'unsupported_claim' not in issues

    contradicted_8k = [{
        'ordinal': 1,
        'source_type': 'official_filing',
        'saved_text': 'primary_document_only',
        'quote': 'Item 2.02 Results of Operations. The company did not acquire ExampleCo.',
    }]
    # A contradiction is a hint carrying the filing's own sentence, not an issue: no repair, no downgrade.
    from app.agent_workflow.evidence import claim_hints
    _, issues_neg = reviewed_passages('收购了 ExampleCo [1]。', contradicted_8k, check_claims=True)
    assert 'unsupported_claim' not in issues_neg
    assert 'source_part_not_stored' not in issues_neg
    hints = claim_hints('收购了 ExampleCo [1]。', contradicted_8k)
    assert [h['reason'] for h in hints] == ['polarity_conflict']
    assert hints[0]['ordinal'] == 1 and 'did not acquire' in hints[0]['snippet']


@pytest.mark.parametrize('claim,quote', [
    ('张三卸任CEO[1]', '张三没有卸任。'),                      # a real contradiction
    ('CEO不久前辞职[1]', 'The CEO resigned on Monday.'),       # misreads: 不久 is no negation
    ('CEO不得不辞职[1]', 'The CEO resigned on Monday.'),       # 不得不
    ('CEO因不满薪酬而辞职[1]', 'The CEO resigned on Monday.'),  # 不满
    ('CEO已辞职[1]', 'The CFO did not resign.'),               # a different subject
])
def test_polarity_hit_is_a_hint_with_the_source_sentence_never_an_unsupported_verdict(claim, quote):
    from app.agent_workflow.evidence import claim_hints, polarity_conflicts, reviewed_passages, unsupported_claims
    cites = [{'ordinal': 1, 'source_type': 'web', 'quote': quote}]
    hits = polarity_conflicts(claim, cites)
    assert len(hits) == 1 and hits[0]['ordinal'] == 1 and hits[0]['snippet'] and hits[0]['snippet'] in quote
    assert not unsupported_claims(claim, cites)
    _, issues = reviewed_passages(claim, cites, check_claims=True)
    assert 'unsupported_claim' not in issues
    assert [h['reason'] for h in claim_hints(claim, cites)] == ['polarity_conflict']


@pytest.mark.parametrize('claim,quote', [
    ('CFO已辞职[1]', 'The CEO resigned. The CFO did not resign.'),  # both readings in the source: silent
    ('公司已被收购[1]', 'The merger never closed.'),                  # a negation the word list cannot see
])
def test_polarity_misses_stay_silent_and_are_not_unsupported(claim, quote):
    from app.agent_workflow.evidence import claim_hints, polarity_conflicts, reviewed_passages, unsupported_claims
    cites = [{'ordinal': 1, 'source_type': 'web', 'quote': quote}]
    assert polarity_conflicts(claim, cites) == [] and claim_hints(claim, cites) == []
    assert not unsupported_claims(claim, cites)
    _, issues = reviewed_passages(claim, cites, check_claims=True)
    assert 'unsupported_claim' not in issues


def test_event_word_beside_a_figure_the_source_holds_is_a_hint_not_unsupported():
    from app.agent_workflow.evidence import claim_hints, reviewed_passages, unsupported_claims
    cites = [{'ordinal': 1, 'source_type': 'saved_price', 'quote': '100'}]
    claim = '公司没有破产，收盘价100美元[1]'
    # The source-kind rule still sees an event on a number-only source, but the figure is the source's own.
    assert unsupported_claims(claim, cites)
    _, issues = reviewed_passages(claim, cites, check_claims=True)
    assert issues == []
    hints = claim_hints(claim, cites)
    assert [h['reason'] for h in hints] == ['event_not_in_source'] and hints[0]['ordinal'] == 1
    # With no figure of its own to stand on, the event on a price source is still unsupported.
    _, issues = reviewed_passages('苹果 CEO 已辞职[1]', cites, check_claims=True)
    assert issues == ['unsupported_claim']
    assert claim_hints('苹果 CEO 已辞职[1]', cites) == []


def test_cagr_power_calculation():
    from app.agent_workflow.calculation import calculate
    res = calculate({
        'expression': '(a / b) ** (1 / 3) - 1',
        'inputs': [
            {'name': 'a', 'value': '150', 'user_stated': True},
            {'name': 'b', 'value': '100', 'user_stated': True},
        ],
        'decimals': 4,
    }, [], user_text='150 100')
    assert res['value'] == '0.1447'


def test_inference_label_expansion():
    from app.agent_workflow.evidence import is_inference_label
    assert is_inference_label('由此推断，营收将继续增长。')
    assert is_inference_label('据此估算，毛利率约为 45%。')
    assert is_inference_label('预计明年资本开支达到 100 亿美元。')
    assert is_inference_label('建议仓位不超过 15%。')

