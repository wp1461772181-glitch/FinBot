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



