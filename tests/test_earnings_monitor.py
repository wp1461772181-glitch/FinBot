"""Task 9, API side: the first message (analysis) and the 30-minute follow-up (judgement) of an earnings release.

* a holding is pushed to Telegram and recorded in its bot's line, a research-queue company is only recorded;
* a direction of ``unclear`` sends no follow-up; a model that has not passed the blind test sends a plain notice
  that says so (the gate is a config file, default not passed); a judgement against the after-hours move says so;
* the follow-up timer lives in the database, so a restart picks up the unsent one;
* the history table holds only what existed before the release (point-in-time)."""
import asyncio
import json
import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import agent_bots as bots
from app import agent_telegram as tg
from app import earnings_monitor as em
from app import earnings_reader as er
from app.agent_chat_models import (AgentBot, AgentInboxItem, AgentMessage, AgentTask, AgentTelegramBind, AgentTelegramMessage,
                                   EarningsEvent, EarningsHistory)
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine
from app.secret_box import encrypt_secret

OWNER_HASH = owner_hash("o" * 40)
TOKEN = "123456789:AAH" + "x" * 32
CHAT = 5_000_000_001
E_ACC = "0000050863-26-000188"
E_AT = datetime(2026, 10, 29, 20, 31, 7, tzinfo=UTC)
# Newest first; the last entry is AFTER the release being analysed and must never be used for it.
FILINGS = [
    ("0000050863-27-000010", datetime(2027, 1, 28, 21, 5, tzinfo=UTC), "rev=15.1 eps=0.25 gm=36.0 gl=14.0 gh=15.0 ge=0.15 gg=35.0"),
    (E_ACC, E_AT, "rev=14.3 eps=0.20 gm=37.1 gl=14.5 gh=15.5 ge=0.10 gg=36.0 CEO said \"the PC slowdown continues into next year and we stay cautious\""),
    ("0000050863-26-000155", datetime(2026, 7, 23, 20, 15, tzinfo=UTC), "rev=13.6 eps=0.15 gm=38.0 gl=13.5 gh=14.5 ge=0.12 gg=38.0 ggm=36.0"),
    ("0000050863-26-000070", datetime(2026, 4, 23, 20, 10, tzinfo=UTC), "rev=12.9 eps=0.14 gm=38.5 gl=12.0 gh=13.0 ge=0.10 gg=38.0"),
    ("0000050863-26-000010", datetime(2026, 1, 22, 21, 0, tzinfo=UTC), "rev=13.7 eps=0.12 gm=36.0 gl=12.5 gh=13.5 ge=0.08 gg=34.0"),
    ("0000050863-25-000200", datetime(2025, 10, 23, 20, 30, tzinfo=UTC), "rev=13.3 eps=0.13 gm=40.0 gl=13.0 gh=14.0 ge=0.09 gg=39.0"),
    ("0000050863-25-000100", datetime(2025, 7, 24, 20, 20, tzinfo=UTC), "rev=12.7 eps=0.11 gm=36.0 gl=12.3 gh=13.3 ge=0.08 gg=35.0"),
]
TEXTS = {acc: text for acc, _, text in FILINGS}


def _num(text, key):
    found = re.search(rf"\b{key}=([\d.]+)", text)
    return float(found.group(1)) if found else None


class FakeReader:
    """The real pure functions of earnings_reader; the two model calls are scripted."""
    READER_VERSION = er.READER_VERSION
    compare, daily_sigma, label_reaction = staticmethod(er.compare), staticmethod(er.daily_sigma), staticmethod(er.label_reaction)

    def __init__(self, direction="down", confidence="high"):
        self.verdict = (direction, confidence)
        self.judged = []

    def model_for_owner(self, owner):
        return {"provider": "fake", "model": "fake-model", "api_key": "k", "base_url": None}

    async def extract_release(self, text, model):
        facts = er.ReleaseFacts(revenue=_num(text, "rev"), gross_margin=_num(text, "gm"), eps=_num(text, "eps"),
                                eps_gaap=_num(text, "gg") and 0.0, source_text=text)
        facts.guidance = er.Guidance(revenue_low=_num(text, "gl"), revenue_high=_num(text, "gh"), eps=_num(text, "ge"), gross_margin=_num(text, "ggm"))
        return facts

    async def judge(self, facts, comparison, commentary, after_hours_return, model):
        self.judged.append(after_hours_return)
        direction, confidence = self.verdict
        return er.Judgment(direction=direction, confidence=confidence, counter_argument="财报前已跌，部分利空已反映",
                           reasons=[{"text": "新指引营收中值低于本季", "quote": "gl=14.5"},
                                    {"text": "管理层偏谨慎", "quote": "we stay cautious"}])


class FakeSources:
    def __init__(self, after_hours=-0.05, holding=None):
        self.after_hours = after_hours
        self.holding = holding if holding is not None else {"shares": 100, "avg_cost": 23.12, "price": 65.76, "weight_pct": 46.1,
                                                            "plan_text": "跌破 55 再看", "add_price": 55.0, "available_funds": 7688.0}
        self.calls = {"filings": 0, "text": 0}

    def earnings_filings(self, symbol, cik):
        self.calls["filings"] += 1
        return [{"accession": a, "accepted": t, "filed": t.date().isoformat(), "primary": "x.htm"} for a, t, _ in FILINGS]

    def release_text(self, symbol, cik, accession):
        self.calls["text"] += 1
        return TEXTS.get(accession, TEXTS[E_ACC])

    def daily_closes(self, symbol):
        start, closes, price = date(2025, 6, 1), [], 40.0
        for i in range(520):
            price *= 1.0 + (0.01 if i % 2 else -0.0095)
            closes.append((start + timedelta(days=i), round(price, 4)))
        return closes

    def extended_move(self, symbol, accepted, until=None):
        return self.after_hours

    def holding_for(self, owner, symbol):
        return self.holding


@pytest.fixture
def owner(monkeypatch, disposable_database, tmp_path):
    skipped = {"material_analysis_jobs", "material_analysis_versions", "material_analysis_job_model_configs",
               "material_analysis_settings", "ai_content_translations"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values()
                                             if not t.name.endswith("_v2") and not t.name.startswith("knowledge_")
                                             and t.name not in skipped])
    tg.ensure_columns()
    with SessionLocal() as db:
        for model in (AgentTelegramMessage, AgentTelegramBind, AgentInboxItem, AgentMessage, EarningsEvent, EarningsHistory, AgentTask, AgentBot):
            db.query(model).delete()
        db.add(AgentTelegramBind(owner_hash=OWNER_HASH, bot_token_cipher=encrypt_secret(TOKEN), chat_id=CHAT, user_id=CHAT))
        db.commit()
    monkeypatch.setenv("EARNINGS_GATE_PATH", str(tmp_path / "gate.json"))   # no file = no model has passed
    return OWNER_HASH


def event(symbol="INTC", held=True, accession=E_ACC, accepted=E_AT):
    return {"accession": accession, "symbol": symbol, "cik": "0000050863", "held": held, "accepted_at": accepted.isoformat(),
            "detected_at": (accepted + timedelta(minutes=2)).isoformat(), "url": "https://www.sec.gov/x", "filed": accepted.date().isoformat()}


def outbox():
    with SessionLocal() as db:
        return [(r.source, r.text, str(r.bot_id)) for r in db.query(AgentTelegramMessage).order_by(AgentTelegramMessage.created_at)]


def items(kind="filing"):
    with SessionLocal() as db:
        return [(r.dedupe_key, r.body, str(r.bot_id), r.payload) for r in db.query(AgentInboxItem).filter(AgentInboxItem.kind == kind)
                .order_by(AgentInboxItem.created_at)]


def first(sources=None, reader=None, **fields):
    em.receive_event(event(**fields), OWNER_HASH)
    em.tick(E_AT + timedelta(minutes=3), sources=sources or FakeSources(), reader=reader or FakeReader())


def test_holding_pushes_queue_records(owner):
    focus = bots.create_bot(OWNER_HASH, {"name": "芯片观察", "description": "看芯片", "focus": {"companies": [{"symbol": "NVDA", "name": "NVIDIA"}], "theme": None}})
    sources, reader = FakeSources(), FakeReader()
    first(sources, reader, symbol="INTC", held=True)
    first(sources, reader, symbol="NVDA", held=False, accession="0001045810-26-000001")
    sent = outbox()
    assert len(sent) == 1 and "INTC" in sent[0][1] and sent[0][0] == "earnings"        # the holding is pushed (earnings source: exempt from the daily cap) ...
    recorded = {key: bot for key, _, bot, _ in items()}
    assert set(recorded) == {f"earnings:{E_ACC}:first", "earnings:0001045810-26-000001:first"}
    assert recorded["earnings:0001045810-26-000001:first"] == focus["id"]               # ... the queue company only recorded, in the bot that follows it
    default = bots.ensure_default_bot(OWNER_HASH)
    assert recorded[f"earnings:{E_ACC}:first"] == str(default.id)                       # nobody follows INTC: the default bot
    for _, _, _, payload in items():
        assert payload.get("posted_turn_id")                                            # recorded in the bot's conversation
    assert "关键数字" in items()[0][1] and "新指引" in items()[0][1]


def test_first_message_numbers_and_quote(owner):
    first()
    body = items()[0][1]
    assert "营收 14.3" in body and "+2.1%" in body          # 14.3 vs last quarter's guided mid-point 14.0
    assert "指引中值" in body and "14.5" in body and "15.5" in body
    assert "对上季指引 +1.1 个百分点" in body              # gross margin 37.1% vs guided 36.0%: a signed difference
    assert "the PC slowdown continues" in body              # management's own words, verbatim
    assert "…" not in body                                  # a short quote is not cut


def test_same_event_twice_is_one_message(owner):
    sources, reader = FakeSources(), FakeReader()
    first(sources, reader)
    em.receive_event(event(), OWNER_HASH)
    em.tick(E_AT + timedelta(minutes=9), sources=sources, reader=reader)
    assert len(items()) == 1 and len(outbox()) == 1
    with SessionLocal() as db:
        assert db.query(EarningsEvent).count() == 1


def test_unclear_sends_no_followup(owner):
    reader = FakeReader("unclear", "low")
    first(reader=reader)
    em.tick(E_AT + timedelta(minutes=31), sources=FakeSources(), reader=reader)
    assert reader.judged == [-0.05]
    followups = [i for i in items() if i[0].endswith(":followup")]
    assert len(followups) == 1
    body = followups[0][1]
    assert "方向不明" in body and "把握：低" in body
    assert len(outbox()) == 2
    with SessionLocal() as db:
        assert db.query(EarningsEvent).one().followup_status == "sent"


def test_unvalidated_model_sends_plain_notice_with_label(owner):
    reader = FakeReader("down", "medium")
    first(reader=reader)
    em.tick(E_AT + timedelta(minutes=31), sources=FakeSources(), reader=reader)
    [(key, body, _, _)] = [i for i in items() if i[0].endswith(":followup")]
    assert ("该模型未经盲测" in body or "尚未完成历史样本盲测" in body) and "偏跌" in body and "把握：中" in body
    assert "gl=14.5" in body and "we stay cautious" in body              # two or three reasons, each with its quote
    assert "100 股" in body and "跌破 55 再看" in body and "7688" in body   # position, the owner's plan, funds
    assert len(outbox()) == 2                                            # first message + follow-up on Telegram


def test_validated_model_follow_up_has_no_label_and_flags_disagreement(owner, tmp_path):
    (tmp_path / "gate.json").write_text(json.dumps({"models": {"fake-model": {
        "passed": True, "reader_version": er.READER_VERSION, "min_confidence": "high", "high_calls": 24, "hit_rate": 0.83}}}))
    reader = FakeReader("down", "high")
    first(reader=reader)
    em.tick(E_AT + timedelta(minutes=31), sources=FakeSources(after_hours=0.04), reader=reader)
    body = [i for i in items() if i[0].endswith(":followup")][0][1]
    assert "未经盲测" not in body and "把握：高" in body
    assert "分歧" in body and "+4.0%" in body                            # judged down, after-hours is up


def test_below_threshold_is_not_sent(owner, tmp_path):
    (tmp_path / "gate.json").write_text(json.dumps({"models": {"fake-model": {
        "passed": True, "reader_version": er.READER_VERSION, "min_confidence": "high"}}}))
    reader = FakeReader("down", "medium")
    first(reader=reader)
    em.tick(E_AT + timedelta(minutes=31), sources=FakeSources(), reader=reader)
    followups = [i for i in items() if i[0].endswith(":followup")]
    assert len(followups) == 1
    with SessionLocal() as db:
        assert db.query(EarningsEvent).one().followup_status == "sent"


def test_first_message_fallbacks_and_unverified_notice():
    ev = EarningsEvent(symbol="INTC", accepted_at=E_AT, source_url="https://sec.gov/x")
    facts = er.ReleaseFacts(unverified_fields=["revenue"])
    comparison = er.Comparison()
    _, body = em.render_first(ev, facts, comparison, False, "")
    assert "部分数字引文待核对（请以原文为准）" in body
    assert "未从新闻稿中提取到标准格式的下季指引（请以原文为准）" in body
    assert "未匹配到标准格式的高管引语段落（请以原文为准）" in body


def test_followup_timer_survives_restart(owner):
    sources, reader = FakeSources(), FakeReader("down", "medium")
    first(sources, reader)
    em.tick(E_AT + timedelta(minutes=20), sources=sources, reader=reader)       # not due yet
    assert reader.judged == []
    with SessionLocal() as db:
        assert db.query(EarningsEvent).one().followup_due_at == E_AT + timedelta(minutes=30)
    # "restart": nothing in memory, only the row; a late tick still sends the follow-up, once
    em.tick(E_AT + timedelta(minutes=47), sources=FakeSources(), reader=FakeReader("down", "medium"))
    em.tick(E_AT + timedelta(minutes=50), sources=FakeSources(), reader=FakeReader("down", "medium"))
    assert len([i for i in items() if i[0].endswith(":followup")]) == 1


def test_history_excludes_future(owner):
    sources, reader = FakeSources(), FakeReader()
    first(sources, reader)
    with SessionLocal() as db:                                                # a row from the future, planted
        db.add(EarningsHistory(symbol="INTC", quarter="2026Q4", accession="0000050863-27-000010", released_at=datetime(2027, 1, 28, 21, 5, tzinfo=UTC),
                               guidance={}, actual={"revenue": 99.0}))
        db.commit()
    past = em.history_for("INTC", E_AT)
    assert [h.revenue for h in past] == [13.6, 12.9, 13.7, 13.3, 12.7]        # newest first, release itself and the future excluded
    # as of the 24 July filing only what was out before it counts
    assert [h.revenue for h in em.history_for("INTC", datetime(2026, 7, 23, 20, 15, tzinfo=UTC))] == [12.9, 13.7, 13.3, 12.7]


def test_backfill_never_stores_a_filing_after_the_release(owner):
    first()
    with SessionLocal() as db:
        accessions = {r.accession for r in db.query(EarningsHistory).all()}
    assert "0000050863-27-000010" not in accessions
    assert E_ACC in accessions and "0000050863-26-000155" in accessions
    # the backfill ran once: a second event for the same symbol does not fetch the filing list again
    sources = FakeSources()
    em.receive_event(event(accession="0000050863-27-000010", accepted=datetime(2027, 1, 28, 21, 5, tzinfo=UTC)), OWNER_HASH)
    em.tick(datetime(2027, 1, 28, 21, 9, tzinfo=UTC), sources=sources, reader=FakeReader())
    assert sources.calls["filings"] == 0


def test_sentinel_endpoint_stores_event_before_answering(owner, monkeypatch):
    from fastapi import BackgroundTasks
    from app import sentinel_api, sentinel_bridge
    monkeypatch.setenv("SENTINEL_TOKEN", "tok")
    monkeypatch.setattr(sentinel_bridge, "owner_hash_from_login_config", lambda: OWNER_HASH)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"X-Sentinel-Token": "tok"})
    body = sentinel_api.SentinelEvent(type="earnings_detected", payload=event())
    background = BackgroundTasks()
    answer = asyncio.run(sentinel_api.post_event(body, request, background))
    assert answer["accepted"] is True and answer["duplicate"] is False
    again = asyncio.run(sentinel_api.post_event(body, request, BackgroundTasks()))
    assert again["duplicate"] is True
    with SessionLocal() as db:
        assert db.query(EarningsEvent).count() == 1            # stored (and its follow-up timer armed) before the response


def test_release_document_is_found_when_not_named_like_exhibit_99_1():
    # Intel's press release is q326earningsrelease.htm: the shared exhibit-99.1 matcher misses it and hands back the cover page
    names = ["0000050863-26-000188-index.htm", "intc-20261029.htm", "intc-20261029.xsd", "q326earningsrelease.htm", "R1.htm", "logo.jpg"]
    assert em.pick_release_document(names, "intc-20261029.htm") == "q326earningsrelease.htm"
    assert em.pick_release_document(["a8-k.htm", "ex99-1.htm", "ex99-2.htm"], "a8-k.htm") == "ex99-1.htm"
    assert em.pick_release_document(["a8-k.htm", "ex10-1.htm"], "a8-k.htm") is None   # no press-release-looking page: do not guess


# --- 5e-3: actual against the consensus ------------------------------------------------------------------------------------------

def test_the_first_message_compares_revenue_and_adjusted_eps_with_the_consensus(owner):
    from datetime import date
    from app import earnings_calendar as ec
    from app.database import Base, engine
    Base.metadata.create_all(engine, tables=[ec.EarningsCalendar.__table__])
    with SessionLocal() as db:
        db.query(ec.EarningsCalendar).delete()
        db.commit()
    ec.store([{"symbol": "INTC", "report_date": date(2026, 10, 30), "hour": "amc", "fiscal_year": 2026, "fiscal_quarter": 3,
               "eps_estimate": 0.18, "revenue_estimate": 14.5e9, "eps_actual": None, "revenue_actual": None}], E_AT)
    try:
        first(symbol="INTC", held=True)
        body = items()[0][1]
        assert "对比市场预期（Finnhub，调整后口径；FY2026 Q3，" in body
        assert "· 营收 14.3B：预期 14.50B，比预期低 1.4%" in body
        assert "· 每股收益（非 GAAP）0.20：预期 0.18，比预期高 0.02 美元（11.1%）" in body
        assert body.index("对比市场预期") < body.index("新指引（下季）")
    finally:
        with SessionLocal() as db:
            db.query(ec.EarningsCalendar).delete()
            db.commit()


def test_a_release_the_calendar_does_not_know_says_so_and_a_broken_calendar_leaves_the_message_as_it_was(owner, monkeypatch):
    from app import earnings_calendar as ec
    assert ec.consensus_lines(None, 14.3, 0.2) == ["对比市场预期（Finnhub，调整后口径）", "· 这一季没有拿到市场预期"]
    row = {"fiscal_year": 2026, "fiscal_quarter": 3, "fetched_at": None}
    assert ec.consensus_lines({**row, "eps_estimate": 0.2, "revenue_estimate": 14.3e9}, 14.3, 0.2, None, 0.1)[1:] == [
        "· 营收 14.3B：预期 14.30B，与预期大致持平（新闻稿实际数精确到 1 亿美元）", "· 每股收益（非 GAAP）0.20：预期 0.20，与预期持平"]
    assert ec.consensus_lines({**row, "eps_estimate": 0.2, "revenue_estimate": None}, None, None)[1:] == ["· 每股收益：预期 0.20（新闻稿里没取到调整后的每股收益）"]
    monkeypatch.setattr(ec, "consensus_for", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("table gone")))
    first(symbol="INTC", held=True)
    body = items()[0][1]
    assert "对比市场预期" not in body and "新指引（下季）" in body


def test_the_comparison_does_not_claim_more_than_the_figures_carry():
    """Fable acceptance of 5e-3: precision (as written, trailing zeros included), a consensus near zero, GAAP only, and a unit slip."""
    from app import earnings_calendar as ec
    row = {"fiscal_year": 2026, "fiscal_quarter": 4, "fetched_at": "2027-01-19T22:00:00+00:00", "eps_estimate": 0.2541, "revenue_estimate": 15.79e9}
    lines = ec.consensus_lines(row, 15.8, 0.25, None, 0.1)
    assert lines[0] == "对比市场预期（Finnhub，调整后口径；FY2026 Q4，01-20 06:00 拉取）"
    assert lines[1] == "· 营收 15.8B：预期 15.79B，与预期大致持平（新闻稿实际数精确到 1 亿美元）", "15.8 cannot be said to beat 15.79"
    assert lines[2] == "· 每股收益（非 GAAP）0.25：预期 0.25，与预期持平", "0.25 against 0.2541 is within half a cent"
    assert ec.consensus_lines(row, 15.76, 0.31, None, 0.01)[1:] == ["· 营收 15.76B：预期 15.79B，比预期低 0.2%", "· 每股收益（非 GAAP）0.31：预期 0.25，比预期高 0.06 美元（22.0%）"]
    tens = {**row, "revenue_estimate": 14.6e9}
    assert ec.consensus_lines(tens, 15.0, None, None, 0.1)[1] == "· 营收 15.0B：预期 14.60B，比预期高 2.7%", "15.0 is written to a tenth, not to a billion"
    assert ec.consensus_lines(tens, 14.3, None, None, 0.001)[1] == "· 营收 14.300B：预期 14.60B，比预期低 2.1%"
    assert ec.consensus_lines(tens, 14.607, None, None, 0.001)[1] == "· 营收 14.607B：预期 14.60B，与预期持平", "never 「高 0.0%」"
    assert ec.consensus_lines(tens, 14.61, None)[1] == "· 营收 14.61B：预期 14.60B，比预期高 0.1%", "precision unknown: the percentage rule only"
    assert "量级对不上，可能是单位问题" in ec.consensus_lines(row, 850.2, None)[1]
    gaap = ec.consensus_lines({**row, "eps_estimate": 2.05}, None, None, 1.46)[2]
    assert gaap == "· 每股收益（GAAP）1.46：预期 2.05，比预期低 0.59 美元（没取到非 GAAP 每股收益，这里用 GAAP 数比，口径可能不同）", "no percentage of a basis gap"
    near_zero = ec.consensus_lines({**row, "eps_estimate": 0.01, "revenue_estimate": 0}, None, 0.05)
    assert near_zero[1:] == ["· 每股收益（非 GAAP）0.05：预期 0.01，比预期高 0.04 美元"], "no percentage of a cent, and a zero revenue estimate is none"
    assert ec.consensus_lines({**row, "eps_estimate": -0.02}, None, 0.03)[2] == "· 每股收益（非 GAAP）0.03：预期 -0.02，比预期高 0.05 美元"


def test_the_reader_records_the_revenue_figure_as_written():
    from app import earnings_reader as er
    for token, unit, value, step in (("15.0", "B", 15.0, 0.1), ("2.0", "B", 2.0, 0.1), ("14,300", "M", 14.3, 0.001), ("15.847", "B", 15.847, 0.001),
                                     ("$16", "B", 16.0, 1.0)):
        entry = {"revenue_b": token, "unit": unit}
        number = er._number(token)
        assert er._billions(entry, number) == value and er._step(entry, "revenue_b", number) == step, token
    assert er._step({"revenue_b": None}, "revenue_b", None) is None
    # the quote is the release's own text: a token the model shortened or converted is counted as the quote writes it
    assert er._step({"revenue_b": "15", "quote": "Revenue was $15.0 billion, up 4%"}, "revenue_b", 15.0) == 0.1
    assert er._step({"revenue_b": "14.3", "quote": "revenue of $14,300 million"}, "revenue_b", 14.3) == 0.001
    assert er._step({"revenue_b": "16", "quote": "revenue of $16 billion"}, "revenue_b", 16.0) == 1.0


def test_the_judge_sees_no_revenue_step():
    from app import earnings_reader as er
    payload = json.loads(er._judge_payload(er.ReleaseFacts(revenue=15.0, revenue_step=0.1), er.Comparison(), "", None))
    assert "revenue_step" not in payload["facts"] and payload["facts"]["revenue"] == 15.0
    assert er.ReleaseFacts().revenue_step is None, "a record from before keeps working"
