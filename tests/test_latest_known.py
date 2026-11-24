"""The 「系统最新掌握」 block: who the owner's words mention, what the database holds for them, how it is laid out."""
import asyncio
import logging
import sqlite3
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete

from app import latest_known as lk
from app.agent_chat_models import AgentResearchQueue, NewsItem, PortfolioTransaction
from app.database import Base, SessionLocal, engine
from app.models import MarketPrice, SecFilingInventory

NOW = datetime(2026, 11, 23, 14, 43, tzinfo=UTC)  # 22:43 Beijing
SYMBOLS = ("NVDA", "AMD", "AAPL", "MSFT", "TSLA", "INTC", "QCOM", "IT")
OWNER = "o" * 64
KNOWN = {"NVDA", "AMD", "AAPL", "MSFT", "TSLA", "INTC", "QCOM", "IT", "ON", "AI", "CEO"}


def _wipe():
    with SessionLocal() as db:
        db.execute(delete(SecFilingInventory).where(SecFilingInventory.symbol.in_(SYMBOLS)))
        db.execute(delete(MarketPrice).where(MarketPrice.symbol.in_(SYMBOLS)))
        db.execute(delete(NewsItem).where(NewsItem.source_id == "lk-test"))
        db.execute(delete(AgentResearchQueue).where(AgentResearchQueue.owner_hash == OWNER))
        db.execute(delete(PortfolioTransaction).where(PortfolioTransaction.owner_hash == OWNER))
        db.commit()


@pytest.fixture()
def world(disposable_database, tmp_path, monkeypatch):
    Base.metadata.create_all(engine)
    _wipe()
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "sentinel.db"))
    lk.forget_known()
    yield tmp_path / "sentinel.db"
    _wipe()
    lk.forget_known()


def _filing(symbol, form="8-K", accepted="2026-11-23T14:02:00.000Z", observed=None, excerpt=None,
            kind="exhibit_99_1", status="fetched", filed=date(2026, 11, 23), review="pending_review"):
    observed = observed or datetime(2026, 11, 23, 14, 3, tzinfo=UTC)
    with SessionLocal() as db:
        db.add(SecFilingInventory(
            symbol=symbol, cik="0000000001", accession_number=f"0000000001-26-{uuid.uuid4().int % 10**6:06}",
            form=form, filed_at=filed, accepted_at=accepted, primary_document="x.htm", source_url="https://www.sec.gov/x",
            source="sec-edgar", review_status=review, observed_at=observed, content_status=status,
            content_kind=kind if status == "fetched" else None, content_excerpt=excerpt if status == "fetched" else None))
        db.commit()


def _news(symbol_list, title, published, inferred=False, source="测试源"):
    with SessionLocal() as db:
        db.add(NewsItem(source_id="lk-test", source_name=source, dedupe_key=uuid.uuid4().hex, title=title,
                        url="https://example.com/n", published_at=published, time_inferred=inferred,
                        tickers=symbol_list))
        db.commit()


def _bar(symbol, day, close, fetched=None, source="yahoo"):
    with SessionLocal() as db:
        db.add(MarketPrice(symbol=symbol, trading_date=day, open=close, high=close, low=close, close=close, volume=1,
                           source=source, fetched_at=fetched or datetime(day.year, day.month, day.day, 21, 59, tzinfo=UTC)))
        db.commit()


def _sentinel(path, symbol, price, ts):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS price_state (symbol TEXT PRIMARY KEY, price REAL NOT NULL, ts REAL NOT NULL)")
    conn.execute("INSERT OR REPLACE INTO price_state VALUES (?, ?, ?)", (symbol, price, ts))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------------------------- who is named

def test_two_companies_in_order_of_mention():
    assert lk.mentions("英伟达和 AMD 哪个毛利率高", known=KNOWN) == ["NVDA", "AMD"]


def test_a_word_inside_a_longer_word_is_not_a_company():
    assert lk.mentions("高通胀会怎样", known=KNOWN) == []
    assert lk.mentions("高通公司的财报", known=KNOWN) == ["QCOM"]
    assert lk.mentions("the metadata is stale", known=KNOWN | {"META"}) == []


def test_everyday_words_are_not_tickers_unless_cashtag_or_owned():
    assert lk.mentions("IT 板块", known=KNOWN) == []
    assert lk.mentions("AI 和 CEO 的看法", known=KNOWN) == []
    assert lk.mentions("$ON 怎么样", known=KNOWN) == ["ON"]
    assert lk.mentions("IT 怎么样", known=KNOWN, owned={"IT"}) == ["IT"]
    assert lk.mentions("英伟达NVDA怎么样 nvda", known=KNOWN) == ["NVDA"]


def test_a_company_with_no_data_is_not_named():
    assert lk.mentions("特斯拉呢", known={"NVDA"}) == []


def test_focus_first_then_mention_order_without_duplicates():
    assert lk.mentions("AMD 和英伟达，还有 AMD", focus="aapl", known=KNOWN) == ["AAPL", "AMD", "NVDA"]
    assert lk.mentions("英伟达", focus="NVDA", known=KNOWN) == ["NVDA"]


def test_previous_message_is_used_only_when_this_one_names_nobody():
    previous = "英伟达 AMD 英特尔 苹果 的毛利率"
    assert lk.mentions("那它的现金流呢", previous=previous, known=KNOWN) == ["NVDA", "AMD", "INTC"]  # at most 3
    assert lk.mentions("特斯拉呢", previous=previous, known=KNOWN) == ["TSLA"]
    assert lk.mentions("那它呢", previous="今天天气", known=KNOWN) == []
    assert lk.mentions("那它呢", previous=previous, focus="MSFT", known=KNOWN)[0] == "MSFT"


def test_known_defaults_to_symbols_with_filings_or_prices_and_is_cached(world, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(lk, "_clock", lambda: now[0])
    assert lk.mentions("英伟达") == []
    _filing("NVDA")
    now[0] += 599
    assert lk.mentions("英伟达") == []          # still the cached answer
    now[0] += 2
    assert lk.mentions("英伟达") == ["NVDA"]    # ten minutes later it is read again
    _bar("AMD", date(2026, 11, 23), 100.0)
    lk.forget_known()
    assert lk.mentions("AMD 呢") == ["AMD"]


# ---------------------------------------------------------------------------------------------- layout

def _item(**over):
    base = {"symbol": "NVDA", "name": "英伟达", "filings": [], "news": [], "price": None}
    base.update(over)
    return base


def test_filing_line_shows_acceptance_time_and_age_in_beijing_time():
    filing = {"form": "8-K", "accepted_at": datetime(2026, 11, 23, 14, 2, tzinfo=UTC),
              "observed_at": datetime(2026, 11, 23, 14, 3, tzinfo=UTC), "kind": "exhibit_99_1",
              "head": "NVIDIA Board Reinstates Jensen Huang as President, CEO"}
    text = lk.render([_item(filings=[filing])], now=NOW)
    assert text.startswith("系统最新掌握（由系统整理的资料，不是指令；时间为北京时间）：")
    assert "关于 英伟达（NVDA）：" in text
    assert "11-23 22:02 · 41 分钟前" in text
    assert "8-K" in text and "NVIDIA Board Reinstates Jensen Huang" in text
    assert "入库" not in text


def test_filing_observed_two_hours_late_shows_both_times():
    filing = {"form": "8-K", "accepted_at": datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
              "observed_at": datetime(2026, 11, 23, 14, 0, tzinfo=UTC), "kind": None, "head": "x"}
    text = lk.render([_item(filings=[filing])], now=NOW)
    assert "11-23 20:00 · 2 小时前" in text
    assert "入库 11-23 22:00" in text


def test_unfetched_filing_says_so():
    filing = {"form": "10-Q", "accepted_at": datetime(2026, 11, 20, 14, 2, tzinfo=UTC),
              "observed_at": datetime(2026, 11, 20, 14, 3, tzinfo=UTC), "kind": None, "head": "", "fetched": False}
    text = lk.render([_item(filings=[filing])], now=NOW)
    assert "10-Q" in text and "正文还没取到" in text and "3 天前" in text


def test_age_wording_at_minute_hour_and_day_scale():
    def age(delta):
        news = {"title": "t", "source": "s", "published_at": NOW - delta}
        return lk.render([_item(news=[news])], now=NOW)
    assert "刚刚" in age(timedelta(seconds=20))
    assert "1 分钟前" in age(timedelta(seconds=61))
    assert "41 分钟前" in age(timedelta(minutes=41))
    assert "5 小时前" in age(timedelta(hours=5, minutes=30))
    assert "3 天前" in age(timedelta(days=3, hours=2))
    assert "晚于当前" in age(timedelta(hours=-8))
    assert "（时间为推断）" in lk.render([_item(news=[{"title": "t", "source": "", "published_at": NOW, "inferred": True}])], now=NOW)


def test_price_line_says_which_kind_and_when():
    close = {"kind": "close", "value": 165.05, "change_pct": 31.5, "at": datetime(2026, 11, 23, 21, 59, tzinfo=UTC),
             "date": date(2026, 11, 23)}
    text = lk.render([_item(price=close)], now=NOW + timedelta(days=3))
    assert "日线收盘 165.05" in text and "较前收 +31.5%" in text and "2 天前" in text
    intraday = {"kind": "intraday", "value": 166.2, "change_pct": -0.4, "at": NOW - timedelta(minutes=5)}
    text = lk.render([_item(price=intraday)], now=NOW)
    assert "盘中价 166.20" in text and "较前收 -0.4%" in text and "5 分钟前" in text


def test_nothing_to_show_means_no_block():
    assert lk.render([], now=NOW) is None
    assert lk.render([_item()], now=NOW) is None


def test_each_line_and_the_whole_block_are_bounded():
    long_title = "很长的标题" * 80
    news = [{"title": long_title, "source": "s", "published_at": NOW - timedelta(minutes=i)} for i in range(3)]
    text = lk.render([_item(news=news)], now=NOW)
    assert all(len(line) <= 160 for line in text.splitlines())
    assert text.splitlines()[2].endswith("…")

    big = [_item(symbol=s, name="", news=[{"title": "标题" * 60, "source": "s", "published_at": NOW - timedelta(hours=1)}] * 3,
                 filings=[{"form": "8-K", "accepted_at": NOW, "observed_at": NOW, "kind": None, "head": "头" * 80}] * 3,
                 price={"kind": "close", "value": 1.0, "change_pct": None, "at": NOW, "date": date(2026, 11, 23)})
           for s in ("NVDA", "AMD", "AAPL")]
    text = lk.render(big, now=NOW, extra=["另提到：特斯拉（TSLA）（没有展开）"])
    assert len(text) <= 2000
    assert text.splitlines()[0] == lk.HEADING
    assert text.splitlines()[-1].startswith("另提到：")
    for symbol in ("NVDA", "AMD", "AAPL"):   # every company keeps its headline items; the surplus old ones went
        assert f"关于 {symbol}：" in text
    assert text.count("  价格 ") == 3 and text.count("  官方公告 ") >= 3 and text.count("  新闻 ") >= 3
    assert text.count("  新闻 ") < 9


# ---------------------------------------------------------------------------------------------- reading the database

def test_gather_reads_newest_filings_news_and_close(world):
    _filing("NVDA", accepted="2026-11-23T13:57:54.000Z",
            excerpt="EX-99.1 2 nov23pressrelease.htm EX-99.1  Document  NVIDIA Board Reinstates Jensen Huang as CEO")
    _filing("NVDA", accepted="2026-11-17T21:20:51.000Z", filed=date(2026, 11, 17), excerpt="EX-99.1 2 q3.htm EX-99.1  Document  Q3 results")
    _filing("NVDA", form="10-Q", accepted=None, status="not_fetched", filed=date(2026, 11, 1))
    _filing("NVDA", accepted="2026-11-24T00:00:00.000Z", filed=date(2026, 11, 24), review="rejected", excerpt="skip me")
    _news(["NVDA", "AMD"], "老新闻", NOW - timedelta(hours=9))
    _news(["NVDA"], "新新闻", NOW - timedelta(minutes=30))
    _news(["NVDA"], "新新闻", NOW - timedelta(minutes=29))   # same title twice: shown once
    _news(["AMD"], "别家新闻", NOW)
    _bar("NVDA", date(2026, 11, 20), 125.53)
    _bar("NVDA", date(2026, 11, 23), 165.05)
    [item] = lk.gather(["NVDA", "TSLA"], now=NOW)             # TSLA has nothing: no entry
    assert item["symbol"] == "NVDA" and item["name"] == "英伟达"
    assert [f["form"] for f in item["filings"]] == ["8-K", "8-K", "10-Q"]
    assert item["filings"][0]["head"] == "NVIDIA Board Reinstates Jensen Huang as CEO"
    assert lk._head("EX-99.1 4 d117670dex991.htm EX-99.1 EX-99.1 Exhibit 99.1 Intel Corporation News", "exhibit_99_1") == "Intel Corporation News"
    assert lk._head("EX-99.1 2 a.htm EX-99.1  Document  " + "word " * 40, "exhibit_99_1").endswith("…")
    assert item["filings"][0]["accepted_at"] == datetime(2026, 11, 23, 13, 57, 54, tzinfo=UTC)
    assert item["filings"][2]["fetched"] is False
    assert [n["title"] for n in item["news"]] == ["新新闻", "老新闻"]
    assert item["price"]["kind"] == "close" and item["price"]["value"] == pytest.approx(165.05)
    assert item["price"]["change_pct"] == pytest.approx((165.05 / 125.53 - 1) * 100)


def test_8k_body_head_is_the_first_item_not_the_cover_page(world):
    cover = "nvda-20260902\n\nUNITED STATES\n\nFORM 8-K\n\nCURRENT REPORT\n" + "x" * 300 + "\nItem 5.02 Departure of Directors or Officers\nblah"
    _filing("NVDA", kind="primary_document", excerpt=cover)
    [item] = lk.gather(["NVDA"], now=NOW)
    assert item["filings"][0]["head"] == "Item 5.02 Departure of Directors or Officers"


def test_intraday_price_from_the_sentinel_when_fresh(world):
    _bar("NVDA", date(2026, 11, 20), 100.0)
    _bar("NVDA", date(2026, 11, 23), 120.0)
    _sentinel(world, "NVDA", 126.0, (NOW - timedelta(minutes=10)).timestamp())
    [item] = lk.gather(["NVDA"], now=NOW)
    assert item["price"]["kind"] == "intraday" and item["price"]["value"] == 126.0
    # 22:33 Beijing is 09:33 in New York on 11-23, so the previous close is the one of 11-20
    assert item["price"]["change_pct"] == pytest.approx(26.0)


def test_stale_or_missing_or_broken_sentinel_falls_back_to_the_close(world):
    _bar("NVDA", date(2026, 11, 20), 100.0)
    _bar("NVDA", date(2026, 11, 23), 120.0)
    assert lk.gather(["NVDA"], now=NOW)[0]["price"]["kind"] == "close"          # no file at all
    _sentinel(world, "NVDA", 126.0, (NOW - timedelta(days=7)).timestamp())
    assert lk.gather(["NVDA"], now=NOW)[0]["price"]["kind"] == "close"          # last week's row
    world.write_bytes(b"not a database")
    assert lk.gather(["NVDA"], now=NOW)[0]["price"]["kind"] == "close"          # garbage


def test_a_locked_sentinel_does_not_cost_the_block(world):
    _bar("NVDA", date(2026, 11, 23), 120.0)
    _sentinel(world, "NVDA", 126.0, (NOW - timedelta(minutes=1)).timestamp())
    holder = sqlite3.connect(world, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        started = time.monotonic()
        text, symbols = asyncio.run(lk.block_for("英伟达怎么样", previous=None, focus=None, owner_hash="", now=NOW))
        assert time.monotonic() - started < lk.BUDGET_SECONDS + 0.3
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert symbols == ["NVDA"] and "日线收盘 120.00" in text and "盘中价" not in text


# ---------------------------------------------------------------------------------------------- the whole path

def test_block_for_reproduces_the_incident_line(world):
    _filing("NVDA", accepted="2026-11-23T14:02:00.000Z", observed=datetime(2026, 11, 23, 14, 3, tzinfo=UTC),
            excerpt="EX-99.1 2 a.htm EX-99.1  Document  NVIDIA Board Reinstates Jensen Huang as President, CEO and Board Director")
    text, symbols = asyncio.run(lk.block_for("黄仁勋是不是复任英伟达 CEO 了？", previous=None, focus=None, owner_hash="", now=NOW))
    assert symbols == ["NVDA"]
    assert "11-23 22:02 · 41 分钟前" in text and "8-K" in text and "Reinstates Jensen Huang" in text


def test_five_companies_give_three_sections_and_one_line_for_the_rest(world):
    for symbol in ("NVDA", "AMD", "AAPL", "MSFT", "TSLA"):
        _filing(symbol, excerpt=f"EX-99.1 2 a.htm EX-99.1  Document  {symbol} news")
    text, symbols = asyncio.run(lk.block_for("英伟达 AMD 苹果 微软 特斯拉 比一比", previous=None, focus=None, owner_hash="", now=NOW))
    assert symbols == ["NVDA", "AMD", "AAPL"]
    assert text.count("关于 ") == 3
    assert text.splitlines()[-1] == "另提到：微软（MSFT）、特斯拉（TSLA）（没有展开）"


def test_the_focus_company_comes_first_and_a_follow_up_keeps_its_subject(world):
    _filing("NVDA", excerpt="EX-99.1 2 a.htm EX-99.1  Document  nvda")
    _filing("AMD", excerpt="EX-99.1 2 a.htm EX-99.1  Document  amd")
    _, symbols = asyncio.run(lk.block_for("英伟达怎么样", previous=None, focus="AMD", owner_hash="", now=NOW))
    assert symbols == ["AMD", "NVDA"]
    _, symbols = asyncio.run(lk.block_for("那它的现金流呢", previous="英伟达最近怎么样", focus=None, owner_hash="", now=NOW))
    assert symbols == ["NVDA"]
    assert asyncio.run(lk.block_for("高通胀会怎样", previous=None, focus=None, owner_hash="", now=NOW)) == (None, [])


def test_owner_queue_and_holdings_make_everyday_tickers_count_but_guests_get_none_of_that(world):
    _filing("INTC", excerpt="EX-99.1 2 a.htm EX-99.1  Document  intc")
    with SessionLocal() as db:
        db.add(AgentResearchQueue(owner_hash=OWNER, symbols=["INTC"]))
        db.add(PortfolioTransaction(owner_hash=OWNER, symbol="NVDA", kind="buy", quantity=10, price=100, occurred_on=date(2026, 11, 1)))
        db.commit()
    _filing("NVDA", excerpt="EX-99.1 2 a.htm EX-99.1  Document  nvda")
    assert lk._owned_symbols(OWNER) == {"INTC", "NVDA"}
    assert lk._owned_symbols("x" * 64) == set()
    # an everyday word is a ticker for the owner only when it is theirs
    _filing("IT", excerpt="EX-99.1 2 a.htm EX-99.1  Document  it")
    with SessionLocal() as db:
        row = db.get(AgentResearchQueue, OWNER)
        row.symbols = ["INTC", "IT"]
        db.commit()
    lk.forget_known()
    assert asyncio.run(lk.block_for("IT 怎么样", previous=None, focus=None, owner_hash=OWNER, now=NOW))[1] == ["IT"]
    assert asyncio.run(lk.block_for("IT 怎么样", previous=None, focus=None, owner_hash="", now=NOW)) == (None, [])


def test_a_database_error_gives_no_block_and_one_log_line(world, monkeypatch, caplog):
    def broken(symbols, *, now):
        raise RuntimeError("database is down")
    monkeypatch.setattr(lk, "gather", broken)
    _filing("NVDA")
    with caplog.at_level(logging.INFO, logger="finbot.latest_known"):
        assert asyncio.run(lk.block_for("英伟达", previous=None, focus=None, owner_hash="", now=NOW)) == (None, [])
    assert len([r for r in caplog.records if r.name == "finbot.latest_known" and r.levelno >= logging.WARNING]) == 1


def test_a_slow_reader_is_cut_off_at_the_budget(world, monkeypatch, caplog):
    def slow(symbols, *, now):
        time.sleep(2.5)
        return []
    monkeypatch.setattr(lk, "gather", slow)
    _filing("NVDA")

    async def timed():
        started = time.monotonic()
        result = await lk.block_for("英伟达", previous=None, focus=None, owner_hash="", now=NOW)
        return result, time.monotonic() - started

    with caplog.at_level(logging.INFO, logger="finbot.latest_known"):
        result, elapsed = asyncio.run(timed())
    assert result == (None, [])
    assert elapsed < lk.BUDGET_SECONDS + 0.4
    assert len([r for r in caplog.records if r.name == "finbot.latest_known" and r.levelno >= logging.WARNING]) == 1
