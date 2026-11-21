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


def test_p1_the_wordlist_no_longer_mistakes_a_compound_for_an_instruction(monkeypatch):
    for text in (QUESTION, "用身份证识别用户", "区别用在哪里", "特别用心看财报"):
        _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
        assert authorized("remember", text) is False
    for text in ("以后别用万元", "别用万元，用亿元", "今后别再用万元"):
        assert authorized("remember", text) is True
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    assert authorized("remember", QUESTION) is True  # the 2026-11-16 accident, as it was


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


def test_p1_the_question_is_not_stored_even_when_jev_would_say_yes(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    added, judged = _extract(monkeypatch, QUESTION, gate.MemoryVerdict("ok", 0.99))
    assert added == 0 and judged == [] and profile.list_items(OWNER_HASH) == []


def test_p1_off_the_old_fallback_writes_the_sentence_as_explicit(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    added, judged = _extract(monkeypatch, QUESTION, gate.MemoryVerdict("timeout"))
    assert added == 1 and judged == []
    [item] = profile.list_items(OWNER_HASH)
    assert item["origin"] == "explicit" and item["quote"] == QUESTION


def _empty_extractor_turn(words, conversation):
    def decider(messages, _schemas):
        if _is_extract(messages):
            return {"content": json.dumps({"items": []})}
        return {"content": "好的。"}
    return _turn(words, _context(conversation, intent_recognizer=_route(), decider=decider))


def test_p1_in_turn_an_empty_extractor_leaves_a_card_not_a_row(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    result = _empty_extractor_turn(STANDING, "conv-ph1-on")
    card = result["pending_request"]
    assert card and card["display"]["title"] == "记住这条偏好"
    target = card["display"]["targets"][0]
    assert target["title"] == STANDING and target["quote"] == STANDING
    assert result["audit"].get("memory_fallback_card") is True and not result["audit"].get("memory_fallback")
    assert profile.list_items(OWNER_HASH) == []  # nothing is written before the press


def test_p1_in_turn_a_question_with_the_old_false_hit_makes_neither_card_nor_row(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    result = _empty_extractor_turn(QUESTION, "conv-ph1-q")
    assert not result.get("pending_request") and profile.list_items(OWNER_HASH) == []
    assert not result["audit"].get("profile_ask")


def test_p1_in_turn_off_is_the_old_direct_write(owner, monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", False)
    result = _empty_extractor_turn(STANDING, "conv-ph1-off")
    assert not result.get("pending_request") and result["audit"].get("memory_fallback") is True
    [item] = profile.list_items(OWNER_HASH)
    assert item["origin"] == "explicit" and item["quote"] == STANDING


def test_p1_remember_quote_keeps_picking_the_asking_sentence_of_a_long_message(monkeypatch):
    _switch(monkeypatch, "FINBOT_PH1_MEMORY_FALLBACK", True)
    long_words = "苹果和微软分别用什么口径算营收。" + "背景说明" * 60 + "。以后都用亿元显示。"
    context = _context("conv-quote", intent_recognizer=_route(), decider=lambda *_: {"content": "好的。"})
    turn = Turn(long_words, context, _quiet, [{"role": "user", "content": long_words}], {})
    assert turn.remember_quote("模型改写的话") == "以后都用亿元显示。"


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
                                  "营收 1,234,567,890 美元", "FY2024 Q3", "市值 15000000000 元"])
def test_a1_dates_and_figures_are_not_phone_numbers(monkeypatch, text):
    from app.knowledge import extraction
    _switch(monkeypatch, "FINBOT_PH1_SECRET_MASK", True)
    assert not extraction._secret().search(text)


@pytest.mark.parametrize("text", ["13812345678", "+86 138 1234 5678", "+61 412 345 678", "(03) 9905 1234",
                                  "138-1234-5678", "sk-abcdefghijklmnopqrstuvwx", "me@example.com", "password: hunter2"])
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
