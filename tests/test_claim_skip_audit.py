from app.agent_workflow.claim_shadow_extract import select_sentences


def _answer(n):
    return '\n\n'.join(f'## 小节 {i}\n\n这是第 {i} 段内容，没有任何引用的事实性陈述。' for i in range(n))


def test_skipped_items_are_sampled_deterministically_and_do_not_change_counts():
    answer = _answer(200)
    first = select_sentences(answer, [{'ordinal': 1, 'source_type': 'news', 'text': 'x'}])
    second = select_sentences(answer, [{'ordinal': 1, 'source_type': 'news', 'text': 'x'}])
    assert first.skipped == second.skipped
    assert first.skipped['heading'] == 200
    assert first.candidates == [] or all(c.ordinals for c in first.candidates)
    audit = first.skipped_audit
    assert audit == second.skipped_audit
    assert 5 <= len(audit) <= 40
    assert all(item['category'] == 'heading' and item['text'] for item in audit)
    assert len(audit) < first.skipped['heading']


def test_audit_is_empty_when_nothing_is_skipped():
    result = select_sentences('没有标题。', [])
    assert result.skipped_audit == []
