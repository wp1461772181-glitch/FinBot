"""C1–C14 migration: retained independent unit contracts. Legacy planner/node-injection
checks were replaced by production direct-loop, consent and provenance tests; see
docs/reports/agent-routing-test-migration.md. Originals are in Git main 81f62be.
"""
from __future__ import annotations
import asyncio

def test_accession_digits_are_not_interpreted_as_requested_period():
    from app.agent_workflow.graph import deterministic_confidence_gate
    question = "AMD 0000320193-26-000001 这份财报的营收主题是什么"
    result = {"ok": True, "source": "knowledge_chunks", "data": [{"id": "1", "symbol": "AMD",
        "excerpt": "AMD revenue grew in the filing; 营收 increased."}]}
    assert deterministic_confidence_gate(question, result, verified_symbols=["AMD"])[0]


