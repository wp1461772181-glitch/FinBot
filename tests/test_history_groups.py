"""3c review fix: history is a sequence of whole turn groups in answer order; nothing cuts through a group.

A summary covers a set of whole turns (named by turn id), and the history view leaves out exactly those; the messages page cursor
pages by group in answer order.  Turns that ran together overlap in their row sequences, which is what these tests build.
"""
from types import SimpleNamespace

from app import agent_context as layers
from app.agent_chat_store import _eligible_turn_groups, _select_message_page
from tests.test_agent_context import _run_with_store

MINE = "m" * 40


def srow(sequence, turn_id, role, content="", status="complete", **extra):
    return {"id": f"{role}-{sequence}", "turn_id": turn_id, "sequence": sequence, "role": role, "content": content, "status": status,
            "tool_calls": None, "tool_call_id": None, **extra}


def question_and_answer(turn_id, first, last, text):
    return [srow(first, turn_id, "user", text), srow(last, turn_id, "assistant", "答" + text * 200)]


# ---- summaries ----

def review_rows():
    """Z (1-2), A long (3..8), B parallel (4..5, answers first), C (9-10): answer order is Z, B, A, C."""
    return sorted([*question_and_answer("Z", 1, 2, "Z"), *question_and_answer("A", 3, 8, "A"), *question_and_answer("B", 4, 5, "B"),
                   *question_and_answer("C", 9, 10, "C")], key=lambda r: r["sequence"])


def test_a_summary_names_the_turns_it_covers_and_the_history_leaves_out_exactly_those():
    rows = review_rows()
    # The summary was made of Z and B (both ended before A): its range is 1..5, which A's first row (3) lies inside.
    segment = {"seq": 1, "from_sequence": 1, "upto_sequence": 5, "content": "摘要", "turn_ids": ["Z", "B"]}
    context = layers.layer_rows(rows, [segment], l1_bytes=100_000, l2_bytes=100_000, l3_bytes=100_000)
    carried = [t for t in dict.fromkeys(r["turn_id"] for r in context["l1_rows"])]
    assert carried == ["A", "C"]                                    # A is still there, whole; Z and B are in the summary only
    older = layers.layer_rows(rows, [{**segment, "turn_ids": None}], l1_bytes=100_000, l2_bytes=100_000, l3_bytes=100_000)
    assert [t for t in dict.fromkeys(r["turn_id"] for r in older["l1_rows"])] == ["C"]       # a segment without ids still reads by range, as it always did


def test_the_overflow_a_summary_takes_is_whole_turns_that_carry_their_ids():
    context = layers.layer_rows(review_rows(), [], l1_bytes=1500, l2_bytes=1, l3_bytes=1)
    overflow = [t.turn_id for t in context["overflow"]]
    assert overflow and set(overflow) <= {"Z", "B", "A"} and overflow == [t for t in ["Z", "B", "A"] if t in overflow]      # answer order
    assert context["live_turns"] and all(t.turn_id for t in context["live_turns"])


def test_the_store_keeps_the_covered_turns_and_the_next_context_still_carries_the_overlapping_one(disposable_database):
    import uuid

    async def exercise(store):
        cid = await store.create_conversation(MINE)
        z, a, b, c = (str(uuid.uuid4()) for _ in range(4))
        plan = [(z, "Z"), (a, "A"), (b, "B")]
        await store.append_message(cid, z, "user", "Z问题")                     # 1
        await store.append_message(cid, z, "assistant", "Z答")                  # 2
        await store.append_message(cid, a, "user", "A问题")                     # 3
        await store.append_message(cid, b, "user", "B问题")                     # 4
        await store.append_message(cid, b, "assistant", "B答")                  # 5
        await store.append_message(cid, a, "assistant", "A答")                  # 6
        assert await store.append_summary(cid, 1, 5, "摘要", turn_ids=[z, b])
        context = await store.conversation_context(cid, MINE)
        ids = {r["turn_id"] for r in context["l1_rows"]}
        return ids, a, z, b

    ids, a, z, b = _run_with_store(exercise)
    assert ids == {a}


# ---- the messages page ----

def row(sequence, turn_id, role, status="complete"):
    return SimpleNamespace(sequence=sequence, turn_id=turn_id, role=role, status=status, tool_calls=None)


def turn(turn_id, first, last):
    return [row(first, turn_id, "user"), row(last, turn_id, "assistant")]


def test_a_long_turn_that_overlapped_a_parallel_one_is_whole_on_exactly_one_page():
    rows = [*turn("A", 1, 4), *turn("S", 2, 3), *turn("t1", 5, 6), *turn("t2", 7, 8), *turn("t3", 9, 10), *turn("t4", 11, 12)]
    rows.sort(key=lambda r: r.sequence)
    groups = _eligible_turn_groups(rows)
    first, more, cursor = _select_message_page(groups, limit_turns=5)
    assert more and {g[0].turn_id for g in first} == {"A", "t1", "t2", "t3", "t4"}
    second, more2, cursor2 = _select_message_page(groups, before_sequence=cursor, limit_turns=5)
    assert [g[0].turn_id for g in second] == ["S"] and not more2 and cursor2 is None
    assert [g[0].turn_id for g in first][0] == "A"                                  # shown in answer order: A answered after S


def test_a_conversation_without_overlap_pages_exactly_as_before():
    rows = [entry for index in range(5) for entry in turn(f"t{index}", index * 2 + 1, index * 2 + 2)]
    groups = _eligible_turn_groups(rows)
    selected, more, cursor = _select_message_page(groups, limit_turns=2)
    assert [g[-1].sequence for g in selected] == [8, 10] and more and cursor == 7
    selected, more, cursor = _select_message_page(groups, before_sequence=7, limit_turns=2)
    assert [g[-1].sequence for g in selected] == [4, 6] and more and cursor == 3
