"""5d-1 Task 5: the history API hands a stored answer's figure check to the web (the 出处 tab shows it)."""
import asyncio

import app.agent_chat_stream as stream

FLAGGED = {"version": 1, "figures": 2, "flagged": [{"line": "利润是 8888 美元。", "values": ["8888"]}]}


def history(monkeypatch, protocol):
    async def page(*_a, **_k):
        return {"messages": [
            {"role": "user", "content": "苹果利润多少", "status": "complete", "turn_id": "t1", "tool_calls": None},
            {"role": "assistant", "content": "利润是 8888 美元。", "status": "complete", "turn_id": "t1", "tool_calls": protocol},
        ], "has_more": False, "next_before": None}

    monkeypatch.setattr(stream, "owned_message_page", page)
    messages = asyncio.run(stream.get_messages("conversation", before=None, limit=20, x_chat_session="owner"))["messages"]
    return [m for m in messages if m["role"] == "assistant"][-1]


def test_a_checked_answer_carries_its_reconciliation(monkeypatch):
    answer = history(monkeypatch, {"route": "K", "audit": {"terminal_status": "succeeded"}, "reconciliation": FLAGGED})
    assert answer["reconciliation"] == FLAGGED


def test_a_clean_and_a_failed_check_are_passed_as_stored(monkeypatch):
    clean = {"version": 1, "figures": 3, "flagged": []}
    assert history(monkeypatch, {"route": "K", "reconciliation": clean})["reconciliation"] == clean
    failed = {"version": 1, "error": "KeyError"}
    assert history(monkeypatch, {"route": "K", "reconciliation": failed})["reconciliation"] == failed


def test_an_unchecked_answer_has_no_reconciliation(monkeypatch):
    assert "reconciliation" not in history(monkeypatch, {"route": "K", "audit": {"terminal_status": "succeeded"}})
    assert "reconciliation" not in history(monkeypatch, {"route": "K", "reconciliation": "junk"})
    assert "reconciliation" not in history(monkeypatch, None)
