"""Browser history pages are bounded by turns, not by the model's byte budget."""
import asyncio
from types import SimpleNamespace

from app.agent_chat_store import _eligible_turn_groups, _select_message_page, owned_message_page


def row(sequence, turn_id, role, status="complete"):
    return SimpleNamespace(sequence=sequence, turn_id=turn_id, role=role, status=status)


def turn(turn_id, start, status="complete"):
    return [row(start, turn_id, "user"), row(start + 1, turn_id, "assistant", status)]


def test_pages_are_whole_turns_with_an_exclusive_cursor():
    groups = _eligible_turn_groups([entry for index in range(5) for entry in turn(f"t{index}", index * 2 + 1)])
    selected, has_more, next_before = _select_message_page(groups, limit_turns=2)
    assert [group[-1].sequence for group in selected] == [8, 10]
    assert has_more is True and next_before == 7

    selected, has_more, next_before = _select_message_page(groups, before_sequence=7, limit_turns=2)
    assert [group[-1].sequence for group in selected] == [4, 6]
    assert has_more is True and next_before == 3

    selected, has_more, next_before = _select_message_page(groups, before_sequence=3, limit_turns=2)
    assert [group[-1].sequence for group in selected] == [2]
    assert has_more is False and next_before is None


def test_incomplete_and_non_user_turns_are_not_restored():
    rows = [
        row(1, "a", "user"), row(2, "a", "assistant"),
        row(3, "b", "user"), row(4, "b", "assistant", "running"),
        row(5, "c", "assistant"), row(6, "c", "assistant"),
        row(7, "d", "user"), row(8, "d", "assistant", "failed"),
    ]
    groups = _eligible_turn_groups(rows)
    assert [[entry.turn_id for entry in group] for group in groups] == [["a", "a"], ["d", "d"]]
    selected, has_more, next_before = _select_message_page(groups, limit_turns=None)
    assert [group[-1].sequence for group in selected] == [2, 8]
    assert has_more is False and next_before is None


def test_page_returns_turns_beyond_the_old_100kb_display_budget(monkeypatch):
    from app import agent_chat_store

    rows = []
    for index in range(10):
        body = "x" * 30_000
        rows.append(row(index * 2 + 1, f"t{index}", "user"))
        rows.append(row(index * 2 + 2, f"t{index}", "assistant"))
        rows[-1].content = body
        rows[-1].tool_calls = None
        rows[-1].tool_call_id = None
        rows[-2].content = "question"
        rows[-2].tool_calls = None
        rows[-2].tool_call_id = None

    class Rows:
        def all(self): return rows

    class SessionStub:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def scalars(self, statement): return Rows()

    async def owned(*args, **kwargs): return True
    monkeypatch.setattr(agent_chat_store, "verify_conversation", owned)
    monkeypatch.setattr(agent_chat_store, "Session", SessionStub)

    page = asyncio.run(owned_message_page("00000000-0000-0000-0000-000000000001", "owner", limit_turns=None))
    assert len(page["messages"]) == 20
    assert page["has_more"] is False
    assert page["next_before"] is None

    first = asyncio.run(owned_message_page("00000000-0000-0000-0000-000000000001", "owner", limit_turns=3))
    assert len(first["messages"]) == 6
    assert first["has_more"] is True
    assert first["next_before"] == 15

    older = asyncio.run(owned_message_page("00000000-0000-0000-0000-000000000001", "owner", before_sequence=15, limit_turns=3))
    assert len(older["messages"]) == 6
    assert older["has_more"] is True
    assert older["next_before"] == 9


def request_row(sequence, turn_id):
    """An assistant row that asks for tools; its result rows are written only after the tools run."""
    item = row(sequence, turn_id, "assistant")
    item.tool_calls = {"calls": [{"id": f"call-{sequence}", "type": "function",
                                  "function": {"name": "lookup", "arguments": "{}"}}]}
    return item


def test_a_turn_whose_last_row_asks_for_a_tool_is_still_running():
    assert _eligible_turn_groups([row(1, "a", "user"), request_row(2, "a")]) == []


def test_a_turn_waiting_on_a_second_tool_request_is_not_restored():
    rows = [row(1, "a", "user"), request_row(2, "a"), row(3, "a", "tool"), request_row(4, "a")]
    assert _eligible_turn_groups(rows) == []


def test_a_turn_is_restored_once_its_last_tool_round_has_an_answer():
    rows = [row(1, "a", "user"), request_row(2, "a"), row(3, "a", "tool"), row(4, "a", "assistant")]
    groups = _eligible_turn_groups(rows)
    assert [[entry.sequence for entry in group] for group in groups] == [[1, 2, 3, 4]]


def test_a_failed_or_cancelled_turn_is_restored_even_with_a_citation_only_protocol():
    cancelled = row(4, "b", "assistant", "cancelled")
    cancelled.tool_calls = {"citations": []}
    groups = _eligible_turn_groups([row(1, "a", "user"), row(2, "a", "assistant", "failed"),
                                    row(3, "b", "user"), cancelled])
    assert [group[-1].sequence for group in groups] == [2, 4]
