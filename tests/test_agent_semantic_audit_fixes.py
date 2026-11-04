"""C1–C14 migration: retained independent unit contracts. Legacy planner/node-injection
checks were replaced by production direct-loop, consent and provenance tests; see
docs/reports/agent-routing-test-migration.md. Originals are in Git main 81f62be.
"""
from __future__ import annotations


def test_the_code_does_not_decide_which_company_a_sentence_is_about_by_a_name_list():
    """The known-company list is retired, and the company/neighbour rule only ranks (anchored
    sentences first: company named in the sentence, in the sentence before it, or in the headline
    when it is the first); it drops nothing.  Whose figure it is, is the model's reading; a
    sentence is never left out because its subject is a company name from a list.  (These texts fit
    the bound, so they come back whole.)"""
    from app.agent_web_research import focus_excerpt
    assert "revenue rose 20%" in focus_excerpt(
        "Samsung revenue rose 20% in 2025.", "Apple revenue news", heading="Apple revenue report")
    assert "Samsung revenue rose 20%" in focus_excerpt(
        "Apple introduced a phone. Samsung revenue rose 20% in 2025.", "Apple revenue news")
    assert "Microsoft revenue rose" in focus_excerpt(
        "Apple introduced a phone. Microsoft revenue rose 12% in 2025.", "Apple revenue news")
    text = "Apple introduced a phone. The company revenue rose 20% in 2025."
    assert focus_excerpt(text, "Apple revenue news") == text
