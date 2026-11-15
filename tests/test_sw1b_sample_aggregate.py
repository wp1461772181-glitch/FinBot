"""SW1B B2 (spec-sw1b §4.2, B15–B18): the sample-aggregate permission in the instruction the model is shown."""
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

SWITCH = 'FINBOT_SW1B_SAMPLE_AGGREGATE'
PRIOR_GUEST_LIMIT = int(4505 * 0.7)   # test_agent_prompt_contract's ceiling for the guest instruction (3153)


def _instruction(credential='guest', closing=False):
    async def emit(_):
        pass
    turn = direct.Turn('q', AgentRuntimeContext('custom', 'test', 'dummy', identity_credential=credential), emit, [], {})
    return turn.tool_messages(closing)[0]['content']


def test_b15_the_permission_follows_the_inference_sentence_once(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    assert '\n'.join(direct.INSTRUCTION).count(direct.SAMPLE_ANCHOR) == 1
    assert direct.SAMPLE_ANCHOR + direct.SAMPLE_AGGREGATE_SENTENCE in _instruction()


def test_b16_switch_off_removes_exactly_the_sentence(monkeypatch):
    text = '\n'.join(direct.INSTRUCTION)
    monkeypatch.delenv(SWITCH, raising=False)
    on_text = direct.evidence_instruction(text)
    on_message = _instruction()
    monkeypatch.setenv(SWITCH, 'off')
    off_text = direct.evidence_instruction(text)
    off_message = _instruction()
    assert direct.SAMPLE_AGGREGATE_SENTENCE not in off_text and direct.SAMPLE_AGGREGATE_SENTENCE not in off_message
    assert on_text.replace(direct.SAMPLE_ANCHOR + direct.SAMPLE_AGGREGATE_SENTENCE, direct.SAMPLE_ANCHOR, 1) == off_text
    assert on_message.replace(direct.SAMPLE_AGGREGATE_SENTENCE, '', 1) == off_message


def test_b17_the_guest_instruction_fits_its_budget_and_the_owner_differs_by_exactly_the_sentence(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    assert len(_instruction('guest')) <= PRIOR_GUEST_LIMIT
    # The owner's instruction was already past the guest ceiling before this sentence (K4), so only the difference is asserted.
    monkeypatch.setattr(direct, 'owner_credential_matches', lambda credential: True)
    owner_on = _instruction('owner-token')
    monkeypatch.setenv(SWITCH, 'off')
    owner_off = _instruction('owner-token')
    assert len(owner_on) - len(owner_off) == len(direct.SAMPLE_AGGREGATE_SENTENCE)


def test_b18_the_sentence_keeps_its_contract():
    sentence = direct.SAMPLE_AGGREGATE_SENTENCE
    for part in ('样本', '各家期间', '标推算', '仍读不到就照实说缺这一家', '不要补数'):
        assert part in sentence
    assert '必须给出' not in sentence
