"""The kernel behind the endpoint: what the client and the store see of a kernel turn.

The endpoint is the real ``stream.stream_chat`` with in-memory stand-ins (the ``stream_fixture`` of
test_agent_chat_stream); the kernel's model is a scripted ``stream_decision``.  Since stage 6b every turn is the kernel's.
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
        from app.agent_workflow import tools

        self.send_old, _, _, self.executed, self.stored, _, _ = stream_fixture
        self.monkeypatch = monkeypatch
        self.stream = stream
        self.script = None

        async def invoke(name, args, context, *, emit=None, page_chars=None):
            self.executed.append((name, args))
            return {"ok": True, "data": [dict(ROW)], "source": "saved"}

        monkeypatch.setattr(tools, "invoke", invoke)
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

    async def _send(self, message="show AAPL prices", **fields):
        payload = StreamRequest(message=message, **fields)
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await self.stream.stream_chat(payload, request, "x" * 40)
        return frames("".join([part async for part in response.body_iterator]))

    def bot_turn(self, message="show AAPL prices", **fields):
        return asyncio.run(self._send(message, bot_id=self.bot["bot_id"], **fields))

    def catalog_turn(self):
        return asyncio.run(self._send(catalog_model=""))

    def rows(self):
        return [(args[2], kwargs) for args, kwargs in self.stored if len(args) >= 3 and args[2] in ("user", "assistant", "tool")]


@pytest.fixture
def wiring(stream_fixture, monkeypatch):  # noqa: F811
    return Wiring(stream_fixture, monkeypatch)


def stored_engine(wiring):
    """The engine the last stored answer's audit names."""
    return [kw for role, kw in wiring.rows() if role == "assistant"][-1]["tool_calls"]["audit"]["engine"]


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
    final = [(role, kw) for role, kw in wiring.rows() if role == "assistant"][-1]
    stored = next(args[3] for args, kwargs in wiring.stored if len(args) >= 4 and args[2] == "assistant")
    assert stored == "营收 1158"
    assert final[1]["tool_calls"]["audit"]["engine"] == "v2"


def test_bot_without_engine_runs_the_kernel(wiring):
    """A bot that names no engine (a newly made one) runs the kernel: since 6b every turn does."""
    wiring.model([(["好的"], [])])
    events = wiring.bot_turn()
    assert done_of(events)["status"] == "succeeded"
    assert stored_engine(wiring) == "v2"


def test_a_turn_without_a_bot_runs_the_kernel_whatever_the_old_switches_say(wiring):
    """The old turn's switches (``FINBOT_KERNEL_DEFAULT``, ``FINBOT_KERNEL_V2``) went with it in 6b: they change nothing."""
    for name, value in ((None, None), ("FINBOT_KERNEL_DEFAULT", "v1"), ("FINBOT_KERNEL_V2", "off")):
        if name:
            wiring.monkeypatch.setenv(name, value)
        wiring.model([(["好的"], [])])
        events = wiring.catalog_turn()
        assert "".join(d["text"] for n, d in events if n == "delta") == "好的"
        assert wiring.script.count == 1 and stored_engine(wiring) == "v2"


def _unattended_events(wiring):
    from app.agent_workflow.graph import stream_workflow

    async def run():
        return [event async for event in stream_workflow(
            question="show AAPL prices", messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "show AAPL prices"}],
            provider="deepseek", model="deepseek-chat", api_key="abcdefgh", base_url=None, owner_hash=str(uuid4()),
            conversation_id=str(uuid4()), turn_id=str(uuid4()), unattended=True, bot=dict(wiring.bot))]

    return asyncio.run(run())


def test_an_unattended_task_runs_the_kernel(wiring):
    wiring.bot["engine"] = "v1"      # an engine a bot may still carry from before 6b: not read any more
    wiring.monkeypatch.setenv("FINBOT_KERNEL_ROUTINES", "off")
    wiring.model([(["无新消息"], [])])
    events = _unattended_events(wiring)
    assert next(e for e in events if e.get("event") == "done")["audit"]["engine"] == "v2"


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


def test_kernel_own_tools_are_not_stored_as_tool_traces(wiring):
    wiring.bot["engine"] = "v2"
    steps, _ = say_and_plan_turn()
    wiring.model(steps)
    events = wiring.bot_turn()
    assert [d["name"] for n, d in events if n == "tool_result"] == ["query_financials", "plan", "escalate"]   # still forwarded
    final = [kw for role, kw in wiring.rows() if role == "assistant"][-1]["tool_calls"]
    assert [t["name"] for t in final["tool_trace"]] == ["query_financials"]


def test_engine_validation():
    from app import agent_bots as bots

    bot = AgentBot(name="b", title="", description="", focus={}, avatar="", group_name="", pinned=False, hidden=False,
                   is_default=False, template="", daily_notify_cap=0)
    bots._apply(bot, {"engine": "v2"})
    assert bots.serialize(bot)["engine"] == "v2"
    bots._apply(bot, {"engine": "v1"})
    assert bots.serialize(bot)["engine"] == "v1"
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
    # The kernel's own tools are not lookups: the rebuilt trace lists only the catalog's.
    assert {t["name"] for t in assistant["tool_trace"]} == {"query_financials"}
    assert all(t["status"] == "complete" for t in assistant["tool_trace"])
    # A row an older turn stored has none of the three and is returned without them.
    old = [dict(row, tool_calls={"audit": {"terminal_status": "succeeded"}}) if row["role"] == "assistant" and row["content"] else row
           for row in rows if row["role"] in ("user", "assistant") and not (row["tool_calls"] or {}).get("calls")]
    shown = [m for m in reload_history(wiring, old) if m["role"] == "assistant"][-1]
    assert not {"narration", "checklist", "tier"} & set(shown) and shown["content"] == "营收 1158 [1]"


PROGRESS = [{"event": "narration", "text": "先看财报"}, {"event": "narration", "text": "再比同行", "item": 1},
            {"event": "checklist", "items": [{"text": "查财报", "status": "doing"}]},
            {"event": "tier", "tier": "mid"},
            {"event": "checklist", "items": [{"text": "查财报", "status": "done"}]},
            {"event": "tier", "tier": "high"}]
KEPT = {"narration": ["先看财报", "再比同行"], "checklist": [{"text": "查财报", "status": "done"}], "tier": "high"}


class Unfinished(Exception):
    pass


def unfinished_turn(wiring, events, ending):
    """Run a turn whose engine says ``events`` and then ``ending`` ('cancel' or 'fail'); returns the frames seen."""

    async def fake_engine(**kwargs):
        for event in events:
            yield event
        if ending == "fail":
            raise Unfinished("the engine broke")
        await asyncio.sleep(3600)

    wiring.monkeypatch.setattr(wiring.stream, "stream_workflow", fake_engine)

    async def run():
        payload = StreamRequest(message="show AAPL prices", bot_id=wiring.bot["bot_id"])
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await wiring.stream.stream_chat(payload, request, "x" * 40)
        seen = []

        async def drain():
            async for part in response.body_iterator:
                seen.append(part)

        task = asyncio.ensure_future(drain())
        if ending == "cancel":
            for _ in range(300):  # at most 3 s for the frame of every event to arrive
                if "".join(seen).count("event: ") > len(events) or task.done():
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.gather(*list(wiring.stream._BACKGROUND), return_exceptions=True)
        return frames("".join(part for part in seen if part.startswith("event: ")))

    return asyncio.run(run())


def last_assistant(wiring):
    return [kw for role, kw in wiring.rows() if role == "assistant"][-1]


def test_tier_frame_is_forwarded(wiring):
    wiring.bot["engine"] = "v2"
    steps, _ = say_and_plan_turn()
    wiring.model(steps)
    events = wiring.bot_turn()
    assert [d for n, d in events if n == "tier"] == [{"tier": "high"}]


def test_cancelled_turn_keeps_its_progress(wiring):
    wiring.bot["engine"] = "v2"
    unfinished_turn(wiring, PROGRESS, "cancel")
    row = last_assistant(wiring)
    assert row["status"] == "cancelled" and {k: row["tool_calls"][k] for k in KEPT} == KEPT
    shown = [m for m in reload_history(wiring, reload_rows(wiring)) if m["role"] == "assistant"][-1]
    assert {k: shown[k] for k in KEPT} == KEPT


def test_failed_turn_keeps_its_progress(wiring):
    wiring.bot["engine"] = "v2"
    events = unfinished_turn(wiring, PROGRESS, "fail")
    row = last_assistant(wiring)
    assert row["status"] == "failed" and {k: row["tool_calls"][k] for k in KEPT} == KEPT
    assert [d for n, d in events if n == "tier"] == [{"tier": "mid"}, {"tier": "high"}]
    shown = [m for m in reload_history(wiring, reload_rows(wiring)) if m["role"] == "assistant"][-1]
    assert {k: shown[k] for k in KEPT} == KEPT


def test_hanging_up_at_the_done_frame_does_not_store_a_cancelled_copy(wiring):
    """The ruler's client closes the stream as soon as it reads ``done``; the stored answer must stay the only one."""
    wiring.bot["engine"] = "v2"
    done = {"event": "done", "answer": "收入是 100。", "status": "succeeded", "citations": [], "audit": {"engine": "v2"},
            "final_protocol": {"tier": "low", "narration": [], "checklist": []}}
    unfinished_turn(wiring, [{"event": "delta", "text": "收入是 100。"}, done], "cancel")
    answers = [kw for role, kw in wiring.rows() if role == "assistant"]
    assert [row["status"] for row in answers] == ["complete"]


def test_a_proposed_card_reaches_the_client_and_the_stored_row(wiring):
    from app.agent_workflow import consent

    from app.kernel import act, loop, prompt

    wiring.bot["engine"] = "v2"
    for module in (act, loop, prompt):       # this stand-in turn's credential is the owner's
        wiring.monkeypatch.setattr(module, "owner_credential_matches", lambda value: True)
    proposed = []

    def propose(credential, conversation, operations, display, *, question="", variants=None):
        proposed.append((operations, display, question))
        return {"id": "card-1", "reason": "write_confirmation", "display": display, "question": question,
                "choices": [{"label": "同意", "value": "confirm:" + "T" * 43}, {"label": "取消", "value": "cancel:card-1"}]}

    wiring.monkeypatch.setattr(consent, "propose", propose)
    wiring.monkeypatch.setattr(consent, "execute", lambda *a, **k: pytest.fail("a card must not execute by itself"))
    wiring.model([([], [call("c1", "act", {"operation": "forecast", "arguments": {"symbol": "AAPL"}})]), (["我准备生成 AAPL 的预测，请核对卡片"], [])])
    events = wiring.bot_turn()
    names = [name for name, _ in events]
    assert names.index("clarification") < names.index("done")
    card = next(data for name, data in events if name == "clarification")
    assert card["request_id"] == "card-1" and card["reason"] == "write_confirmation" and card["display"]["title"] == "生成研究预测"
    assert done_of(events)["status"] == "waiting_for_input"
    assert [d["name"] for n, d in events if n == "tool_result"] == ["act"]
    final = [kw for role, kw in wiring.rows() if role == "assistant"][-1]["tool_calls"]
    assert final["clarification"]["request_id"] == "card-1" and final["clarification"]["display"]["title"] == "生成研究预测"
    assert [t["name"] for t in final["tool_trace"]] == ["act"]          # a write stays visible in the record
    stored = next(args[3] for args, kwargs in wiring.stored if len(args) >= 4 and args[2] == "assistant" and args[3])
    assert stored == "我准备生成 AAPL 的预测，请核对卡片" and "T" * 43 not in json.dumps(final["audit"], default=str)
    assert proposed[0][0][0]["name"] == "forecast" and proposed[0][2] == "show AAPL prices"


def test_propose_in_one_request_press_in_the_next(wiring):
    """The card survives in the graph's own state between two requests; the press executes it and the turn carries on."""
    import copy

    from app.agent_workflow import consent, tools
    from app.kernel import act, loop, prompt

    wiring.bot["engine"] = "v2"
    for module in (act, loop, prompt):
        wiring.monkeypatch.setattr(module, "owner_credential_matches", lambda value: True)
    token, saved, executed, models = "T" * 43, {}, [], []

    def propose(credential, conversation, operations, display, *, question="", variants=None):
        saved["card-1"] = {"id": "card-1", "operations": copy.deepcopy(operations), "display": display, "status": "proposed"}
        return {"id": "card-1", "reason": "write_confirmation", "display": display, "original_question": question,
                "choices": [{"label": "同意", "value": "confirm:" + token}, {"label": "取消", "value": "cancel:card-1"}]}

    def execute(credential, conversation, tok, operations, handler):
        assert tok == token and operations == saved["card-1"]["operations"]
        outcomes = [handler(op, "card-1.0") for op in operations]
        saved["card-1"]["status"] = "complete"
        return {"ok": True, "data": outcomes, "status": "complete"}

    wiring.monkeypatch.setattr(consent, "propose", propose)
    wiring.monkeypatch.setattr(consent, "execute", execute)
    wiring.monkeypatch.setattr(consent, "lookup", lambda credential, conversation, request_id: copy.deepcopy(saved[request_id]))
    wiring.monkeypatch.setattr(tools, "execute_costly", lambda operation, key, context: executed.append(operation["name"]) or {"ok": True, "status": "queued", "job_id": "j1"})
    wiring.model([([], [call("c1", "act", {"operation": "forecast", "arguments": {"symbol": "AAPL"}})]), (["请核对卡片"], [])])
    first = wiring.bot_turn()
    assert done_of(first)["status"] == "waiting_for_input" and executed == []

    wiring.model([(["预测已提交"], [])])
    inner, sent = wiring.script, []

    async def spy(provider_name, model, api_key, messages, schemas, **kwargs):
        sent.append(json.dumps(messages, ensure_ascii=False))
        return await inner(provider_name, model, api_key, messages, schemas, **kwargs)

    wiring.monkeypatch.setattr(provider, "stream_decision", spy)
    second = wiring.bot_turn("confirm:" + token, pending_request_id="card-1", display_message="同意")
    assert executed == ["forecast"]
    assert [d["text"] for n, d in second if n == "delta"] == ["预测已提交"]
    assert done_of(second)["status"] == "succeeded" and not any(n == "clarification" for n, _ in second)
    assert len(sent) == 1 and "confirm:" not in sent[0] and token not in sent[0] and "系统事实：用户在一张确认卡上点了按钮" in sent[0]
    user_rows = [args[3] for args, kwargs in wiring.stored if len(args) >= 4 and args[2] == "user"]
    assert user_rows == ["show AAPL prices", "同意"]            # what the endpoint stores for a press today: the button's label


def record_context_calls(wiring):
    seen = []

    async def recorded(*args, **kwargs):
        seen.append(kwargs.get("anchored"))
        return {"l1_rows": []}

    wiring.monkeypatch.setattr(wiring.stream, "conversation_context", recorded)
    return seen


def test_a_kernel_turn_asks_for_the_anchored_history(wiring):
    wiring.bot["engine"] = "v2"
    wiring.model([(["好"], [])])
    seen = record_context_calls(wiring)
    wiring.bot_turn()
    assert seen == [True]


def test_a_turn_without_a_bot_asks_for_the_anchored_history_too(wiring):
    wiring.model([(["好"], [])])
    seen = record_context_calls(wiring)
    wiring.catalog_turn()
    assert seen == [True]


# --- 5d-1: the figure check after a kernel answer ------------------------------------------------------------------

def reconcile_spy(wiring, hold=None):
    """The background job replaced by a recorder; with ``hold`` (a threading.Event) it waits for it before it finishes."""
    import threading
    from app.kernel import reconcile

    calls, finished = [], threading.Event()

    def job(message_id):
        calls.append(message_id)
        if hold is not None:
            hold.wait(5)
        finished.set()

    wiring.monkeypatch.setattr(reconcile, "check_and_store", job)
    return calls, finished


async def settle(stream):
    """Wait for this loop's background tasks (the check among them)."""
    loop = asyncio.get_running_loop()
    for task in [t for t in list(stream._BACKGROUND) if t.get_loop() is loop]:
        await asyncio.gather(task, return_exceptions=True)


def checked_turn(wiring, message="show AAPL prices"):
    async def scenario():
        events = await wiring._send(message, bot_id=wiring.bot["bot_id"])
        await settle(wiring.stream)
        return events
    return asyncio.run(scenario())


def final_answer(wiring):
    return [kw for args, kw in wiring.stored if len(args) >= 4 and args[2] == "assistant" and args[3]][-1]


def test_a_kernel_answer_schedules_the_check_and_the_done_frame_does_not_wait_for_it(wiring):
    import threading

    wiring.bot["engine"] = "v2"
    wiring.model([(["利润 8888 美元"], [])])
    wiring.monkeypatch.setattr(wiring.stream, "_reconcile_wanted", lambda credential: True)
    hold = threading.Event()
    calls, finished = reconcile_spy(wiring, hold)

    async def scenario():
        events = await wiring._send("show AAPL prices", bot_id=wiring.bot["bot_id"])
        assert done_of(events)["status"] == "succeeded"
        assert not finished.is_set(), "the response ended only after the check: it waited for it"
        hold.set()
        await settle(wiring.stream)
        return events

    events = asyncio.run(scenario())
    assert finished.is_set()
    stored = final_answer(wiring)
    assert stored["status"] == "complete" and calls == [stored["message_id"]], "the check is of the stored answer, by the id it was stored under"
    assert "reconcil" not in json.dumps(events, ensure_ascii=False), "nothing of it goes to the stream"


def test_the_switch_off_schedules_nothing(wiring):
    from app.agent_workflow.fp_flags import flag

    wiring.bot["engine"] = "v2"
    wiring.model([(["利润 8888 美元"], [])])
    wiring.monkeypatch.setattr(wiring.stream, "_reconcile_wanted", lambda credential: flag("FINBOT_KERNEL_RECONCILE", True))
    wiring.monkeypatch.setenv("FINBOT_KERNEL_RECONCILE", "off")
    calls, _ = reconcile_spy(wiring)
    assert done_of(checked_turn(wiring))["status"] == "succeeded"
    assert calls == []


def test_only_the_owners_answers_are_checked_and_only_with_the_switch_on(wiring):
    stream = wiring.stream
    wiring.monkeypatch.setattr(stream, "_is_owner", lambda credential: credential == "owner")
    wiring.monkeypatch.delenv("FINBOT_KERNEL_RECONCILE", raising=False)
    assert stream._reconcile_wanted("owner") is True, "on by default"
    assert stream._reconcile_wanted("guest") is False
    wiring.monkeypatch.setenv("FINBOT_KERNEL_RECONCILE", "off")
    assert stream._reconcile_wanted("owner") is False
