"""The kernel behind the per-bot ``engine`` switch: which turn runs, what the client and the store see.

The endpoint is the real ``stream.stream_chat`` with in-memory stand-ins (the ``stream_fixture`` of
test_agent_chat_stream); the kernel's model is a scripted ``stream_decision``, and the old turn's model call
is recorded so a test can prove which path ran.
"""
import asyncio
import json
from uuid import uuid4

import pytest
from starlette.requests import Request

import app.agent_chat_provider as provider
from app.agent_chat_models import AgentBot
from app.agent_chat_stream import StreamRequest
from test_agent_chat_stream import frames, stream_fixture  # noqa: F401  (the fixture is used by name)

ROW = {"id": "r1", "symbol": "AAPL", "source_type": "official_filing", "excerpt": "Revenue was 1158 (USD millions)."}


def call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Script:
    """A fake ``stream_decision``: ``(pieces, calls)`` per model step; the final text is the pieces joined."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.count = 0

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        self.count += 1
        pieces, calls = self.steps.pop(0)
        for piece in pieces:
            await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": "".join(pieces)}
        if calls:
            message["tool_calls"] = calls
        return {"usage": {"total_tokens": 10}}, message


class Wiring:
    def __init__(self, stream_fixture, monkeypatch):
        import app.agent_chat_stream as stream
        from app.agent_workflow import direct, tools

        self.send_old, _, _, self.executed, self.stored, _, _ = stream_fixture
        self.monkeypatch = monkeypatch
        self.stream = stream
        self.script = None
        self.old_calls = []
        old_model = direct.decision_request

        async def counted(*args, **kwargs):
            self.old_calls.append(args[3] if len(args) > 3 else None)
            return await old_model(*args, **kwargs)

        monkeypatch.setattr(provider, "decision_request", counted)
        monkeypatch.setattr(direct, "decision_request", counted)

        async def invoke(name, args, context, *, emit=None, page_chars=None):
            self.executed.append((name, args))
            return {"ok": True, "data": [dict(ROW)], "source": "saved"}

        monkeypatch.setattr(tools, "invoke", invoke)
        monkeypatch.delenv("FINBOT_KERNEL_DEFAULT", raising=False)
        monkeypatch.delenv("FINBOT_KERNEL_V2", raising=False)
        resolved = {"name": "test-model", "provider": "anthropic", "model": "m", "api_key": "k" * 12, "base_url": None, "context_window": None}
        self.resolved = resolved
        self.bot = {"bot_id": str(uuid4()), "bot_name": "测试", "is_default": False, "conversation_id": str(uuid4()),
                    "model": None, "reasoning_effort": None, "engine": None, "description": "", "theme": None,
                    "focus_companies": [], "tool_scope": None, "default_company": None, "block": ""}
        monkeypatch.setattr(stream, "_bot_turn", lambda payload, credential: (dict(self.bot), resolved))
        monkeypatch.setattr(stream, "_catalog_turn", lambda name, credential: resolved)

    def model(self, steps):
        self.script = Script(steps)
        self.monkeypatch.setattr(provider, "stream_decision", self.script)

    def kernel_must_not_run(self):
        async def forbidden(*args, **kwargs):
            raise AssertionError("the kernel's model call was made")

        self.monkeypatch.setattr(provider, "stream_decision", forbidden)

    async def _send(self, **fields):
        payload = StreamRequest(message="show AAPL prices", **fields)
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await self.stream.stream_chat(payload, request, "x" * 40)
        return frames("".join([part async for part in response.body_iterator]))

    def bot_turn(self):
        return asyncio.run(self._send(bot_id=self.bot["bot_id"]))

    def catalog_turn(self):
        return asyncio.run(self._send(catalog_model=""))

    def rows(self):
        return [(args[2], kwargs) for args, kwargs in self.stored if len(args) >= 3 and args[2] in ("user", "assistant", "tool")]


@pytest.fixture
def wiring(stream_fixture, monkeypatch):  # noqa: F811
    return Wiring(stream_fixture, monkeypatch)


def done_of(events):
    return next(data for name, data in events if name == "done")


def test_bot_with_engine_v2_runs_the_kernel(wiring):
    wiring.bot["engine"] = "v2"
    wiring.model([(["营收 ", "1158"], [])])
    events = wiring.bot_turn()
    names = [name for name, _ in events]
    assert [d["text"] for n, d in events if n == "delta"] == ["营收 ", "1158"]
    assert names.count("delta") == 2 and "answer_reset" not in names
    assert done_of(events)["status"] == "succeeded"
    assert wiring.old_calls == []
    final = [(role, kw) for role, kw in wiring.rows() if role == "assistant"][-1]
    stored = next(args[3] for args, kwargs in wiring.stored if len(args) >= 4 and args[2] == "assistant")
    assert stored == "营收 1158"
    assert final[1]["tool_calls"]["audit"]["engine"] == "v2"


def test_bot_without_engine_runs_the_old_turn(wiring):
    wiring.kernel_must_not_run()
    events = wiring.bot_turn()
    assert done_of(events)["status"] in ("complete", "succeeded")
    assert "First increment" in "".join(d["text"] for n, d in events if n == "delta")
    assert wiring.old_calls


def test_env_default_applies_to_non_bot_turns(wiring):
    wiring.monkeypatch.setenv("FINBOT_KERNEL_DEFAULT", "v2")
    wiring.model([(["好的"], [])])
    events = wiring.catalog_turn()
    assert "".join(d["text"] for n, d in events if n == "delta") == "好的"
    assert wiring.script.count == 1 and wiring.old_calls == []
    for value in ("v3", ""):
        wiring.monkeypatch.setenv("FINBOT_KERNEL_DEFAULT", value)
        wiring.kernel_must_not_run()
        wiring.old_calls.clear()
        assert done_of(wiring.catalog_turn())["status"] in ("complete", "succeeded")
        assert wiring.old_calls


def test_flag_off_forces_the_old_turn(wiring):
    wiring.bot["engine"] = "v2"
    wiring.monkeypatch.setenv("FINBOT_KERNEL_V2", "off")
    wiring.kernel_must_not_run()
    events = wiring.bot_turn()
    assert done_of(events)["status"] in ("complete", "succeeded")
    assert wiring.old_calls


def test_unattended_task_never_uses_the_kernel(wiring):
    from app.agent_workflow.graph import stream_workflow

    wiring.bot["engine"] = "v2"
    wiring.monkeypatch.setenv("FINBOT_KERNEL_DEFAULT", "v2")
    wiring.kernel_must_not_run()

    async def run():
        return [event async for event in stream_workflow(
            question="show AAPL prices", messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "show AAPL prices"}],
            provider="deepseek", model="deepseek-chat", api_key="abcdefgh", base_url=None, owner_hash=str(uuid4()),
            conversation_id=str(uuid4()), turn_id=str(uuid4()), unattended=True, bot=dict(wiring.bot))]

    events = asyncio.run(run())
    assert any(e.get("event") == "done" for e in events)
    assert wiring.old_calls


def tool_then_answer():
    return [(["我查一下"], [call("c1", "query_financials", {"symbol": "AAPL"})]), (["营收 1158 [1]"], [])]


def test_answer_reset_clears_the_stored_answer(wiring):
    wiring.bot["engine"] = "v2"
    wiring.model(tool_then_answer())
    events = wiring.bot_turn()
    names = [name for name, _ in events if name in ("delta", "answer_reset")]
    assert names == ["delta", "answer_reset", "delta"]
    answer = next(args[3] for args, kwargs in wiring.stored if len(args) >= 4 and args[2] == "assistant" and args[3])
    assert "我查一下" not in answer and answer == "营收 1158 [1]"


def test_tool_rows_are_stored(wiring):
    wiring.bot["engine"] = "v2"
    wiring.model(tool_then_answer())
    wiring.bot_turn()
    rows = wiring.rows()
    assert [role for role, _ in rows] == ["user", "assistant", "tool", "assistant"]
    assert rows[1][1]["tool_calls"]["calls"]


def test_old_turn_runs_on_a_conversation_whose_last_turn_was_the_kernel(wiring):
    """The rollback case: engine switched off after kernel turns; the checkpointed state must still be readable."""
    wiring.bot["engine"] = "v2"
    wiring.model([(["好的"], [])])
    assert done_of(wiring.bot_turn())["status"] == "succeeded"
    wiring.bot["engine"] = None
    wiring.kernel_must_not_run()
    events = wiring.bot_turn()
    assert wiring.old_calls
    assert done_of(events)["status"] in ("complete", "succeeded")
    assert not any(name == "error" for name, _ in events)


def test_engine_validation():
    from app import agent_bots as bots

    bot = AgentBot(name="b", title="", description="", focus={}, avatar="", group_name="", pinned=False, hidden=False,
                   is_default=False, template="", daily_notify_cap=0)
    bots._apply(bot, {"engine": "v2"})
    assert bots.serialize(bot)["engine"] == "v2"
    bots._apply(bot, {"engine": None})
    assert bots.serialize(bot)["engine"] is None
    with pytest.raises(bots.BotError):
        bots._apply(bot, {"engine": "v9"})


def test_bridges_drop_text_before_a_reset():
    from scripts import run_telegram_bridge, run_wechat_bridge

    def frame(name, data):
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    sequence = [("delta", {"text": "我查一下"}), ("answer_reset", {}), ("delta", {"text": "营收 1158"})]
    assert run_telegram_bridge.format_turn(sequence)[0] == "营收 1158"
    raw = "".join(frame(name, data) for name, data in sequence)
    assert run_wechat_bridge.parse_turn(raw)[0] == "营收 1158"


def say_and_plan_turn():
    plan = [{"text": "查财报", "status": "doing"}, {"text": "写结论", "status": "pending"}]
    return [([], [call("c1", "query_financials", {"say": "先看财报", "symbol": "AAPL"}), call("c2", "plan", {"items": plan}),
                  call("c3", "escalate", {"depth": "high"})]),
            (["营收 1158 [1]"], [])], plan


def test_narration_and_checklist_frames_reach_the_client_and_the_stored_row(wiring):
    wiring.bot["engine"] = "v2"
    steps, plan = say_and_plan_turn()
    wiring.model(steps)
    events = wiring.bot_turn()
    assert [d for n, d in events if n == "narration"] == [{"text": "先看财报"}]
    closed = [{"text": "查财报", "status": "done"}, {"text": "写结论", "status": "done"}]
    assert [d for n, d in events if n == "checklist"] == [{"items": plan}, {"items": closed}]   # shown, then closed with the answer
    names = [n for n, _ in events]
    assert names.index("narration") < names.index("tool_start") and not any(n == "error" for n in names)
    assert "".join(d["text"] for n, d in events if n == "delta") == "营收 1158 [1]"
    final = [kw for role, kw in wiring.rows() if role == "assistant"][-1]["tool_calls"]
    assert final["narration"] == ["先看财报"] and final["checklist"] == closed and final["tier"] == "high"
    assert wiring.executed == [("query_financials", {"symbol": "AAPL"})]


def reload_rows(wiring):
    """The turn as the store would hand it back to the history endpoint."""
    rows = []
    for args, kwargs in wiring.stored:
        if len(args) >= 4 and args[2] in ("user", "assistant", "tool"):
            rows.append({"role": args[2], "content": args[3], "status": kwargs.get("status", "complete"), "turn_id": args[1],
                         "tool_calls": kwargs.get("tool_calls"), "tool_call_id": kwargs.get("tool_call_id")})
    return rows


def reload_history(wiring, rows):
    async def page(*_args, **_kwargs):
        return {"messages": rows, "has_more": False, "next_before": None}

    wiring.monkeypatch.setattr(wiring.stream, "owned_message_page", page)
    return asyncio.run(wiring.stream.get_messages("conversation", before=None, limit=20, x_chat_session="s" * 40))["messages"]


def test_history_reload_returns_narration_checklist_and_tier(wiring):
    closed = [{"text": "查财报", "status": "done"}, {"text": "写结论", "status": "done"}]
    wiring.bot["engine"] = "v2"
    steps, plan = say_and_plan_turn()
    wiring.model(steps)
    wiring.bot_turn()
    rows = reload_rows(wiring)
    assistant = [m for m in reload_history(wiring, rows) if m["role"] == "assistant"][-1]
    assert assistant["narration"] == ["先看财报"] and assistant["checklist"] == closed and assistant["tier"] == "high"
    # The kernel's own tools are in the rebuilt trace next to the catalog's, and nothing broke on their names.
    assert {t["name"] for t in assistant["tool_trace"]} == {"query_financials", "plan", "escalate"}
    assert all(t["status"] == "complete" for t in assistant["tool_trace"])
    # A row an older turn stored has none of the three and is returned without them.
    old = [dict(row, tool_calls={"audit": {"terminal_status": "succeeded"}}) if row["role"] == "assistant" and row["content"] else row
           for row in rows if row["role"] in ("user", "assistant") and not (row["tool_calls"] or {}).get("calls")]
    shown = [m for m in reload_history(wiring, old) if m["role"] == "assistant"][-1]
    assert not {"narration", "checklist", "tier"} & set(shown) and shown["content"] == "营收 1158 [1]"
