"""5e-2b: the evening-before preparation (``app.kernel.prep``) — which companies, when they are out in Beijing, and how it is written and sent.

No network: the model is a script (the brief tests' fixtures), the calendar rows are stored directly; the suite's disposable PostgreSQL."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app import earnings_calendar as ec
from app.database import Base, SessionLocal, engine
from app.kernel import prep
from tests.test_agent_notify import OWNER_HASH, _bind, owner  # noqa: F401  (fixture)
from tests.test_kernel_brief import env, outbox, script  # noqa: F401  (fixtures)
from tests.test_kernel_loop import step

EVENING = datetime(2027, 1, 20, 20, 30, tzinfo=prep.BEIJING)        # a Beijing Wednesday evening
KNOWN = prep._known          # the real one (the calendar fixture replaces it)
TEXT = "英特尔今晚美东盘后出 Q4 财报，北京时间明早 5 点前后。市场预期每股收益 0.25 美元、营收 158.5 亿美元（Finnhub，调整后口径）。"


def row(symbol, day, hour, **fields):
    return {"symbol": symbol, "report_date": day, "hour": hour, "fiscal_year": 2026, "fiscal_quarter": 4, "eps_estimate": 0.25,
            "revenue_estimate": 15.85e9, "eps_actual": None, "revenue_actual": None, **fields}


@pytest.fixture
def calendar(env, monkeypatch):
    Base.metadata.create_all(engine, tables=[ec.EarningsCalendar.__table__, ec.EarningsPrep.__table__])
    with SessionLocal() as db:
        db.query(ec.EarningsPrep).delete()
        db.query(ec.EarningsCalendar).delete()
        db.commit()
    monkeypatch.setattr(ec, "tracked_symbols", lambda owner: ["INTC", "AAPL", "MSFT", "TSLA", "META", "AMD"])
    monkeypatch.setattr(prep, "_known", lambda symbols, now: "系统最新掌握：英特尔上一季营收 165.13 亿美元。")
    ec.store([row("INTC", date(2027, 1, 20), "amc"),                    # tonight after the close: in
              row("AAPL", date(2027, 1, 21), "bmo"),                    # tomorrow before the open: in (out tomorrow evening Beijing)
              row("MSFT", date(2027, 1, 20), None),                     # not said, today: in
              row("TSLA", date(2027, 1, 20), "bmo"),                    # today before the open: out already in Beijing (20:00): not tonight's
              row("META", date(2027, 1, 21), "amc"),                    # tomorrow after the close: tomorrow evening's
              row("AMD", date(2027, 1, 20), "amc", eps_actual=0.5)],    # out already: no
             datetime.now(UTC))
    yield env
    with SessionLocal() as db:            # other suites read the calendar (latest_known): leave it as found
        db.query(ec.EarningsPrep).delete()
        db.query(ec.EarningsCalendar).delete()
        db.commit()


def run(now=EVENING, **kwargs):
    return asyncio.run(prep.run_once(OWNER_HASH, now.astimezone(UTC), **kwargs))


def test_tonights_companies_are_after_the_close_today_and_before_the_open_tomorrow(calendar):
    picked = ec.reporting_next(["INTC", "AAPL", "MSFT", "TSLA", "META", "AMD"], date(2027, 1, 20))
    assert [r["symbol"] for r in picked] == ["INTC", "MSFT", "AAPL"]
    assert ec.beijing_release(picked[0]) == "北京时间 01-21 清晨 4 点到 6 点前后（美东 01-20 盘后）"
    assert ec.beijing_release(picked[2]) == "北京时间 01-21 晚上 7 点到 9 点前后（美东 01-21 盘前）"
    assert "盘前还是盘后没有说" in ec.beijing_release(picked[1])


def test_it_is_due_from_20_to_23_beijing_once_a_day(calendar):
    assert prep.due_day(EVENING.astimezone(UTC)) == "2027-01-20"
    assert prep.due_day((EVENING - timedelta(hours=1)).astimezone(UTC)) is None
    assert prep.due_day(EVENING.replace(hour=23).astimezone(UTC)) is None
    script(calendar, [step(text=TEXT)])
    first = run()
    assert first["outcome"] == "done" and run() is None


def test_shadow_writes_and_keeps_it_without_sending(calendar):
    fake = script(calendar, [step(text=TEXT)])
    done = run()
    assert (done["outcome"], done["symbols"], done["delivery"]) == ("done", "INTC,MSFT,AAPL", None)
    assert done["message"] == prep.HEAD + TEXT and outbox("prep") == []
    system = fake.calls[0]["messages"][0]["content"] if isinstance(fake.calls[0], dict) else str(fake.calls[0])
    assert "北京时间 01-21 清晨 4 点到 6 点前后" in system and "系统最新掌握：英特尔上一季营收" in system and "不要自己换算" in system


def test_on_sends_it_through_the_outbox_outside_the_notify_count(calendar):
    calendar.monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    _bind()
    script(calendar, [step(text=TEXT)])
    done = run()
    assert (done["outcome"], done["delivery"]) == ("done", "queued") and len(outbox("prep")) == 1
    from app import agent_telegram
    assert "prep" in agent_telegram.UNCAPPED


def test_a_failed_turn_sends_the_code_written_list(calendar):
    script(calendar, [])            # the model never answers
    done = run()
    assert done["outcome"] == "done" and done["reason"].endswith("改发原样列表。")
    assert "英特尔（INTC）：北京时间 01-21 清晨" in done["message"] and "下次财报：2027-01-20" in done["message"]


def test_nothing_tonight_and_off_write_nothing(calendar):
    fake = script(calendar, [])
    quiet = run(EVENING + timedelta(days=3))
    assert (quiet["outcome"], quiet["reason"]) == ("skipped", prep.NOTHING) and fake.calls == []
    calendar.monkeypatch.setenv("FINBOT_DUTY_MODE", "off")
    assert run(EVENING + timedelta(days=4))["outcome"] == "skipped_off"


def test_an_empty_answer_is_no_preview_and_the_list_goes_instead(calendar):
    script(calendar, [step(text=""), step(text="")])
    done = run()
    assert done["reason"].endswith("改发原样列表。") and "这次没能生成回答" not in done["message"]
    assert "英特尔（INTC）：北京时间 01-21 清晨" in done["message"]


def test_the_latest_known_block_is_built_three_companies_at_a_time(monkeypatch):
    from app import latest_known
    seen = []
    monkeypatch.setattr(latest_known, "gather", lambda symbols, **kw: (seen.append(list(symbols)), [{"symbol": s} for s in symbols])[1])
    monkeypatch.setattr(latest_known, "_render", lambda items, now, extra, rows: ("块：" + ",".join(i["symbol"] for i in items), []))
    text = KNOWN(["A", "B", "C", "D", "E"], EVENING)
    assert seen == [["A", "B", "C"], ["D", "E"]] and text == "块：A,B,C\n\n块：D,E"


def test_the_prompt_says_where_the_time_is_and_leaves_buying_to_him():
    from app.kernel import prompt
    text = prompt.prep_system_text()
    assert "十几个小时" not in text and "out 里" in text and "决定在他" in text and "不给买卖建议" not in text
    assert "称呼他用「你」" in text and "没有就整项不写" in text
    assert "【接下来要发财报的】" in prompt.prep_block([], {}, None)
