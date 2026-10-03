"""The deterministic, domain-neutral analysis core — LEVEL 2
(COMPUTATION) in the Phase 8 four-level model.

Every function here is pure (no I/O, no database, no randomness) and
operates only on plain `float`/`int` values already extracted from
`Metric` rows by a caller in `researchos.analysis.records` — this
module has no idea what a "Run" or a "Metric" even is. Uses only the
Python standard library `statistics` module (no `numpy`/`scipy`
dependency was added — none exists in `pyproject.toml`, and none is
needed for the deterministic descriptive statistics this phase
implements).

**No inferential statistics** (hypothesis tests, p-values, confidence
intervals) are implemented in this phase — see
docs/PHASE8_ANALYSIS_SCIENTIFIC_REVIEW.md's Statistics section for why:
Phase 8 spec section 13 requires that if significance testing is ever
introduced, it must explicitly carry its test/assumptions/sample
size/alpha/p-value/effect-size — a half-implemented significance
claim (or one silently smuggled in via an unvalidated third-party
statistics library) is worse than none. This module only ever produces
descriptive facts (mean, median, standard deviation, ...), never a
significance verdict.

Every function rejects NaN/Infinity/empty/insufficient input outright
via `NumericSafetyError`/`InsufficientObservationsError` — never
silently coerces an invalid value into a plausible-looking result
(Phase 8 spec section 7).
"""

from __future__ import annotations

import math
import statistics as _stats
from typing import Sequence

from .errors import InsufficientObservationsError, NumericSafetyError


def _validate_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NumericSafetyError(f"{name} must be a number, got {value!r}.")
    if not math.isfinite(value):
        raise NumericSafetyError(f"{name} must be finite (NaN/Infinity are rejected), got {value!r}.")
    return float(value)


def _validate_population(values: Sequence[float], *, min_size: int, name: str = "values") -> list[float]:
    if values is None or len(values) == 0:
        raise NumericSafetyError(f"{name} must not be empty.")
    validated = [_validate_finite(v, f"{name}[{i}]") for i, v in enumerate(values)]
    if len(validated) < min_size:
        raise InsufficientObservationsError(
            f"{name} has {len(validated)} observation(s); at least {min_size} required."
        )
    return validated


# --------------------------------------------------------------------------
# Pairwise comparison
# --------------------------------------------------------------------------


def absolute_difference(a: float, b: float) -> float:
    """`a - b`. No directional/scientific meaning is implied by the
    sign — the caller decides what `a`/`b` represent."""
    a = _validate_finite(a, "a")
    b = _validate_finite(b, "b")
    return a - b


def relative_difference(a: float, b: float) -> float:
    """`(a - b) / |b|` — the difference expressed as a fraction of
    `b`. Raises `NumericSafetyError` if `b == 0` (division by zero is
    never silently treated as infinity or zero)."""
    a = _validate_finite(a, "a")
    b = _validate_finite(b, "b")
    if b == 0:
        raise NumericSafetyError("relative_difference is undefined when b == 0 (division by zero).")
    return (a - b) / abs(b)


def percentage_change(baseline: float, new: float) -> float:
    """`(new - baseline) / baseline * 100`. Raises `NumericSafetyError`
    if `baseline == 0`."""
    baseline = _validate_finite(baseline, "baseline")
    new = _validate_finite(new, "new")
    if baseline == 0:
        raise NumericSafetyError("percentage_change is undefined when baseline == 0 (division by zero).")
    return (new - baseline) / baseline * 100.0


def paired_comparison(baseline_values: Sequence[float], comparison_values: Sequence[float]) -> dict:
    """Element-wise `comparison[i] - baseline[i]` for two equal-length,
    already-matched (e.g. same seed, same fold) sequences. Raises
    `NumericSafetyError` if the sequences differ in length or either is
    empty."""
    baseline = _validate_population(baseline_values, min_size=1, name="baseline_values")
    comparison = _validate_population(comparison_values, min_size=1, name="comparison_values")
    if len(baseline) != len(comparison):
        raise NumericSafetyError(
            f"paired_comparison requires equal-length sequences, got {len(baseline)} and {len(comparison)}."
        )
    differences = [c - b for b, c in zip(baseline, comparison)]
    return {
        "n": len(differences),
        "differences": differences,
        "mean_difference": _stats.fmean(differences),
    }


# --------------------------------------------------------------------------
# Single-population descriptive statistics
# --------------------------------------------------------------------------


def compute_mean(values: Sequence[float]) -> float:
    validated = _validate_population(values, min_size=1)
    return _stats.fmean(validated)


def compute_median(values: Sequence[float]) -> float:
    validated = _validate_population(values, min_size=1)
    return _stats.median(validated)


def compute_minimum(values: Sequence[float]) -> float:
    validated = _validate_population(values, min_size=1)
    return min(validated)


def compute_maximum(values: Sequence[float]) -> float:
    validated = _validate_population(values, min_size=1)
    return max(validated)


def compute_range(values: Sequence[float]) -> float:
    validated = _validate_population(values, min_size=1)
    return max(validated) - min(validated)


def compute_standard_deviation(values: Sequence[float], *, sample: bool = True) -> float:
    """Sample standard deviation (`sample=True`, Bessel's correction,
    `n - 1` denominator — appropriate when `values` is a sample of a
    larger population, e.g. a handful of repeated runs) requires at
    least 2 observations. Population standard deviation (`sample=False`)
    requires at least 1."""
    validated = _validate_population(values, min_size=2 if sample else 1)
    return _stats.stdev(validated) if sample else _stats.pstdev(validated)


def compute_variance(values: Sequence[float], *, sample: bool = True) -> float:
    validated = _validate_population(values, min_size=2 if sample else 1)
    return _stats.variance(validated) if sample else _stats.pvariance(validated)


def rank_values(values: Sequence[float], *, descending: bool = True) -> list[dict]:
    """A purely mathematical ordering — `[{"index": <original index>,
    "value": <value>, "rank": <1-based position>}, ...]`. This is
    **not** a scientific verdict (Phase 8 spec section 6/29): the
    result never contains a word like "best"/"winner", and callers
    must not present it as one. Ties share the same rank (competition
    ranking, e.g. 1, 2, 2, 4)."""
    validated = _validate_population(values, min_size=1)
    order = sorted(range(len(validated)), key=lambda i: validated[i], reverse=descending)
    ranked: list[dict] = []
    current_rank = 0
    previous_value = None
    for position, index in enumerate(order, start=1):
        value = validated[index]
        if value != previous_value:
            current_rank = position
        ranked.append({"index": index, "value": value, "rank": current_rank})
        previous_value = value
    return ranked


def aggregate_repeated_runs(values: Sequence[float]) -> dict:
    """The Phase 8 spec section 13 example: repeated-run aggregation.
    `n=1` still produces a result (mean = the single value; no
    standard deviation/variance, which are `None` rather than a
    fabricated `0.0` — a single observation has no meaningful spread).
    Never includes a significance claim of any kind."""
    validated = _validate_population(values, min_size=1)
    n = len(validated)
    result = {
        "n": n,
        "mean": _stats.fmean(validated),
        "median": _stats.median(validated),
        "minimum": min(validated),
        "maximum": max(validated),
        "range": max(validated) - min(validated),
        "standard_deviation": _stats.stdev(validated) if n >= 2 else None,
        "variance": _stats.variance(validated) if n >= 2 else None,
    }
    return result
