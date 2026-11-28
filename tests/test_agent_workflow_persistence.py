"""C1–C14 migration: retained independent unit contracts. Legacy planner/node-injection
checks were replaced by production direct-loop, consent and provenance tests; see
docs/reports/agent-routing-test-migration.md. Originals are in Git main 81f62be.
"""
from __future__ import annotations
import asyncio
from app.agent_workflow.checkpoints import open_postgres_checkpointer
import os

def test_workflow_health_reports_migrated_saver_and_key_configuration(disposable_database, monkeypatch):
    from app.main import agent_workflow_health
    from app.agent_workflow.checkpoints import checkpoint_ready
    database_url=os.environ["DATABASE_URL"]
    async def migrate():
        async with open_postgres_checkpointer(database_url) as saver:
            await saver.setup()
    asyncio.run(migrate())
    monkeypatch.delenv("TAVILY_API_KEY",raising=False)
    assert checkpoint_ready(database_url)
    assert agent_workflow_health()["checkpoint_ready"] is True
    assert agent_workflow_health()["tavily_configured"] is False





def test_postgres_reopen_keeps_the_turn_but_never_the_runtime_key_and_owners_do_not_share_a_thread(disposable_database, monkeypatch):
    """A kernel turn through the real Postgres checkpointer (6b: the old turn's version of this test went with it): the stored state
    holds the turn's answer, never the model key that ran it, and another owner's thread for the same conversation id is empty."""
    import json
    from uuid import uuid4
    import app.agent_chat_provider as provider
    from app.agent_workflow.settings import checkpoint_database_url
    from app.agent_workflow.graph import build_workflow
    from app.agent_workflow.state import AgentRuntimeContext, checkpoint_thread_id
    key = 'synthetic-provider-key-not-for-state'
    chat = str(uuid4())
    thread = checkpoint_thread_id('owner-a', chat)

    async def answer(provider_name, model, api_key, messages, schemas, **kwargs):
        assert api_key == key
        await kwargs["on_text"]("公司销售产品和服务。")
        return {"usage": {"total_tokens": 5}}, {"role": "assistant", "content": "公司销售产品和服务。"}
    monkeypatch.setattr(provider, "stream_decision", answer)

    async def exercise():
        async with open_postgres_checkpointer(checkpoint_database_url()) as saver:
            await saver.setup()
            context = AgentRuntimeContext('anthropic', 'test', key, owner_hash='owner-a', conversation_id=chat, engine="v2")
            value = await build_workflow(saver).ainvoke({'question': '运营模式', 'messages': [{"role": "system", "content": "s"}]},
                                                        {'configurable': {'thread_id': thread}}, context=context)
            assert value['answer'] == '公司销售产品和服务。'
        async with open_postgres_checkpointer(checkpoint_database_url()) as saver:
            restored = (await build_workflow(saver).aget_state({'configurable': {'thread_id': thread}})).values
            assert restored['answer'] == '公司销售产品和服务。'
            assert key not in json.dumps(restored, ensure_ascii=False, default=str)
            other = (await build_workflow(saver).aget_state({'configurable': {'thread_id': checkpoint_thread_id('owner-b', chat)}})).values
            assert not other
    asyncio.run(exercise())
