"""Pre-hardcode audit, tier 2 (2026-11-21). Each behaviour change sits behind a FINBOT_PH2_* switch (default on);
every item is tested on and off, and "off" is the old behaviour word for word.
"""
from datetime import UTC, datetime, timedelta

import pytest

from app import fin_news_engine as engine_mod
from app.agent_chat_models import NewsItem
from app.database import Base, SessionLocal, engine


def _switch(monkeypatch, name, on):
    monkeypatch.setenv(name, "on" if on else "off")


# --------------------------------------------------------------------------------------------------------------------
# 1. S5: configured news search ranks instead of filtering (FINBOT_PH2_NEWS_RANK)
# --------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def news_db(monkeypatch, disposable_database, tmp_path):
    Base.metadata.create_all(engine, tables=[NewsItem.__table__])
    with SessionLocal() as db:
        db.query(NewsItem).delete()
        db.commit()
    cfg_path = tmp_path / "news_sources.yaml"
    cfg_path.write_text(engine_mod.config_path().read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("FINBOT_NEWS_SOURCES_CONFIG", str(cfg_path))
    engine_mod.clear_runtime_state()
    engine_mod.set_http_fetcher(None)
    cfg = engine_mod.load_config(cfg_path)
    for src in cfg["sources"]:
        src["enabled"] = src["id"] == "yahoo-finance-rss"
    engine_mod.save_config(cfg, cfg_path)
    yield cfg_path


def _add(title, summary="", tickers=(), keywords=(), minutes_ago=10, key=None):
    with SessionLocal() as db:
        db.add(NewsItem(
            source_id="yahoo-finance-rss", source_name="Y", dedupe_key=key or title, title=title,
            url="https://example.com/" + (key or title).replace(" ", "-"), summary=summary,
            published_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            tickers=list(tickers), keywords_hit=list(keywords), language="zh-CN"))
        db.commit()


def test_news_query_terms_bigrams_and_stopwords():
    terms = engine_mod._news_query_terms("苹果最新财报 NVDA earnings")
    assert "苹果最新财报" in terms and "苹果" in terms and "财报" in terms
    assert "最新" not in terms and "nvda" in terms and "earnings" in terms
    assert engine_mod._news_query_terms("特斯拉的交付量吗") == ["特斯拉的交付量吗", "特斯", "斯拉", "交付", "付量"]


def test_news_rank_chinese_sentence_matches_split_title(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("苹果发布新品", "财报季前瞻")
    _add("无关的天气新闻", "晴")
    res = engine_mod.search_configured_news(query="苹果最新财报")
    assert [i["title"] for i in res["items"]] == ["苹果发布新品"]
    assert set(res["items"][0]["matched_terms"]) == {"苹果", "财报"}
    assert "no_term_matched" not in res["meta"]


def test_news_rank_chinese_sentence_off_is_old_behaviour(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", False)
    _add("苹果发布新品", "财报季前瞻")
    res = engine_mod.search_configured_news(query="苹果最新财报")
    assert res["items"] == []
    assert res["meta"]["hint"] == "fallback_to_web_search_recommended"


def test_news_rank_ticker_only_row_kept_below_ticker_and_keyword_row(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("NVDA shipments", "降息预期升温", tickers=["NVDA"], minutes_ago=60, key="both")
    _add("NVDA other news", "nothing special", tickers=["NVDA"], minutes_ago=1, key="ticker-only")
    res = engine_mod.search_configured_news(tickers=["NVDA"], keywords=["降息"])
    assert [i["url"].rsplit("/", 1)[-1] for i in res["items"]] == ["both", "ticker-only"]
    assert res["items"][0]["matched_terms"] == ["NVDA", "降息"]
    assert res["items"][1]["matched_terms"] == ["NVDA"]
    assert "match" not in res["items"][0] and "no_term_matched" not in res["meta"]


def test_news_rank_ticker_only_row_off_is_dropped(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", False)
    _add("NVDA other news", "nothing special", tickers=["NVDA"])
    res = engine_mod.search_configured_news(tickers=["NVDA"], keywords=["降息"])
    assert res["items"] == []


def test_news_rank_ticker_with_no_term_hit_falls_back_to_marked_rows(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("NVDA older", "x", tickers=["NVDA"], minutes_ago=120, key="older")
    _add("NVDA newer", "y", tickers=["NVDA"], minutes_ago=5, key="newer")
    _add("MSFT news", "降息", tickers=["MSFT"], key="other")
    res = engine_mod.search_configured_news(tickers=["NVDA"], keywords=["并购"], limit=1)
    assert [i["url"].rsplit("/", 1)[-1] for i in res["items"]] == ["newer"]
    assert res["items"][0]["match"] == "none"
    assert res["meta"]["no_term_matched"] is True
    assert res["meta"]["hint"] == "fallback_to_web_search_recommended"


def test_news_rank_no_ticker_rows_at_all_stays_empty(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("MSFT news", "降息", tickers=["MSFT"])
    res = engine_mod.search_configured_news(tickers=["NVDA"], keywords=["并购"])
    assert res["items"] == []
    assert res["meta"]["hint"] == "fallback_to_web_search_recommended"
    assert "no_term_matched" not in res["meta"]


def test_news_rank_no_filter_returns_everything_both_ways(news_db, monkeypatch):
    _add("one"), _add("two", key="two")
    for on in (True, False):
        _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", on)
        res = engine_mod.search_configured_news()
        assert len(res["items"]) == 2
        assert all("matched_terms" not in i or on for i in res["items"])


# --------------------------------------------------------------------------------------------------------------------
# 2. S1: web research time window (FINBOT_PH2_WEB_DATE_SOFT)
# --------------------------------------------------------------------------------------------------------------------
import asyncio

import app.agent_web_research as web
from app.agent_workflow.evidence import deterministic_confidence_gate, gate_row


def _day(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _install_web(monkeypatch, page_dates, search_dates=None):
    rows = [{"url": f"https://example.com/{i}", "title": f"Page {i}", "snippet": f"snippet {i}",
             "published_at": (search_dates or {}).get(i)} for i in range(len(page_dates))]

    async def search(*args, **kwargs):
        return rows

    async def fetch(url, limit):
        date = page_dates[int(url.rsplit("/", 1)[-1])]
        meta = f'<meta property="article:published_time" content="{date}">' if date else ""
        return url, "text/html", f"<html><head>{meta}</head><body><p>Substantial news content for readers.</p></body></html>".encode()

    monkeypatch.setattr(web, "_search", search)
    monkeypatch.setattr(web, "_get_public", fetch)


def _urls(result):
    return [row["url"].rsplit("/", 1)[-1] for row in result["data"]]


def test_web_explicit_window_still_drops_a_dated_page_outside_it(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [_day(30), _day(2)])
    result = asyncio.run(web._research("news", days_back=7))
    assert _urls(result) == ["1"]
    assert "outside_inferred_window" not in result["data"][0] and "published_at_status" not in result["data"][0]
    assert "meta" not in result


def test_web_explicit_window_all_dated_outside_is_still_not_found(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [_day(30), _day(31)])
    result = asyncio.run(web._research("news", days_back=7))
    assert result["data"] == [] and result["status"] == "not_found" and result["meta"]["empty_reason"] == "date_window"


def test_web_undated_page_is_kept_marked_and_ordered_after_dated_ones(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [None, _day(30), _day(2)])
    result = asyncio.run(web._research("news", days_back=7))
    assert _urls(result) == ["2", "0"]
    assert result["data"][1]["published_at_status"] == "unknown"
    assert "published_at_status" not in result["data"][0]
    assert result["ok"] is True


def test_web_undated_page_off_is_dropped_as_before(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    _install_web(monkeypatch, [None, _day(30), _day(2)])
    result = asyncio.run(web._research("news", days_back=7))
    assert _urls(result) == ["2"]
    assert all("published_at_status" not in row for row in result["data"])


def test_web_inferred_window_orders_but_does_not_drop(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [_day(60), None, _day(1)])
    result = asyncio.run(web._research("苹果 最近三天 新闻"))     # window_days guesses 3 days from the query words
    assert _urls(result) == ["2", "1", "0"]
    by_url = {row["url"].rsplit("/", 1)[-1]: row for row in result["data"]}
    assert by_url["0"]["outside_inferred_window"] is True
    assert "outside_inferred_window" not in by_url["2"] and "outside_inferred_window" not in by_url["1"]
    assert by_url["1"]["published_at_status"] == "unknown"
    assert result["meta"] == {"window_source": "inferred_from_query", "applied_window_days": 3}


def test_web_inferred_window_off_still_cuts(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    _install_web(monkeypatch, [_day(60), None, _day(1)])
    result = asyncio.run(web._research("苹果 最近三天 新闻"))
    assert _urls(result) == ["2"] and "meta" not in result


def test_web_inferred_window_is_not_a_given_window_even_when_every_page_is_outside(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [_day(60), _day(90)])
    result = asyncio.run(web._research("last 3 days news"))
    assert _urls(result) == ["0", "1"] and all(r["outside_inferred_window"] for r in result["data"])


def test_web_explicit_days_back_wins_over_words_in_the_query(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    _install_web(monkeypatch, [_day(60), _day(1)])
    result = asyncio.run(web._research("苹果 最近三天 新闻", days_back=7))
    assert _urls(result) == ["1"] and "meta" not in result


def _page(**extra):
    return {"source_type": "web", "url": "https://example.com/a", "title": "Apple news", "excerpt": "Apple said something today.", **extra}


def test_gate_row_undated_page_gets_a_soft_note_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    ok, reason = gate_row("Apple news", _page(), company="Apple", days_back=7, soft=True)
    assert ok and reason == "soft:publisher_date_unknown"


def test_gate_row_undated_page_with_entity_soft_carries_both_notes(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    row = _page(title="The iPhone maker", excerpt="The iPhone maker said something today.")
    ok, reason = gate_row("Apple news", row, company="Apple", days_back=7, soft=True)
    assert ok and reason == "soft:requested_entity_missing,publisher_date_unknown"


def test_gate_row_dated_outside_the_window_is_still_refused_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    assert gate_row("Apple news", _page(published_at=_day(30)), company="Apple", days_back=7, soft=True) == (False, "requested_time_window_missing")
    assert gate_row("Apple news", _page(published_at=_day(1)), company="Apple", days_back=7, soft=True) == (True, "sufficient_evidence")


def test_gate_row_unreadable_date_string_counts_as_unknown(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    ok, reason = gate_row("Apple news", _page(published_at="last Tuesday"), company="Apple", days_back=7, soft=True)
    assert ok and reason == "soft:publisher_date_unknown"


def test_gate_row_undated_page_off_is_refused_as_before(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    assert gate_row("Apple news", _page(), company="Apple", days_back=7, soft=True) == (False, "requested_time_window_missing")


def test_gate_row_no_days_back_means_no_date_note_either_way(monkeypatch):
    for on in (True, False):
        _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", on)
        assert gate_row("Apple news", _page(published_at=_day(400)), company="Apple", soft=True) == (True, "sufficient_evidence")


def test_coverage_gate_undated_rows_do_not_fail_the_read(monkeypatch):
    result = {"ok": True, "source": "public web search", "data": [_page(), _page(url="https://example.com/b", published_at=_day(1))]}
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    assert deterministic_confidence_gate("Apple news", result, symbol=None, days_back=7, company="Apple")[0] is True
    stale = {**result, "data": [*result["data"], _page(url="https://example.com/c", published_at=_day(40))]}
    assert deterministic_confidence_gate("Apple news", stale, symbol=None, days_back=7, company="Apple") == (False, "publisher_date_unavailable")
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    assert deterministic_confidence_gate("Apple news", result, symbol=None, days_back=7, company="Apple") == (False, "publisher_date_unavailable")


def test_tool_descriptions_explain_the_marks_only_while_on(monkeypatch):
    from app.agent_tool_catalog import PH2_NEWS_NOTE, PH2_WEB_NOTE, definitions
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    on = {n: p.description for n, p in definitions().items()}
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", False)
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    off = {n: p.description for n, p in definitions().items()}
    assert on["search_configured_news"] == off["search_configured_news"] + PH2_NEWS_NOTE
    assert on["web_research"] == off["web_research"] + PH2_WEB_NOTE
    assert {n: d for n, d in on.items() if n not in {"search_configured_news", "web_research"}} == \
           {n: d for n, d in off.items() if n not in {"search_configured_news", "web_research"}}
    assert "matched_terms" in PH2_NEWS_NOTE and 'match:"none"' in PH2_NEWS_NOTE
    assert "published_at_status" in PH2_WEB_NOTE and "publisher_date_unknown" in PH2_WEB_NOTE and "outside_inferred_window" in PH2_WEB_NOTE


# --------------------------------------------------------------------------------------------------------------------
# 3. B-6: a rewritten search variant may add a stock code only if it is not a finance word (FINBOT_PH2_VARIANT_TICKER)
# --------------------------------------------------------------------------------------------------------------------
from app.knowledge import query_understanding as qu


@pytest.fixture
def sec_list(monkeypatch):
    """A small SEC ticker list; the real one is a network read."""
    from app.agent_workflow import entities
    rows = [{"ticker": "AAPL", "title": "Apple Inc."}, {"ticker": "MSFT", "title": "MICROSOFT CORP"}, {"ticker": "NVDA", "title": "NVIDIA CORP"}]
    monkeypatch.setattr(entities, "ticker_records", lambda: rows)


def test_variant_finance_words_in_capitals_pass_when_on(monkeypatch, sec_list):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    for variant in ("diluted EPS", "GAAP net income", "AI revenue", "ROE and FCF"):
        assert qu._grounded(variant, "每股收益是多少"), variant
    assert qu.clean_variants("每股收益是多少", ["diluted EPS", "GAAP net income"]) == ["每股收益是多少", "diluted EPS", "GAAP net income"]


def test_variant_finance_words_off_are_refused_as_before(monkeypatch, sec_list):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", False)
    for variant in ("diluted EPS", "GAAP net income", "AI revenue", "ROE and FCF"):
        assert not qu._grounded(variant, "每股收益是多少"), variant


def test_variant_new_sec_listed_code_is_still_refused_both_ways(monkeypatch, sec_list):
    for on in (True, False):
        _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", on)
        assert not qu._grounded("MSFT revenue", "苹果的营收是多少")
        assert not qu._grounded("AAPL diluted EPS", "每股收益是多少")


def test_variant_code_the_query_already_names_passes_both_ways(monkeypatch, sec_list):
    for on in (True, False):
        _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", on)
        assert qu._grounded("AAPL revenue", "AAPL 营收是多少")


def test_variant_figure_and_year_rules_unchanged_when_on(monkeypatch, sec_list):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    assert not qu._grounded("EPS 2024", "每股收益是多少")
    assert not qu._grounded("EPS 12%", "每股收益是多少")
    assert qu._grounded("EPS 2024", "2024 年每股收益")


def test_variant_sec_list_unreadable_is_not_a_refusal_when_on(monkeypatch):
    from app.agent_workflow import entities

    def boom():
        raise ValueError("entity_mapping_unavailable")
    monkeypatch.setattr(entities, "ticker_records", boom)
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    assert qu._grounded("MSFT diluted EPS", "每股收益是多少")
