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


def test_direction_in_words_is_not_absence():
    # 'declined about 19.2%' with the source's '−19.2%' is present; only a missing magnitude is absent.
    assert number_presence('19.2%', [JudgeSource(1, 'Q2 2026 | −19.2%', complete=True)]) == 'present'
    assert number_presence('19.3%', [JudgeSource(1, 'Q2 2026 | −19.2%', complete=True)]) == 'absent'
