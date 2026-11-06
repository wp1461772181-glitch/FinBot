import json

from app.agent_workflow import claim_judge_pin as pin
from app.agent_workflow import claim_shadow


def test_pinned_versions_match_the_code():
    assert pin.version_mismatches() == []


def test_default_model_is_the_pinned_glm_and_env_only_overrides_the_label(monkeypatch):
    monkeypatch.delenv('CLAIM_JUDGE_SHADOW_MODEL', raising=False)
    monkeypatch.delenv('CLAIM_JUDGE_SHADOW_EXPECT_MODEL', raising=False)
    assert pin.load_pin()['judge']['provider'] == 'zhipu'
    assert pin.shadow_model_name() == 'glm-5.3-flash' and pin.expected_model() == 'glm-5.3-flash'
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_MODEL', 'other-label')
    assert pin.shadow_model_name() == 'other-label'


def test_pin_file_holds_no_key(tmp_path):
    text = json.dumps(pin.load_pin(), ensure_ascii=False)
    assert 'api_key' not in text and 'sk-' not in text


def test_shadow_refuses_to_run_when_code_drifts_from_the_pin(monkeypatch, tmp_path):
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW', 'on')
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_DIR', str(tmp_path))
    monkeypatch.delenv('CLAIM_JUDGE_SHADOW_MODEL', raising=False)
    assert claim_shadow.enabled() is True
    drifted = dict(pin.load_pin(), versions=dict(pin.load_pin()['versions'], window='numeric-window-v1'))
    monkeypatch.setattr(pin, 'load_pin', lambda path=None: drifted)
    assert 'window' in pin.version_mismatches()
    assert claim_shadow.enabled() is False
