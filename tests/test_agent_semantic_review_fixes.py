"""C1–C14 migration: retained independent unit contracts. Legacy planner/node-injection
checks were replaced by production direct-loop, consent and provenance tests; see
docs/reports/agent-routing-test-migration.md. Originals are in Git main 81f62be.
"""
from __future__ import annotations

SHORT_MIXED = ("Apple introduced a new iPhone. Samsung reported strong demand for its phones. "
               "The company revenue rose 20% in 2025.")


def test_a_short_page_is_returned_as_it_is():
    """Wordlist cleanup (b): the neighbour rule is a ranking, not a filter.  A page that fits the
    bound comes back unchanged - the metric sentence that follows another company's sentence is no
    longer left out; whose figure it is, is the model's reading."""
    from app.agent_web_research import focus_excerpt
    out = focus_excerpt(SHORT_MIXED, "Apple revenue news")
    assert out == SHORT_MIXED
    assert "Apple introduced a new iPhone." in out and "revenue rose 20%" in out


def test_a_short_page_with_the_company_beside_its_metric_sentence_is_unchanged():
    """GUARD."""
    from app.agent_web_research import focus_excerpt
    text = "Apple introduced a new iPhone. The company revenue rose 20% in 2025."
    assert focus_excerpt(text, "Apple revenue news") == text
    assert focus_excerpt("Apple revenue rose 6%.", "Apple revenue") == "Apple revenue rose 6%."
    assert focus_excerpt(SHORT_MIXED, "latest news") == SHORT_MIXED            # no metric asked: no rule


def test_the_title_and_a_metric_first_sentence_no_longer_decide_whether_a_sentence_is_shown():
    """A page whose headline names Apple and whose first sentence only says 'revenue' used to need
    the headline to keep that sentence.  The headline now only anchors it (ranking); a page that
    fits is returned whole with or without a headline, and no row is marked as cut."""
    from app.agent_web_research import _focus_source, focus_excerpt
    text = "Revenue rose 20% in 2025. The company also announced a buyback."
    assert focus_excerpt(text, "Apple revenue news") == text
    assert focus_excerpt(text, "Apple revenue news", heading="Apple results: services grow") == text
    source = {"excerpt": SHORT_MIXED, "title": "Samsung and Apple at the same show"}
    _focus_source(source, "Apple revenue news")
    assert source["excerpt"] == SHORT_MIXED and "truncated" not in source
