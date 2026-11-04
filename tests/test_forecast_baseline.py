import pytest

from app.forecast_baseline import BASELINE_VERSION, naive_vol_probabilities, score_against_label


def _snap(sigma=0.40, s=20, r=0.0):
    return {"volatility_20d": sigma, "remaining_sessions": s, "realized_return_from_anchor": r}


def test_worked_example_at_issue():
    p = naive_vol_probabilities(_snap(0.40, 20, 0.0))
    assert p["bullish"] == pytest.approx(0.42957, abs=5e-4)
    assert p["neutral"] == pytest.approx(0.14087, abs=5e-4)
    assert p["bearish"] == pytest.approx(0.42957, abs=5e-4)
    bull = score_against_label(p, "bullish")
    assert bull["brier_score"] == pytest.approx(0.52977, abs=5e-4)
    assert bull["log_loss"] == pytest.approx(0.84498, abs=5e-4)
    assert score_against_label(p, "neutral")["brier_score"] == pytest.approx(1.10716, abs=5e-4)


def test_worked_example_revision_near_target():
    p = naive_vol_probabilities(_snap(0.40, 5, 0.05))
    assert p["bullish"] == pytest.approx(0.69395, abs=5e-4)
    assert p["neutral"] == pytest.approx(0.18768, abs=5e-4)
    assert p["bearish"] == pytest.approx(0.11836, abs=5e-4)


def test_probabilities_sum_to_one():
    for args in [(0.4, 20, 0.0), (0.4, 5, 0.05), (0.1, 1, -0.3), (2.0, 60, 0.5)]:
        p = naive_vol_probabilities(_snap(*args))
        assert sum(p.values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {},
        {"volatility_20d": 0.4, "remaining_sessions": 20},
        {"volatility_20d": None, "remaining_sessions": 20, "realized_return_from_anchor": 0.0},
        _snap(sigma=0),
        _snap(sigma=-0.4),
        _snap(sigma="0.4"),
        _snap(sigma=True),
        _snap(sigma=float("nan")),
        _snap(sigma=float("inf")),
        _snap(s=0),
        _snap(s=-3),
        _snap(s="20"),
        _snap(r=-1),
        _snap(r=-1.5),
        _snap(r="0"),
        _snap(r=float("nan")),
    ],
)
def test_unusable_inputs_return_none(snapshot):
    assert naive_vol_probabilities(snapshot) is None


def test_version_name():
    assert BASELINE_VERSION == "naive-vol-v1"
