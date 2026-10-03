"""The analysis service: reads already-recorded execution facts
(`Run`/`Metric`), computes over them via `researchos.analysis.numeric`,
and persists the result as an immutable `AnalysisRecord` with explicit
`AnalysisInput` provenance — LEVEL 2 (COMPUTATION) in the Phase 8
four-level model, never LEVEL 4 (a scientific conclusion).

Every function here reuses `researchos.planning.orchestration.
require_in_project` for existence/project checks (never a bare
repository call) and `researchos.execution.errors`-style typed
exceptions raised by `researchos.analysis.numeric` for invalid numeric
input — a genuinely invalid request never reaches `repository.
create_analysis_record` at all.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import sessionmaker

from .. import __version__ as researchos_version
from ..db import repository
from ..db.engine import session_scope
from ..db.models import AnalysisInputType, AnalysisRecord, AnalysisRecordStatus
from ..planning import orchestration
from . import comparability as comparability_module
from . import numeric
from .errors import InvalidAnalysisInputError

_SOFTWARE_VERSIONS = {"researchos": researchos_version}


def _link_run_and_metric_inputs(session, *, project_id: int, analysis_record_id: int, run_id: int, metric_id: Optional[int]) -> None:
    repository.create_analysis_input(
        session, project_id=project_id, analysis_record_id=analysis_record_id,
        input_type=AnalysisInputType.RUN, input_id=run_id,
    )
    if metric_id is not None:
        repository.create_analysis_input(
            session, project_id=project_id, analysis_record_id=analysis_record_id,
            input_type=AnalysisInputType.METRIC, input_id=metric_id,
        )


def compare_runs(
    project_id: int,
    baseline_run_id: int,
    comparison_run_id: int,
    metric_name: str,
    *,
    actor: str,
    split: Optional[str] = None,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
) -> AnalysisRecord:
    """Pairwise comparison of one metric between two `Run`s — Phase 8
    spec section 27's exact example (`absolute_difference`/
    `relative_change`/`percentage_change`). Checks comparability first
    (`researchos.analysis.comparability.check_comparability`); if the
    two runs are not comparable, this still persists an `AnalysisRecord`
    (`status=NOT_COMPARABLE`, `result={"comparable": False, "reasons":
    [...]}`) — a comparability check that found incompatibility is
    itself a valid, reproducible computed fact, not an error to hide.
    Never writes a sentence like "Run B is scientifically better" —
    `result` contains only numbers and the metric name/split.
    """
    with session_scope(session_factory) as session:
        baseline_run = repository.get_run(session, baseline_run_id)
        orchestration.require_in_project(baseline_run, baseline_run_id, "Run", project_id)
        comparison_run = repository.get_run(session, comparison_run_id)
        orchestration.require_in_project(comparison_run, comparison_run_id, "Run", project_id)
        if supersedes_id is not None:
            superseded = repository.get_analysis_record(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "AnalysisRecord", project_id)

        comparability = comparability_module.check_comparability(
            session, project_id, baseline_run_id, comparison_run_id, metric_name, split=split,
        )
        parameters = {"metric_name": metric_name, "split": split, "baseline_run_id": baseline_run_id, "comparison_run_id": comparison_run_id}

        if not comparability.comparable:
            # Still resolve whatever metric each Run unambiguously has for
            # this name/split, even though the pair overall is not
            # comparable (e.g. a unit mismatch still means both sides
            # resolved a real Metric row) — every input actually available
            # is linked, so the evidence trail is as complete as the
            # inputs allow, never silently thinner than what was found.
            baseline_metric, _ = comparability_module.resolve_unique_metric(session, baseline_run, metric_name, split)
            comparison_metric, _ = comparability_module.resolve_unique_metric(session, comparison_run, metric_name, split)

            record = repository.create_analysis_record(
                session, project_id=project_id, method="pairwise_comparison",
                result={"comparable": False, "reasons": comparability.reasons},
                parameters=parameters, status=AnalysisRecordStatus.NOT_COMPARABLE,
                supersedes_id=supersedes_id, software_versions=dict(_SOFTWARE_VERSIONS),
            )
            _link_run_and_metric_inputs(
                session, project_id=project_id, analysis_record_id=record.id, run_id=baseline_run_id,
                metric_id=(baseline_metric.id if baseline_metric is not None else None),
            )
            _link_run_and_metric_inputs(
                session, project_id=project_id, analysis_record_id=record.id, run_id=comparison_run_id,
                metric_id=(comparison_metric.id if comparison_metric is not None else None),
            )
            repository.append_audit_event(
                session, project_id=project_id, actor=actor, event_type="analysis.comparison_not_comparable",
                description=f"AnalysisRecord #{record.id}: Runs {baseline_run_id}/{comparison_run_id} not comparable for {metric_name!r}",
                metadata={"analysis_record_id": record.id, "reasons": comparability.reasons},
            )
            record_id = record.id
        else:
            baseline_metric, _ = comparability_module.resolve_unique_metric(session, baseline_run, metric_name, split)
            comparison_metric, _ = comparability_module.resolve_unique_metric(session, comparison_run, metric_name, split)

            result = {
                "baseline_value": baseline_metric.value,
                "comparison_value": comparison_metric.value,
                "unit": baseline_metric.unit,
                "absolute_difference": numeric.absolute_difference(comparison_metric.value, baseline_metric.value),
            }
            try:
                result["relative_difference"] = numeric.relative_difference(comparison_metric.value, baseline_metric.value)
                result["percentage_change"] = numeric.percentage_change(baseline_metric.value, comparison_metric.value)
            except Exception:
                # baseline == 0: absolute_difference is still well-defined
                # and reported; relative/percentage change are simply
                # omitted rather than fabricated or raising the whole
                # comparison — see numeric.py's own division-by-zero policy.
                pass

            record = repository.create_analysis_record(
                session, project_id=project_id, method="pairwise_comparison", result=result,
                parameters=parameters, status=AnalysisRecordStatus.COMPLETED,
                supersedes_id=supersedes_id, software_versions=dict(_SOFTWARE_VERSIONS),
            )
            _link_run_and_metric_inputs(session, project_id=project_id, analysis_record_id=record.id, run_id=baseline_run_id, metric_id=baseline_metric.id)
            _link_run_and_metric_inputs(session, project_id=project_id, analysis_record_id=record.id, run_id=comparison_run_id, metric_id=comparison_metric.id)
            repository.append_audit_event(
                session, project_id=project_id, actor=actor, event_type="analysis.comparison_created",
                description=f"AnalysisRecord #{record.id}: compared Runs {baseline_run_id}/{comparison_run_id} on {metric_name!r}",
                metadata={"analysis_record_id": record.id, "result": result},
            )
            record_id = record.id

    with session_scope(session_factory) as session:
        return repository.get_analysis_record(session, record_id)


def aggregate_runs(
    project_id: int,
    run_ids: list[int],
    metric_name: str,
    *,
    actor: str,
    split: Optional[str] = None,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
) -> AnalysisRecord:
    """Repeated-run aggregation (Phase 8 spec section 13's example):
    mean/median/min/max/range/standard-deviation/variance across
    `run_ids`' values for one metric. Every `run_id` is explicit —
    never "the latest N runs" inferred implicitly (Phase 8 spec section
    8). Does not run the full pairwise `check_comparability` (dataset-
    version/fingerprint/unit checks) — aggregation assumes repeated
    measurements of the *same* experimental condition by construction;
    a caller comparing genuinely different conditions should use
    `compare_runs` instead, which does check comparability. Raises
    `InvalidAnalysisInputError` if any run is missing the metric
    unambiguously — never silently drops a run from the aggregation.
    """
    if not run_ids:
        raise InvalidAnalysisInputError("aggregate_runs requires at least one run_id.")

    with session_scope(session_factory) as session:
        if supersedes_id is not None:
            superseded = repository.get_analysis_record(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "AnalysisRecord", project_id)

        values: list[float] = []
        metric_ids: list[int] = []
        for run_id in run_ids:
            run = repository.get_run(session, run_id)
            orchestration.require_in_project(run, run_id, "Run", project_id)
            metric, reasons = comparability_module.resolve_unique_metric(session, run, metric_name, split)
            if metric is None:
                raise InvalidAnalysisInputError("; ".join(reasons))
            values.append(metric.value)
            metric_ids.append(metric.id)

        aggregate = numeric.aggregate_repeated_runs(values)
        parameters = {"metric_name": metric_name, "split": split, "run_ids": list(run_ids)}

        record = repository.create_analysis_record(
            session, project_id=project_id, method="repeated_run_aggregation", result=aggregate,
            parameters=parameters, status=AnalysisRecordStatus.COMPLETED,
            supersedes_id=supersedes_id, software_versions=dict(_SOFTWARE_VERSIONS),
        )
        for run_id, metric_id in zip(run_ids, metric_ids):
            _link_run_and_metric_inputs(session, project_id=project_id, analysis_record_id=record.id, run_id=run_id, metric_id=metric_id)
        repository.append_audit_event(
            session, project_id=project_id, actor=actor, event_type="analysis.analysis_completed",
            description=f"AnalysisRecord #{record.id}: aggregated {len(run_ids)} run(s) on {metric_name!r}",
            metadata={"analysis_record_id": record.id, "run_ids": list(run_ids), "result": aggregate},
        )
        record_id = record.id

    with session_scope(session_factory) as session:
        return repository.get_analysis_record(session, record_id)


def rank_runs(
    project_id: int,
    run_ids: list[int],
    metric_name: str,
    *,
    actor: str,
    split: Optional[str] = None,
    descending: bool = True,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
) -> AnalysisRecord:
    """A purely mathematical ordering of `run_ids` by one metric (Phase
    8 spec section 6/29) — the persisted `result` contains only
    `{"index": ..., "run_id": ..., "value": ..., "rank": ...}` entries;
    it never contains any "best"/"winner" semantic field."""
    if not run_ids:
        raise InvalidAnalysisInputError("rank_runs requires at least one run_id.")

    with session_scope(session_factory) as session:
        if supersedes_id is not None:
            superseded = repository.get_analysis_record(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "AnalysisRecord", project_id)

        values: list[float] = []
        metric_ids: list[int] = []
        for run_id in run_ids:
            run = repository.get_run(session, run_id)
            orchestration.require_in_project(run, run_id, "Run", project_id)
            metric, reasons = comparability_module.resolve_unique_metric(session, run, metric_name, split)
            if metric is None:
                raise InvalidAnalysisInputError("; ".join(reasons))
            values.append(metric.value)
            metric_ids.append(metric.id)

        ranked = numeric.rank_values(values, descending=descending)
        # Replace the numeric-only "index" with the caller's actual run_id
        # for readability, without losing the original positional index.
        result_entries = [{"run_id": run_ids[entry["index"]], **entry} for entry in ranked]
        parameters = {"metric_name": metric_name, "split": split, "run_ids": list(run_ids), "descending": descending}

        record = repository.create_analysis_record(
            session, project_id=project_id, method="ranking", result={"ranked": result_entries},
            parameters=parameters, status=AnalysisRecordStatus.COMPLETED,
            supersedes_id=supersedes_id, software_versions=dict(_SOFTWARE_VERSIONS),
        )
        for run_id, metric_id in zip(run_ids, metric_ids):
            _link_run_and_metric_inputs(session, project_id=project_id, analysis_record_id=record.id, run_id=run_id, metric_id=metric_id)
        repository.append_audit_event(
            session, project_id=project_id, actor=actor, event_type="analysis.analysis_completed",
            description=f"AnalysisRecord #{record.id}: ranked {len(run_ids)} run(s) on {metric_name!r}",
            metadata={"analysis_record_id": record.id, "run_ids": list(run_ids)},
        )
        record_id = record.id

    with session_scope(session_factory) as session:
        return repository.get_analysis_record(session, record_id)
