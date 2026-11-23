"""Metrics for ruler: turn results, their JSON form, and the summary that the report renders."""

import math
from collections import Counter
from dataclasses import asdict, dataclass

CALC_TOOLS = ("calculate", "calculate_formula")

# Statuses that are a normal ending of a turn; anything else is a failure.
_NORMAL_STATUSES = ("succeeded", "waiting_for_input", "skipped")
# Only turns that finished normally count toward the timings.
_TIMED_STATUS = "succeeded"
_NO_STOP_REASON = "(none)"


@dataclass
class TurnResult:
    case_id: str
    kind: str
    turn_index: int
    passed: bool
    failed_checks: list[str]
    status: str
    reason: str | None
    first_event_ms: int | None
    first_delta_ms: int | None
    total_ms: int
    tools: list[str]
    model_calls: int | None
    token_usage: int | None
    decision_steps: int | None
    stop_reason: str | None
    answer_chars: int
    answer: str
    error: str | None


def to_json(result: TurnResult) -> dict:
    return asdict(result)


def from_json(data: dict) -> TurnResult:
    return TurnResult(**data)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the value at rank ceil(p * n / 100), or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = min(len(ordered), max(1, math.ceil(p * len(ordered) / 100)))
    return ordered[rank - 1]


def summarize(results: list[TurnResult]) -> dict:
    turns = len(results)
    timed = [result for result in results if result.status == _TIMED_STATUS]
    all_calls = [name for result in results for name in result.tools]
    model_calls = [result.model_calls for result in results if result.model_calls is not None]
    token_usage = [result.token_usage for result in results if result.token_usage is not None]
    stop_reasons = Counter(
        result.stop_reason if result.stop_reason is not None else _NO_STOP_REASON for result in results
    )
    kinds = dict.fromkeys(result.kind for result in results)

    return {
        "turns": turns,
        "cases": len({result.case_id for result in results}),
        "pass_rate": _ratio(sum(result.passed for result in results), turns),
        "failure_rate": _ratio(sum(result.status not in _NORMAL_STATUSES for result in results), turns),
        "total_ms_p50": _timing(timed, "total_ms", 50),
        "total_ms_p90": _timing(timed, "total_ms", 90),
        "first_delta_ms_p50": _timing(timed, "first_delta_ms", 50),
        "first_delta_ms_p90": _timing(timed, "first_delta_ms", 90),
        "first_event_ms_p50": _timing(timed, "first_event_ms", 50),
        "tool_calls_mean": _ratio(len(all_calls), turns),
        "calc_share": _ratio(sum(name in CALC_TOOLS for name in all_calls), len(all_calls)),
        "model_calls_mean": _mean(model_calls),
        "token_usage_mean": _mean(token_usage),
        "stop_reasons": dict(stop_reasons),
        "by_kind": {kind: _kind_summary([result for result in results if result.kind == kind]) for kind in kinds},
        "failed": [
            {
                "case_id": result.case_id,
                "turn_index": result.turn_index,
                "status": result.status,
                "failed_checks": list(result.failed_checks),
            }
            for result in results
            if not result.passed
        ],
    }


def _kind_summary(results: list[TurnResult]) -> dict:
    timed = [result for result in results if result.status == _TIMED_STATUS]
    return {
        "turns": len(results),
        "pass_rate": _ratio(sum(result.passed for result in results), len(results)),
        "total_ms_p50": _timing(timed, "total_ms", 50),
        "total_ms_p90": _timing(timed, "total_ms", 90),
        "first_delta_ms_p50": _timing(timed, "first_delta_ms", 50),
        "first_event_ms_p50": _timing(timed, "first_event_ms", 50),
    }


def _timing(results: list[TurnResult], field: str, p: int) -> float | None:
    # A turn with no value for this field (for example, no delta ever arrived) is left out.
    values = [getattr(result, field) for result in results if getattr(result, field) is not None]
    return percentile(values, p)


def _ratio(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
