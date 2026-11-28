"""User-visible invariants of the direct workflow; no legacy planner callbacks."""
import asyncio
import json
from datetime import UTC,datetime
import pytest
from app.agent_workflow.graph import deterministic_confidence_gate
from app.agent_workflow.state import AgentRuntimeContext

def test_gate_rejects_cross_company_and_period():
    result={'ok':True,'data':[{'symbol':'NVDA','excerpt':'NVDA net income FY2020','published_at':'2020-01-01'}]}
    assert deterministic_confidence_gate('AAPL FY2025 revenue',result,verified_symbols=['AAPL'])[0] is False

async def _emit(_): pass

