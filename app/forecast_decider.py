"""Who decided a forecast version, read from its frozen manifest (pure; no database, no network).

Absent values are ``None``, never "unknown": a version that predates a field shows 未记录 in the UI.
``binding`` exists only on versions written after B6 (how the forecast role resolved: role / server_default /
role_model_missing); older versions have ``None``, which is never inferred.
"""
from __future__ import annotations

from typing import Any

_BINDING_SOURCES = ("role", "server_default", "role_model_missing")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _binding(value: Any) -> dict | None:
    if not isinstance(value, dict) or value.get("source") not in _BINDING_SOURCES:
        return None
    return {"source": value["source"], "role_model": _text(value.get("role_model"))}


def decider_from_manifest(manifest: Any, research_report: Any) -> dict:
    manifest = manifest if isinstance(manifest, dict) else {}
    report = research_report if isinstance(research_report, dict) else {}
    provider = manifest.get("decision_provider") if isinstance(manifest.get("decision_provider"), dict) else {}
    calibration = manifest.get("local_calibration") if isinstance(manifest.get("local_calibration"), dict) else {}
    return {
        "provider": _text(provider.get("provider")),
        "actual_model": _text(provider.get("actual_model")),
        "question_version": _text(provider.get("question_version")),
        "time_mode": _text(manifest.get("time_mode")) or _text(report.get("time_mode")),
        "decision_mode": _text(manifest.get("decision_mode")) or _text(report.get("decision_mode")),
        "binding": _binding(provider.get("binding")),
        "calibration_status": _text(calibration.get("status")),
    }
