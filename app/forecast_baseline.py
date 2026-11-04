"""``naive-vol-v1``: a free, zero-drift volatility baseline for the ±2% question.

Pure functions: no database, no network, no writes. The baseline is computed
at read time from a version's frozen ``feature_snapshot`` and never stored.
Never change this formula silently; a new formula gets a new version name.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from .forecast_evaluation_v2 import LOG_LOSS_EPSILON

BASELINE_VERSION = "naive-vol-v1"
_CLASSES = ("bearish", "neutral", "bullish")
_TRADING_DAYS_PER_YEAR = 252
_NORMAL = NormalDist()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def naive_vol_probabilities(feature_snapshot: dict | None) -> dict[str, float] | None:
    """Zero-drift normal for the remaining simple return, anchored to the original close.

    Returns ``None`` when any input is missing or not a finite non-bool number,
    or when sigma <= 0, remaining sessions <= 0 or the realized return <= -1.
    Strings are never coerced.
    """

    if not isinstance(feature_snapshot, dict):
        return None
    sigma = _number(feature_snapshot.get("volatility_20d"))
    sessions = _number(feature_snapshot.get("remaining_sessions"))
    realized = _number(feature_snapshot.get("realized_return_from_anchor"))
    if sigma is None or sessions is None or realized is None:
        return None
    if sigma <= 0 or sessions <= 0 or realized <= -1:
        return None
    q = sigma * math.sqrt(sessions / _TRADING_DAYS_PER_YEAR)
    bullish = 1.0 - _NORMAL.cdf((1.02 / (1.0 + realized) - 1.0) / q)
    bearish = _NORMAL.cdf((0.98 / (1.0 + realized) - 1.0) / q)
    neutral = max(0.0, 1.0 - bullish - bearish)
    return {"bearish": bearish, "neutral": neutral, "bullish": bullish}


def score_against_label(probabilities: dict[str, float], actual_label: str) -> dict[str, float]:
    """Same arithmetic as ``forecast_evaluation_v2._scores_for``: 3-class Brier, floored log loss."""

    if actual_label not in _CLASSES:
        raise ValueError(f"unknown label: {actual_label!r}")
    brier = sum(
        (float(probabilities[name]) - (1.0 if name == actual_label else 0.0)) ** 2 for name in _CLASSES
    )
    log_loss = -math.log(max(float(probabilities[actual_label]), LOG_LOSS_EPSILON))
    return {"brier_score": brier, "log_loss": log_loss}
