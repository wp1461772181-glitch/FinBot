"""Jev no longer forecasts. The word may stay only where a record or a non-forecast check still needs it."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Memory gate and claim check: not forecasting.
_NOT_FORECASTING = {
    "app/jev_memory_gate.py",
    "app/jev_claim_support.py",
    "app/agent_workflow/claim_gate_flags.py",
    "app/agent_workflow/claim_review.py",
    "app/agent_workflow/direct.py",
    "app/agent_profile_extract.py",
    "scripts/score_claim_jev_labels.py",
}
# Old versions must still score.
_OLD_VERSIONS_STILL_SCORE = {"app/forecast_evaluation_v2.py", "app/forecast_v2.py"}
# CHECK constraint and the retained calibrator table.
_SCHEMA = {"app/forecast_v2_models.py", "scripts/migrate_agent_forecast.py"}
# The experimental_jev comparison for old versions.
_COMPARISON = {"app/forecast_v2_api.py"}

ALLOWED = _NOT_FORECASTING | _OLD_VERSIONS_STILL_SCORE | _SCHEMA | _COMPARISON

# Must have zero matches, whatever else is allowed.
FORBIDDEN = (
    "app/agent_forecast_processor.py",
    "app/official_monitor_v2.py",
    "app/forecast_worker.py",
    "app/forecast_model_provider.py",
)


def _files_mentioning_jev() -> set[str]:
    found: set[str] = set()
    for folder in ("app", "scripts"):
        for path in sorted((ROOT / folder).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if "jev" in rel.lower():
                found.add(rel)
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "jev" in text.lower():
                found.add(rel)
    return found


def test_jev_appears_only_in_the_agreed_files():
    unexpected = sorted(_files_mentioning_jev() - ALLOWED)
    assert unexpected == [], f"Jev found outside the retirement allowlist: {unexpected}"


def test_the_forecast_path_has_no_jev_at_all():
    text_by_file = {name: (ROOT / name).read_text(encoding="utf-8").lower() for name in FORBIDDEN}
    assert [name for name, text in text_by_file.items() if "jev" in text] == []


def test_the_calibrator_modules_and_scripts_are_gone():
    for name in (
        "app/jev_learning.py",
        "scripts/enqueue_jev_history_batch.py",
        "scripts/watch_and_train_jev_history.py",
        "scripts/train_jev_historical_research.py",
        "scripts/backfill_jev_replay_prices.py",
        "tests/test_jev_learning.py",
    ):
        assert not (ROOT / name).exists(), name
