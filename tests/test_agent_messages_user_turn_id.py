import asyncio


def test_history_marks_user_messages_with_their_turn_id(monkeypatch):
    """The browser merges externally written turns (Telegram, reminders) by turn id, so the user side needs one too."""
    import app.agent_chat_stream as stream

    async def rows(*_a, **_k):
        return {"messages": [
            {"role": "user", "content": "hi", "status": "complete", "turn_id": "t1", "tool_calls": None},
            {"role": "assistant", "content": "hello", "status": "complete", "turn_id": "t1", "tool_calls": None},
        ], "has_more": False, "next_before": None}

    monkeypatch.setattr(stream, "owned_message_page", rows)
    messages = asyncio.run(stream.get_messages("conversation", before=None, limit=20, x_chat_session="owner"))["messages"]
    assert [(m["role"], m["turn_id"]) for m in messages] == [("user", "t1"), ("assistant", "t1")]
