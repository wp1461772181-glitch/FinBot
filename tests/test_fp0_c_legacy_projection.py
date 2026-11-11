"""FP0 slice c (WP0 step 8): stored answers from the retired legacy check are projected when they are read.

The three reading surfaces: the web replay and the inbox (agent_chat_stream), the briefing write
(agent_task_runner) and the Telegram text (the bridge). The realtime stream's regression test is in
test_agent_chat_stream.py; the Telegram flip is in test_telegram_bridge_flow.py.
"""
import asyncio
import copy
import hashlib
import json
import uuid

import pytest

from app.agent_workflow.legacy_projection import (
    RETIRED_FLAG,
    project_answer,
    project_inbox_items,
    project_rows,
    stored_run_protocol,
)

BODY = "AMD 收盘价为 100 美元 [1]。"
FOOT = "\n\n（另有 1 处表述未能与来源核对，已保留并标注“证据不足”。）"
ENFORCE_FOOT = "\n\n（另有 2 处表述未能与来源核对，已略去。）"
UNV = [{"line": "AMD 成交量为 999 万股 [1]。", "reason": "unsupported_numeric_claim", "numbers": ["999 万"]}]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---- the rule ------------------------------------------------------------------------------------

def test_stored_unverified_lines_with_a_trailing_footnote_lose_it_and_are_marked():
    assert project_answer(BODY + FOOT, {"unverified_lines": UNV}) == (BODY, True)


def test_a_footnote_is_kept_when_the_protocol_stores_no_unverified_lines():
    """A model that writes the same words is writing prose: nothing is removed, nothing is marked."""
    text = BODY + FOOT
    assert project_answer(text, {"audit": {}}) == (text, False)
    assert project_answer(text, None) == (text, False)
    assert project_answer(text, {"unverified_lines": []}) == (text, False)


def test_stored_unverified_lines_without_a_footnote_are_marked_only():
    assert project_answer(BODY, {"unverified_lines": UNV}) == (BODY, True)


def test_an_enforce_era_footnote_is_marked_but_not_removed():
    text = BODY + ENFORCE_FOOT
    assert project_answer(text, {"audit": {}}) == (text, True)


def test_a_footnote_that_is_not_the_last_text_is_not_removed():
    text = BODY + FOOT + "\n\n后文。"
    assert project_answer(text, {"unverified_lines": UNV}) == (text, True)


# ---- archive: projection never writes back ---------------------------------------------------------

def test_projection_leaves_the_stored_row_and_its_bytes_unchanged():
    row = {"role": "assistant", "content": BODY + FOOT, "status": "complete", "turn_id": "t1",
           "tool_calls": {"unverified_lines": UNV, "audit": {"x": 1}}}
    before, snapshot = _digest(row), copy.deepcopy(row)
    assert project_rows([row], lookup=lambda *_: None) == [(BODY, True)]
    assert row == snapshot and _digest(row) == before


# ---- line posts and inbox items point at their run ---------------------------------------------

def test_a_line_post_reads_the_run_protocol_it_points_at():
    post = {"role": "assistant", "content": BODY + FOOT,
            "tool_calls": {"task_post": {"run_conversation_id": "c-run", "item_id": "i1"}, "audit": {}}}
    seen = []

    def lookup(conversation_id, body):
        seen.append((conversation_id, body))
        return {"unverified_lines": UNV}

    assert project_rows([post], lookup=lookup) == [(BODY, True)]
    assert seen == [("c-run", BODY + FOOT)]


def test_a_line_post_whose_run_stored_no_unverified_lines_keeps_its_text():
    post = {"role": "assistant", "content": BODY + FOOT,
            "tool_calls": {"task_post": {"run_conversation_id": "c-run"}, "audit": {}}}
    assert project_rows([post], lookup=lambda *_: {"audit": {}}) == [(BODY + FOOT, False)]


def test_the_run_is_only_looked_up_for_a_footnoted_line_post():
    plain = {"role": "assistant", "content": BODY, "tool_calls": {"task_post": {"run_conversation_id": "c"}}}
    calls = []
    project_rows([plain], lookup=lambda *args: calls.append(args))
    assert calls == []


def test_user_rows_are_never_projected():
    row = {"role": "user", "content": BODY + FOOT, "tool_calls": {"unverified_lines": UNV}}
    assert project_rows([row], lookup=lambda *_: None) == [(BODY + FOOT, False)]


def _item(body, *, section="brief", conversation="c-run"):
    return {"id": "i1", "section": section, "body": body, "conversation_id": conversation, "title": "t"}


def test_a_brief_body_is_projected_from_its_run():
    out = project_inbox_items([_item(BODY + FOOT)], lookup=lambda *_: {"unverified_lines": UNV})
    assert out[0]["body"] == BODY and out[0][RETIRED_FLAG] is True


def test_a_brief_with_no_footnote_or_no_run_is_returned_as_it_is():
    no_footnote = _item(BODY)
    assert project_inbox_items([no_footnote], lookup=lambda *_: {"unverified_lines": UNV})[0] is no_footnote
    no_run = _item(BODY + FOOT)
    assert project_inbox_items([no_run], lookup=lambda *_: None)[0] is no_run


def test_other_inbox_sections_are_not_projected():
    item = _item(BODY + FOOT, section="confirm")
    assert project_inbox_items([item], lookup=lambda *_: {"unverified_lines": UNV})[0] is item


# ---- surface 1: the web replay (end to end through get_messages) -----------------------------------

def test_web_replay_shows_a_retired_answer_without_its_footnote_and_keeps_a_model_written_one(monkeypatch):
    import app.agent_chat_stream as stream

    rows = [
        {"role": "user", "content": "AMD 收盘价？", "status": "complete", "turn_id": "t1", "tool_calls": None},
        {"role": "assistant", "content": BODY + FOOT, "status": "complete", "turn_id": "t1",
         "tool_calls": {"unverified_lines": UNV, "audit": {}}},
        {"role": "user", "content": "再说一次", "status": "complete", "turn_id": "t2", "tool_calls": None},
        {"role": "assistant", "content": BODY + FOOT, "status": "complete", "turn_id": "t2",
         "tool_calls": {"audit": {}}},
    ]
    before = _digest(rows)

    async def page(*_args, **_kwargs):
        return {"messages": rows, "has_more": False, "next_before": None, "compactions": []}

    monkeypatch.setattr(stream, "owned_message_page", page)
    messages = asyncio.run(stream.get_messages("c", before=None, limit=20, x_chat_session="owner"))["messages"]
    retired, kept = [m for m in messages if m["role"] == "assistant"]
    assert retired["content"] == BODY and retired[RETIRED_FLAG] is True
    assert "unverified_lines" not in retired
    assert kept["content"] == BODY + FOOT and RETIRED_FLAG not in kept
    assert _digest(rows) == before


# ---- surface 2: the inbox endpoint (end to end) -----------------------------------------------------

def test_the_inbox_endpoint_shows_a_retired_brief_without_its_footnote(monkeypatch):
    import app.agent_chat_stream as stream
    import app.agent_tasks as tasks

    monkeypatch.setattr(stream, "_owner_only", lambda _session: "owner")
    monkeypatch.setattr(tasks, "list_inbox", lambda *_a, **_k: [_item(BODY + FOOT), _item("今天没有新变化。")])
    import app.agent_workflow.legacy_projection as projection
    monkeypatch.setattr(projection, "stored_run_protocol", lambda *_: {"unverified_lines": UNV})
    out = asyncio.run(stream.list_inbox_endpoint(section="brief", limit=50, bot_id=None, x_chat_session="x"))
    retired, plain = out["items"]
    assert retired["body"] == BODY and retired[RETIRED_FLAG] is True
    assert plain["body"] == "今天没有新变化。" and RETIRED_FLAG not in plain


# ---- the lookup of a run's stored protocol (real database) -----------------------------------------

@pytest.fixture
def run_conversation():
    from app.agent_chat_models import AgentConversation, AgentMessage
    from app.database import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    cid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(AgentConversation(id=cid, owner_hash=f"fp0c-{uuid.uuid4().hex}"))
        db.add(AgentMessage(conversation_id=cid, turn_id=uuid.uuid4(), sequence=1, role="assistant",
                            content=BODY + FOOT, tool_calls={"unverified_lines": UNV, "audit": {}}, status="complete"))
        db.commit()
    yield cid
    with SessionLocal() as db:
        db.query(AgentConversation).filter(AgentConversation.id == cid).delete()
        db.commit()


def test_the_run_protocol_is_found_by_its_conversation_and_its_text(run_conversation):
    protocol = stored_run_protocol(str(run_conversation), BODY)
    assert protocol["unverified_lines"] == UNV
    assert stored_run_protocol(str(run_conversation), "另一段文字") is None
    assert stored_run_protocol(str(uuid.uuid4()), BODY) is None
    assert stored_run_protocol("not-a-uuid", BODY) is None


# ---- briefing write: a new briefing stores no unverified lines -----------------------------------------

def test_a_new_briefing_stores_no_unverified_lines(monkeypatch):
    import app.agent_chat_store as store
    import app.agent_chat_stream as stream
    import app.agent_task_runner as runner
    from app.agent_workflow import graph

    stored = []

    async def create(_credential):
        return "c-run"

    async def set_title(*_args, **_kwargs):
        return None

    async def append(cid, turn, role, content, *, tool_calls=None, tool_call_id=None, status="complete"):
        stored.append({"role": role, "content": content, "tool_calls": tool_calls, "status": status})

    async def finish(*_args, **_kwargs):
        return None

    async def profile(*_args, **_kwargs):
        return None

    async def workflow(**_kwargs):
        yield {"event": "delta", "text": BODY}
        yield {"event": "done", "status": "succeeded", "reason": None, "final_protocol": {}, "audit": {},
               "citations": [], "unverified_lines": UNV, "route": "A"}

    monkeypatch.setattr(store, "create_conversation", create)
    monkeypatch.setattr(store, "set_conversation_title", set_title)
    monkeypatch.setattr(store, "append_message", append)
    monkeypatch.setattr(store, "finish_conversation", finish)
    monkeypatch.setattr(store, "owner_hash", lambda _credential: "owner")
    monkeypatch.setattr(stream, "_profile_block", profile)
    monkeypatch.setattr(graph, "stream_workflow", workflow)

    model = {"provider": "deepseek", "model": "deepseek-chat", "api_key": "k", "base_url": None}
    result = asyncio.run(runner.run_unattended_turn("cred", "AMD 收盘价？", model, title="收盘价"))
    assert result["answer"] == BODY and result["status"] == "succeeded"
    briefing = [row for row in stored if row["role"] == "assistant"]
    assert len(briefing) == 1 and briefing[0]["content"] == BODY
    assert "unverified_lines" not in (briefing[0]["tool_calls"] or {})


# ---- surface 3: the Telegram text (end to end through the bridge) -----------------------------------

def test_telegram_text_of_a_turn_with_a_legacy_check_carries_no_unverified_suffix():
    from scripts import run_telegram_bridge as bridge

    events = [("delta", {"text": "AMD 收盘价为 100 美元 [1]。\nAMD 成交量为 999 万股 [1]。"}),
              ("unverified_lines", {"items": UNV})]
    answer, _cards, _cid = bridge.format_turn(events)
    assert "（未核实）" not in answer and "[1]" not in answer
    assert answer.split("\n") == ["AMD 收盘价为 100 美元。", "AMD 成交量为 999 万股。"]
