"""Experiment + ExperimentResult tests, including JSON serialization."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import ExperimentStatus


def test_register_experiment_with_configuration(session: Session):
    project = repository.create_project(session, title="Exp Project")
    experiment = repository.register_experiment(
        session,
        project_id=project.id,
        name="baseline-run",
        configuration={"lr": 0.001, "batch_size": 32, "layers": [64, 32, 1]},
        random_seed=42,
        hardware="1x RTX 5060",
    )
    assert experiment.status == ExperimentStatus.PLANNED
    assert experiment.configuration == {"lr": 0.001, "batch_size": 32, "layers": [64, 32, 1]}
    assert experiment.random_seed == 42


def test_start_and_complete_experiment_lifecycle(session: Session):
    project = repository.create_project(session, title="Lifecycle Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="run-1")

    started = repository.start_experiment(session, experiment.id)
    assert started.status == ExperimentStatus.RUNNING
    assert started.started_at is not None

    completed = repository.complete_experiment(session, experiment.id)
    assert completed.status == ExperimentStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.completed_at >= completed.started_at


def test_complete_experiment_can_record_failure_status(session: Session):
    project = repository.create_project(session, title="Failure Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="run-fail")
    repository.start_experiment(session, experiment.id)
    failed = repository.complete_experiment(session, experiment.id, status=ExperimentStatus.FAILED)
    assert failed.status == ExperimentStatus.FAILED


def test_start_experiment_raises_not_found_for_missing_id(session: Session):
    with pytest.raises(NotFoundError):
        repository.start_experiment(session, 999_999)


def test_record_experiment_result_with_metadata(session: Session):
    project = repository.create_project(session, title="Metrics Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="run-metrics")
    result = repository.record_experiment_result(
        session,
        experiment_id=experiment.id,
        metric_name="accuracy",
        metric_value=0.913,
        metric_unit="ratio",
        metadata={"split": "test", "confusion_matrix": [[50, 2], [3, 45]]},
    )
    assert result.metric_value == pytest.approx(0.913)
    assert result.metadata_ == {"split": "test", "confusion_matrix": [[50, 2], [3, 45]]}


def test_multiple_results_with_same_metric_name_are_allowed(session: Session):
    """Repeated measurements of the same metric (e.g. per-epoch loss) must
    not be blocked by a uniqueness constraint."""
    project = repository.create_project(session, title="Repeated Metric Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="run-epochs")
    repository.record_experiment_result(session, experiment_id=experiment.id, metric_name="loss", metric_value=0.5)
    repository.record_experiment_result(session, experiment_id=experiment.id, metric_name="loss", metric_value=0.3)
    results = repository.list_experiment_results(session, experiment.id)
    assert [r.metric_value for r in results] == [0.5, 0.3]


def test_record_experiment_result_rejects_nonexistent_experiment(session: Session):
    with pytest.raises(NotFoundError):
        repository.record_experiment_result(
            session, experiment_id=999_999, metric_name="accuracy", metric_value=1.0
        )


def test_deleting_experiment_cascades_to_results(session: Session):
    project = repository.create_project(session, title="Cascade Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="run-cascade")
    repository.record_experiment_result(session, experiment_id=experiment.id, metric_name="f1", metric_value=0.7)
    session.flush()

    session.delete(experiment)
    session.flush()

    assert repository.list_experiment_results(session, experiment.id) == []
