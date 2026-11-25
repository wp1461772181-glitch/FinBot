"""3c Task 2: which messages an answer answers (``reply_to``).

It lives in the stored protocol (``tool_calls["reply_to"]`` of the answer row): the answer row already carries its protocol and every reader
(the messages endpoint, the history projection, the backstage) already reads that row, so there is no migration and the ids are written in the same
row as the answer.  Old rows have none and read as they always did.
"""
import asyncio

import app.agent_chat_stream as stream
from app import agent_context as layers
from tests.test_backstage_api import (G, H, OWNER_HASH, bot, conversation, get, kernel_record, turn, world)  # noqa: F401  (fixture by name)


def row(turn_id, sequence, role, content="", *, ident=None, status="complete", **extra):
    return {"id": ident or f"{role[0]}{sequence}", "turn_id": turn_id, "sequence": sequence, "role": role, "content": content,
            "status": status, "tool_calls": extra.pop("tool_calls", None), **extra}


def answer(turn_id, sequence, content, reply_to=None, **extra):
    return row(turn_id, sequence, "assistant", content, tool_calls={"reply_to": reply_to} if reply_to is not None else {}, **extra)


# ---- history projection ----

def test_an_answer_is_paired_with_exactly_the_messages_it_answered_in_the_order_it_names_them():
    group = [row("A", 1, "user", "NVDA 的营收"), row("A", 2, "user", "停", ident="u-stop"), row("A", 3, "user", "也比 AMD", ident="u-merge"),
             answer("A", 4, "NVDA 与 AMD ...", ["u1", "u-merge"])]
    assert layers.project_turn_history(group) == [{"role": "user", "content": "NVDA 的营收\n也比 AMD"},
                                                  {"role": "assistant", "content": "NVDA 与 AMD ..."}]       # the unlisted row is not paired


def test_old_rows_without_reply_to_answer_the_user_rows_of_their_turn():
    group = [row("A", 1, "user", "问题"), row("A", 2, "assistant", "", tool_calls={"calls": [{"id": "c"}]}), row("A", 3, "tool", "{}"),
             answer("A", 4, "回答")]
    assert layers.project_turn_history(group) == [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}]
    twin = [row("A", 1, "user", "问题"), answer("A", 2, "回答", [])]       # an empty list is as good as none
    assert layers.project_turn_history(twin) == [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}]


def test_turns_that_ran_together_are_ordered_by_when_they_were_answered_so_the_prefix_never_changes():
    rows = [row("A", 1, "user", "长问题"), row("B", 2, "user", "短问题"), answer("B", 3, "短回答", ["u2"])]
    first = layers.complete_turns(rows)
    assert [g[0]["turn_id"] for g in first] == ["B"]                       # A is still working
    rows += [answer("A", 4, "长回答", ["u1"]), row("C", 5, "user", "再问"), answer("C", 6, "再答", ["u5"])]
    later = layers.complete_turns(rows)
    assert [g[0]["turn_id"] for g in later] == ["B", "A", "C"]              # B's place did not move; A came after it
    before = [m for g in first for m in layers.project_turn_history(g)]
    after = [m for g in later for m in layers.project_turn_history(g)]
    assert after[:len(before)] == before                                   # the history only grows at the end


def test_a_merged_turn_and_a_parallel_turn_read_naturally_in_the_model_history():
    rows = [row("A", 1, "user", "NVDA 的营收"), row("S", 2, "user", "记一笔 TSLA"), answer("S", 3, "请核对卡片", ["u2"]),
            row("A", 4, "user", "顺便 AMD", ident="u-merge"), answer("A", 5, "NVDA 与 AMD", ["u1", "u-merge"])]
    context = layers.layer_rows(rows, [], l1_bytes=100_000, l2_bytes=100_000, l3_bytes=100_000)
    history = [m for g in layers.complete_turns(context["l1_rows"]) for m in layers.project_turn_history(g)]
    assert history == [{"role": "user", "content": "记一笔 TSLA"}, {"role": "assistant", "content": "请核对卡片"},
                       {"role": "user", "content": "NVDA 的营收\n顺便 AMD"}, {"role": "assistant", "content": "NVDA 与 AMD"}]


def test_the_second_layer_and_the_catalogue_carry_the_whole_question_of_a_merged_turn():
    rows = [row("A", 1, "user", "NVDA 的营收"), row("A", 2, "user", "顺便 AMD", ident="u-merge"), answer("A", 3, "NVDA 与 AMD [1]", ["u1", "u-merge"])]
    context = layers.layer_rows(rows, [], l1_bytes=10, l2_bytes=100_000, l3_bytes=100_000)
    assert context["half_turns"] and context["half_turns"][0].user == "NVDA 的营收\n顺便 AMD"


# ---- the messages endpoint ----

def test_the_messages_endpoint_returns_reply_to_with_a_one_line_quote_of_each_question(monkeypatch):
    long = "顺便把 AMD 也和它比一下，\n尤其是毛利率和研发费用占收入的比例，还有最近四个季度的变化趋势和管理层的说明"
    page = {"messages": [
        {"id": "m1", "role": "user", "content": "NVDA 的营收", "status": "complete", "turn_id": "t1", "tool_calls": None, "tool_call_id": None},
        {"id": "m2", "role": "user", "content": long, "status": "complete", "turn_id": "t1", "tool_calls": None, "tool_call_id": None},
        {"id": "a1", "role": "assistant", "content": "NVDA 与 AMD", "status": "complete", "turn_id": "t1", "tool_call_id": None,
         "tool_calls": {"reply_to": ["m1", "m2", "m-old"]}},
        {"id": "m3", "role": "user", "content": "再问", "status": "complete", "turn_id": "t2", "tool_calls": None, "tool_call_id": None},
        {"id": "a2", "role": "assistant", "content": "好", "status": "complete", "turn_id": "t2", "tool_calls": {}, "tool_call_id": None}],
        "has_more": False, "next_before": None, "compactions": []}

    async def fake_page(*args, **kwargs):
        return page

    async def earlier(conversation_id, ids):
        return {"m-old": "更早的一个问题"}
    monkeypatch.setattr(stream, "owned_message_page", fake_page)
    monkeypatch.setattr(stream, "message_texts", earlier)
    messages = asyncio.run(stream.get_messages("conversation", "owner"))["messages"]
    by_id = {m.get("id"): m for m in messages if m.get("id")}
    assert by_id["m1"]["role"] == "user" and by_id["a1"]["reply_to"][0] == {"id": "m1", "text": "NVDA 的营收"}
    quote = by_id["a1"]["reply_to"][1]
    assert quote["id"] == "m2" and len(quote["text"]) <= 60 and "\n" not in quote["text"] and quote["text"].startswith("顺便把 AMD 也和它比一下，")
    assert by_id["a1"]["reply_to"][2] == {"id": "m-old", "text": "更早的一个问题"}          # a question on an earlier page
    assert "reply_to" not in messages[-1]                                                  # an old row: nothing added


# ---- the backstage ----

def test_the_backstage_detail_says_what_each_answer_answered(client):
    from sqlalchemy import select
    from app.agent_chat_models import AgentMessage
    from app.database import SessionLocal
    cid = conversation(bot())
    tid, mid = turn(cid, question="NVDA 的营收", record=kernel_record())
    with SessionLocal() as db:
        first = db.scalars(select(AgentMessage).where(AgentMessage.turn_id == tid, AgentMessage.role == "user")).first()
        extra = AgentMessage(conversation_id=cid, turn_id=tid, sequence=99, role="user", content="顺便把 AMD 也比一下")
        db.add(extra)
        db.flush()
        final = db.get(AgentMessage, mid)
        final.tool_calls = {**final.tool_calls, "reply_to": [str(first.id), str(extra.id)]}
        db.commit()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert [item["label"] for item in body["answered"]] == ["回答了：NVDA 的营收", "回答了：顺便把 AMD 也比一下"]
    assert body["answered"][0]["message_id"] == str(first.id)
    older, old_id = turn(cid, record=kernel_record())
    assert get(client, f"/backstage/answers/{old_id}").json()["answered"] == []
