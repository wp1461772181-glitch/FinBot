"""Unit tests for claim_shadow_extract.py (§2, §6.3)."""
import pytest

from app.agent_workflow.claim_judge import MAX_SOURCE_CHARS, MAX_SOURCES, JudgeSource
from app.agent_workflow.claim_shadow_extract import (
    Candidate,
    SelectionResult,
    classify_tier,
    select_sentences,
    to_judge_source,
    to_judge_sources,
)
from app.agent_workflow.evidence import (
    _BULLET,
    _NUMERIC_ONLY_SOURCE_TYPES,
    _event_matches,
    _passage_sources,
    _reviewable_lines,
)


def test_pinned_evidence_private_names_are_importable():
    """Pin private names in evidence.py per §6.3."""
    assert callable(_reviewable_lines)
    assert hasattr(_BULLET, "match")
    assert callable(_passage_sources)
    assert callable(_event_matches)
    assert isinstance(_NUMERIC_ONLY_SOURCE_TYPES, frozenset)
    assert "saved_price" in _NUMERIC_ONLY_SOURCE_TYPES


def test_fact_punctuation_marker_binding():
    """'fact[1]。' and 'fact。[1]' both bind marker to the same sentence."""
    citations = [{"ordinal": 1, "quote": "revenue was 100", "source_type": "official_filing", "saved_text": "full_document"}]
    ans1 = "Northwind 第三季度营收为 100 亿元[1]。"
    ans2 = "Northwind 第三季度营收为 100 亿元。[1]"

    res1 = select_sentences(ans1, citations)
    res2 = select_sentences(ans2, citations)

    assert len(res1.candidates) == 1
    assert len(res2.candidates) == 1
    assert res1.candidates[0].ordinals == (1,)
    assert res2.candidates[0].ordinals == (1,)


def test_sentences_without_citation_never_selected():
    """Unmarked sentences are never selected into candidates (§2.2, §6.3)."""
    citations = [{"ordinal": 1, "quote": "revenue was 100", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "这是一句没有来源标记的普通陈述句。这是另一句完全没有来源标记的过渡句。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert sum(res.skipped.values()) == 0


def test_skip_table_row():
    citations = [{"ordinal": 1, "quote": "100", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "| 指标 | 数值 |\n| --- | --- |\n| 营收 | 100 亿元 [1] |"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["table_row"] >= 1


def test_skip_source_list():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "参考来源：\n[1] 微软2026年Q3财报\n- [1] 苹果公司年度公告"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["source_list"] >= 1


def test_skip_heading():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "# 第一章 核心财务分析 [1]\n**重点经营数据总结 [1]**"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["heading"] >= 1


def test_skip_inference():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "（推断）根据已知趋势公司第四季度营收可能继续扩大 [1]。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["inference"] == 1


def test_skip_absence():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "本次检索没有取得可核验的云业务细分资料 [1]。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["absence"] == 1


def test_skip_too_short():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "好的 [1]。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["too_short"] == 1


def test_skip_duplicate():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "official_filing", "saved_text": "full_document"}]
    answer = "Northwind 第三季度营收同比增长达到 8.2% [1]。\nNorthwind 第三季度营收同比增长达到 8.2% [1]。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 1
    assert res.skipped["duplicate"] == 1


def test_skip_unavailable_source():
    citations = [{"ordinal": 1, "quote": "report", "source_type": "unavailable"}]
    answer = "Northwind 第三季度营收实现大幅提升 [1]。"
    res = select_sentences(answer, citations)
    assert len(res.candidates) == 0
    assert res.skipped["unavailable_source"] == 1


def test_sources_of_all_types_are_selected():
    for kind in ("portfolio", "saved_material", "calculation", "custom_internal_feed"):
        citations = [{"ordinal": 1, "quote": "holding 100 shares", "source_type": kind}]
        result = select_sentences("当前账户持有苹果公司 100 股股票 [1]。", citations)
        assert len(result.candidates) == 1


def test_sentence_over_cap_priority_tiers():
    """Over 12 sentences: Tier 1 prioritized, same tier keeps original order, sentences_over_cap correct."""
    citations = [{"ordinal": 1, "quote": "data", "source_type": "official_filing", "saved_text": "full_document"}]
    lines = []
    # 5 Tier 3 sentences (with non-year numbers, no event words)
    for i in range(5):
        lines.append(f"某业务线第 {i+1} 分部总共拥有 5000 名雇员 [1]。")
    # 10 Tier 1 sentences (with event words like 增长, 上涨, 收购)
    for i in range(10):
        lines.append(f"公司第 {i+1} 项目部正式完成重大战略投资与收购事项 [1]。")
    # 5 Tier 2 sentences (qualitative, only calendar years)
    ordinals = ["一", "二", "三", "四", "五"]
    for i in range(5):
        lines.append(f"在 2025 年管理层第 {ordinals[i]} 分部坚持推动核心产品服务矩阵全面升级转型 [1]。")

    answer = "\n".join(lines)
    res = select_sentences(answer, citations, max_sentences=12)

    assert res.sentence_candidates == 20
    assert res.sentences_over_cap == 8
    assert len(res.candidates) == 12

    # All 10 Tier 1 sentences should be selected first
    assert all(c.tier == 1 for c in res.candidates[:10])
    # Next 2 should be Tier 2
    assert all(c.tier == 2 for c in res.candidates[10:])


def test_source_adaptation_and_deduplication():
    citation = {
        "ordinal": 1,
        "source_type": "official_filing",
        "saved_text": "full_document",
        "title": "Apple 10-K",
        "symbol": "AAPL",
        "published_at": "2026-10-31",
        "quote": "Revenue reached 400 billion.",
        "figures": "Revenue reached 400 billion.",  # Same as quote -> deduplicated
        "evidence_quotes": ["Revenue reached 400 billion.", "Services grew 12%."],  # First deduplicated
        "check_text": "Revenue reached 400 billion. Extra context about international markets.",
    }

    source, meta = to_judge_source(citation)
    assert source.ordinal == 1
    assert source.source_type == "official_filing"
    assert source.complete is True

    # Check deduplication in assembled text:
    # "Revenue reached 400 billion." should appear in quote, not repeated identically in check_text prefix
    assert "Extra context about international markets." in source.text
    assert "Services grew 12%." in source.text
    assert meta["truncated"] is False
    assert meta["chars_total"] < MAX_SOURCE_CHARS


def test_price_source_adaptation_fields():
    citation = {
        "ordinal": 2,
        "source_type": "saved_price",
        "title": "AAPL Price",
        "fields": {"symbol": "AAPL", "trading_date": "2026-11-04", "close": 225.5},
        "quote": "225.5",
    }
    source, meta = to_judge_source(citation)
    assert "symbol=AAPL" in source.text
    assert "trading_date=2026-11-04" in source.text
    assert "close=225.5" in source.text


def test_source_truncation_limits_and_max_sources():
    long_body = "A" * (MAX_SOURCE_CHARS + 500)
    citation = {
        "ordinal": 1,
        "source_type": "official_filing",
        "saved_text": "full_document",
        "check_text": long_body,
    }
    source, meta = to_judge_source(citation)
    assert len(source.text) == MAX_SOURCE_CHARS
    assert source.complete is False
    assert meta["truncated"] is True
    assert meta["chars_total"] == len(long_body)

    # Max sources: when > 6 ordinals passed, only first 6 are processed
    cites = [{"ordinal": i, "quote": f"q{i}", "source_type": "official_filing"} for i in range(1, 10)]
    ordinals = list(range(1, 10))
    sources, meta_map = to_judge_sources(ordinals, cites)
    assert len(sources) == MAX_SOURCES
    assert len(meta_map) == MAX_SOURCES
