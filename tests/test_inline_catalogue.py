"""Kernel turns: each turn's citation entry stands right after that turn's answer (an inline note, no ``answers_back``), so the
history up to the new question is the same bytes on the next turn and the provider's prompt cache holds.  The old engine, and a
kernel turn with ``FINBOT_KERNEL_INLINE_CATALOGUE`` off, keep the one catalogue message after the question."""
import asyncio
import json
import random
from types import SimpleNamespace
from uuid import UUID

import pytest

import app.agent_chat_provider as provider
import app.agent_context as layers
from app.agent_context import ANCHOR_GRID, layer_rows
from test_agent_chat_stream import stream_fixture  # noqa: F401  (the fixture is used by name)
from test_kernel_wiring import Wiring, call  # noqa: F401

L1, L2, L3 = 24000, 16000, 4000


def build(turns=200, seed=11, cited=0.5):
    """Rows of a conversation: (rows, ends).  About half the answers carry citations (one to three sources)."""
    rng = random.Random(seed)
    rows, ends, seq = [], [], 0

    def add(role, content, turn, **extra):
        nonlocal seq
        seq += 1
        rows.append({"role": role, "content": content, "turn_id": str(UUID(int=turn)), "sequence": seq, "status": "complete",
                     "tool_calls": extra.get("tool_calls"), "tool_call_id": extra.get("tool_call_id")})

    for turn in range(1, turns + 1):
        add("user", f"question {turn} " + "q" * rng.randint(20, 200), turn)
        if rng.random() < 0.3:
            add("assistant", "", turn, tool_calls={"calls": [{"id": f"c{turn}", "function": {"name": "search_news"}}]})
            add("tool", "x" * rng.randint(50, 600), turn, tool_call_id=f"c{turn}")
        answer, protocol = f"answer {turn} " + "a" * rng.randint(30, 300), None
        if rng.random() < cited:
            n = rng.randint(1, 3)
            answer += "".join(f" [{k}]" for k in range(1, n + 1))
            protocol = {"citations": [{"ordinal": k, "title": f"Filing {turn}.{k}", "source_type": "official_filing", "quote": "q"}
                                      for k in range(1, n + 1)]}
        add("assistant", answer, turn, tool_calls=protocol)
        ends.append(len(rows))
    return rows, ends


def inline_at(rows, ends, n, *, grid=ANCHOR_GRID, l1=L1, l2=L2, segments=()):
    return layer_rows(rows[:ends[n - 1]], list(segments), l1_bytes=l1, l2_bytes=l2, l3_bytes=L3, anchor_grid=grid, inline_catalogue=True)


def starts(context):
    l1 = context["l1_rows"][0]["turn_id"] if context["l1_rows"] else None
    half = context["half_turns"][0].turn_id if context["half_turns"] else None
    return l1, half, len(context["overflow"])


def notes_of(messages):
    return [m for m in messages if layers.is_catalogue_message(m)]


# --- B1: placement, no answers_back ------------------------------------------------------------------------------

def test_each_cited_answer_is_followed_by_its_own_note_and_nothing_names_a_position():
    rows, ends = build(30, cited=1.0)
    context = inline_at(rows, ends, 30, l1=3000, l2=6000)
    assert context["half_turns"] and context["l1_turns"], "both layers must hold turns for the test to mean anything"
    messages = layers.inline_history_messages(context)
    notes = notes_of(messages)
    assert len(notes) == len(context["catalogue"]) == context["l1_turns"] + len(context["half_turns"])
    for at, message in enumerate(messages):
        if message in notes:
            entry = json.loads(message["content"].split("\n", 1)[1])
            assert messages[at - 1]["role"] == "assistant" and message["role"] == "user"
            assert "answers_back" not in entry and set(entry) == {"turn_id", "opening", "sources"}
            assert messages[at - 1]["content"].startswith(entry["opening"][:10])      # the answer it belongs to
    assert all("answers_back" not in entry for entry in context["catalogue"])
    assert context["inline_catalogue"] is True


def test_the_note_head_is_the_plans_text_and_notes_are_not_conversation():
    head = ("（系统附注，不是用户的话：上面这条回答的出处目录。要用其中一条，调用 read_history_citation(turn_id, ordinal) "
            "取回原文，再引用新的编号。派生的数字先取回它的来源。）")
    assert layers.INLINE_CATALOGUE_HEAD == head
    note = layers.inline_catalogue_message({"turn_id": "t", "opening": "o", "sources": [], "answers_back": 3})
    assert note["content"] == head + '\n{"turn_id":"t","opening":"o","sources":[]}'
    assert layers.is_catalogue_message(note) and not layers.is_memory_message(note)
    question = {"role": "user", "content": "question"}
    assert layers.conversation_messages([question, note]) == [question]


def test_an_answer_without_citations_has_no_note():
    rows, ends = build(10, cited=0.0)
    context = inline_at(rows, ends, 10)
    assert context["catalogue"] == [] and notes_of(layers.inline_history_messages(context)) == []


def test_the_omitted_turns_marker_still_comes_first():
    rows, ends = build(120, cited=1.0)
    context = inline_at(rows, ends, 120, l1=3000, l2=4000)
    assert context["overflow"]
    first = layers.inline_history_messages(context)[0]
    assert first["content"].startswith("[系统提示：有 ") and f"有 {len(context['overflow'])} 轮" in first["content"]


# --- B1: the cache requirement: byte-identical history from one turn to the next ---------------------------------

def test_history_up_to_the_new_turn_is_byte_identical_between_turn_n_and_n_plus_1():
    rows, ends = build(240)
    previous = inline_at(rows, ends, 1)
    checked = full = 0
    for n in range(2, 241):
        current = inline_at(rows, ends, n)
        before, after = layers.inline_history_messages(previous), layers.inline_history_messages(current)
        if starts(current) == starts(previous):          # no turn changed layer
            own = layers.inline_history_messages({**current, "half_turns": [], "overflow": [],
                                                  "l1_rows": [r for r in current["l1_rows"] if r["turn_id"] == str(UUID(int=n))]})
            assert json.dumps(after[:len(before)], ensure_ascii=False) == json.dumps(before, ensure_ascii=False), f"prefix broke at turn {n}"
            assert after[len(before):] == own
            checked += 1
        full += bool(current["half_turns"] and current["overflow"])
        previous = current
    assert checked > 200 and full > 50, "layers must be full and the check must really run"


def test_the_old_catalogue_after_the_question_is_not_a_stable_prefix():
    """The reason for the change: the single message renumbers every entry every turn."""
    rows, ends = build(40, cited=1.0)

    def old(n):
        context = layer_rows(rows[:ends[n - 1]], [], l1_bytes=10 ** 6, l2_bytes=L2, l3_bytes=L3)
        return layers.render_citation_catalogue(context["catalogue"])["content"]

    assert not old(21).startswith(old(20)[:-2]) and "answers_back" in old(20)


def test_a_turn_that_changes_layer_changes_only_its_own_form():
    rows, ends = build(60, cited=1.0)
    wide = inline_at(rows, ends, 60, l1=10 ** 6)
    narrow = inline_at(rows, ends, 60, l1=3000, l2=10 ** 6)
    by_turn = lambda context: {e["turn_id"]: e for e in context["catalogue"]}      # noqa: E731
    assert by_turn(wide) == {k: v for k, v in by_turn(narrow).items() if k in by_turn(wide)}      # the entry itself never differs


# --- B1: budget ----------------------------------------------------------------------------------------------------

def test_layer_bytes_equal_what_is_sent_including_every_note():
    rows, ends = build(150)
    for n in (20, 80, 150):
        context = inline_at(rows, ends, n, l1=6000, l2=8000)
        l1_only = layers.inline_history_messages({**context, "half_turns": [], "overflow": []})
        assert context["l1_bytes"] == sum(layers.json_bytes(m) for m in l1_only)
        half = layers.inline_history_messages({**context, "l1_rows": [], "overflow": []})
        report_half = sum(layers.half_size(t) + (layers.inline_note_bytes(t.catalogue) if t.catalogue else 0) for t in context["half_turns"])
        assert report_half == sum(layers.json_bytes(m) for m in half)
        assert context["l1_bytes"] <= 6000 and report_half <= 8000


def test_a_turn_whose_answer_plus_note_does_not_fit_is_handled_as_before():
    group, ends = build(3, cited=1.0)
    rows = group[:ends[0]]
    entry = layers.turn_catalogue_entry(rows)
    projected = sum(layers.json_bytes(m) for m in layers.project_turn_history(rows))
    fits = layer_rows(rows, [], l1_bytes=projected + layers.inline_note_bytes(entry), l2_bytes=0, l3_bytes=0, inline_catalogue=True)
    tight = layer_rows(rows, [], l1_bytes=projected + layers.inline_note_bytes(entry) - 1, l2_bytes=0, l3_bytes=0, inline_catalogue=True)
    assert fits["l1_turns"] == 1 and fits["l1_bytes"] == projected + layers.inline_note_bytes(entry)
    assert tight["l1_turns"] == 0 and tight["overflow"] and not tight["catalogue"]


def test_the_inline_total_differs_from_the_old_one_by_about_a_head_per_entry():
    rows, ends = build(60, cited=1.0)
    old = layer_rows(rows[:ends[59]], [], l1_bytes=10 ** 6, l2_bytes=L2, l3_bytes=L3)
    new = layer_rows(rows[:ends[59]], [], l1_bytes=10 ** 6, l2_bytes=L2, l3_bytes=L3, inline_catalogue=True)
    entries = len(new["catalogue"])
    assert old["l1_turns"] == new["l1_turns"] and entries == len(old["catalogue"])
    # per entry: the head the note repeats, minus the position the old entry carried; the old message shared one head
    extra = new["l1_bytes"] - old["l1_bytes"]
    assert 0 < extra <= entries * (len(layers.INLINE_CATALOGUE_HEAD.encode()) + 40)


def test_a_summary_covered_turn_has_no_note_and_costs_nothing():
    rows, ends = build(30, cited=1.0)
    upto = rows[ends[9] - 1]["sequence"]
    context = inline_at(rows, ends, 30, segments=[{"seq": 1, "from_sequence": 1, "upto_sequence": upto, "content": "s"}])
    shown = {e["turn_id"] for e in context["catalogue"]}
    assert shown and not any(str(UUID(int=n)) in shown for n in range(1, 11))


# --- the old engine and the flag-off kernel keep today's result ------------------------------------------------------

def test_without_the_argument_the_result_is_what_it_was():
    rows, ends = build(80, cited=1.0)
    plain = layer_rows(rows[:ends[79]], [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=ANCHOR_GRID)
    off = layer_rows(rows[:ends[79]], [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=ANCHOR_GRID, inline_catalogue=False)
    assert repr(plain) == repr(off) and "inline_catalogue" not in plain
    assert plain["catalogue"] and all("answers_back" in e for e in plain["catalogue"])
    assert [e["answers_back"] for e in plain["catalogue"]] == list(range(1, len(plain["catalogue"]) + 1))


def test_the_store_asks_for_inline_notes_only_for_kernel_turns_and_only_with_the_flag(monkeypatch):
    import app.agent_chat_store as store
    calls = []

    class Result:
        def all(self):
            return []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalars(self, statement):
            return Result()

    async def yes(*args):
        return True

    monkeypatch.setattr(store, "Session", Session)
    monkeypatch.setattr(store, "verify_conversation", yes)
    monkeypatch.setattr(store.layers, "layer_rows", lambda *a, **k: calls.append(k) or {})
    cid = str(UUID(int=5))
    monkeypatch.delenv("FINBOT_KERNEL_INLINE_CATALOGUE", raising=False)
    asyncio.run(store.conversation_context(cid, "c", anchored=True))
    asyncio.run(store.conversation_context(cid, "c"))
    monkeypatch.setenv("FINBOT_KERNEL_INLINE_CATALOGUE", "off")
    asyncio.run(store.conversation_context(cid, "c", anchored=True))
    assert [k.get("inline_catalogue") for k in calls] == [True, None, None]


# --- read_history_citation: the check is unchanged ------------------------------------------------------------------

def test_read_history_citation_accepts_every_entry_shown_inline_and_refuses_one_not_shown(monkeypatch):
    import app.agent_chat_store as store
    from app.agent_workflow.history_citations import read_history_citation
    rows, ends = build(60, cited=1.0)
    context = inline_at(rows, ends, 60, l1=4000, l2=5000)
    shown = {(e["turn_id"], s["ordinal"]) for e in context["catalogue"] for s in e["sources"]}
    inline = {(json.loads(m["content"].split("\n", 1)[1])["turn_id"], s["ordinal"])
              for m in notes_of(layers.inline_history_messages(context))
              for s in json.loads(m["content"].split("\n", 1)[1])["sources"]}
    assert shown == inline and shown
    hidden = (str(UUID(int=1)), 1)
    assert hidden not in shown and context["overflow"]

    async def remembered(*_):
        return False

    async def loaded(_cid, _credential, turn_id, ordinal):
        return {"ok": False, "error_code": "reached_the_store"}

    monkeypatch.setattr(store, "citation_remembered", remembered)
    monkeypatch.setattr(store, "load_turn_citation", loaded)
    ctx = SimpleNamespace(conversation_id="c", identity_credential="k", history_citation_catalogue=tuple(context["catalogue"]))
    for turn_id, ordinal in shown:
        assert asyncio.run(read_history_citation({"turn_id": turn_id, "ordinal": ordinal}, ctx))["error_code"] == "reached_the_store"
    assert asyncio.run(read_history_citation({"turn_id": hidden[0], "ordinal": hidden[1]}, ctx))["error_code"] == "history_citation_not_found"


# --- what the kernel and the providers do with consecutive user messages -----------------------------------------------

def test_the_kernel_prompt_keeps_notes_in_the_history_and_marks_the_cache_point_after_the_last_one():
    from app.kernel import prompt
    from app.kernel.loop import _previous_user_message
    rows, ends = build(4, cited=1.0)
    context = inline_at(rows, ends, 4)
    history = layers.inline_history_messages(context)
    built = prompt.build_messages("下一个问题", SimpleNamespace(identity_credential=""), history)
    assert built[-1] == {"role": "user", "content": "下一个问题"}
    assert layers.is_catalogue_message(built[-2]) and built[-2].get("cache_point") is True
    assert sum(layers.is_catalogue_message(m) for m in built) == 4
    assert [m.get("cache_point") for m in built].count(True) == 1
    previous = _previous_user_message(history + [{"role": "user", "content": "下一个问题"}], "下一个问题")
    assert previous == "question 4 " + previous[len("question 4 "):]      # his own words, never a note


def test_the_native_converter_merges_a_note_and_the_next_question_into_one_user_message():
    from app.anthropic_native import CACHE_POINT, convert_messages
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1 [1]"},
                {**layers.inline_catalogue_message({"turn_id": "t", "opening": "a1", "sources": []}), "cache_point": True},
                {"role": "user", "content": "q2"}]
    _system, out = convert_messages(messages)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    texts = [b["text"] for b in out[2]["content"]]
    assert texts[0].startswith(layers.INLINE_CATALOGUE_MARKER) and texts[1] == "q2"
    assert out[2]["content"][0].get(CACHE_POINT) is True and CACHE_POINT not in out[2]["content"][1]


# --- B2: the endpoint --------------------------------------------------------------------------------------------------

def turn_rows(count):
    rows, ends = build(count, seed=3, cited=1.0)
    return rows[:ends[count - 1]]


@pytest.fixture
def kernel(stream_fixture, monkeypatch):  # noqa: F811
    wiring = Wiring(stream_fixture, monkeypatch)
    wiring.bot["engine"] = "v2"
    return wiring


def sent_messages(wiring, rows, *, inline, message="下一个问题"):
    """Run one kernel turn through the real endpoint over ``rows`` as the stored history; the messages the model got."""
    async def saved(*_args, **kwargs):
        assert kwargs.get("anchored") is True
        return layer_rows(rows, [], anchor_grid=ANCHOR_GRID, inline_catalogue=inline)

    wiring.monkeypatch.setattr(wiring.stream, "conversation_context", saved)
    wiring.model([(["好"], [])])
    seen = []
    inner = wiring.script

    async def spy(provider_name, model, api_key, messages, schemas, **kwargs):
        seen.append(json.loads(json.dumps(messages, ensure_ascii=False)))
        return await inner(provider_name, model, api_key, messages, schemas, **kwargs)

    wiring.monkeypatch.setattr(provider, "stream_decision", spy)
    wiring.bot_turn(message)
    return seen[0]


def test_a_kernel_turn_places_the_notes_inline_and_adds_no_catalogue_after_the_question(kernel):
    messages = sent_messages(kernel, turn_rows(5), inline=True)
    conversation = [m for m in messages if m["role"] != "system"]
    assert conversation[-1] == {"role": "user", "content": "下一个问题"} or conversation[-1]["content"].endswith("下一个问题")
    at = max(i for i, m in enumerate(conversation) if m["content"].endswith("下一个问题"))
    assert not any(layers.is_catalogue_message(m) for m in conversation[at:])
    notes = [i for i, m in enumerate(conversation) if layers.is_catalogue_message(m)]
    assert len(notes) == 5 and all(conversation[i - 1]["role"] == "assistant" for i in notes)
    assert all(m.get("content", "").find("answers_back") < 0 for m in messages)


def test_the_history_before_the_question_is_byte_identical_on_the_next_kernel_turn(kernel):
    five = sent_messages(kernel, turn_rows(5), inline=True)
    six = sent_messages(kernel, turn_rows(6), inline=True)

    def history(messages):
        at = max(i for i, m in enumerate(messages) if m["role"] == "user" and m["content"] == "下一个问题")
        # ``cache_point`` is the breakpoint marker, not content: it sits on the last history message of each request.
        return [{k: v for k, v in m.items() if k != "cache_point"} for m in messages[:at]]

    before = history(five)
    assert json.dumps(history(six)[:len(before)], ensure_ascii=False) == json.dumps(before, ensure_ascii=False)
    assert len(history(six)) == len(before) + 3          # the new turn: question, answer, note


def test_with_the_flag_off_a_kernel_turn_has_the_one_catalogue_message_after_the_question(kernel):
    messages = sent_messages(kernel, turn_rows(5), inline=False)
    conversation = [m for m in messages if m["role"] != "system"]
    assert layers.is_catalogue_message(conversation[-1]) and conversation[-1]["content"].startswith(layers.CATALOGUE_MARKER)
    assert sum(layers.is_catalogue_message(m) for m in conversation) == 1 and "answers_back" in conversation[-1]["content"]


def test_an_old_engine_turn_keeps_the_catalogue_after_the_question(stream_fixture, monkeypatch):
    import app.agent_chat_stream as stream
    send, _, _, _, _, requests, _ = stream_fixture
    rows = turn_rows(3)

    async def saved(*_args, **_kwargs):
        return layer_rows(rows, [])

    monkeypatch.setattr(stream, "conversation_context", saved)
    seen = []
    original = stream.stream_workflow

    async def recording(**kwargs):
        seen.append(list(kwargs["messages"]))
        async for event in original(**kwargs):
            yield event

    monkeypatch.setattr(stream, "stream_workflow", recording)
    asyncio.run(send("下一个问题"))
    assert layers.is_catalogue_message(seen[0][-1]) and seen[0][-1]["content"].startswith(layers.CATALOGUE_MARKER)
    assert not any(m["content"].startswith(layers.INLINE_CATALOGUE_MARKER) for m in seen[0])


# --- B3: the context card and the compaction line -----------------------------------------------------------------------

def test_the_context_report_counts_the_notes_where_they_are_sent():
    from app.agent_chat_stream import _context_report
    rows, ends = build(120)
    context = {**inline_at(rows, ends, 120, l1=6000, l2=8000), "segments": []}
    assert context["half_turns"] and context["l1_turns"]
    report = {p["key"]: p for p in _context_report(context)["parts"]}
    sent = [m for m in layers.inline_history_messages(context) if not m["content"].startswith("[系统提示：有 ")]
    assert report["recent"]["bytes"] + report["compressed"]["bytes"] == sum(layers.json_bytes(m) for m in sent)
    assert report["recent"]["bytes"] == context["l1_bytes"]


def test_the_report_of_a_turn_that_is_not_inline_is_unchanged():
    from app.agent_chat_stream import _context_report
    rows, ends = build(120)
    context = {**layer_rows(rows[:ends[119]], [], l1_bytes=6000, l2_bytes=8000, l3_bytes=L3, anchor_grid=ANCHOR_GRID), "segments": []}
    report = {p["key"]: p for p in _context_report(context)["parts"]}
    half = [t for t in context["half_turns"]]
    marginal = 0
    existing = [e for e in context["catalogue"] if e["answers_back"] <= context["l1_turns"]]
    for item in (e for e in context["catalogue"] if e["answers_back"] > context["l1_turns"]):
        marginal += layers.catalogue_entry_bytes(item, existing) if existing else layers.catalogue_bytes([item]) - layers.CATALOGUE_HEAD_BYTES
        existing = [*existing, item]
    assert report["compressed"]["bytes"] == sum(layers.half_size(t) for t in half) + marginal


def test_compaction_pressure_includes_the_half_compressed_notes():
    rows, ends = build(120, cited=1.0)
    context = inline_at(rows, ends, 120, l1=6000, l2=8000)
    plain = {**context, "inline_catalogue": False}
    notes = sum(layers.inline_note_bytes(t.catalogue) for t in context["half_turns"] if t.catalogue)
    assert notes and layers.history_usage(context)["bytes"] - layers.history_usage(plain)["bytes"] == notes
