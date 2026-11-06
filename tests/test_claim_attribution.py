from app.agent_workflow.claim_attribution import number_presence
from app.agent_workflow.claim_judge import JudgeSource


def test_absence_needs_complete_parseable_sources():
    complete = [JudgeSource(1, 'Revenue was $0.25.', complete=True)]
    assert number_presence('$0.25', complete) == 'present'
    assert number_presence('$0.43', complete) == 'absent'
    assert number_presence('$0.43', [JudgeSource(1, 'Revenue $0.25', complete=False)]) == 'unknown'
    assert number_presence('$0.43', complete, truncated=True) == 'unknown'
    assert number_presence('$0.43', [JudgeSource(1, 'half a dollar', complete=True)]) == 'unknown'


def test_attribution_candidate_needs_closed_confirmation_and_complete_source():
    import asyncio
    import json
    from app.agent_workflow.claim_judge import judge_claims
    async def run(complete, direct):
        async def call(model, system, user):
            payload = json.loads(user)
            answers = [{'id': item['id'], 'direct': direct} for item in payload['absent_numbers']]
            return {}, {'content': json.dumps({'verdict': 'supported', 'quote': '', 'direct_answers': answers})}
        return await judge_claims('Reported $0.43', [JudgeSource(1, 'Revenue was $0.25.', complete=complete)], {}, call=call)
    assert asyncio.run(run(True, 'yes')).attribution_candidates
    assert not asyncio.run(run(True, 'no')).attribution_candidates
    assert not asyncio.run(run(False, 'yes')).attribution_candidates
