"""Stage 4a: ``read_turn(turn_id)`` gives back what was actually said in one earlier turn (the owner's message(s) and the final
answer), so the rolling summary only has to point at a turn.  Own conversation only; kernel only; the old engine is unchanged."""
import asyncio
import json
import uuid

import pytest

from app.agent_chat_models import AgentConversation, AgentConversationSummary, AgentMessage
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine

OWNER = "owner"
GUEST = "g" * 64
OTHER = "o" * 64


def _tid(n):
    return f"33333333-3333-4333-8333-{n:012d}"


@pytest.fixture
def db(disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, AgentConversationSummary.__table__])
    with SessionLocal() as s:
        s.query(AgentConversation).delete()
        s.commit()


def _store(credential, turns):
    """turns: (n, [user texts], answer, reply_to_indexes|None); returns (conversation id, {text: message id})"""
    from app import agent_chat_store as store

    async def run():
        try:
            cid = await store.create_conversation(credential)
            ids = {}
            for n, users, answer, named in turns:
                for text in users:
                    mid = str(uuid.uuid4())
                    ids[text] = mid
                    await store.append_message(cid, _tid(n), "user", text, message_id=mid)
                if answer is not None:
                    protocol = {"reply_to": [ids[users[i]] for i in named]} if named is not None else None
                    await store.append_message(cid, _tid(n), "assistant", answer, tool_calls=protocol)
            return cid, ids
        finally:
            await store.engine.dispose()
    return asyncio.run(run())


def _read(cid, credential, turn):
    from app import agent_chat_store as store

    async def run():
        try:
            return await store.read_turn(cid, credential, turn)
        finally:
            await store.engine.dispose()
    return asyncio.run(run())


def test_a_turn_comes_back_as_said_with_its_neighbours(db):
    cid, _ = _store(OWNER, [(1, ["英伟达数据中心还会翻倍吗"], "我的看法是……", None), (2, ["那 AMD 呢"], "AMD 的情况是……", None),
                            (3, ["再说说台积电"], "台积电……", None)])
    got = _read(cid, OWNER, _tid(2))
    assert got["user_messages"] == ["那 AMD 呢"] and got["answer"] == "AMD 的情况是……"
    assert got["turn_id"] == _tid(2) and got["time"] and got["previous_turn_id"] == _tid(1) and got["next_turn_id"] == _tid(3)
    assert _read(cid, OWNER, _tid(1))["previous_turn_id"] is None and _read(cid, OWNER, _tid(3))["next_turn_id"] is None
    assert not got["cut"]


def test_interjections_merged_into_a_turn_come_back_in_order(db):
    cid, _ = _store(OWNER, [(1, ["先看英伟达", "顺便也看 AMD", "算了别管这个"], "两家的情况……", [0, 1])])
    got = _read(cid, OWNER, _tid(1))
    assert got["user_messages"] == ["先看英伟达", "顺便也看 AMD"]
    cid2, _ = _store(OWNER, [(1, ["一", "二"], "答", None)])
    assert _read(cid2, OWNER, _tid(1))["user_messages"] == ["一", "二"]


def test_the_final_answer_not_a_tool_step(db):
    from app import agent_chat_store as store

    async def run():
        try:
            cid = await store.create_conversation(OWNER)
            await store.append_message(cid, _tid(1), "user", "问")
            await store.append_message(cid, _tid(1), "assistant", "我先查一下", tool_calls={"calls": [{"id": "c"}]})
            await store.append_message(cid, _tid(1), "assistant", "最终答案")
            return cid
        finally:
            await store.engine.dispose()
    cid = asyncio.run(run())
    assert _read(cid, OWNER, _tid(1))["answer"] == "最终答案"


def test_a_long_text_is_cut_and_marked(db):
    cid, _ = _store(OWNER, [(1, ["问" * 13000], "答" * 20000, None)])
    got = _read(cid, OWNER, _tid(1))
    assert got["cut"] is True
    assert got["answer"].startswith("答" * 12000) and "已截断" in got["answer"] and "20000" in got["answer"]
    assert got["user_messages"][0].startswith("问" * 12000) and "已截断" in got["user_messages"][0]


def test_other_conversation_other_owner_or_made_up_id_is_not_found(db):
    mine, _ = _store(OWNER, [(1, ["我的问题"], "我的答案", None)])
    theirs, _ = _store(OTHER, [(1, ["别人的问题"], "别人的答案", None)])
    _store(OWNER, [(5, ["同一个主人的另一个会话"], "答", None)])
    assert _read(mine, OWNER, _tid(5)) is None             # a turn of another conversation of the same owner
    assert _read(mine, OTHER, _tid(1)) is None             # another owner reading this conversation
    assert _read(theirs, OWNER, _tid(1)) is None
    assert _read(mine, OWNER, str(uuid.uuid4())) is None and _read(mine, OWNER, "not-an-id") is None and _read("bad", OWNER, _tid(1)) is None


def _context(credential, cid):
    from app.agent_workflow.state import AgentRuntimeContext
    return AgentRuntimeContext("custom", "test", "dummy", identity_credential=credential, owner_hash=owner_hash(credential), conversation_id=cid)


def _invoke(credential, cid, turn):
    from app.agent_workflow import tools
    return asyncio.run(_dispatch_in_loop(tools, credential, cid, turn))


async def _dispatch_in_loop(tools, credential, cid, turn):
    from app import agent_chat_store as store
    try:
        return await tools.invoke("read_turn", {"turn_id": turn}, _context(credential, cid))
    finally:
        await store.engine.dispose()


def test_the_tool_answers_owner_and_guest_but_never_across_conversations(db, monkeypatch):
    import app.agent_workflow.tools as tools
    monkeypatch.setattr(tools, "owner_credential_matches", lambda c: c == OWNER)
    mine, _ = _store(OWNER, [(1, ["我问了什么"], "我得到了什么", None)])
    guest, _ = _store(GUEST, [(2, ["访客问了什么"], "访客得到了什么", None)])
    got = _invoke(OWNER, mine, _tid(1))
    assert got["ok"] and got["data"][0]["user_messages"] == ["我问了什么"] and got["data"][0]["answer"] == "我得到了什么"
    assert got["label"] == "往事，不是证据"
    seen = _invoke(GUEST, guest, _tid(2))
    assert seen["ok"] and seen["data"][0]["answer"] == "访客得到了什么"
    assert _invoke(GUEST, guest, _tid(1))["error_code"] == "turn_not_found"
    assert _invoke(GUEST, mine, _tid(1))["error_code"] == "turn_not_found"
    assert _invoke(OWNER, mine, str(uuid.uuid4()))["error_code"] == "turn_not_found"


def test_kernel_offers_it_to_owner_and_guest_and_the_old_engine_never():
    from app.agent_tool_catalog import KERNEL_ONLY, definitions, legacy_definitions, schemas, validate
    from app.kernel import loop, progress, toolrun
    assert definitions()["read_turn"].level == "read" and definitions()["read_turn"].guest
    assert "read_turn" in KERNEL_ONLY and "read_turn" in loop.READ_TOOLS and "read_turn" in toolrun._UNNUMBERED
    assert progress.TOOL_PHRASES["read_turn"] == "翻看之前那一轮"
    names = lambda items: {i["function"]["name"] for i in items}
    assert "read_turn" in names(schemas(owner=True, kernel=True)) and "read_turn" in names(schemas(owner=False, kernel=True))
    assert "read_turn" not in legacy_definitions() and "read_turn" not in names(schemas(owner=True)) and "read_turn" not in names(schemas(owner=False))
    with pytest.raises(Exception):
        validate("read_turn", {"turn_id": "x"})
    validate("read_turn", {"turn_id": _tid(1)})


def test_the_memory_note_gets_the_sentence_only_in_a_kernel_turn():
    from app import agent_context as layers
    old = layers.summary_message([{"content": "摘要"}])
    new = layers.summary_message([{"content": "摘要"}], kernel=True)
    assert old["content"] == layers.MEMORY_NOTE + "\n1. 摘要" and "read_turn" not in old["content"]
    assert new["content"].startswith(layers.MEMORY_MARKER) and "read_turn" in new["content"] and "摘要" in new["content"]
    assert "read_history_citation" in new["content"] and is_memory(new)
    assert layers.summary_message([], kernel=True) is None


def is_memory(message):
    from app import agent_context as layers
    return layers.is_memory_message(message)


# --- final-review fix wave -----------------------------------------------------------------------------------------------------

def _turn_with(status, content="答到一半", users=("问",), protocol=None):
    from app import agent_chat_store as store

    async def run():
        try:
            cid = await store.create_conversation(OWNER)
            for text in users:
                await store.append_message(cid, _tid(1), "user", text)
            if status is not None:
                await store.append_message(cid, _tid(1), "assistant", content, status=status, tool_calls=protocol)
            return cid
        finally:
            await store.engine.dispose()
    return asyncio.run(run())


@pytest.mark.parametrize("status", ["complete", "failed", "cancelled", "stopped", "running"])
def test_the_answer_says_what_state_it_is_in(db, status):
    cid = _turn_with(status)
    got = _read(cid, OWNER, _tid(1))
    assert got["answer_status"] == status and got["answer"] == "答到一半" and got["user_messages"] == ["问"]


def test_a_turn_with_no_answer_yet_says_so(db):
    cid = _turn_with(None)
    got = _read(cid, OWNER, _tid(1))
    assert got["answer"] is None and got["answer_status"] == "no_answer" and got["user_messages"] == ["问"]


def test_the_description_says_what_a_status_other_than_complete_means():
    from app.agent_tool_catalog import definitions
    text = definitions()["read_turn"].description
    assert "answer_status" in text and "cut off" in text and "failed" in text and "still being written" in text


def test_a_scoped_bot_is_offered_read_turn_record_view_and_drop_view(owner_env):
    from app import agent_bots
    from app.kernel import loop
    scope = agent_bots.expand_legacy(["web_research"]) | agent_bots.ALWAYS_ON
    assert {"read_turn", "record_view", "drop_view"} <= agent_bots.ALWAYS_ON <= scope
    from tests.test_kernel_loop import make_context
    names = {s["function"]["name"] for s in loop._tool_schemas(make_context(tool_scope=scope))}
    assert "read_turn" in names and "web_research" in names
    from app.agent_tool_catalog import KERNEL_ONLY, legacy_definitions
    assert {"read_turn", "record_view", "drop_view"} <= KERNEL_ONLY and not {"read_turn", "record_view", "drop_view"} & set(legacy_definitions())


@pytest.fixture
def owner_env(monkeypatch):
    return monkeypatch
