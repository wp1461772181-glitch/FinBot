"""decider_from_manifest: who decided a version, straight from its frozen manifest."""
from app.forecast_decider import decider_from_manifest

FULL = {
    "time_mode": "observed", "decision_mode": "llm", "model_status": "experimental_llm",
    "decision_provider": {"provider": "zhipu", "actual_model": "glm-5.3-flash", "question_version": "llm-direction-v1",
                          "binding": {"source": "role", "role_model": "glm"}},
    "local_calibration": {"status": "not_applied"},
}


def test_full_manifest():
    assert decider_from_manifest(FULL, {}) == {
        "provider": "zhipu", "actual_model": "glm-5.3-flash", "question_version": "llm-direction-v1",
        "time_mode": "observed", "decision_mode": "llm", "binding": {"source": "role", "role_model": "glm"},
        "calibration_status": "not_applied",
    }


def test_jev_manifest():
    manifest = {"model_status": "experimental_jev", "decision_mode": "jev",
                "decision_provider": {"provider": "jev", "actual_model": "jev-v1", "question_version": "jev-direction"},
                "local_calibration": {"status": "active"}}
    result = decider_from_manifest(manifest, {"time_mode": "historical_research"})
    assert result["provider"] == "jev" and result["actual_model"] == "jev-v1"
    assert result["binding"] is None and result["calibration_status"] == "active"
    assert result["time_mode"] == "historical_research"  # falls back to the research report


def test_missing_fields_are_none_not_unknown():
    empty = {"provider": None, "actual_model": None, "question_version": None, "time_mode": None,
             "decision_mode": None, "binding": None, "calibration_status": None}
    for manifest in (None, {}, "junk", {"decision_provider": "x", "local_calibration": 3}):
        assert decider_from_manifest(manifest, None) == empty
    partial = decider_from_manifest({"decision_provider": {"actual_model": "  ", "binding": {"source": "bogus"}}}, {})
    assert partial["actual_model"] is None and partial["binding"] is None
    unset = decider_from_manifest({"decision_provider": {"binding": {"source": "server_default", "role_model": None}}}, {})
    assert unset["binding"] == {"source": "server_default", "role_model": None}
