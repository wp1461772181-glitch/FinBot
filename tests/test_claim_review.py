import asyncio
import json

from app.agent_workflow.claim_judge import JudgeResult, JudgeSource
from app.agent_workflow.claim_review import review_candidate


def test_closed_review_hides_first_verdict_and_fails_closed():
    source = JudgeSource(1, 'Revenue in Q2 was 100.', complete=True)
    candidate = JudgeResult(status='ok', verdict='contradiction', subtype='number', quote=source.text,
                            quote_verified=True, quote_ordinal=1, reason='secret first verdict')
    async def run(answers):
        async def call(model, system, user):
            assert 'secret first verdict' not in user and 'contradiction' not in user
            return {}, {'content': json.dumps(answers)}
        return await review_candidate('Revenue was 90.', 'In Q2.', [source], candidate, {}, call=call)
    yes = dict.fromkeys(('subject', 'metric', 'period', 'conditions', 'incompatible'), 'yes')
    assert asyncio.run(run(yes))['passed']
    assert not asyncio.run(run({**yes, 'period': 'uncertain'}))['passed']
    assert asyncio.run(run({'subject': 'yes'}))['status'] == 'parse_error'


def test_subject_needs_verified_name_and_complete_quote_block():
    candidate = JudgeResult(status='ok', verdict='contradiction', subtype='subject', quote='Alpha sold 10',
                            quote_verified=True, quote_ordinal=1)
    result = asyncio.run(review_candidate('Beta sold 10', '', [JudgeSource(1, 'Alpha sold 10')], candidate, {}))
    assert result['status'] == 'not_reviewed' and not result['passed']
