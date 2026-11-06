from app.agent_workflow.claim_judge import JudgeSource
from app.agent_workflow.claim_windows import figures, numeric_windows


def test_rounded_location_preserves_list_item_and_source_offsets():
    source = JudgeSource(7, '- BlackRock removed 21,071,170 shares (-4.7%)\n- Other added 10 shares')
    result = numeric_windows('减少约 2,107 万股 [7]', [source])
    window = result['windows'][0]
    assert window['match'] == 'rounded'
    assert window['text'] == '- BlackRock removed 21,071,170 shares (-4.7%)'
    a, b = window['source_number_span']
    assert source.text[a:b] == '21,071,170 shares'
    assert '归属' not in str(result)


def test_sign_percent_and_table_header_are_preserved():
    source = JudgeSource(1, '| Period | Change % |\n|---|---|\n| Q2 | −30.9% |')
    result = numeric_windows('下降 −30.9% [1]', [source])
    assert len(result['windows']) == 1
    assert result['windows'][0]['headers'][0]['text'] == '| Period | Change % |'
    assert not numeric_windows('上涨 30.9% [1]', [source])['windows']
    assert not numeric_windows('0.309 [1]', [source])['windows']


def test_limits_record_omitted_without_negative_conclusion():
    result = numeric_windows('100 [1]', [JudgeSource(1, '- 100\n- 100')], max_windows=1)
    assert len(result['windows']) == 1 and result['omitted'] == 1
    assert figures('二千四百六十六万股') == []


def test_later_table_rows_keep_original_header():
    source = JudgeSource(2, '| Name | Amount |\n|---|---|\n| A | 23 |\n| B | 42 |')
    result = numeric_windows('42 [2]', [source])
    assert result['windows'][0]['headers'][0]['text'] == '| Name | Amount |'


def test_judge_receives_location_windows_without_attribution():
    import json
    from app.agent_workflow.claim_judge import _user_message
    source = JudgeSource(1, '- Holder A removed 21,071,170 shares')
    payload = json.loads(_user_message('减少约 2,107 万股', [source]))
    assert payload['numeric_windows']['windows'][0]['text'] == source.text
    assert '归属于' not in json.dumps(payload['numeric_windows'], ensure_ascii=False)


def test_period_is_extracted_from_table_header_and_kept_none_when_absent():
    from app.agent_workflow.claim_windows import periods
    source = JudgeSource(3, '| Quarter | Change |\n|---|---|\n| Q2 2026 | −30.9% |\n| Q3 2026 | 5 |')
    result = numeric_windows('2026年第二季度下降 −30.9% [3]', [source])
    window = result['windows'][0]
    assert window['period'] is not None and window['period']['text'] == 'Q2 2026'
    assert source.text[window['period']['span'][0]:window['period']['span'][1]] == 'Q2 2026'
    assert result['answer_periods'] == ['2026年第二季度']
    bare = numeric_windows('减少 21,071,170 股 [1]', [JudgeSource(1, '- Holder removed 21,071,170 shares')])
    assert bare['windows'][0]['period'] is None
    assert [p['text'] for p in periods('截至2026-06-30 与 Q1 FY25')] == ['2026-06-30', 'Q1 FY25']
    assert periods('24,664,315 shares') == []
