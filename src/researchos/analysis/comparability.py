"""Explicit comparability checking (Phase 8 spec section 12): two
numbers are never assumed comparable merely because they share a
metric name.

`check_comparability` never guesses — it returns a structured
`ComparabilityResult` naming every mismatch it found, or raises a
typed error for a genuine caller mistake (an unknown/cross-project Run
id, which is not itself a comparability *finding*, it is a request
that cannot even be evaluated).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import Metric, Run
from ..planning import orchestration
from .types import ComparabilityResult


def resolve_unique_metric(session: Session, run: Run, metric_name: str, split: Optional[str]) -> tuple[Optional[Metric], list[str]]:
    """Returns `(metric_or_None, reasons)` — `reasons` is non-empty
    exactly when no single, unambiguous `Metric` row could be resolved
    (missing entirely, or ambiguous across multiple splits with no
    `split` given to disambiguate)."""
    candidates = [m for m in repository.list_metrics(session, run.project_id, run_id=run.id, name=metric_name)]
    if split is not None:
        candidates = [m for m in candidates if m.split == split]
    if not candidates:
        return None, [f"Run {run.id} has no metric named {metric_name!r}" + (f" for split {split!r}" if split else "") + "."]
    if len(candidates) > 1:
        distinct_splits = sorted({c.split for c in candidates}, key=lambda s: (s is None, s))
        return None, [
            f"Run {run.id} has {len(candidates)} metrics named {metric_name!r} across splits "
            f"{distinct_splits} — specify split= to disambiguate."
        ]
    return candidates[0], []


def check_comparability(
    session: Session,
    project_id: int,
    baseline_run_id: int,
    comparison_run_id: int,
    metric_name: str,
    *,
    split: Optional[str] = None,
) -> ComparabilityResult:
    """Checks (Phase 8 spec section 12): same project (a genuine
    caller error, not a finding — raised, not returned), same
    `DatasetVersion` id, same dataset content fingerprint, the metric
    exists unambiguously on both runs, and the two resolved metrics
    share the same unit and evaluation split.
    """
    baseline_run = repository.get_run(session, baseline_run_id)
    orchestration.require_in_project(baseline_run, baseline_run_id, "Run", project_id)
    comparison_run = repository.get_run(session, comparison_run_id)
    orchestration.require_in_project(comparison_run, comparison_run_id, "Run", project_id)

    reasons: list[str] = []

    if baseline_run.dataset_version_id != comparison_run.dataset_version_id:
        reasons.append(
            f"different DatasetVersion ids: {baseline_run.dataset_version_id} vs {comparison_run.dataset_version_id}."
        )
    if baseline_run.dataset_fingerprint != comparison_run.dataset_fingerprint:
        reasons.append(
            f"different dataset content fingerprints: {baseline_run.dataset_fingerprint!r} vs "
            f"{comparison_run.dataset_fingerprint!r}."
        )

    baseline_metric, baseline_reasons = resolve_unique_metric(session, baseline_run, metric_name, split)
    comparison_metric, comparison_reasons = resolve_unique_metric(session, comparison_run, metric_name, split)
    reasons.extend(baseline_reasons)
    reasons.extend(comparison_reasons)

    if baseline_metric is not None and comparison_metric is not None:
        if baseline_metric.unit != comparison_metric.unit:
            reasons.append(f"metric unit mismatch: {baseline_metric.unit!r} vs {comparison_metric.unit!r}.")
        if baseline_metric.split != comparison_metric.split:
            reasons.append(f"different evaluation splits: {baseline_metric.split!r} vs {comparison_metric.split!r}.")

    return ComparabilityResult(comparable=(len(reasons) == 0), reasons=reasons)
