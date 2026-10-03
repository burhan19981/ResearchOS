"""Category C: comparability checking (`researchos.analysis.
comparability`). Two Runs are never assumed comparable merely because
they share a metric name."""

from __future__ import annotations

import pytest

from researchos.analysis.comparability import check_comparability, resolve_unique_metric
from researchos.analysis.errors import CrossProjectReferenceError, MissingEntityError
from researchos.db import repository
from researchos.db.models import MetricValueType


def test_comparable_runs(session_factory, project_id, two_comparable_run_ids):
    with session_factory() as session:
        result = check_comparability(session, project_id, *two_comparable_run_ids, "f1")
    assert result.comparable is True
    assert result.reasons == []


def test_unit_mismatch_is_not_comparable(session_factory, project_id, experiment_id):
    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT, unit="ratio")
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.9, value_type=MetricValueType.FLOAT, unit="percent")
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    with session_factory() as session:
        result = check_comparability(session, project_id, run1_id, run2_id, "f1")
    assert result.comparable is False
    assert any("unit mismatch" in reason for reason in result.reasons)


def test_dataset_version_mismatch_is_not_comparable(session_factory, project_id, experiment_id):
    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60, dataset_version_id=None)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60, dataset_fingerprint="different-fingerprint")
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.9, value_type=MetricValueType.FLOAT)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    with session_factory() as session:
        result = check_comparability(session, project_id, run1_id, run2_id, "f1")
    assert result.comparable is False
    assert any("dataset content fingerprint" in reason for reason in result.reasons)


def test_missing_metric_is_not_comparable(session_factory, project_id, experiment_id):
    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    with session_factory() as session:
        result = check_comparability(session, project_id, run1_id, run2_id, "f1")
    assert result.comparable is False
    assert any("no metric named" in reason for reason in result.reasons)


def test_ambiguous_metric_across_splits_is_not_comparable(session_factory, project_id, experiment_id):
    with session_factory() as session:
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT, split="val")
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.7, value_type=MetricValueType.FLOAT, split="test")
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.9, value_type=MetricValueType.FLOAT, split="val")
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    with session_factory() as session:
        # No split= given -> ambiguous on run1 (two splits).
        result = check_comparability(session, project_id, run1_id, run2_id, "f1")
        assert result.comparable is False
        assert any("ambiguous" in reason or "specify split=" in reason for reason in result.reasons)

        # Disambiguated with split= -> comparable.
        result2 = check_comparability(session, project_id, run1_id, run2_id, "f1", split="val")
        assert result2.comparable is True


def test_check_comparability_rejects_cross_project_run(session_factory, project_id, second_project_id, experiment_id, two_comparable_run_ids):
    baseline_id, _ = two_comparable_run_ids
    with session_factory() as session:
        with pytest.raises(CrossProjectReferenceError):
            check_comparability(session, second_project_id, baseline_id, baseline_id, "f1")


def test_check_comparability_rejects_unknown_run(session_factory, project_id):
    with session_factory() as session:
        with pytest.raises(MissingEntityError):
            check_comparability(session, project_id, 999999, 999998, "f1")


def test_resolve_unique_metric_missing_and_unique(session_factory, project_id, experiment_id):
    with session_factory() as session:
        run = repository.create_run(session, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=run.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        session.commit()
        run_id = run.id

    with session_factory() as session:
        run = repository.get_run(session, run_id)
        metric, reasons = resolve_unique_metric(session, run, "f1", None)
        assert metric is not None
        assert reasons == []

        metric2, reasons2 = resolve_unique_metric(session, run, "does_not_exist", None)
        assert metric2 is None
        assert reasons2
