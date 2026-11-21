"""Pre-hardcode audit, tier 1 (2026-11-21): six places where a written-down rule screened content before the
model saw it. Each behaviour change sits behind a FINBOT_PH1_* switch (default on); every item is tested on
and off, and "off" is the old behaviour word for word.
"""
import asyncio
import json
import uuid

import pytest

from app import agent_profile as profile
from app import agent_profile_extract as extract
from app import jev_memory_gate as gate
from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage, AgentProfileItem
from app.agent_chat_store import owner_hash
from app.agent_workflow import consent
from app.agent_workflow.authorization import authorized, vetoed
from app.agent_workflow.direct import Turn
from app.agent_workflow.evidence import gate_row
from app.agent_workflow.models import AgentConsent
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)


def _switch(monkeypatch, name, on):
    monkeypatch.setenv(name, "on" if on else "off")


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConsent.__table__, AgentProfileItem.__table__, AgentBot.__table__,
                                             AgentConversation.__table__, AgentMessage.__table__])
    with SessionLocal() as db:
        db.query(AgentProfileItem).delete()
        db.commit()
    from app.agent_workflow import direct, tools
    import app.agent_chat_identity as identity
    for module in (consent, direct, tools, identity):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return OWNER


def _context(conversation, **kwargs):
    return AgentRuntimeContext("custom", "test", "dummy", identity_credential=OWNER, owner_hash=OWNER_HASH,
                               conversation_id=conversation, **kwargs)


def _route(*actions, category="D"):
    return lambda _payload: {"category": category, "days_back": None, "requested_actions": list(actions)}


async def _quiet(_event):
    pass


def _turn(question, context):
    from app.agent_workflow import direct
    return asyncio.run(direct.run_direct_turn(question, context, emit=_quiet))


def _is_extract(messages):
    return bool(messages) and messages[0].get("role") == "system" and messages[0].get("content") == extract.EXTRACT_PROMPT


def _extract(monkeypatch, message, verdict, items=()):
    from app import agent_chat_provider

    async def fake(_provider, _model, _key, _messages, _tools, _base):
        return {}, {"content": json.dumps({"items": list(items)}, ensure_ascii=False)}
    monkeypatch.setattr(agent_chat_provider, "decision_request", fake)
    judged = []

    def judge(msg, text, evidence, **_kw):
        judged.append(text)
        return verdict
    monkeypatch.setattr(gate, "judge", judge)
    added = asyncio.run(extract.extract_from_turn(OWNER_HASH, message, conversation_id="c", turn_id=str(uuid.uuid4()),
                                                  provider="custom", model="m", api_key="dummy-key", base_url=None))
    return added, judged


# --- 1. P-1: the memory fallback ----------------------------------------------------------------

QUESTION = "苹果和微软分别用什么口径算营收"
STANDING = "以后都用亿元显示"


def test_p1_the_wordlist_still_hands_the_remember_tool_over_on_a_compound_hit():
    """分别用 / 区别用 hit 别用: the table is the old one. What changed is what a hit alone can cause (see below)."""
    for text in (QUESTION, "区别用什么指标衡量"):
        assert authorized("remember", text) is True


def test_p1_background_fallback_needs_jev_and_is_never_explicit(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    added, judged = _extract(monkeypatch, STANDING, gate.MemoryVerdict("ok", 0.95))
    assert added == 1 and judged == [STANDING]
    [item] = profile.list_items(OWNER_HASH)
    assert item["origin"] == "inferred" and item["quote"] == STANDING


@pytest.mark.parametrize("verdict", [gate.MemoryVerdict("ok", 0.4), gate.MemoryVerdict("skipped"),
                                     gate.MemoryVerdict("timeout"), gate.MemoryVerdict("http_error")])
def test_p1_background_fallback_without_a_yes_from_jev_writes_nothing(owner, monkeypatch, verdict):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    added, judged = _extract(monkeypatch, STANDING, verdict)
    assert added == 0 and judged == [STANDING] and profile.list_items(OWNER_HASH) == []


def test_p1_the_question_is_not_stored_when_jev_does_not_allow_it(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    added, judged = _extract(monkeypatch, QUESTION, gate.MemoryVerdict("ok", 0.2))
    assert added == 0 and judged == [QUESTION] and profile.list_items(OWNER_HASH) == []


def test_p1_off_the_old_fallback_writes_the_sentence_as_explicit(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    added, judged = _extract(monkeypatch, QUESTION, gate.MemoryVerdict("timeout"))
    assert added == 1 and judged == []
    [item] = profile.list_items(OWNER_HASH)
    assert item["origin"] == "explicit" and item["quote"] == QUESTION


def _empty_extractor_turn(words, conversation, *actions, answer="好的。"):
    def decider(messages, _schemas):
        if _is_extract(messages):
            return {"content": json.dumps({"items": []})}
        return {"content": answer}
    return _turn(words, _context(conversation, intent_recognizer=_route(*actions), decider=decider))


def test_p1_in_turn_the_classifier_says_remember_and_the_model_did_not_a_card_rides_beside_the_answer(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    result = _empty_extractor_turn(STANDING, "conv-ph1-on", "remember", answer="好的，之后都用亿元显示。")
    card = result["pending_request"]
    assert card and card["display"]["title"] == "记住这条偏好"
    target = card["display"]["targets"][0]
    assert target["title"] == STANDING and target["quote"] == STANDING
    assert "好的，之后都用亿元显示。" in result["answer"] and "请核对确认卡" not in result["answer"]
    assert result["status"] == "succeeded"
    assert result["audit"].get("memory_fallback_card") is True and not result["audit"].get("memory_fallback")
    assert profile.list_items(OWNER_HASH) == []  # nothing is written before the press


@pytest.mark.parametrize("question", [QUESTION, "区别用什么指标衡量", "以后美联储降息对苹果有什么影响"])
def test_p1_in_turn_a_wordlist_hit_alone_gives_no_card_no_row_and_leaves_background_reading_on(owner, monkeypatch, question):
    from app.agent_workflow import direct
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    answered = "这是对问题的正常回答。"
    result = _empty_extractor_turn(question, "conv-ph1-word", answer=answered)
    audit = result["audit"]
    assert answered in result["answer"] and not result.get("pending_request") and profile.list_items(OWNER_HASH) == []
    assert audit.get("profile_ask") is True and not audit.get("remember_handled")
    assert audit.get("memory_fallback_skipped") == "classifier_not_remember"
    assert extract.remember_handled(audit) is False       # the background reading is scheduled as usual
    # the word still hands the tool over, as on 2026-10-28
    context = _context("conv-ph1-grant", intent_recognizer=_route(), decider=lambda *_: {"content": "好"})
    turn = direct.Turn(question, context, _quiet, [{"role": "user", "content": question}], {})
    asyncio.run(turn.classify())
    assert "remember" in turn.granted_actions


def test_p1_background_reading_stays_out_only_when_a_model_took_the_ask(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    assert extract.remember_handled({"profile_ask": True, "remember_handled": True}) is True
    assert extract.remember_handled({"profile_ask": True}) is False
    assert extract.remember_handled({}) is False and extract.remember_handled(None) is False
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    assert extract.remember_handled({"profile_ask": True}) is True   # the old reading of the word hit


def test_p1_a_card_the_extractor_found_rides_beside_the_answer_too_and_counts_as_handled(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    item = {"kind": "about_me", "topic": None, "text": "看好苹果的服务业务", "quote": "我看好苹果的服务业务"}

    def decider(messages, _schemas):
        if _is_extract(messages):
            return {"content": json.dumps({"items": [item]}, ensure_ascii=False)}
        return {"content": "好的，我记住了。"}
    result = _turn("记住我看好苹果的服务业务", _context("conv-ph1-handled", intent_recognizer=_route(), decider=decider))
    card = result["pending_request"]
    assert result["status"] == "succeeded" and "好的，我记住了。" in result["answer"]
    assert "尚未保存" in result["answer"]                       # the server says what the model's 记住了 is not yet
    assert card["side"] is True and card["display"]["side"] is True
    assert result["audit"].get("remember_handled") is True and extract.remember_handled(result["audit"]) is True
    assert profile.list_items(OWNER_HASH) == []


def test_p1_with_the_switch_off_a_found_card_still_ends_the_turn(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    item = {"kind": "about_me", "topic": None, "text": "看好苹果的服务业务", "quote": "我看好苹果的服务业务"}

    def decider(messages, _schemas):
        if _is_extract(messages):
            return {"content": json.dumps({"items": [item]}, ensure_ascii=False)}
        return {"content": "好的，我记住了。"}
    result = _turn("记住我看好苹果的服务业务", _context("conv-ph1-found-off", intent_recognizer=_route(), decider=decider))
    assert result["status"] == "waiting_for_input" and "请核对确认卡" in result["answer"]
    assert "side" not in result["pending_request"] and "side" not in result["pending_request"]["display"]


def test_p1_a_side_card_turn_is_an_answered_turn_for_the_claim_check(monkeypatch):
    from app.agent_workflow import claim_shadow
    monkeypatch.setattr(claim_shadow, "enabled", lambda: False)
    assert claim_shadow.maybe_schedule({"pending_request": {"side": True}}, object(), {}) == "shadow_off"
    monkeypatch.setattr(claim_shadow, "enabled", lambda: True)
    ctx = type("C", (), {"unattended": False})()
    assert claim_shadow.maybe_schedule({"pending_request": {"id": "x"}}, ctx, {}) == "pending_request"
    assert claim_shadow.maybe_schedule({"pending_request": {"side": True}, "status": "succeeded", "citations": []}, ctx, {}) == "no_numbered_sources"


def test_p1_in_turn_off_is_the_old_direct_write(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    result = _empty_extractor_turn(STANDING, "conv-ph1-off")
    assert not result.get("pending_request") and result["audit"].get("memory_fallback") is True
    [item] = profile.list_items(OWNER_HASH)
    assert item["origin"] == "explicit" and item["quote"] == STANDING


# --- 2. M-1: first turn ordinal -------------------------------------------------------------------

def _first_turn(question, resolver):
    context = AgentRuntimeContext("p", "m", "k", conversation_id="c", resolver=resolver, classifier=lambda _: {"category": "D"},
                                  decider=lambda *_: {"content": "好"})
    turn = Turn(question, context, _quiet, [{"role": "user", "content": question}], {})
    asyncio.run(turn.reference())
    return turn


@pytest.mark.parametrize("question", ["苹果最后一份财报讲了什么", "Show me Tesla's last filing", "第二季度财报怎么样"])
def test_m1_a_first_turn_ordinal_word_reaches_the_resolver(monkeypatch, question):
    _switch(monkeypatch, "FINBOT_PH1_FIRST_TURN_ORDINAL", True)
    calls = []
    turn = _first_turn(question, lambda payload: calls.append(payload) or {"relationship": "new"})
    assert len(calls) == 1 and turn.pending is None


@pytest.mark.parametrize("question", ["苹果最后一份财报讲了什么", "Show me Tesla's last filing"])
def test_m1_off_the_old_card_returns_without_calling_the_resolver(monkeypatch, question):
    _switch(monkeypatch, "FINBOT_PH1_FIRST_TURN_ORDINAL", False)
    calls = []
    turn = _first_turn(question, lambda payload: calls.append(payload) or {"relationship": "new"})
    assert calls == [] and turn.pending and "当前没有可指代的清单" in json.dumps(turn.pending, ensure_ascii=False)


# --- 3. M-3: a web page that does not spell the company ------------------------------------------

def _web_row(**kw):
    return {"source_type": "web", "url": "https://example.com/a", "title": "Quarterly results", **kw}


@pytest.mark.parametrize("body", ["The iPhone maker reported revenue of $90 billion for the quarter.",
                                  "苹果公司公布营收900亿美元"])
def test_m3_a_page_that_never_names_the_company_is_kept_with_a_note(monkeypatch, body):
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    row = _web_row(excerpt=body)
    ok, reason = gate_row("AAPL revenue", row, symbol="AAPL", company="Apple Inc.", metrics=[], soft=True)
    assert ok and reason == "soft:requested_entity_missing"
    assert gate_row("AAPL revenue", row, symbol="AAPL", company="Apple Inc.", metrics=[], soft=False) == (False, "requested_entity_missing")
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", False)
    assert gate_row("AAPL revenue", row, symbol="AAPL", company="Apple Inc.", metrics=[], soft=True) == (False, "requested_entity_missing")


def test_m3_the_hard_stops_stay_hard(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    named = "Apple reported revenue of $90 billion."
    assert gate_row("q", _web_row(excerpt=named, symbol="MSFT"), symbol="AAPL", company="Apple Inc.", metrics=[], soft=True) == (False, "requested_entity_missing")
    assert gate_row("q", {"source_type": "configured_news", "title": "Apple", "excerpt": named}, symbol="AAPL", company="Apple Inc.", metrics=[], soft=True) == (False, "missing_citation_url")
    assert gate_row("q", _web_row(excerpt=named, fetch_error="x"), symbol="AAPL", company="Apple Inc.", metrics=[], soft=True) == (False, "invalid_source_body")
    assert gate_row("q", _web_row(excerpt=""), symbol="AAPL", company="Apple Inc.", metrics=[], soft=True) == (False, "zero_evidence")
    assert gate_row("q", _web_row(excerpt=named), symbol="AAPL", company="Apple Inc.", metrics=[], soft=True)[0] is True


def test_m3_a_stale_page_that_does_not_name_the_company_is_refused_by_the_time_window(monkeypatch):
    from datetime import UTC, datetime
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    now = datetime(2026, 11, 21, tzinfo=UTC)
    unnamed = "The iPhone maker reported revenue of $90 billion."
    kw = dict(symbol="AAPL", company="Apple Inc.", metrics=[], soft=True, days_back=7, now=now)
    assert gate_row("q", _web_row(excerpt=unnamed, published_at="2025-01-02T00:00:00+00:00"), **kw) == (False, "requested_time_window_missing")
    assert gate_row("q", {**_web_row(excerpt=unnamed, published_at="2025-01-02T00:00:00+00:00"), "source_type": "configured_news"}, **kw) == (False, "requested_time_window_missing")
    assert gate_row("q", _web_row(excerpt="Apple reported revenue.", published_at="2025-01-02T00:00:00+00:00"), **kw) == (False, "requested_time_window_missing")
    assert gate_row("q", _web_row(excerpt=unnamed, published_at="2026-11-20T00:00:00+00:00"), **kw) == (True, "soft:requested_entity_missing")


def test_m3_the_entity_note_carries_the_other_soft_notes_and_does_not_add_a_metric_miss(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    unnamed = "The iPhone maker reported revenue of $90 billion for the quarter."
    ok, reason = gate_row("AAPL revenue Q3 2024", _web_row(excerpt=unnamed), symbol="AAPL", company="Apple Inc.", metrics=["revenue"], soft=True)
    assert ok and reason.startswith("soft:requested_entity_missing")
    assert "requested_metric_missing" not in reason          # the unnamed passage counts for the metric
    assert "requested_period_missing" in reason              # the quarter is not in the page: noted, not dropped
    named = _web_row(excerpt="Apple reported revenue of $90 billion for the quarter.")
    assert gate_row("AAPL revenue Q3 2024", named, symbol="AAPL", company="Apple Inc.", metrics=["revenue"], soft=True) == (True, "soft:requested_period_missing")


def test_m3_a_soft_entity_row_does_not_borrow_the_scopes_symbol_in_its_citation(monkeypatch):
    from tests.test_agent_scope_phase1 import _context, _step, _run, SECTOR_PAGE
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    context, _, _, _ = _context(classified={"symbol": "AAPL", "company": "Apple"}, steps=[_step("web_research", query="AAPL 新闻"), {"content": "没有可核验资料。"}],
                                rows={"web_research": [SECTOR_PAGE]})
    [citation] = _run("Apple（AAPL）最近有什么新闻", context)["citations"]
    assert "requested_entity_missing" in citation["fields"]["gate_note"] and citation["symbol"] is None


def test_m3_the_note_rides_on_the_row_the_model_reads(monkeypatch):
    """direct.py puts the reason after ``soft:`` on the accepted row as ``gate_note``, which the system prompt tells the model to weigh."""
    from app.agent_system_prompt import INSTRUCTION
    assert "gate_note" in "".join(INSTRUCTION)
    ok, reason = gate_row("AAPL revenue", _web_row(excerpt="The iPhone maker reported revenue."), symbol="AAPL",
                          company="Apple Inc.", metrics=[], soft=True)
    assert ok and reason.startswith("soft:") and reason[5:] == "requested_entity_missing"


# --- 4. M-7: 别忘了 is not a refusal ---------------------------------------------------------------

def test_m7_dont_forget_is_not_a_negation():
    sentence = "别忘了把这篇保存到知识库"
    assert vetoed("import", sentence) is False
    assert authorized("import", sentence) is True
    assert vetoed("import", "不要忘记把这篇保存到知识库") is False
    assert vetoed("import", "别保存到知识库") is True
    assert authorized("import", "别保存到知识库") is False


# --- 5. A1: the phone pattern --------------------------------------------------------------------

@pytest.mark.parametrize("text", ["财报日期 2024-03-31", "revenue 12 13 14 15 16", "2024-01-01 至 2024-03-31",
                                  "营收 1,234,567,890 美元", "FY2024 Q3", "涨幅 +1.2345678%", "同比 +12345678 元",
                                  "2023-01-15 至 2024-06-30", "AAPL 2024-11-21", "600519 2024-11-21", "123.45-678.90",
                                  "2024.11.21 2025.01.02", "ISIN US0378331005", "CUSIP 037833100"])
def test_a1_dates_and_figures_are_not_phone_numbers(monkeypatch, text):
    from app.knowledge import extraction
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    assert not extraction._secret().search(text)


@pytest.mark.parametrize("text", ["13812345678", "电话 13800000000", "+86 138 1234 5678", "+61 412 345 678", "(03) 9905 1234",
                                  "138-1234-5678", "555 123 4567", "555.123.4567", "(555) 123-4567", "1-800-555-1234",
                                  "0412345678", "+44 20 7946 0958", "+852 1234 5678", "+8613812345678",
                                  "sk-abcdefghijklmnopqrstuvwx", "me@example.com", "password: hunter2"])
def test_a1_real_secrets_still_match(monkeypatch, text):
    from app.knowledge import extraction
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    assert extraction._secret().search(text)


def test_a1_off_is_the_old_pattern(monkeypatch):
    from app.knowledge import extraction
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", False)
    assert extraction._secret() is extraction._SECRET and extraction._secret().search("财报日期 2024-03-31")


def _conversation(text):
    owner = "a" * 64
    return [{"conversation_id": "conv-a1", "owner_hash": owner, "opted_in": True, "turns": [
        {"turn_id": "t1", "created_at": "2026-01-01T00:00:00+00:00", "status": "complete", "messages": [
            {"role": "user", "content": text, "status": "complete"},
            {"role": "assistant", "content": "好的。", "status": "complete"}]}]}]


def _run_extract(monkeypatch, text, items):
    from sqlalchemy.orm import Session
    from app.knowledge.extraction import extract_once
    from app.knowledge.models import KnowledgeCandidate
    seen = []

    def provider(payload):
        seen.append(payload)
        return {"candidates": items(payload)}
    from scripts.migrate_knowledge import migrate
    migrate(engine)
    with Session(engine) as s, s.begin():
        s.query(KnowledgeCandidate).delete()
    counts = extract_once(provider, None, _conversation(text), provider, session_factory=lambda: Session(engine))
    with Session(engine) as s:
        stored = s.query(KnowledgeCandidate).count()
    return counts, seen, stored


def _candidate(quote, answer="好的。"):
    return {"question": "怎么看？", "answer": answer, "category": "x", "candidate_kind": "other", "evidence_quote": quote}


def test_a1_a_turn_with_a_phone_number_is_read_with_the_number_masked(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    text = "我的电话 13812345678，请分析苹果财报日期 2024-03-31"
    counts, seen, stored = _run_extract(monkeypatch, text, lambda p: [_candidate("请分析苹果财报日期 2024-03-31")])
    sent = json.dumps(seen, ensure_ascii=False)
    assert counts["processed"] == 1 and len(seen) == 1 and stored == 1
    assert "13812345678" not in sent and "[REDACTED]" in sent and "2024-03-31" in sent


def test_a1_a_candidate_that_touches_the_masked_span_is_still_refused(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    text = "我的电话 13812345678，请分析苹果财报"
    counts, seen, stored = _run_extract(monkeypatch, text, lambda p: [_candidate("我的电话 [REDACTED]，请分析苹果财报")])
    assert len(seen) == 1 and stored == 0 and counts["skipped"] == 1


def test_a1_a_password_label_still_skips_the_whole_turn(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    counts, seen, stored = _run_extract(monkeypatch, "password: hunter2 请分析苹果财报", lambda p: [_candidate("请分析苹果财报")])
    assert seen == [] and stored == 0 and counts["skipped"] == 1


def test_a1_off_a_date_still_skips_the_whole_turn(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", False)
    counts, seen, stored = _run_extract(monkeypatch, "请分析苹果财报日期 2024-03-31", lambda p: [_candidate("请分析苹果财报日期 2024-03-31")])
    assert seen == [] and stored == 0 and counts["skipped"] == 1


# --- 6. P-4: the profile block says what it left out --------------------------------------------

def _fill(count, origin="inferred", prefix="关注公司"):
    for n in range(count):
        text = f"{prefix}{n}的长篇说明" + "很长" * 25
        profile.add_item(OWNER_HASH, kind="about_me", text=text, quote=text, message=text, origin=origin)


def test_p4_a_cut_block_says_how_many_items_it_left_out(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_PROFILE_OMITTED_NOTE", True)
    _fill(30)
    block, ids = profile.render_block(OWNER_HASH)
    left_out = 30 - len(ids)
    assert left_out > 0 and block.rstrip().endswith(f"（另有 {left_out} 条记忆因长度限制未显示，可在记忆页查看。）")
    assert len(block.encode()) <= profile.MAX_BLOCK_BYTES
    assert profile.render_block(OWNER_HASH) == (block, ids)
    _switch(monkeypatch, "FINBOT_PH1_PROFILE_OMITTED_NOTE", False)
    old, old_ids = profile.render_block(OWNER_HASH)
    assert "未显示" not in old and len(old_ids) >= len(ids)


def test_p4_nothing_left_out_adds_nothing(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_PROFILE_OMITTED_NOTE", True)
    _fill(3)
    on = profile.render_block(OWNER_HASH)
    _switch(monkeypatch, "FINBOT_PH1_PROFILE_OMITTED_NOTE", False)
    assert profile.render_block(OWNER_HASH) == on and "未显示" not in on[0]


# --- M-3 prompt: the note is explained where gate_note is -------------------------------------------

def test_m3_the_prompt_explains_the_entity_note_only_when_the_switch_is_on(monkeypatch):
    from app.agent_system_prompt import INSTRUCTION
    from app.agent_workflow import direct
    text = "\n".join(INSTRUCTION)
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", True)
    on = direct.evidence_instruction(text)
    _switch(monkeypatch, "FINBOT_PH1_WEB_ENTITY_SOFT", False)
    off = direct.evidence_instruction(text)
    assert "requested_entity_missing" in on and "不相关别引用" in on
    assert "requested_entity_missing" not in off
    assert on.replace(direct.GATE_NOTE_ENTITY_SENTENCE, "", 1) == off
    assert len(direct.GATE_NOTE_ENTITY_SENTENCE) <= 70   # the guest instruction has little room (test_b17)
