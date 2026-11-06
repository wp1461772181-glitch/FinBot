import asyncio
import json
from app.agent_workflow.claim_judge import JudgeSource
from app.agent_workflow.claim_pool_review import confirm_pool_support, pool_record


def _run(period, ordinal=1):
    async def call(model, system, user):
        payload = json.loads(user)
        assert 'verdict' not in payload and 'reason' not in payload
        return {}, {'content': json.dumps({**dict.fromkeys(payload['required'], 'yes'), 'period': period,
                                           'ordinal': ordinal})}
    return asyncio.run(confirm_pool_support('Profit 1', [JudgeSource(1, 'Profit 1')], {}, call=call))


def test_full_support_needs_every_dimension_and_a_code_given_ordinal():
    assert _run('yes')['passed'] and _run('yes')['ordinal'] == 1
    assert not _run('uncertain')['passed']
    assert not _run('yes', ordinal=9)['passed']
    assert pool_record(_run('yes')) == {'status': 'found', 'ordinal': 1}
    assert pool_record(_run('uncertain')) == {'status': 'not_found_in_visible_material', 'note': '当前可见材料未找到依据'}
    assert pool_record(None) is None
