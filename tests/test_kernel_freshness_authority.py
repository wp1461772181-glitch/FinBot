"""Freshness and authority on numbered read results (stage 2d, task 1): computed by code, nothing hidden or reordered."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app import source_authority
from app.agent_workflow import tools
from app.kernel import prompt, toolrun

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def iso(**delta):
    return (NOW - timedelta(**delta)).isoformat()


def call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def run_with(monkeypatch, name, rows, args=None, meta=None):
    async def fake_invoke(n, a, context, *, emit=None, page_chars=None):
        out = {"ok": True, "data": rows, "source": "test"}
        if meta:
            out["meta"] = meta
        return out

    async def emit(event):
        pass

    monkeypatch.setattr(tools, "invoke", fake_invoke)
    monkeypatch.setattr(toolrun, "_now", lambda: NOW)
    run = SimpleNamespace(context=SimpleNamespace(query_expander=None, owner_hash="o", conversation_id="c"), emit=emit, user_text="",
                          tool_names=frozenset({name, "calculate"}), citations=[], audit={"tool_calls": 0}, read_results=0, web_rows={}, new_sets=[])
    messages = asyncio.run(toolrun.run_step_tools(run, [call("c1", name, args or {"query": "x"})]))
    return run, json.loads(messages[0]["content"])


def news(i, published, source_name="Some Wire", url=None):
    return {"id": f"n{i}", "title": f"t{i}", "excerpt": f"body {i}", "published_at": published, "source_name": source_name,
            "url": url or f"https://example.com/{i}"}


def test_news_search_states_three_day_old_newest(monkeypatch):
    rows = [news(1, iso(days=3)), news(2, iso(days=9)), news(3, None)]
    _, result = run_with(monkeypatch, "search_configured_news", rows)
    assert result["meta"]["newest"] == iso(days=3)
    assert result["meta"]["newest_age"] == "3 天前"
    assert "future_dated" not in result["meta"]


def test_future_stamped_row_is_ignored_and_counted(monkeypatch):
    rows = [news(1, iso(hours=2)), news(2, (NOW + timedelta(days=2)).isoformat())]
    _, result = run_with(monkeypatch, "search_configured_news", rows)
    assert result["meta"]["newest"] == iso(hours=2)
    assert result["meta"]["newest_age"] == "2 小时前"
    assert result["meta"]["future_dated"] == 1


def test_existing_meta_is_kept_and_undated_batch_has_no_newest(monkeypatch):
    _, result = run_with(monkeypatch, "search_configured_news", [news(1, None)], meta={"queries": 2})
    assert result["meta"] == {"queries": 2}


def test_filing_uses_accepted_at_then_filed_at_and_figure_uses_period_end():
    assert source_authority.row_date({"source_type": "official_filing", "accepted_at": "2026-11-20T10:00:00Z", "filed_at": "2026-11-19"}).day == 20
    assert source_authority.row_date({"source_type": "official_filing", "filed_at": "2026-11-19"}).day == 19
    assert source_authority.row_date({"source_type": "reported_figure", "period_end": "2026-09-30", "filed_at": "2026-11-01"}).month == 9
    assert source_authority.row_date({"source_type": "web"}) is None


def test_tiers_by_source():
    tier = source_authority.tier_of
    assert tier({"source_type": "web", "url": "https://www.reuters.com/markets/a"}) == 2
    assert tier({"source_type": "web", "url": "https://someblog.example.org/post"}) == 4
    assert tier({"source_type": "web"}) == 4
    assert tier({"source_type": "x_post", "url": "https://x.com/a/status/1"}) == 4
    assert tier({"source_type": "official_filing", "form": "10-Q"}) == 1
    assert tier({"source_type": "web", "url": "https://www.sec.gov/Archives/x"}) == 1
    assert tier({"source_type": "configured_news", "url": "https://finance.yahoo.com/n", "source_name": "Yahoo Finance"}) == 3
    assert tier({"source_type": "configured_news", "url": "https://x.cn/1", "source_name": "财新网"}) == 2
    assert tier({"source_type": "configured_news", "url": "https://unknown.example/1", "source_name": "Other"}) == 3
    assert tier({"source_type": "market_quote"}) == 1
    assert tier({"source_type": "reported_figure"}) == 1
    assert tier({"source_type": "uploaded_media"}) is None


def test_rows_and_citations_carry_authority(monkeypatch):
    rows = [news(1, iso(hours=1), "Reuters", "https://www.reuters.com/a"), news(2, iso(hours=2), None, "https://blog.example.org/b")]
    run, result = run_with(monkeypatch, "search_configured_news", rows)
    shown = {r["id"]: r for r in result["data"]}
    assert shown["n1"]["来源等级"] == "通讯社和主流媒体"
    assert shown["n2"]["来源等级"] == "聚合和其他新闻"
    assert [r["id"] for r in result["data"]] == ["n1", "n2"]
    assert [(c["authority"], c["authority_label"]) for c in run.citations] == [(2, "通讯社和主流媒体"), (3, "聚合和其他新闻")]


def test_web_result_tiers(monkeypatch):
    rows = [{"url": "https://www.reuters.com/a", "title": "a", "excerpt": "A text", "published_at": iso(days=1)},
            {"url": "https://myblog.example.org/b", "title": "b", "excerpt": "B text"}]
    run, result = run_with(monkeypatch, "web_research", rows)
    assert [r["来源等级"] for r in result["data"]] == ["通讯社和主流媒体", "社交平台和网页"]
    assert result["meta"]["newest_age"] == "1 天前"


def test_x_post_is_tier_four(monkeypatch):
    rows = [{"id": "p1", "text": "NVDA to the moon", "url": "https://x.com/a/status/1", "published_at": iso(minutes=41)}]
    run, result = run_with(monkeypatch, "search_x", rows)
    assert result["data"][0]["来源等级"] == "社交平台和网页"
    assert result["meta"]["newest_age"] == "41 分钟前"


def test_calculation_is_as_authoritative_as_its_weakest_input():
    citations = [{"ordinal": 1, "source_type": "official_filing"}, {"ordinal": 2, "source_type": "x_post"},
                 {"ordinal": 3, "source_type": "calculation", "derived": True, "calculation": {"parents": [1], "inputs": [{"source_ordinal": 1}]}},
                 {"ordinal": 4, "source_type": "calculation", "derived": True, "calculation": {"parents": [1, 2]}}]
    source_authority.rank(citations)
    assert [c["authority"] for c in citations] == [1, 4, 1, 4]


def test_latest_known_derived_figure_is_tier_one():
    run = SimpleNamespace(citations=[])
    rows = [{"_k": 1, "id": "company-fact:1", "symbol": "NVDA", "title": "Revenue", "source_type": "official_filing", "excerpt": "Revenue 100",
             "url": "https://www.sec.gov/a", "source_url": "https://www.sec.gov/a", "filed_at": "2026-11-20"},
            {"_k": 2, "title": "Growth", "symbol": "NVDA", "_calc": {"inputs": [{"k": 1, "name": "a", "value": "100"}], "value": "100", "expression": "a"}}]
    text = toolrun.number_attached(run, "line [#1]\nderived [#2]", rows)
    assert "[1]" in text and "[2]" in text
    assert [c["authority"] for c in run.citations] == [1, 1]


def test_system_text_explains_the_two_labels_and_stays_short():
    assert "来源等级" in prompt.SYSTEM and "newest_age" in prompt.SYSTEM


def test_nasdaq_pages_are_aggregated_news_not_official():
    from app import source_authority as sa
    assert sa.tier_of({"source_type": "web", "url": "https://www.nasdaq.com/articles/some-syndicated-story"}) == 3
    assert sa.tier_of({"source_type": "web", "url": "https://www.sec.gov/Archives/edgar/data/1/x.htm"}) == 1
