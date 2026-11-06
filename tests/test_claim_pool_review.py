import asyncio
import json
from app.agent_workflow.claim_judge import JudgeSource
from app.agent_workflow.claim_pool_review import confirm_pool_support


def test_full_support_needs_every_dimension_and_is_independent():
    async def run(period):
        async def call(model, system, user):
            payload = json.loads(user)
            assert 'verdict' not in payload and 'reason' not in payload
            return {}, {'content': json.dumps({**dict.fromkeys(payload['required'], 'yes'), 'period': period})}
        return await confirm_pool_support('Profit 1', [JudgeSource(1, 'Profit 1')], {}, call=call)
    assert asyncio.run(run('yes'))['passed']
    assert not asyncio.run(run('uncertain'))['passed']
