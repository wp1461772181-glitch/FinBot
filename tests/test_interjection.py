"""3c Task 1: the owner speaks while a kernel turn works.

Loop level (no network, no database): the inbox is read at the end of a step and between answer deltas, ``handle_message`` records the
decision, a stop ends the turn without a card.  Endpoint level: the real ``stream_chat`` with the stream fixture's in-memory stand-ins and
a scripted model, several requests at once.  The work table (the concurrency slots, the queue, the restart sweep) lives in the test database.

Review Focus: 1 merge, 2 stop while writing, 3 a separate turn beside the running one, 4 the fourth piece of work waits, 5 two messages at once.
"""
import asyncio
import copy
import json
import re
import uuid
from runpy import run_path

import pytest
from sqlalchemy import select
from starlette.requests import Request

import app.agent_chat_provider as provider
import app.agent_chat_stream as stream
from app import work
from app.agent_chat_models import AgentConversation, AgentMessage
from app.agent_chat_stream import StreamRequest
from app.agent_workflow import consent, tools
from app.database import SessionLocal, engine
from app.kernel import inbox as inboxes
from app.kernel import loop
from tests.test_agent_chat_stream import stream_fixture  # noqa: F401  (fixture)
from tests.test_kernel_loop import FakeConsent, act_call, call, env, fake_consent, make_context  # noqa: F401  (fixtures by name)
from tests.test_kernel_wiring import Wiring

CRED = "x" * 40


def _new_id():
    return str(uuid.uuid4())


def _arrive(box, text):
    """The endpoint's part: a message put in the inbox (the loop reads it at the end of its step)."""
    message = inboxes.Message(id=_new_id(), text=text, turn_id=_new_id(), future=asyncio.get_running_loop().create_future())
    assert box.put(message)
    return message


def _handle(call_id, message, decision, note=None):
    arguments = {"message_id": message.id[:8], "decision": decision, **({"note": note} if note else {})}
    return call(call_id, inboxes.HANDLE, arguments)


class Model:
    """A scripted ``stream_decision``.  A step is ``{"pieces": [str | callable], "calls": [...]}``: a callable piece is run between two
    pieces of text (it is where a message arrives while the answer is written), a piece is streamed through ``on_text``."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    async def __call__(self, provider_name, model, api_key, messages, schemas, **kwargs):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": [s["function"]["name"] for s in schemas]})
        item = self.steps.pop(0)
        item = item(messages) if callable(item) else item
        text = ""
        for piece in item.get("pieces", []):
            if callable(piece):
                piece()
            else:
                text += piece
                await kwargs["on_text"](piece)
        message = {"role": "assistant", "content": item.get("text", text)}
        if item.get("calls"):
            message["tool_calls"] = item["calls"]
        return {"usage": {"total_tokens": 10}}, message


def _run_loop(env, steps, *, own="own-1", context=None, invoke=None, setup=None):
    """One kernel turn with an inbox.  ``setup(box)`` runs inside the loop before the turn starts (it may schedule arrivals)."""
    model = Model(steps)
    env.monkeypatch.setattr(provider, "stream_decision", model)
    if invoke is not None:
        env.monkeypatch.setattr(tools, "invoke", invoke)
    events = []

    async def emit(event):
        events.append(event)

    async def scenario():
        box = inboxes.Inbox("turn-a", own_message_id=own)
        if setup:
            setup(box)
        ctx = context or make_context(conversation_id="conv")
        ctx.inbox = box
        history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "NVDA 的营收"}]
        result = await loop.run_turn("NVDA 的营收", ctx, emit, history, {})
        return result, box

    result, box = asyncio.run(scenario())
    return result, box, events, model


ROW = {"id": "r1", "symbol": "NVDA", "source_type": "official_filing", "excerpt": "Revenue was 100 (USD billions)."}


# ---- Review Focus 1: 「顺便把 AMD 也比一下」 while NVDA is being fetched ----

def test_a_merged_message_is_answered_in_the_same_turn_with_what_was_already_found(env):
    arrived = []

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        if not arrived:      # NVDA is being fetched when the owner speaks
            arrived.append(_arrive(box_of[0], "顺便把 AMD 也比一下"))
        env.invoked.append((name, args))
        return {"ok": True, "data": [{**ROW, "id": f"r-{args['symbol']}", "symbol": args["symbol"]}], "source": "saved"}

    box_of = []
    seen = []

    def merge_and_fetch(messages):
        seen.append(messages)
        return {"calls": [_handle("h1", arrived[0], "merge"), call("c2", "query_financials", {"symbol": "AMD"})]}

    result, box, events, model = _run_loop(
        env, [{"calls": [call("c1", "query_financials", {"symbol": "NVDA"})]}, merge_and_fetch, {"pieces": ["NVDA 与 AMD 对比 [1][2]"]}],
        invoke=invoke, setup=lambda b: box_of.append(b))
    second = model.calls[1]["messages"]
    # his words are the user's own, after the work so far; the system adds one note after them
    assert [m["role"] for m in second[-3:]] == ["tool", "user", "system"]
    assert second[-2]["content"] == "顺便把 AMD 也比一下"
    assert arrived[0].id[:8] in second[-1]["content"] and "handle_message" in second[-1]["content"]
    assert [name for name, _ in env.invoked] == ["query_financials", "query_financials"]
    assert [args["symbol"] for _, args in env.invoked] == ["NVDA", "AMD"]       # the AMD numbers were fetched in the same turn
    assert result["answer"] == "NVDA 与 AMD 对比 [1][2]" and result["status"] == "succeeded"
    assert len(result["citations"]) == 2                                          # what NVDA found is kept, AMD's is added
    assert result["final_protocol"]["reply_to"] == ["own-1", arrived[0].id]
    assert arrived[0].future.result() == inboxes.Outcome("merge", "turn-a", False)
    assert result["audit"]["interjections"] == [{"message_id": arrived[0].id, "decision": "merge", "defaulted": False}]
    # the history before the interjection is byte-for-byte what the first call had (the prompt cache)
    first, last = model.calls[0]["messages"], model.calls[2]["messages"]
    assert last[:len(first)] == first
    assert all(inboxes.HANDLE in c["tools"] for c in model.calls)


def test_the_tool_is_offered_only_to_a_turn_that_has_an_inbox(env):
    from app.kernel.loop import _tool_schemas
    assert inboxes.HANDLE not in [s["function"]["name"] for s in _tool_schemas(make_context())]
    with_box = make_context()
    with_box.inbox = inboxes.Inbox("t")
    names = [s["function"]["name"] for s in _tool_schemas(with_box)]
    assert names[-1] == inboxes.HANDLE      # the kernel's own tools go last


# ---- Review Focus 2: 「算了不用了」 while writing ----

def test_a_stop_while_writing_cuts_the_text_within_a_delta_and_ends_the_turn_with_one_sentence(env, fake_consent):
    holder = []

    def speak():
        holder.append(_arrive(box_of[0], "算了不用了"))

    box_of = []
    result, box, events, model = _run_loop(
        env,
        [{"calls": [act_call("p1", "forecast", {"symbol": "NVDA"})]},       # a tier-2 proposal: it would become a card at the end
         {"pieces": ["NVDA 的营收", speak, "是 100", "亿美元"]},
         lambda messages: {"calls": [_handle("h1", holder[0], "stop", "好的，不做了。")]}],
        context=make_context(conversation_id="conv"), setup=lambda b: box_of.append(b))
    deltas = [e["text"] for e in events if e["event"] == "delta"]
    assert deltas[:2] == ["NVDA 的营收", "是 100"]                       # the piece after the message was the last one written
    kinds = [e["event"] for e in events]
    assert kinds.index("answer_paused") == kinds.index("delta", kinds.index("delta") + 1) + 1
    # the model's next step saw its own half-written text, then his words, then the note
    third = model.calls[2]["messages"]
    assert [m["role"] for m in third[-3:]] == ["assistant", "user", "system"]
    assert third[-3]["content"] == "NVDA 的营收是 100" and third[-2]["content"] == "算了不用了"
    assert "写到一半" in third[-1]["content"]
    assert result["status"] == "stopped"
    assert result["answer"] == "NVDA 的营收是 100\n\n好的，不做了。"
    assert kinds[-3:] == ["answer_reset", "delta", "stopped"] and events[-2]["text"] == result["answer"]
    assert fake_consent.proposed == [] and result["pending_request"] is None     # nothing it proposed becomes a card
    assert holder[0].future.result().decision == "stop"
    assert result["final_protocol"]["reply_to"] == ["own-1"]


def test_a_stop_cancels_whatever_else_the_step_asked_for(env, fake_consent):
    holder = []
    box_of = []
    result, box, events, model = _run_loop(
        env,
        [{"pieces": ["先查", lambda: holder.append(_arrive(box_of[0], "停")), "一下"]},
         lambda messages: {"calls": [_handle("h1", holder[0], "stop"), call("c1", "query_financials", {"symbol": "NVDA"}),
                                     act_call("c2", "add_to_research_queue", {"symbol": "NVDA"})]}],
        setup=lambda b: box_of.append(b))
    assert env.invoked == [] and fake_consent.proposed == [] and fake_consent.executed == []     # nothing in that step ran
    assert result["status"] == "stopped" and result["answer"].endswith(inboxes.DEFAULT_STOP_SENTENCE)
    done = [e for e in events if e["event"] == "tool_result" and e["name"] == "query_financials"]
    assert done[0]["result"]["error_code"] == "turn_stopped"


# ---- Review Focus 5: two messages before the step ends ----

def test_two_messages_in_a_row_both_get_a_decision_in_the_order_they_came(env):
    box_of, made = [], []

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        if not made:
            made.extend([_arrive(box_of[0], "也看看 AMD"), _arrive(box_of[0], "记一下我买了 TSLA")])
        env.invoked.append((name, args))
        return {"ok": True, "data": [dict(ROW)], "source": "saved"}

    result, box, events, model = _run_loop(
        env,
        [{"calls": [call("c1", "query_financials", {"symbol": "NVDA"})]},
         lambda messages: {"calls": [_handle("h2", made[1], "separate"), _handle("h1", made[0], "merge")]},   # decided out of order
         {"pieces": ["好"]}],
        invoke=invoke, setup=lambda b: box_of.append(b))
    second = model.calls[1]["messages"]
    assert [m["role"] for m in second[-4:]] == ["tool", "user", "user", "system"]
    assert [m["content"] for m in second[-3:-1]] == ["也看看 AMD", "记一下我买了 TSLA"]
    assert second[-1]["content"].count(made[0].id[:8]) == 1 and second[-1]["content"].index(made[0].id[:8]) < second[-1]["content"].index(made[1].id[:8])
    assert made[0].future.result().decision == "merge" and made[1].future.result().decision == "separate"
    assert result["final_protocol"]["reply_to"] == ["own-1", made[0].id]     # only the merged one is answered here
    assert [r["message_id"] for r in result["audit"]["interjections"]] == [made[0].id, made[1].id]      # arrival order


def test_a_message_nobody_decided_is_its_own_turn_and_says_so(env):
    box_of, made = [], []

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        if not made:
            made.append(_arrive(box_of[0], "另外查一下 AMD"))
        return {"ok": True, "data": [dict(ROW)], "source": "saved"}

    result, box, events, model = _run_loop(
        env, [{"calls": [call("c1", "query_financials", {"symbol": "NVDA"})]}, {"pieces": ["NVDA 的营收是 100"]}],
        invoke=invoke, setup=lambda b: box_of.append(b))
    assert made[0].future.result() == inboxes.Outcome("separate", "turn-a", True)
    assert result["audit"]["interjections"] == [{"message_id": made[0].id, "decision": "separate", "defaulted": True}]
    assert result["final_protocol"]["reply_to"] == ["own-1"] and result["answer"] == "NVDA 的营收是 100"
    assert box.closed


def test_a_message_that_comes_after_the_answer_is_written_is_not_swallowed(env):
    box_of, made = [], []
    result, box, events, model = _run_loop(
        env, [{"pieces": ["好的", lambda: made.append(_arrive(box_of[0], "等一下"))]},       # arrives after the last piece
              lambda messages: {"calls": [_handle("h1", made[0], "separate")]}, {"pieces": ["收到，先答第一件。"]}],
        setup=lambda b: box_of.append(b))
    assert made[0].future.result().decision == "separate" and not made[0].future.result().defaulted
    assert result["answer"] == "收到，先答第一件。"


def test_a_bad_decision_is_refused_and_the_first_one_stands(env):
    box_of, made = [], []
    results = []

    def decide(messages):
        return {"calls": [call("x1", inboxes.HANDLE, {"message_id": "zzzzzzzz", "decision": "merge"}),
                          call("x2", inboxes.HANDLE, {"message_id": made[0].id[:8], "decision": "later"}),
                          _handle("x3", made[0], "merge"), _handle("x4", made[0], "stop")]}

    async def invoke(name, args, context, *, emit=None, page_chars=None):
        if not made:
            made.append(_arrive(box_of[0], "补充"))
        return {"ok": True, "data": [dict(ROW)], "source": "saved"}

    result, box, events, model = _run_loop(
        env, [{"calls": [call("c1", "query_financials", {"symbol": "NVDA"})]}, decide, {"pieces": ["好"]}],
        invoke=invoke, setup=lambda b: box_of.append(b))
    answers = {e["call_id"]: e["result"] for e in events if e["event"] == "tool_result" and e["name"] == inboxes.HANDLE}
    assert answers["x1"]["ok"] is False and answers["x2"]["ok"] is False
    assert answers["x3"]["ok"] is True and answers["x4"]["error_code"] == "already_decided"
    assert made[0].future.result().decision == "merge" and not box.stopping


# ---- the endpoint: the real stream_chat, a scripted model, several requests at once ----

@pytest.fixture(autouse=True)
def work_table():
    import app.agent_tasks  # noqa: F401  (registers its tables)
    from app.database import Base
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name.startswith("agent_") or t.name == "archive_subjects"])
    run_path("scripts/migrate_agent_actions.py")["apply"]()
    with SessionLocal() as db:
        db.query(work.AgentWork).delete()
        db.commit()
    stream.inboxes.ACTIVE.clear()
    yield


def blocks(wire):
    return [(b.splitlines()[0][7:], json.loads(b.splitlines()[1][6:])) for b in wire.strip().split("\n\n") if b.startswith("event: ")]


def names(wire):
    return [name for name, _ in blocks(wire)]


class Lab:
    """The endpoint with a scripted kernel model.  ``bot`` turns share one conversation (the bot's own line)."""

    def __init__(self, stream_fixture, monkeypatch):
        self.w = Wiring(stream_fixture, monkeypatch)
        self.w.bot["engine"] = "v2"
        self.monkeypatch = monkeypatch
        self.stored = stream_fixture[4]
        self.cid = self.w.bot["conversation_id"]
        self.counter = 0
        self.moved = []
        self.contexts = []
        monkeypatch.setattr(stream, "QUEUE_POLL_SECONDS", 0.02)
        monkeypatch.setenv("FINBOT_KERNEL_DEFAULT", "v2")
        lab = self

        async def append(*args, **kwargs):
            lab.stored.append((args, kwargs))
            lab.counter += 1
            return lab.counter
        monkeypatch.setattr(stream, "append_message", append)

        async def move(cid, message_id, turn):
            lab.moved.append((message_id, turn))
            return True
        monkeypatch.setattr(stream, "move_message", move)
        real_context = stream.conversation_context

        async def context(*args, **kwargs):
            lab.contexts.append(kwargs)
            return await real_context(*args, **kwargs)
        monkeypatch.setattr(stream, "conversation_context", context)
        for module in (loop, __import__("app.kernel.prompt", fromlist=["x"]), __import__("app.kernel.act", fromlist=["x"])):
            monkeypatch.setattr(module, "owner_credential_matches", lambda value: bool(value))

    def model(self, fn):
        self.monkeypatch.setattr(provider, "stream_decision", fn)

    async def send(self, message, *, bot=True, **fields):
        payload = StreamRequest(message=message, detach=True, **({"bot_id": self.w.bot["bot_id"]} if bot else {"catalog_model": ""}), **fields)
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        return await stream.stream_chat(payload, request, CRED)

    def user_rows(self):
        return [(args[1], args[3], kwargs.get("message_id")) for args, kwargs in self.stored if len(args) >= 4 and args[2] == "user"]

    def answers(self):
        return [(args[1], args[3], kwargs) for args, kwargs in self.stored if len(args) >= 4 and args[2] == "assistant" and kwargs.get("status")
                in ("complete", "cancelled", "failed") and not (kwargs.get("tool_calls") or {}).get("calls")]


@pytest.fixture
def lab(stream_fixture, monkeypatch):  # noqa: F811
    return Lab(stream_fixture, monkeypatch)


async def collect(response):
    return "".join([part async for part in response.body_iterator])


def _note_id(messages):
    ids = re.findall(r"编号 ([0-9a-f]{8}(?:、[0-9a-f]{8})*)", " ".join(str(m.get("content")) for m in messages if m.get("role") == "system"))
    return ids[-1].split("、") if ids else []


def _scenario(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, 15))


def reply(text, calls=None):
    async def step(on_text):
        if text:
            await on_text(text)
        return {"usage": {"total_tokens": 5}}, {"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})}
    return step


def test_focus_1_an_interjected_message_is_merged_and_the_answer_covers_both(lab):
    started, gate, count = asyncio.Event(), asyncio.Event(), []

    async def model(provider_name, model_name, key, messages, schemas, **kwargs):
        count.append(1)
        if len(count) == 1:
            started.set()
            await gate.wait()
            return await reply("", [call("c1", "query_financials", {"symbol": "NVDA"})])(kwargs["on_text"])
        if len(count) == 2:
            return await reply("", [call("h1", inboxes.HANDLE, {"message_id": _note_id(messages)[0], "decision": "merge"}),
                                    call("c2", "query_financials", {"symbol": "AMD"})])(kwargs["on_text"])
        return await reply("NVDA 与 AMD 对比 [1]")(kwargs["on_text"])
    lab.model(model)

    async def scenario():
        first = await lab.send("NVDA 的营收")
        reading_a = asyncio.ensure_future(collect(first))
        await started.wait()
        second = await lab.send("顺便把 AMD 也比一下")
        reading_b = asyncio.ensure_future(collect(second))
        await asyncio.sleep(0.05)
        assert not reading_b.done()          # decided at the end of the step, not before
        gate.set()
        return await reading_a, await reading_b
    a, b = _scenario(scenario())
    assert names(b) == ["received", "merged"]
    received, merged = (data for _, data in blocks(b))
    assert received["message_id"] and merged["into_turn"] == next(d["turn_id"] for n, d in blocks(a) if n == "conversation")
    assert names(a) == ["conversation", "narration", "tool_start", "tool_result", "narration", "tool_start", "tool_start", "tool_result",
                        "tool_result", "delta", "citations", "done"]
    assert [(name, args["symbol"]) for name, args in lab.w.executed if name == "query_financials"] == [("query_financials", "NVDA"), ("query_financials", "AMD")]
    [(turn_a, answer, kwargs)] = lab.answers()
    assert answer == "NVDA 与 AMD 对比 [1]"
    (user_a, user_b) = lab.user_rows()
    assert kwargs["tool_calls"]["reply_to"] == [user_a[2], received["message_id"]] and user_b[2] == received["message_id"]
    assert lab.moved == [(received["message_id"], turn_a)]       # his row now belongs to the turn that answered it
    assert user_b[0] != turn_a                                    # stored at once under a row of its own
    assert not stream.inboxes.ACTIVE and not stream.LOCKS


def test_focus_2_a_stop_while_writing_ends_the_turn_stopped_and_stores_a_cancelled_answer(lab):
    started, gate, count = asyncio.Event(), asyncio.Event(), []

    async def model(provider_name, model_name, key, messages, schemas, **kwargs):
        count.append(1)
        if len(count) == 1:
            await kwargs["on_text"]("NVDA 的")
            started.set()
            await gate.wait()
            await kwargs["on_text"]("营收是 100")
            await kwargs["on_text"]("亿美元")          # never reached: the writing stops within the piece after his message
        return await reply("", [call("h1", inboxes.HANDLE, {"message_id": _note_id(messages)[0], "decision": "stop", "note": "好的，不做了。"})])(kwargs["on_text"])
    lab.model(model)

    async def scenario():
        first = await lab.send("NVDA 的营收")
        reading_a = asyncio.ensure_future(collect(first))
        await started.wait()
        second = await lab.send("算了不用了")
        reading_b = asyncio.ensure_future(collect(second))
        await asyncio.sleep(0.02)
        gate.set()
        return await reading_a, await reading_b
    a, b = _scenario(scenario())
    assert names(b) == ["received", "stopped"]
    assert names(a) == ["conversation", "delta", "delta", "answer_paused", "tool_start", "tool_result", "answer_reset", "delta", "stopped", "done"]
    texts = [d["text"] for n, d in blocks(a) if n == "delta"]
    assert texts == ["NVDA 的", "营收是 100", "NVDA 的营收是 100\n\n好的，不做了。"]
    assert dict(blocks(a))["done"]["status"] == "stopped"
    [(turn, answer, kwargs)] = lab.answers()
    assert answer == "NVDA 的营收是 100\n\n好的，不做了。" and kwargs["status"] == "cancelled"
    with SessionLocal() as db:
        item = db.scalars(select(work.AgentWork).where(work.AgentWork.ref == turn)).one()
    assert (item.status, item.reason) == ("stopped", stream.WORK_STOPPED_BY_MESSAGE)


def test_focus_3_a_separate_message_runs_beside_the_turn_and_both_answer(lab, fake_consent):
    started, gate, count = asyncio.Event(), asyncio.Event(), {"a": 0, "s": 0}
    lab.monkeypatch.setattr(consent, "propose", fake_consent.propose)
    from app import portfolio
    lab.monkeypatch.setattr(portfolio, "describe_write", lambda owner, name, args: {"title": "记一笔买入 TSLA", "targets": [{"symbol": args["symbol"]}]})

    async def model(provider_name, model_name, key, messages, schemas, **kwargs):
        mine = "TSLA" in json.dumps(messages, ensure_ascii=False) and "NVDA" not in json.dumps(messages[1:], ensure_ascii=False)
        if mine:       # the separate turn: its history is the conversation as of the message, so it has never heard of NVDA
            count["s"] += 1
            if count["s"] == 1:
                return await reply("", [act_call("t1", "record_trade", {"kind": "buy", "symbol": "TSLA", "quantity": 10, "price": 250})])(kwargs["on_text"])
            return await reply("我准备记下这笔 TSLA 买入，请核对卡片")(kwargs["on_text"])
        count["a"] += 1
        if count["a"] == 1:
            started.set()
            await gate.wait()
            return await reply("", [call("c1", "query_financials", {"symbol": "NVDA"})])(kwargs["on_text"])
        if count["a"] == 2:
            return await reply("", [call("h1", inboxes.HANDLE, {"message_id": _note_id(messages)[0], "decision": "separate"})])(kwargs["on_text"])
        return await reply("NVDA 的营收是 100 [1]")(kwargs["on_text"])
    lab.model(model)

    async def scenario():
        first = await lab.send("NVDA 的营收")
        reading_a = asyncio.ensure_future(collect(first))
        await started.wait()
        second = await lab.send("另外，帮我记一下我买了 10 股 TSLA")
        reading_b = asyncio.ensure_future(collect(second))
        await asyncio.sleep(0.02)
        gate.set()
        return await reading_a, await reading_b
    a, b = _scenario(scenario())
    assert names(b) == ["received", "separate", "conversation", "tool_start", "tool_result", "delta", "clarification", "done"]
    assert names(a) == ["conversation", "narration", "tool_start", "tool_result", "tool_start", "tool_result", "delta", "citations", "done"]
    card = next(d for n, d in blocks(b) if n == "clarification")
    assert card["request_id"] == "card-1"
    turn_b = next(d["turn_id"] for n, d in blocks(b) if n == "separate")
    assert next(d["turn_id"] for n, d in blocks(b) if n == "conversation") == turn_b
    # two answers, each with its own reply_to; his message was stored once (not again by the turn it became)
    rows = lab.user_rows()
    assert len(rows) == 2 and rows[1][0] == turn_b
    answers = {turn: kwargs["tool_calls"]["reply_to"] for turn, _, kwargs in lab.answers()}
    assert answers[turn_b] == [rows[1][2]] and answers[rows[0][0]] == [rows[0][2]]
    assert lab.moved == []                                       # a separate message keeps its own row
    cut = [c for c in lab.contexts if c.get("upto_sequence")]
    assert len(cut) == 1 and rows[0][0] in {str(t) for t in cut[0]["exclude_turns"]}     # as of its arrival, without the running turn
    assert dict(blocks(b))["done"]["status"] == "waiting_for_input" and not stream.inboxes.ACTIVE


def test_a_separate_turn_still_starts_when_the_request_that_brought_it_is_dropped(lab):
    started, gate, count = asyncio.Event(), asyncio.Event(), {"a": 0}
    finished = asyncio.Event()

    async def model(provider_name, model_name, key, messages, schemas, **kwargs):
        if "TSLA" in json.dumps(messages[1:], ensure_ascii=False) and "NVDA" not in json.dumps(messages[1:], ensure_ascii=False):
            finished.set()
            return await reply("TSLA 好了")(kwargs["on_text"])
        count["a"] += 1
        if count["a"] == 1:
            started.set()
            await gate.wait()
            return await reply("", [call("c1", "query_financials", {"symbol": "NVDA"})])(kwargs["on_text"])
        if count["a"] == 2:
            return await reply("", [call("h1", inboxes.HANDLE, {"message_id": _note_id(messages)[0], "decision": "separate"})])(kwargs["on_text"])
        return await reply("NVDA 好了")(kwargs["on_text"])
    lab.model(model)

    async def scenario():
        reading_a = asyncio.ensure_future(collect(await lab.send("NVDA 的营收")))
        await started.wait()
        second = await lab.send("另外说说 TSLA")
        body = second.body_iterator
        assert (await body.__anext__()).startswith("event: received")
        await body.aclose()                                  # the page is closed before the decision
        gate.set()
        await reading_a
        await asyncio.wait_for(finished.wait(), 5)
        await asyncio.sleep(0.1)
    _scenario(scenario())
    assert len(lab.answers()) == 2


def test_a_message_while_a_card_press_runs_is_not_taken_in_and_old_engine_turns_keep_the_409(lab):
    from fastapi import HTTPException
    lab.w.bot["engine"] = None
    lab.monkeypatch.delenv("FINBOT_KERNEL_DEFAULT")
    lock = asyncio.Lock()

    async def scenario():
        await lock.acquire()
        stream.LOCKS[lab.cid] = lock
        with pytest.raises(HTTPException) as busy:
            await lab.send("再问一句")
        assert busy.value.status_code == 409 and busy.value.detail == "conversation_busy"
        lock.release()
        stream.LOCKS.pop(lab.cid, None)
    _scenario(scenario())


# ---- Review Focus 4: three at a time per owner; the fourth waits ----

def test_focus_4_the_fourth_piece_of_work_waits_is_told_how_many_are_ahead_and_starts_when_one_ends(lab, monkeypatch):
    monkeypatch.delenv("FINBOT_CONCURRENT_WORK", raising=False)
    gates = [asyncio.Event() for _ in range(4)]
    started = []

    async def model(provider_name, model_name, key, messages, schemas, **kwargs):
        text = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        index = int(text[-1]) - 1
        started.append(index)
        await gates[index].wait()
        return await reply(f"答案 {index + 1}")(kwargs["on_text"])
    lab.model(model)

    async def scenario():
        readings = []
        for number in range(1, 4):
            readings.append(asyncio.ensure_future(collect(await lab.send(f"问题 {number}", bot=False))))
        while len(started) < 3:
            await asyncio.sleep(0.01)
        fourth = asyncio.ensure_future(collect(await lab.send("问题 4", bot=False)))
        await asyncio.sleep(0.2)
        assert started == [0, 1, 2] and not fourth.done()                 # nothing of the fourth has started
        with SessionLocal() as db:
            statuses = sorted(i.status for i in db.scalars(select(work.AgentWork)))
        assert statuses == ["queued", "running", "running", "running"]
        gates[1].set()                                                    # one ends: the fourth gets its place
        await readings[1]
        while 3 not in started:
            await asyncio.sleep(0.01)
        gates[0].set(), gates[2].set(), gates[3].set()
        return [await r for r in readings], await fourth
    first_three, fourth = _scenario(scenario())
    assert names(fourth) == ["conversation", "queued", "delta", "done"]
    assert dict(blocks(fourth))["queued"] == {"ahead": 3}
    assert all(names(wire) == ["conversation", "delta", "done"] for wire in first_three)
    with SessionLocal() as db:
        assert sorted(i.status for i in db.scalars(select(work.AgentWork))) == ["done"] * 4


def test_the_limit_is_per_owner_and_can_be_set(lab, monkeypatch):
    monkeypatch.setenv("FINBOT_CONCURRENT_WORK", "1")
    assert work.concurrent_limit() == 1
    monkeypatch.setenv("FINBOT_CONCURRENT_WORK", "bad")
    assert work.concurrent_limit() == 3
    monkeypatch.delenv("FINBOT_CONCURRENT_WORK")
    assert work.concurrent_limit() == 3


# ---- the work table: slots, FIFO, the list, the restart ----

OWNER = "owner-3c"


def _conversation(text="问题"):
    turn = uuid.uuid4()
    with SessionLocal() as db:
        conversation = AgentConversation(owner_hash=OWNER)
        db.add(conversation)
        db.flush()
        db.add(AgentMessage(conversation_id=conversation.id, turn_id=turn, sequence=1, role="user", content=text, status="complete"))
        db.commit()
        return str(conversation.id), str(turn)


def _status(turn):
    with SessionLocal() as db:
        return db.scalars(select(work.AgentWork).where(work.AgentWork.ref == turn)).one().status


def test_slots_are_first_in_first_out_and_a_slot_goes_to_the_oldest_in_line():
    turns = []
    for number in range(5):
        conversation, turn = _conversation(f"q{number}")
        turns.append((turn, work.enter_turn(OWNER, conversation, turn, f"q{number}", limit=3)))
    assert [state for _, state in turns] == [("running", 0)] * 3 + [("queued", 3), ("queued", 4)]
    fourth, fifth = turns[3][0], turns[4][0]
    assert work.promote(fifth, limit=3) == (False, 4)             # not its turn, and no slot
    assert work.promote(fourth, limit=3) == (False, 3)
    work.end_turn(turns[0][0], "done")
    assert work.promote(fifth, limit=3) == (False, 3)              # a slot is free but the fourth is first (two running, the fourth ahead)
    assert work.promote(fourth, limit=3) == (True, 0) and _status(fourth) == "running"
    assert work.promote(fifth, limit=3) == (False, 3)              # now three run again
    other, other_turn = _conversation()
    assert work.enter_turn("someone-else", other, other_turn, "q", limit=3) == ("running", 0)      # another owner has slots of his own


def test_a_queued_item_is_on_the_list_as_waiting_and_can_be_closed():
    items = []
    for number in range(4):
        conversation, turn = _conversation(f"q{number}")
        work.enter_turn(OWNER, conversation, turn, f"q{number}", limit=3)
        items.append(turn)
    listed = [i for i in work.list_for(OWNER) if i["kind"] == "chat"]
    assert sorted(i["status_label"] for i in listed) == ["排队中", "进行中", "进行中", "进行中"]
    assert work.end_turn(items[3], "stopped", "你停了") is True and _status(items[3]) == "stopped"


def test_a_restart_closes_the_queued_item_with_the_restart_message_and_loses_nothing_silently():
    for number in range(3):
        conversation, turn = _conversation(f"q{number}")
        work.enter_turn(OWNER, conversation, turn, f"q{number}", limit=3)
    conversation, queued = _conversation("第四件")
    assert work.enter_turn(OWNER, conversation, queued, "第四件", limit=3) == ("queued", 3)
    assert work.sweep_interrupted() == 4
    with SessionLocal() as db:
        item = db.scalars(select(work.AgentWork).where(work.AgentWork.ref == queued)).one()
        assert (item.status, item.reason) == ("failed", work.RESTART_REASON)
        rows = db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == uuid.UUID(conversation)).order_by(AgentMessage.sequence)).all()
    assert [r.role for r in rows] == ["user", "assistant"] and rows[-1].status == "failed" and "被系统重启打断了" in rows[-1].content
    assert work.sweep_interrupted() == 0


# ---- the stored rows: turns that run together, a message a turn took in, the history as of a moment ----

def _row(turn, sequence, role, content="", status="complete", **extra):
    return {"turn_id": turn, "sequence": sequence, "role": role, "content": content, "status": status, "tool_calls": None, **extra}


def test_rows_of_turns_that_ran_together_group_by_turn_and_a_merged_message_is_part_of_its_turn():
    from app import agent_context as layers
    rows = [_row("A", 1, "user", "NVDA 的营收"), _row("S", 2, "user", "记一笔 TSLA"),
            _row("A", 3, "assistant", "", tool_calls={"calls": [{"id": "c"}]}), _row("S", 4, "assistant", "请核对卡片"),
            _row("A", 5, "tool", "{}"), _row("A", 6, "user", "顺便把 AMD 也比一下"), _row("A", 7, "assistant", "NVDA 与 AMD [1]")]
    groups = layers.complete_turns(rows)
    assert [[r["sequence"] for r in g] for g in groups] == [[1, 3, 5, 6, 7], [2, 4]]
    assert layers.project_turn_history(groups[0]) == [{"role": "user", "content": "NVDA 的营收\n顺便把 AMD 也比一下"},
                                                      {"role": "assistant", "content": "NVDA 与 AMD [1]"}]
    # a turn the owner stopped is an unfinished turn (cancelled), not a hole in the history
    stopped = [_row("A", 1, "user", "NVDA 的营收"), _row("A", 2, "user", "算了"), _row("A", 3, "assistant", "好的，已停下。", status="cancelled")]
    assert layers.complete_turns(stopped) == [] and layers.trailing_unfinished(stopped) == [
        {"turn_id": "A", "content": "NVDA 的营收", "state": "cancelled"}]


def test_a_stored_message_can_be_named_moved_and_left_out_of_the_history_as_of_a_moment():
    from app import agent_chat_store as store

    async def scenario():
        conversation = await store.create_conversation(CRED)
        turn_a, turn_m, turn_s = _new_id(), _new_id(), _new_id()
        message = _new_id()
        first = await store.append_message(conversation, turn_a, "user", "NVDA 的营收")
        second = await store.append_message(conversation, turn_m, "user", "顺便把 AMD 也比一下", message_id=message)
        await store.append_message(conversation, turn_a, "assistant", "NVDA 100", status="complete")
        sequence_s = await store.append_message(conversation, turn_s, "user", "另外说说 TSLA")
        assert (first, second, sequence_s) == (1, 2, 4)
        assert await store.move_message(conversation, message, turn_a) is True
        assert await store.move_message(conversation, _new_id(), turn_a) is False
        everything = await store.conversation_context(conversation, CRED)
        taken = [r["content"] for r in everything["l1_rows"] if str(r["turn_id"]) == turn_a and r["role"] == "user"]
        assert taken == ["NVDA 的营收", "顺便把 AMD 也比一下"]                # the message now belongs to the turn that took it in
        # a separate turn's history: as of its message, without the turn that was still working
        cut = await store.conversation_context(conversation, CRED, upto_sequence=sequence_s, exclude_turns=[turn_a])
        assert cut["l1_rows"] == [] and [u["turn_id"] for u in cut["unfinished"]] == [turn_s]
        early = await store.conversation_context(conversation, CRED, upto_sequence=1)
        assert early["unfinished"] and early["unfinished"][0]["content"] == "NVDA 的营收"
    _scenario(scenario())
