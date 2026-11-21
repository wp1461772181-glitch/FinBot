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


def test_gate_row_a_soft_metric_miss_does_not_skip_the_date_checks_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    # The page does not mention revenue (a soft miss); the date checks still run after it.
    assert gate_row("Apple revenue", _page(), company="Apple", days_back=7, soft=True) == \
        (True, "soft:requested_metric_missing:revenue,publisher_date_unknown")
    assert gate_row("Apple revenue", _page(published_at=_day(30)), company="Apple", days_back=7, soft=True) == \
        (False, "requested_time_window_missing")
    assert gate_row("Apple revenue", _page(published_at=_day(1)), company="Apple", days_back=7, soft=True) == \
        (True, "soft:requested_metric_missing:revenue")


def test_gate_row_a_soft_metric_miss_off_returns_first_as_before(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", False)
    for row in (_page(), _page(published_at=_day(30))):
        assert gate_row("Apple revenue", row, company="Apple", days_back=7, soft=True) == (True, "soft:requested_metric_missing:revenue")


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
# 3. B-6: the all-caps rule for rewritten search variants is not applied (FINBOT_PH2_VARIANT_TICKER)
# --------------------------------------------------------------------------------------------------------------------
from app.knowledge import query_understanding as qu


def test_variant_all_caps_words_pass_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    for variant in ("diluted EPS", "GAAP net income", "AI revenue", "ROE and FCF", "NVIDIA AI chip revenue", "Apple free cash flow FCF", "MSFT"):
        assert qu._grounded(variant, "每股收益是多少"), variant
    assert qu.clean_variants("每股收益是多少", ["diluted EPS", "MSFT revenue"]) == ["每股收益是多少", "diluted EPS", "MSFT revenue"]


def test_variant_all_caps_words_off_are_refused_as_before(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", False)
    for variant in ("diluted EPS", "GAAP net income", "AI revenue", "NVIDIA AI chip revenue", "Apple free cash flow FCF", "MSFT"):
        assert not qu._grounded(variant, "每股收益是多少"), variant


def test_variant_figure_and_year_rules_unchanged_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    assert not qu._grounded("EPS 2024", "每股收益是多少")
    assert not qu._grounded("EPS 12%", "每股收益是多少")
    assert qu._grounded("EPS 2024", "2024 年每股收益")


def test_variant_search_stays_bound_to_the_symbol_so_another_code_in_a_variant_pulls_nothing(monkeypatch):
    """The premise of dropping the rule: every variant is searched with the same symbol, and the search filters by it."""
    from app import agent_tools
    _switch(monkeypatch, "FINBOT_PH2_VARIANT_TICKER", True)
    corpus = [{"id": "a1", "symbol": "AAPL"}, {"id": "m1", "symbol": "MSFT"}]
    seen_symbols = []

    async def lookup(symbol, query, limit, source_id=None):          # the real search functions take (symbol, query, limit)
        seen_symbols.append((symbol, query))
        return {"ok": True, "data": [r for r in corpus if r["symbol"] == symbol], "source": "knowledge", "as_of": None}

    async def expander(_query):
        return ["MSFT diluted EPS", "AI revenue"]
    with qu.use_expander(expander):
        found = asyncio.run(agent_tools._expanded_retrieval(lookup, "AAPL", "苹果每股收益", 5, None))
    assert [q for _, q in seen_symbols] == ["苹果每股收益", "MSFT diluted EPS", "AI revenue"]      # the MSFT variant is searched ...
    assert {s for s, _ in seen_symbols} == {"AAPL"}                                                  # ... still as AAPL
    assert found["data"] == [{"id": "a1", "symbol": "AAPL"}]


# --------------------------------------------------------------------------------------------------------------------
# 4. T12: the ticker of an event-extraction document (no switch; a format check, not a behaviour)
# --------------------------------------------------------------------------------------------------------------------
import hashlib

from pydantic import ValidationError

from app.event_extraction import DocumentInput

_DOC_TEXT = "Revenue increased 6%."


def _doc(ticker):
    return DocumentInput.model_validate({
        "document_id": "d1", "company": "Example Corp", "ticker": ticker, "source_url": "https://investor.example.com/q1",
        "source_domain": "investor.example.com", "published_date": "2026-01-30", "title": "Results", "text": _DOC_TEXT,
        "sha256": hashlib.sha256(_DOC_TEXT.encode()).hexdigest()})


@pytest.mark.parametrize("ticker", ["AAPL", "BRK.B", "BF-B", "0700", "A", "ABCDEFGHIJ", "9988.HK"])
def test_document_ticker_shapes_that_are_real_tickers_pass(ticker):
    assert _doc(ticker).ticker == ticker


@pytest.mark.parametrize("ticker", ["aapl", "AA PL", "../x", "..", ".B", "-B", "ABCDEFGHIJK", "", "AAPL/x", "AA\\B", "AÄPL", "AA\nPL"])
def test_document_ticker_that_is_not_a_ticker_is_refused(ticker):
    with pytest.raises(ValidationError):
        _doc(ticker)


def test_document_ticker_with_dot_and_dash_is_a_plain_json_value_in_the_cache_key():
    from app.event_extraction import cache_key_for
    keys = {cache_key_for(_doc(t), provider="p", model="m", prompt_version="v") for t in ("BRK.B", "BRK-B", "BRKB")}
    assert len(keys) == 3


# --------------------------------------------------------------------------------------------------------------------
# 5. M-12: count the company-confirmation card, change nothing (FINBOT_PH2_ENTITY_CARD_SHADOW)
# --------------------------------------------------------------------------------------------------------------------
import asyncio

from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext


async def _emit(_):
    pass


def _card_turn(question, *, classifier, canonical=None):
    seen = []

    def decide(messages, tools):
        seen.append(messages)
        return {"content": "好的。"}
    ctx = AgentRuntimeContext("custom", "test", "dummy", decider=decide, classifier=classifier,
                              resolver=lambda _: {"relationship": "new", "canonical_question": canonical or question})
    return asyncio.run(direct.run_direct_turn(question, ctx, emit=_emit, messages=None))


@pytest.fixture
def no_sec(monkeypatch):
    from app.agent_workflow import entities
    monkeypatch.setattr(entities, "resolve_ticker", lambda _: None)
    monkeypatch.setattr(entities, "verified_pair", lambda *_: False)
    monkeypatch.setattr(entities, "sec_title", lambda _: None)
    monkeypatch.setattr(entities, "mapped_title", lambda *_: None)


def _unbound_card(monkeypatch, on, question="最近有什么新闻？"):
    _switch(monkeypatch, "FINBOT_PH2_ENTITY_CARD_SHADOW", on)
    return _card_turn(question, classifier=lambda _: {"category": "D", "company": "Microsoft Corporation", "symbol": "MSFT"})


def test_entity_card_is_recorded_with_its_reasons_when_on(monkeypatch, no_sec):
    result = _unbound_card(monkeypatch, True)
    assert result["status"] == "waiting_for_input" and result["pending_request"]["question"] == "请确认这次指代的公司。"
    [record] = result["audit"]["entity_card_shadow"]
    assert record["classifier"] == {"symbol": "MSFT", "company": "Microsoft Corporation"}
    assert record["user_words"] == "最近有什么新闻？"
    assert record["would_use"] == {"symbol": "MSFT", "company": "Microsoft Corporation"}
    assert record["unbound"] == ["MSFT", "Microsoft Corporation"]
    assert record["fallbacks"] == {
        "resolve_ticker": "not_tried", "multi_entity": "fewer_than_two_symbols", "sec_pair": "mention_not_grounded",
        "two_companies": "company_has_no_unique_sec_ticker", "symbol_anchor": "symbol_not_written_in_user_words",
        "native_mapping": "no_name_without_latin_words"}


def test_entity_card_user_words_are_cut_to_200_characters(monkeypatch, no_sec):
    result = _unbound_card(monkeypatch, True, question="今天" * 150 + "有什么新闻？")
    assert result["status"] == "waiting_for_input"
    assert len(result["audit"]["entity_card_shadow"][0]["user_words"]) == 200


def test_entity_card_off_records_nothing_and_asks_the_same_card(monkeypatch, no_sec):
    on = _unbound_card(monkeypatch, True)
    off = _unbound_card(monkeypatch, False)
    assert "entity_card_shadow" not in off["audit"]
    for key in ("status", "answer"):
        assert on[key] == off[key], key
    volatile = {"id", "expires_at"}      # a new card id and expiry each turn
    assert {k: v for k, v in on["pending_request"].items() if k not in volatile} == {k: v for k, v in off["pending_request"].items() if k not in volatile}
    assert {k: v for k, v in on["audit"].items() if k != "entity_card_shadow"}.keys() == off["audit"].keys()
    assert on["audit"]["stages"]["resolver"] == off["audit"]["stages"]["resolver"]


def test_entity_card_not_asked_records_nothing_either_way(monkeypatch, no_sec):
    for on in (True, False):
        _switch(monkeypatch, "FINBOT_PH2_ENTITY_CARD_SHADOW", on)
        result = _card_turn("微软 MSFT 的营收", classifier=lambda _: {"category": "D", "symbol": "MSFT"},
                            canonical="微软（MSFT）的营收是多少？")
        assert result["pending_request"] is None and "entity_card_shadow" not in result["audit"]


def test_entity_card_record_failure_is_swallowed():
    from types import SimpleNamespace
    fake = SimpleNamespace(scope={"symbol": "MSFT"}, original="hi", audit={})
    assert direct.Turn.record_entity_card(fake, None, {}) is None      # entities=None cannot be iterated
    assert "entity_card_shadow" not in fake.audit


def test_entity_card_report_groups_by_classifier_entity_and_never_writes():
    from scripts.entity_card_report import records_from_audit, render, summarize
    msft = {"classifier": {"symbol": "MSFT", "company": "Microsoft Corporation"}, "user_words": "最近有什么新闻？",
            "fallbacks": {"sec_pair": "mention_not_grounded"}, "would_use": {"symbol": "MSFT", "company": "Microsoft Corporation"}}
    audits = [{"entity_card_shadow": [msft]}, {"entity_card_shadow": [{**msft, "user_words": "它的营收呢"}]},
              {"entity_card_shadow": [{"classifier": {"symbol": "AAPL"}, "user_words": "苹果", "fallbacks": {"sec_pair": "company_or_symbol_missing"}}]},
              {"other": 1}, None, {"entity_card_shadow": "bad"}]
    records = [r for a in audits for r in records_from_audit(a)]
    summary = summarize(records, samples=1)
    assert summary["total"] == 3
    first, second = summary["by_classifier_entity"]
    assert (first["entity"], first["count"], first["samples"]) == ("MSFT / Microsoft Corporation", 2, ["最近有什么新闻？"])
    assert first["fallback_reasons"] == {"sec_pair": {"mention_not_grounded": 2}}
    assert (second["entity"], second["count"]) == ("AAPL", 1)
    assert "3 次" in render(summary)


def test_entity_card_report_reads_stored_messages_without_writing(monkeypatch, disposable_database):
    import uuid
    from app.agent_chat_models import AgentConversation, AgentMessage
    from scripts import entity_card_report
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__])
    record = {"classifier": {"symbol": "MSFT"}, "user_words": "hi", "fallbacks": {}, "would_use": {"symbol": "MSFT"}}
    with SessionLocal() as db:
        cid = uuid.uuid4()
        db.add(AgentConversation(id=cid, owner_hash="o"))
        db.flush()
        db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=1, role="assistant", content="x",
                            tool_calls={"audit": {"entity_card_shadow": [record]}}))
        db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=2, role="assistant", content="y", tool_calls={"audit": {}}))
        db.commit()
        before = db.query(AgentMessage).count()
    assert [r["user_words"] for r in entity_card_report.load_records(days=1, limit=100)] == ["hi"]
    with SessionLocal() as db:
        assert db.query(AgentMessage).count() == before


# --------------------------------------------------------------------------------------------------------------------
# 1b. S5 rework after acceptance: other companies' rows, ordering, stopwords
# --------------------------------------------------------------------------------------------------------------------
def test_news_rank_row_about_another_company_is_skipped_with_several_tickers(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("特斯拉三季度财报：交付量创新高", tickers=["TSLA"], key="tsla")
    _add("苹果财报超预期", tickers=["AAPL"], key="aapl")
    _add("微软财报：云业务增长", tickers=["MSFT", "TSLA"], key="msft")       # shares one code with the request: kept
    _add("行业财报季前瞻", key="untagged")                                    # no code of its own: ranked, not dropped
    res = engine_mod.search_configured_news(tickers=["AAPL", "MSFT"], query="财报")
    assert sorted(i["url"].rsplit("/", 1)[-1] for i in res["items"]) == ["aapl", "msft", "untagged"]
    assert res["items"][-1]["url"].endswith("untagged")


def test_news_rank_a_short_code_counts_only_as_a_whole_case_exact_token(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("Fund flows for the week before earnings", key="noise", minutes_ago=1)   # "f" as a substring, never the code F
    _add("Ford (F) earnings beat estimates", key="ford-text", minutes_ago=5)     # the code written as a token
    _add("Ford quarterly earnings", tickers=["F"], key="ford-tag", minutes_ago=9)
    res = engine_mod.search_configured_news(tickers=["F"], query="earnings")
    order = [i["url"].rsplit("/", 1)[-1] for i in res["items"]]
    assert order[-1] == "noise" and set(order[:2]) == {"ford-text", "ford-tag"}
    noise = next(i for i in res["items"] if i["url"].endswith("noise"))
    assert "F" not in noise["matched_terms"]


def test_news_rank_row_about_another_company_single_ticker_does_not_take_a_slot(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("特斯拉三季度财报：交付量创新高", tickers=["TSLA"], key="tsla")
    res = engine_mod.search_configured_news(tickers=["AAPL"], query="苹果 iPhone 销量 财报")
    assert res["items"] == []


def test_news_rank_row_about_another_company_off_is_unchanged(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", False)
    _add("特斯拉三季度财报：交付量创新高", "AAPL supplier", tickers=["TSLA"], key="tsla")    # off: the old rule, a code in the text counts
    res = engine_mod.search_configured_news(tickers=["AAPL"])
    assert [i["url"].rsplit("/", 1)[-1] for i in res["items"]] == ["tsla"]


def test_news_rank_asked_code_rows_come_before_word_only_rows(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    for n in range(12):
        _add(f"Apple update {n}", tickers=["AAPL"], minutes_ago=100 + n, key=f"a{n}")
    for n in range(5):
        _add(f"茅台三季报业绩稳健{n}", minutes_ago=1 + n, key=f"n{n}")       # newer, and three of the query's two-character pieces
    res = engine_mod.search_configured_news(tickers=["AAPL"], query="苹果最新财报业绩怎么样", limit=10)
    assert len(res["items"]) == 10 and all(i["url"].rsplit("/", 1)[-1].startswith("a") for i in res["items"])
    assert "no_term_matched" not in res["meta"]


def test_news_rank_query_word_that_is_the_asked_code_is_not_counted(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("Apple update", "nothing about the question", tickers=["AAPL"])
    res = engine_mod.search_configured_news(tickers=["AAPL"], query="AAPL 并购")
    assert res["items"][0]["match"] == "none" and res["meta"]["no_term_matched"] is True
    assert res["items"][0]["matched_terms"] == ["AAPL"]


def test_news_rank_generic_words_are_stopwords_and_a_single_word_best_hit_keeps_the_web_hint(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    assert engine_mod._news_query_terms("苹果最近有什么消息") == ["苹果最近有什么消息", "苹果"]
    _add("消息人士称某公司将并购", key="noise")
    _add("苹果发布新品", key="one")
    res = engine_mod.search_configured_news(query="苹果最近有什么消息")
    assert [i["url"].rsplit("/", 1)[-1] for i in res["items"]] == ["one"]
    assert res["meta"]["hint"] == "fallback_to_web_search_recommended"
    _add("苹果有什么新品发布会", "苹果新品", key="two")
    res = engine_mod.search_configured_news(query="苹果新品")
    assert len(res["items"][0]["matched_terms"]) >= 2 and "hint" not in res["meta"]


def test_news_rank_ticker_only_search_has_no_hint(news_db, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_NEWS_RANK", True)
    _add("NVDA shipments", tickers=["NVDA"])
    assert "hint" not in engine_mod.search_configured_news(tickers=["NVDA"])["meta"]


# --------------------------------------------------------------------------------------------------------------------
# 2b / 5b. rework after acceptance: S1 non-soft path, M-12 masking, SEC-list flag, report query
# --------------------------------------------------------------------------------------------------------------------
def test_gate_row_undated_page_without_soft_keeps_the_old_refusal_when_on(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH2_WEB_DATE_SOFT", True)
    assert gate_row("Apple news", _page(), company="Apple", days_back=7) == (False, "requested_time_window_missing")
    assert gate_row("Apple news", _page(published_at=_day(1)), company="Apple", days_back=7) == (True, "sufficient_evidence")


def test_entity_card_user_words_are_masked_before_they_are_kept(monkeypatch, no_sec):
    _switch(monkeypatch, "FINBOT_PH2_ENTITY_CARD_SHADOW", True)
    question = "台积电的毛利率 sk-or-v1-abcdefSECRET1234567890 联系 me@example.com 13812345678 很长"
    result = _card_turn(question, classifier=lambda _: {"category": "D", "company": "Taiwan Semiconductor", "symbol": "TSM"})
    words = result["audit"]["entity_card_shadow"][0]["user_words"]
    assert "sk-or-v1" not in words and "me@example.com" not in words and "13812345678" not in words
    assert words.count("[REDACTED]") == 3 and words.startswith("台积电的毛利率")


def test_entity_card_record_says_whether_the_sec_list_was_ever_read(monkeypatch, no_sec):
    from app.agent_workflow import entities
    _switch(monkeypatch, "FINBOT_PH2_ENTITY_CARD_SHADOW", True)
    monkeypatch.setattr(entities, "_cache", None)
    assert _unbound_card(monkeypatch, True)["audit"]["entity_card_shadow"][0]["sec_list_available"] is False
    monkeypatch.setattr(entities, "_cache", [{"ticker": "MSFT", "title": "MICROSOFT CORP"}])
    assert _unbound_card(monkeypatch, True)["audit"]["entity_card_shadow"][0]["sec_list_available"] is True


def test_entity_card_report_query_returns_only_the_card_element(monkeypatch, disposable_database):
    import uuid
    from app.agent_chat_models import AgentConversation, AgentMessage
    from scripts import entity_card_report
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__])
    big = {"citations": [{"quote": "x" * 5000}] * 50}
    with SessionLocal() as db:
        db.query(AgentMessage).delete()         # rows an earlier test left in the shared test database
        cid = uuid.uuid4()
        db.add(AgentConversation(id=cid, owner_hash="o"))
        db.flush()
        for seq, calls in enumerate([{"audit": {"entity_card_shadow": [{"user_words": "keep", "classifier": {"symbol": "X"}}]}, **big},
                                     {"audit": {"other": 1}, **big}, {"citations": []}, None], start=1):
            db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=seq, role="assistant", content="x", tool_calls=calls))
        db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=9, role="user", content="u",
                            tool_calls={"audit": {"entity_card_shadow": [{"user_words": "not an assistant row"}]}}))
        db.commit()
    assert [r["user_words"] for r in entity_card_report.load_records(days=1, limit=100)] == ["keep"]
