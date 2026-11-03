"""Task 15: the context follows the model window, and old turns are folded into one structured rolling
summary whose conclusions and numbers each carry a {turn_id, ordinal} source marker.

The compression model is always a fake; nothing here reaches a real endpoint.  The conversation store is
replaced by an in-memory one that runs the real layer arithmetic (``agent_context.layer_rows``), so the
rolling cycle is exercised end to end without a database.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import pytest

from app import agent_context as layers
from app import agent_context_summary as summary

KEY = "sk-test-secret-key-0123456789"
SMALL = dict(l1_bytes=1800, l2_bytes=1500, l3_bytes=6000)     # tiny layers so a few turns overflow


def tid(n: int) -> str:
    return str(uuid.UUID(int=n))


def make_rows(first: int, last: int, *, topic="Intel", cited=True) -> list[dict]:
    """Complete turns ``first..last``: a question, a long answer citing source [1], numbers in the answer."""
    rows = []
    for n in range(first, last + 1):
        answer = f"{topic} 第{n}轮分析：毛利率 {30 + n}%，详见 [1]。" + "细节说明。" * 30
        citations = [{"ordinal": 1, "title": f"{topic} 10-Q {n}", "source_type": "filing", "quote": "原文片段"}] if cited else []
        rows.append({"role": "user", "content": f"第{n}轮：{topic} 的毛利率怎么样？" + "背景。" * 20, "tool_calls": None,
                     "tool_call_id": None, "status": "complete", "turn_id": tid(n), "sequence": 2 * n - 1})
        rows.append({"role": "assistant", "content": answer, "tool_calls": {"citations": citations} if citations else None,
                     "tool_call_id": None, "status": "complete", "turn_id": tid(n), "sequence": 2 * n})
    return rows


class MemoryStore:
    """What ``agent_chat_store`` offers the summarizer, held in lists."""

    def __init__(self, rows, segments=None, sizes=None):
        self.rows, self.segments, self.sizes = rows, list(segments or []), sizes or SMALL
        self.appended = []

    async def conversation_context(self, conversation_id, credential, **kwargs):
        sizes = {**self.sizes, **{k: v for k, v in kwargs.items() if k.endswith("_bytes")}}
        return layers.layer_rows(self.rows, self.segments, **sizes)

    async def append_summary(self, conversation_id, from_sequence, upto_sequence, content):
        if self.segments and upto_sequence <= self.segments[-1]["upto_sequence"]:
            return False
        self.segments.append({"seq": len(self.segments) + 1, "from_sequence": from_sequence,
                              "upto_sequence": upto_sequence, "content": content})
        self.appended.append(content)
        return True

    def install(self, monkeypatch):
        import app.agent_chat_store as store
        monkeypatch.setattr(store, "conversation_context", self.conversation_context)
        monkeypatch.setattr(store, "append_summary", self.append_summary)


class FakeModel:
    """Answers the compression call with ``reply`` (a dict, a string, or a function of the payload)."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def __call__(self, provider, model, api_key, messages, schemas, base_url=None):
        payload = json.loads(messages[1]["content"])
        self.calls.append({"messages": messages, "payload": payload, "schemas": schemas})
        reply = self.reply(payload) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return {"usage": {}}, {"content": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)}

    def install(self, monkeypatch):
        import app.agent_chat_provider as provider
        monkeypatch.setattr(provider, "decision_request", self)


def run_compact(**kw):
    return asyncio.run(summary.compact_conversation("cid", "cred", provider="p", model="m", api_key=KEY,
                                                    base_url=None, **kw))


def stored(content: str) -> dict:
    value = json.loads(content)
    assert value["v"] == 2
    return value


def sourced_reply(payload, *, text="Intel 毛利率持续上升", number=None):
    """A faithful model: keeps what it was given and adds one sourced conclusion about the newest turn."""
    turn = payload["turns"][-1]
    out = {"goals": ["跟踪 Intel 毛利率"], "conclusions": [{"text": text, "turn_id": turn["turn_id"], "ordinal": 1}],
           "open": ["下一季指引待确认"], "preferences": [], "numbers": []}
    if number:
        out["numbers"].append({"text": number, "turn_id": turn["turn_id"], "ordinal": 1})
    return out


# --- budget follows the window -------------------------------------------------------------------

def test_budget_follows_window():
    small, large = layers.budget_for_window(128_000), layers.budget_for_window(1_000_000)
    assert small == 128_000 // 2 * layers.BYTES_PER_TOKEN
    assert large == 1_000_000 // 2 * layers.BYTES_PER_TOKEN
    assert large > small > 128 * 1024                      # the old 128 KB ceiling is gone
    for window in (128_000, 1_000_000):
        l1, l2, l3 = layers.layer_sizes(window)
        assert l1 + l2 + l3 == layers.budget_for_window(window) and l1 > l2 > l3 > 0


def test_catalog_entries_carry_a_window_defaulting_to_128k(tmp_path, monkeypatch):
    from app import agent_model_catalog as catalog
    path = tmp_path / "models.yaml"
    path.write_text("models:\n  - {name: big, provider: deepseek, model: m1, key_env: BIG_API_KEY, context_window: 1000000}\n"
                    "  - {name: plain, provider: deepseek, model: m2, key_env: PLAIN_API_KEY}\n"
                    "  - {name: bad, provider: deepseek, model: m3, key_env: BAD_API_KEY, context_window: 12}\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MODELS_CONFIG", str(path))
    entries, _default, problems = catalog._read_file()
    windows = {e["name"]: catalog.window_of(e) for e in entries}
    assert windows == {"big": 1_000_000, "plain": 128_000} and len(problems) == 1


# --- merge, sources, failure -----------------------------------------------------------------------

def test_merge_keeps_old_facts(monkeypatch):
    old = {"v": 2, "goals": ["看 Intel"], "conclusions": [{"text": "Intel 2025Q3 毛利率 38%", "turn_id": tid(1), "ordinal": 1}],
           "open": [], "preferences": ["只看 10-Q"], "numbers": [{"text": "毛利率 38%", "turn_id": tid(1), "ordinal": 1}],
           "turns_compacted": 3}
    store = MemoryStore(make_rows(1, 12), [{"seq": 1, "from_sequence": 1, "upto_sequence": 2,
                                            "content": json.dumps(old, ensure_ascii=False)}])
    store.install(monkeypatch)
    model = FakeModel(lambda payload: sourced_reply(payload))             # a model that forgot the old conclusion
    model.install(monkeypatch)
    result = run_compact(manual=True)
    assert result["compacted"] > 0
    assert model.calls[0]["payload"]["previous_summary"]["conclusions"][0]["text"] == "Intel 2025Q3 毛利率 38%"
    merged = stored(store.appended[-1])
    texts = [c["text"] for c in merged["conclusions"]]
    assert "Intel 2025Q3 毛利率 38%" in texts and "Intel 毛利率持续上升" in texts
    assert any(n["text"] == "毛利率 38%" for n in merged["numbers"])
    assert len(store.segments) == 2                                         # a new version, the old one is kept


@pytest.mark.parametrize("bad, reason", [
    ({"numbers": ["毛利率 38%"]}, "missing_source"),                                         # a bare string
    ({"numbers": [{"text": "毛利率 38%"}]}, "missing_source"),                                # no marker
    ({"numbers": [{"text": "毛利率 38%", "turn_id": tid(1)}]}, "missing_source"),             # no ordinal
    ({"numbers": [{"text": "毛利率 38%", "turn_id": tid(1), "ordinal": True}]}, "missing_source"),
    ({"numbers": [{"text": "毛利率 38%", "turn_id": tid(99), "ordinal": 1}]}, "unknown_source"),
    ({"numbers": [{"text": "毛利率 38%", "turn_id": tid(1), "ordinal": 7}]}, "unknown_source"),
    ({"conclusions": [{"text": "毛利率上升", "turn_id": tid(1)}]}, "missing_source"),
    ({"goals": ["目标是 9999 亿"]}, "ungrounded_figure"),                                     # a number outside any source
    ({"numbers": [{"text": "毛利率 77%", "turn_id": tid(1), "ordinal": 1}]}, "ungrounded_figure"),
])
def test_numbers_carry_source(bad, reason):
    source = "第1轮 Intel 毛利率 38% 见 [1]"
    base = {"goals": [], "conclusions": [], "open": [], "preferences": [], "numbers": []}
    with pytest.raises(summary.SummaryRejected) as caught:
        summary.validate_rolling(json.dumps({**base, **bad}, ensure_ascii=False), source=source,
                                 allowed={(tid(1), 1)}, old=None)
    assert str(caught.value) == reason
    good = {**base, "numbers": [{"text": "毛利率 38%", "turn_id": tid(1), "ordinal": 1}]}
    assert summary.validate_rolling(json.dumps(good, ensure_ascii=False), source=source,
                                    allowed={(tid(1), 1)}, old=None)["numbers"][0]["ordinal"] == 1


def test_a_summary_without_source_is_not_stored_even_if_the_model_insists(monkeypatch):
    store = MemoryStore(make_rows(1, 12))
    store.install(monkeypatch)
    FakeModel({"goals": [], "conclusions": [], "open": [], "preferences": [], "numbers": ["毛利率 38%"]}).install(monkeypatch)
    assert run_compact(manual=True)["compacted"] == 0
    assert store.appended == []


@pytest.mark.parametrize("failure", [RuntimeError("provider down"), "not json", {"goals": "x"}])
def test_model_failure_keeps_old_summary(monkeypatch, caplog, failure):
    old = {"v": 2, "goals": ["看 Intel"], "conclusions": [{"text": "旧结论", "turn_id": tid(1), "ordinal": 1}],
           "open": [], "preferences": [], "numbers": [], "turns_compacted": 2}
    segments = [{"seq": 1, "from_sequence": 1, "upto_sequence": 2, "content": json.dumps(old, ensure_ascii=False)}]
    store = MemoryStore(make_rows(1, 12), segments)
    store.install(monkeypatch)
    FakeModel(failure).install(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(summary._guarded("cid", "cred", provider="p", model="m", api_key=KEY, base_url=None, manual=True))
    assert store.segments == segments and store.appended == []
    assert KEY not in caplog.text
    note = layers.summary_message(asyncio.run(store.conversation_context("cid", "cred"))["segments"])
    assert "旧结论" in note["content"]


# --- triggers -----------------------------------------------------------------------------------------

def test_auto_trigger_at_80_percent(monkeypatch):
    sizes = dict(l1_bytes=3000, l2_bytes=2000, l3_bytes=8000)           # budget 13000
    low, high = MemoryStore(make_rows(1, 3), sizes=sizes), MemoryStore(make_rows(1, 14), sizes=sizes)
    for store, expected in ((low, False), (high, True)):
        context = asyncio.run(store.conversation_context("c", "c"))
        assert layers.should_compact(context) is expected, layers.history_usage(context)
    assert layers.history_usage(asyncio.run(low.conversation_context("c", "c")))["fraction"] < 0.8
    # exactly at the line
    context = asyncio.run(high.conversation_context("c", "c"))
    at = {**context, "budget": int(layers.history_usage(context)["bytes"] / 0.8)}
    assert layers.should_compact(at) is True
    under = {**context, "budget": int(layers.history_usage(context)["bytes"] / 0.79)}
    assert layers.should_compact(under) is False

    for store, calls_expected in ((low, 0), (high, 1)):
        store.install(monkeypatch)
        model = FakeModel(lambda payload: sourced_reply(payload))
        model.install(monkeypatch)
        asyncio.run(summary._guarded("cid", "cred", provider="p", model="m", api_key=KEY, base_url=None))
        assert len(model.calls) == calls_expected
    assert len(high.appended) >= 1
    after = asyncio.run(high.conversation_context("c", "c"))
    assert layers.history_usage(after)["fraction"] < 0.8                  # compressing brought it back under the line


def test_manual_compact_with_focus(monkeypatch):
    assert summary.parse_compact_command("/压缩") == (True, "")
    assert summary.parse_compact_command("/压缩 重点保留 Intel 的分析") == (True, "重点保留 Intel 的分析")
    assert summary.parse_compact_command("  /compact keep the Intel part ") == (True, "keep the Intel part")
    assert summary.parse_compact_command("/压缩了吗") == (False, "")
    assert summary.parse_compact_command("帮我 /压缩") == (False, "")
    store = MemoryStore(make_rows(1, 6), sizes=dict(l1_bytes=60000, l2_bytes=20000, l3_bytes=20000))   # far below 80 %
    store.install(monkeypatch)
    model = FakeModel(lambda payload: sourced_reply(payload))
    model.install(monkeypatch)
    result = run_compact(manual=True, focus="重点保留 Intel 的分析")
    assert result["compacted"] >= 1 and model.calls[0]["payload"]["focus"] == "重点保留 Intel 的分析"
    assert "untrusted" in model.calls[0]["messages"][0]["content"]
    content = stored(store.appended[-1])
    assert content["turns_compacted"] == result["compacted"] and content["focus"] == "重点保留 Intel 的分析"


def test_manual_compact_with_nothing_to_compact_says_so(monkeypatch):
    MemoryStore(make_rows(1, 1)).install(monkeypatch)
    model = FakeModel(lambda payload: sourced_reply(payload))
    model.install(monkeypatch)
    assert run_compact(manual=True)["compacted"] == 0 and model.calls == []


# --- the memory is memory, not evidence ----------------------------------------------------------------

def test_the_rendered_summary_carries_markers_and_is_not_evidence(monkeypatch):
    store = MemoryStore(make_rows(1, 12))
    store.install(monkeypatch)
    FakeModel(lambda payload: sourced_reply(payload, number="毛利率 41%")).install(monkeypatch)
    run_compact(manual=True)
    context = asyncio.run(store.conversation_context("c", "c"))
    note = layers.summary_message(context["segments"])["content"]
    assert note.startswith(layers.MEMORY_MARKER) and "not evidence" in note and "read_history_citation" in note
    assert "毛利率 41%" in note and "turn_id=" in note and "ordinal=1" in note
    assert summary.summary_sources(context["segments"]) >= {(tid(11), 1)}


def test_compacted_turns_leave_the_raw_layers(monkeypatch):
    store = MemoryStore(make_rows(1, 12))
    store.install(monkeypatch)
    FakeModel(lambda payload: sourced_reply(payload)).install(monkeypatch)
    before = asyncio.run(store.conversation_context("c", "c"))
    run_compact(manual=True)
    after = asyncio.run(store.conversation_context("c", "c"))
    upto = store.segments[-1]["upto_sequence"]
    assert all(t.last_sequence > upto for t in after["half_turns"])
    assert {r["turn_id"] for r in after["l1_rows"]}.isdisjoint({tid(n) for n in range(1, upto // 2 + 1)})
    assert layers.history_usage(after)["bytes"] < layers.history_usage(before)["bytes"]


def test_usage_report_uses_the_budget_it_is_given_and_names_the_compaction_line():
    report = layers.usage_report(system_bytes=1000, tools_bytes=2000, summary_bytes=0, summary_segments=0, half_bytes=0,
                                 half_turns=0, recent_bytes=50_000, recent_turns=3, hidden_turns=0, budget_bytes=100_000)
    assert report["budget_bytes"] == 100_000 and report["compact_at_percent"] == 80
    assert report["history_used_percent"] == 50 and report["will_compact"] is False
    hot = layers.usage_report(system_bytes=1000, tools_bytes=2000, summary_bytes=0, summary_segments=0, half_bytes=0,
                              half_turns=0, recent_bytes=85_000, recent_turns=3, hidden_turns=0, budget_bytes=100_000)
    assert hot["history_used_percent"] == 85 and hot["will_compact"] is True


# --- acceptance: early facts survive repeated rolling compressions --------------------------------------

def test_early_facts_survive_repeated_compression(monkeypatch):
    """30 turns, compressed whenever the line is crossed; a fact from turn 1 is still in the memory the model
    is shown after several merges, and the original text is one search away."""
    rows = make_rows(1, 4)
    store = MemoryStore(rows, sizes=dict(l1_bytes=3000, l2_bytes=2000, l3_bytes=8000))
    store.install(monkeypatch)

    def model(payload):                                   # a faithful rolling model
        previous = payload.get("previous_summary") or {}
        turn = payload["turns"][-1]
        out = {"goals": previous.get("goals", []) or ["跟踪 Intel"], "open": [], "preferences": [],
               "conclusions": list(previous.get("conclusions", [])), "numbers": []}
        out["conclusions"].append({"text": f"第{int(turn['turn_id'][-12:], 16)}轮毛利率结论", "turn_id": turn["turn_id"], "ordinal": 1})
        return out

    fake = FakeModel(model)
    fake.install(monkeypatch)
    first_fact = None
    for n in range(5, 31):
        store.rows += make_rows(n, n)
        asyncio.run(summary._guarded("cid", "cred", provider="p", model="m", api_key=KEY, base_url=None))
        if first_fact is None and store.appended:
            first_fact = stored(store.appended[0])["conclusions"][0]
    assert len(store.appended) >= 3 and first_fact
    note = layers.summary_message(asyncio.run(store.conversation_context("c", "c"))["segments"])["content"]
    assert first_fact["text"] in note and first_fact["turn_id"] in note
    assert stored(store.appended[-1])["turns_compacted"] >= 1


# --- recall reaches the original text of compacted turns in the same bot's line ---------------------------

DETAIL = "Orbit 项目的外包成本是每季 7.35 亿美元"
BOT_A, BOT_B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def line(disposable_database):
    from app.agent_chat_models import (AgentBot, AgentConversation, AgentConversationRecall, AgentConversationSummary,
                                       AgentConversationTitle, AgentMessage)
    from app.database import Base, SessionLocal, engine
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, AgentBot.__table__,
                                             AgentConversationTitle.__table__, AgentConversationSummary.__table__,
                                             AgentConversationRecall.__table__])
    with SessionLocal() as db:
        db.query(AgentConversationRecall).delete()
        db.query(AgentConversation).delete()
        db.commit()
    return SessionLocal


def _stored_line(owner_credential, bot_id, *, archived=False):
    from app import agent_chat_store as store
    from app.agent_chat_models import AgentConversation
    from app.database import SessionLocal

    async def run():
        try:
            cid = await store.create_conversation(owner_credential)
            for n in range(1, 5):
                turn = tid(n)
                await store.append_message(cid, turn, "user", f"第{n}个问题 " + (f"问问 {DETAIL}" if n == 1 else "闲聊"))
                await store.append_message(cid, turn, "assistant", f"答复{n} " + (f"{DETAIL} [1]" if n == 1 else "好的"),
                                           tool_calls={"citations": [{"ordinal": 1, "title": "10-Q", "source_type": "filing",
                                                                      "quote": "q"}]} if n == 1 else None)
            rolling = {"v": 2, "goals": ["看 Orbit"], "conclusions": [], "open": [], "preferences": [], "numbers": [],
                       "turns_compacted": 4, "total_compacted": 4, "focus": None}
            assert await store.append_summary(cid, 1, 8, json.dumps(rolling, ensure_ascii=False))
            return cid
        finally:
            await store.engine.dispose()
    cid = asyncio.run(run())
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, __import__("uuid").UUID(cid))
        conversation.bot_id = __import__("uuid").UUID(bot_id)
        if archived:
            from sqlalchemy import func
            conversation.archived_at = func.now()
        db.commit()
    return cid


def test_recall_finds_compacted_detail_in_the_same_bots_line(line):
    from app import agent_recall as recall
    from app.agent_chat_store import owner_hash
    own, mine = "owner", owner_hash("owner")
    a = _stored_line(own, BOT_A)
    _stored_line(own, BOT_B)                                   # another bot's line: not searched for bot A
    hits = recall.search_messages(mine, "Orbit 外包成本", bot_ids=[BOT_A])
    assert hits and all(h["conversation_id"] == a for h in hits)
    top = hits[0]
    assert top["kind"] == "message" and "7.35 亿美元" in top["snippet"] and top["turn_id"] == tid(1)
    assert top["sequence"] <= 8
    assert any(h["role"] == "assistant" and h["citation_ordinals"] == [1] for h in hits)
    assert recall.search_messages(owner_hash("stranger"), "Orbit 外包成本", bot_ids=[BOT_A]) == []


def test_recall_message_search_includes_the_bots_archived_older_conversations(line):
    from app import agent_recall as recall
    from app.agent_chat_store import owner_hash
    old = _stored_line("owner", BOT_A, archived=True)
    assert old in {h["conversation_id"] for h in recall.search_messages(owner_hash("owner"), "Orbit 外包成本", bot_ids=[BOT_A])}


def test_recall_conversations_tool_adds_message_hits_for_a_bot(line):
    from app.agent_chat_store import owner_hash
    from app.agent_workflow import tools
    from app.agent_workflow.state import AgentRuntimeContext
    import app.agent_chat_identity as identity
    a = _stored_line("owner", BOT_A)
    context = AgentRuntimeContext("custom", "test", "dummy", identity_credential="owner", owner_hash=owner_hash("owner"),
                                  conversation_id=a, bot_id=BOT_A, bot_is_default=False)
    result = asyncio.run(tools._dispatch("recall_conversations", {"query": "Orbit 外包成本", "limit": 3}, context, True, None))
    kinds = {row.get("kind") for row in result["data"]}
    assert "message" in kinds and "往事" in result["label"]
    message = next(r for r in result["data"] if r["kind"] == "message")
    assert "turn_id" in message and "7.35" in message["snippet"]


def test_read_history_citation_accepts_a_summary_marker_or_a_compacted_turn(line, monkeypatch):
    import types
    from app import agent_chat_store as store
    from app.agent_workflow import history_citations
    a = _stored_line("owner", BOT_A)
    ctx = types.SimpleNamespace(history_citation_catalogue=(), conversation_id=a, identity_credential="owner")
    reached = []

    async def fake_load(conversation_id, credential, turn_id, ordinal):
        reached.append((turn_id, ordinal))
        return {"ok": False, "error_code": "history_citation_unavailable"}

    monkeypatch.setattr(store, "load_turn_citation", fake_load)
    out = asyncio.run(history_citations.read_history_citation({"turn_id": tid(1), "ordinal": 1}, ctx))
    assert reached == [(tid(1), 1)] and out["error_code"] == "history_citation_unavailable"      # the gate let it through
    reached.clear()
    out = asyncio.run(history_citations.read_history_citation({"turn_id": tid(99), "ordinal": 1}, ctx))
    assert reached == [] and out["error_code"] == "history_citation_not_found"                  # unknown turn: refused at the gate
