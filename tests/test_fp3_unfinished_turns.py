"""FP3: a turn the user asked but that got no complete answer (cancelled, failed, or cut off) is carried
into the next turn as the question plus one system record of how it ended.  These tests pin the pure
rules (which turns, which states, how many, how long), the layer_rows contract (the new key sits outside
the layer budgets and changes no other key), and finally the stream wiring."""
import asyncio

import pytest

from app import agent_context as layers
from test_agent_chat_stream import stream_fixture  # noqa: F401  (the SSE fixture of the sibling module)


def msg(turn, sequence, role, content="", status="complete"):
    return {"turn_id": turn, "sequence": sequence, "role": role, "content": content, "status": status,
            "tool_calls": None, "tool_call_id": None}


def ask(turn, sequence, text):
    return msg(turn, sequence, "user", text)


def answer(turn, sequence, status="complete", text=""):
    return msg(turn, sequence, "assistant", text, status)


def finished(turn, first, question, reply):
    return [ask(turn, first, question), answer(turn, first + 1, "complete", reply)]


def states(items):
    return [(item["turn_id"], item["state"]) for item in items]


def without_unfinished(result):
    return {key: value for key, value in result.items() if key != "unfinished"}


def test_a_cancelled_question_after_a_complete_turn_is_the_one_carried():
    rows = finished("A", 1, "苹果的营收", "约 3900 亿美元") + [ask("B", 3, "英伟达 10-Q 的营收"), answer("B", 4, "cancelled")]

    assert layers.trailing_unfinished(rows) == [{"turn_id": "B", "content": "英伟达 10-Q 的营收", "state": "cancelled"}]


def test_a_failed_and_a_bare_question_are_both_carried_and_the_current_turn_gets_no_messages():
    rows = (finished("A", 1, "苹果的营收", "约 3900 亿美元")
            + [ask("B", 3, "英伟达的营收"), answer("B", 4, "failed"), ask("C", 5, "再说一下")])

    items = layers.trailing_unfinished(rows)

    assert states(items) == [("B", "failed"), ("C", "interrupted")]
    assert layers.unfinished_messages(items, "C") == [
        {"role": "user", "content": "英伟达的营收"},
        {"role": "assistant", "content": layers.UNFINISHED_NOTES["failed"]}]


def test_a_complete_turn_at_the_end_leaves_nothing_to_carry():
    rows = [ask("B", 1, "问B"), answer("B", 2, "cancelled")] + finished("A2", 3, "问A2", "答A2")

    assert layers.trailing_unfinished(rows) == []


def test_a_question_the_summary_already_covers_is_not_carried():
    rows = [ask("B", 3, "问B"), answer("B", 4, "cancelled")]

    assert layers.trailing_unfinished(rows, upto=3) == []
    assert states(layers.trailing_unfinished(rows, upto=2)) == [("B", "cancelled")]


@pytest.mark.parametrize("opening", ["confirm: 同意", "authorize: 好", "cancel: 取消",
                                     "change: 改成 5 月", "reply: 是", "   ", ""])
def test_button_replies_blank_questions_and_assistant_only_groups_are_passed_over_not_blocking(opening):
    rows = ([ask("X", 1, "问X"), answer("X", 2, "cancelled")]
            + [ask("Y", 3, opening), answer("Y", 4, "cancelled")]
            + [msg("Z", 5, "assistant", "简报")]
            + [ask("D", 6, "问D"), answer("D", 7, "failed")])

    assert states(layers.trailing_unfinished(rows)) == [("X", "cancelled"), ("D", "failed")]


def test_only_the_newest_three_unfinished_turns_are_kept_oldest_first_and_long_questions_are_cut():
    rows = []
    for n in range(1, 6):
        rows += [ask(f"T{n}", 2 * n - 1, f"第{n}问"), answer(f"T{n}", 2 * n, "cancelled")]

    assert [item["turn_id"] for item in layers.trailing_unfinished(rows)] == ["T3", "T4", "T5"]

    [item] = layers.trailing_unfinished([ask("L", 1, "字" * 1500), answer("L", 2, "failed")])

    assert item["content"] == "字" * 1000 + "…(略)"


def test_layer_rows_on_complete_turns_has_no_unfinished_and_its_other_keys_keep_their_values():
    rows = finished("t1", 1, "苹果的营收是多少", "约 3900 亿美元 [1]") + finished("t2", 3, "英伟达呢", "约 600 亿美元 [2]")

    result = layers.layer_rows(rows, [], l1_bytes=4096, l2_bytes=4096, l3_bytes=4096)

    assert result["unfinished"] == []
    kept = without_unfinished(result)
    kept["live_turns"] = [(t.first_sequence, t.last_sequence, t.turn_id) for t in kept["live_turns"]]
    assert kept == {
        "live_turns": [(1, 2, "t1"), (3, 4, "t2")],
        "l1_rows": [{"role": "user", "content": "苹果的营收是多少", "tool_calls": None, "tool_call_id": None,
                     "status": "complete", "turn_id": "t1"},
                    {"role": "assistant", "content": "约 3900 亿美元 [1]", "tool_calls": None, "tool_call_id": None,
                     "status": "complete", "turn_id": "t1"},
                    {"role": "user", "content": "英伟达呢", "tool_calls": None, "tool_call_id": None,
                     "status": "complete", "turn_id": "t2"},
                    {"role": "assistant", "content": "约 600 亿美元 [2]", "tool_calls": None, "tool_call_id": None,
                     "status": "complete", "turn_id": "t2"}],
        "l1_turns": 2, "l1_bytes": 201, "half_turns": [], "overflow": [], "segments": [], "segments_total": 0,
        "summary_upto": 0, "catalogue": [], "budget": 12288,
    }


def test_unfinished_turns_take_no_room_in_the_layer_budgets():
    done = finished("t1", 1, "苹果的营收是多少", "约 3900 亿美元 [1]") + finished("t2", 3, "英伟达呢", "约 600 亿美元 [2]")
    with_open = done + [ask("t3", 5, "还没回答的问题"), answer("t3", 6, "failed")]
    sizes = {"l1_bytes": 4096, "l2_bytes": 4096, "l3_bytes": 4096}

    plain = layers.layer_rows(done, [], **sizes)
    carried = layers.layer_rows(with_open, [], **sizes)

    assert states(carried["unfinished"]) == [("t3", "failed")]
    assert without_unfinished(carried) == without_unfinished(plain)


def test_a_turn_a_summary_already_covers_is_not_carried_again():
    rows = [ask("X", 1, "问X"), answer("X", 2, "cancelled"), ask("Y", 3, "问Y"), answer("Y", 4, "cancelled")]
    segments = [{"seq": 1, "from_sequence": 1, "upto_sequence": 2, "content": "更早：用户问过 X"}]

    result = layers.layer_rows(rows, segments, l1_bytes=4096, l2_bytes=4096, l3_bytes=4096)

    assert states(result["unfinished"]) == [("Y", "cancelled")]


def messages_after_a_cancelled_question(stream_fixture, monkeypatch, message="再试一次"):
    """Drive the real stream once after a stored complete turn and a cancelled one.  The stored rows are
    what the stream would read: the new question is already stored before the context is read."""
    import app.agent_chat_stream as stream
    send, _, _, _, stored, _, _ = stream_fixture
    prior = [ask("A", 1, "苹果的营收是多少"), answer("A", 2, "complete", "约 3900 亿美元 [1]"),
             ask("B", 3, "英伟达 10-Q 的营收"), answer("B", 4, "cancelled")]

    async def saved(*_args, **_kwargs):
        turn, text = next((args[1], args[3]) for args, _ in reversed(stored) if len(args) > 3 and args[2] == "user")
        return layers.layer_rows(prior + [ask(turn, 5, text)], [])
    monkeypatch.setattr(stream, "conversation_context", saved)

    sent = []
    original = stream.stream_workflow

    async def recording(**kwargs):
        sent.append(list(kwargs["messages"]))
        async for event in original(**kwargs):
            yield event
    monkeypatch.setattr(stream, "stream_workflow", recording)

    asyncio.run(send(message))
    return [(m["role"], m["content"]) for m in sent[0]]


def test_a_cancelled_question_reaches_the_workflow_as_question_then_record_before_the_new_one(stream_fixture, monkeypatch):
    contents = messages_after_a_cancelled_question(stream_fixture, monkeypatch)

    before = contents.index(("user", "英伟达 10-Q 的营收"))
    assert contents[before + 1] == ("assistant", layers.UNFINISHED_NOTES["cancelled"])
    assert contents.index(("user", "再试一次")) > before + 1


def test_the_switch_off_sends_the_same_messages_as_before(stream_fixture, monkeypatch):
    monkeypatch.setenv("FINBOT_FP3_UNFINISHED_TURNS", "off")

    contents = messages_after_a_cancelled_question(stream_fixture, monkeypatch)

    assert ("user", "英伟达 10-Q 的营收") not in contents
    assert ("assistant", layers.UNFINISHED_NOTES["cancelled"]) not in contents
