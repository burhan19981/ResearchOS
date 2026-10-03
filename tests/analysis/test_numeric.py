"""Category A/B: the pure deterministic math core (`researchos.analysis.
numeric`) — basic correctness and numeric safety (NaN/Infinity/empty/
insufficient observations/division by zero)."""

from __future__ import annotations

import math

import pytest

from researchos.analysis import numeric
from researchos.analysis.errors import InsufficientObservationsError, NumericSafetyError


def test_absolute_difference():
    assert numeric.absolute_difference(0.85, 0.80) == pytest.approx(0.05)


def test_relative_difference():
    assert numeric.relative_difference(0.85, 0.80) == pytest.approx(0.0625)


def test_relative_difference_rejects_zero_baseline():
    with pytest.raises(NumericSafetyError):
        numeric.relative_difference(0.85, 0.0)


def test_percentage_change():
    assert numeric.percentage_change(0.80, 0.85) == pytest.approx(6.25)


def test_percentage_change_rejects_zero_baseline():
    with pytest.raises(NumericSafetyError):
        numeric.percentage_change(0.0, 0.85)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_absolute_difference_rejects_non_finite(bad):
    with pytest.raises(NumericSafetyError):
        numeric.absolute_difference(bad, 1.0)
    with pytest.raises(NumericSafetyError):
        numeric.absolute_difference(1.0, bad)


def test_absolute_difference_rejects_bool_and_non_number():
    with pytest.raises(NumericSafetyError):
        numeric.absolute_difference(True, 1.0)
    with pytest.raises(NumericSafetyError):
        numeric.absolute_difference("0.5", 1.0)  # type: ignore[arg-type]


def test_paired_comparison():
    result = numeric.paired_comparison([0.1, 0.2, 0.3], [0.2, 0.2, 0.4])
    assert result["n"] == 3
    assert result["differences"] == pytest.approx([0.1, 0.0, 0.1])
    assert result["mean_difference"] == pytest.approx(0.2 / 3, rel=1e-6)


def test_paired_comparison_rejects_length_mismatch():
    with pytest.raises(NumericSafetyError):
        numeric.paired_comparison([0.1, 0.2], [0.1])


def test_paired_comparison_rejects_empty():
    with pytest.raises(NumericSafetyError):
        numeric.paired_comparison([], [])


def test_compute_mean_median_min_max_range():
    values = [0.80, 0.85, 0.83]
    assert numeric.compute_mean(values) == pytest.approx(0.826666667, rel=1e-6)
    assert numeric.compute_median(values) == pytest.approx(0.83)
    assert numeric.compute_minimum(values) == pytest.approx(0.80)
    assert numeric.compute_maximum(values) == pytest.approx(0.85)
    assert numeric.compute_range(values) == pytest.approx(0.05)


def test_compute_functions_reject_empty():
    with pytest.raises(NumericSafetyError):
        numeric.compute_mean([])


def test_compute_functions_reject_non_finite_member():
    with pytest.raises(NumericSafetyError):
        numeric.compute_mean([0.5, float("nan")])


def test_sample_standard_deviation_requires_two_observations():
    with pytest.raises(InsufficientObservationsError):
        numeric.compute_standard_deviation([0.5], sample=True)
    # Population standard deviation of a single point is well-defined (0.0).
    assert numeric.compute_standard_deviation([0.5], sample=False) == pytest.approx(0.0)


def test_sample_standard_deviation_and_variance():
    values = [0.81, 0.83, 0.82]
    stdev = numeric.compute_standard_deviation(values, sample=True)
    variance = numeric.compute_variance(values, sample=True)
    assert stdev == pytest.approx(math.sqrt(variance), rel=1e-9)
    assert stdev > 0


def test_rank_values_is_a_pure_ordering_not_a_verdict():
    ranked = numeric.rank_values([0.80, 0.85, 0.83], descending=True)
    # Output is ordered by rank (best-ranked first), each entry
    # preserving its original positional `index` into the input.
    assert [r["rank"] for r in ranked] == [1, 2, 3]
    assert [r["index"] for r in ranked] == [1, 2, 0]
    assert [r["value"] for r in ranked] == [0.85, 0.83, 0.80]
    # Never a "best"/"winner" semantic field anywhere in the output.
    for entry in ranked:
        assert "best" not in entry
        assert "winner" not in entry


def test_rank_values_ties_share_competition_rank():
    ranked = numeric.rank_values([0.5, 0.9, 0.9, 0.1], descending=True)
    ranks = {r["index"]: r["rank"] for r in ranked}
    assert ranks[1] == ranks[2] == 1
    assert ranks[0] == 3
    assert ranks[3] == 4


def test_aggregate_repeated_runs_single_observation_has_no_fabricated_spread():
    result = numeric.aggregate_repeated_runs([0.5])
    assert result["n"] == 1
    assert result["mean"] == pytest.approx(0.5)
    assert result["standard_deviation"] is None
    assert result["variance"] is None


def test_aggregate_repeated_runs_multiple_observations():
    result = numeric.aggregate_repeated_runs([0.80, 0.85, 0.83])
    assert result["n"] == 3
    assert result["standard_deviation"] is not None
    assert result["variance"] is not None
    assert result["minimum"] == pytest.approx(0.80)
    assert result["maximum"] == pytest.approx(0.85)


def test_aggregate_repeated_runs_rejects_empty():
    with pytest.raises(NumericSafetyError):
        numeric.aggregate_repeated_runs([])
