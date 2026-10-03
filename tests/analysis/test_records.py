"""Category A/D: `researchos.analysis.records` — persisted
`AnalysisRecord`/`AnalysisInput` rows for pairwise comparison,
repeated-run aggregation, and ranking."""

from __future__ import annotations

import pytest

from researchos.analysis.errors import InvalidAnalysisInputError
from researchos.analysis.records import aggregate_runs, compare_runs, rank_runs
from researchos.db import repository
from researchos.db.models import AnalysisInputType, AnalysisRecordStatus


def test_compare_runs_persists_completed_record_with_inputs(session_factory, project_id, two_comparable_run_ids):
    baseline_id, comparison_id = two_comparable_run_ids
    record = compare_runs(project_id, baseline_id, comparison_id, "f1", actor="tester", session_factory=session_factory)

    assert record.status == AnalysisRecordStatus.COMPLETED
    assert record.method == "pairwise_comparison"
    assert record.result["absolute_difference"] == pytest.approx(0.05)
    assert record.result["percentage_change"] == pytest.approx(6.25)
    assert record.version == 1
    assert record.supersedes_id is None
    assert record.software_versions is not None

    with session_factory() as session:
        inputs = repository.list_analysis_inputs(session, project_id, analysis_record_id=record.id)
    run_inputs = [i for i in inputs if i.input_type == AnalysisInputType.RUN]
    metric_inputs = [i for i in inputs if i.input_type == AnalysisInputType.METRIC]
    assert {i.input_id for i in run_inputs} == {baseline_id, comparison_id}
    assert len(metric_inputs) == 2


def test_compare_runs_not_comparable_still_persists_a_record(session_factory, project_id, experiment_id):
    from researchos.db.models import MetricValueType

    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT, unit="ratio")
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.9, value_type=MetricValueType.FLOAT, unit="percent")
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    record = compare_runs(project_id, run1_id, run2_id, "f1", actor="tester", session_factory=session_factory)
    assert record.status == AnalysisRecordStatus.NOT_COMPARABLE
    assert record.result["comparable"] is False
    assert record.result["reasons"]
    # Never a scientific verdict phrase anywhere in the persisted result.
    reasons_text = " ".join(record.result["reasons"]).lower()
    assert "better" not in reasons_text
    assert "worse" not in reasons_text


def test_compare_runs_zero_baseline_omits_relative_and_percentage(session_factory, project_id, experiment_id):
    from researchos.db.models import MetricValueType

    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="delta", value=0.0, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="delta", value=5.0, value_type=MetricValueType.FLOAT)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    record = compare_runs(project_id, run1_id, run2_id, "delta", actor="tester", session_factory=session_factory)
    assert record.status == AnalysisRecordStatus.COMPLETED
    assert record.result["absolute_difference"] == pytest.approx(5.0)
    assert "relative_difference" not in record.result
    assert "percentage_change" not in record.result


def test_aggregate_runs_persists_completed_record(session_factory, project_id, three_repeated_run_ids):
    record = aggregate_runs(project_id, three_repeated_run_ids, "f1", actor="tester", session_factory=session_factory)
    assert record.status == AnalysisRecordStatus.COMPLETED
    assert record.method == "repeated_run_aggregation"
    assert record.result["n"] == 3
    assert record.result["mean"] == pytest.approx(0.826666667, rel=1e-6)

    with session_factory() as session:
        inputs = repository.list_analysis_inputs(session, project_id, analysis_record_id=record.id)
    run_inputs = {i.input_id for i in inputs if i.input_type == AnalysisInputType.RUN}
    assert run_inputs == set(three_repeated_run_ids)


def test_aggregate_runs_requires_at_least_one_run(session_factory, project_id):
    with pytest.raises(InvalidAnalysisInputError):
        aggregate_runs(project_id, [], "f1", actor="tester", session_factory=session_factory)


def test_aggregate_runs_rejects_run_missing_the_metric(session_factory, project_id, experiment_id, three_repeated_run_ids):
    with session_factory() as session:
        run = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        session.commit()
        run_without_metric_id = run.id

    with pytest.raises(InvalidAnalysisInputError):
        aggregate_runs(
            project_id, three_repeated_run_ids + [run_without_metric_id], "f1", actor="tester",
            session_factory=session_factory,
        )
    # Nothing partial was persisted for the rejected request.
    with session_factory() as session:
        records = repository.list_analysis_records(session, project_id, method="repeated_run_aggregation")
    assert records == []


def test_rank_runs_produces_pure_ordering_never_best_or_winner(session_factory, project_id, three_repeated_run_ids):
    record = rank_runs(project_id, three_repeated_run_ids, "f1", actor="tester", session_factory=session_factory)
    assert record.status == AnalysisRecordStatus.COMPLETED
    ranked = record.result["ranked"]
    assert len(ranked) == 3
    assert ranked[0]["rank"] == 1
    result_text = str(record.result).lower()
    assert "best" not in result_text
    assert "winner" not in result_text


def test_analysis_record_versioning_via_supersedes_id(session_factory, project_id, two_comparable_run_ids):
    first = compare_runs(project_id, *two_comparable_run_ids, "f1", actor="tester", session_factory=session_factory)
    second = compare_runs(
        project_id, *two_comparable_run_ids, "f1", actor="tester", supersedes_id=first.id,
        session_factory=session_factory,
    )
    assert second.version == first.version + 1
    assert second.supersedes_id == first.id
    # The original record is never mutated.
    with session_factory() as session:
        reloaded_first = repository.get_analysis_record(session, first.id)
    assert reloaded_first.version == 1
    assert reloaded_first.result == first.result
