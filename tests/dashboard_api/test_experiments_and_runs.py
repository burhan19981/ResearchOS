"""Experiments and runs pages, including nested artifacts/metrics on
the run-detail endpoint and cross-project rejection."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import ArtifactType, MetricValueType


def test_experiments_list_and_run_count(client, session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/experiments")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_count"] == 2


def test_get_experiment_detail_and_cross_project_404(client, session_factory, project_id, second_project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        session.commit()
        experiment_id = experiment.id

    response = client.get(f"/api/v1/projects/{project_id}/experiments/{experiment_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Exp A"

    cross_project = client.get(f"/api/v1/projects/{second_project_id}/experiments/{experiment_id}")
    assert cross_project.status_code == 404


def test_run_detail_includes_artifacts_and_metrics(client, session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        run = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=run.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        repository.create_artifact_metadata(
            session, project_id=project_id, run_id=run.id, logical_name="stdout",
            artifact_type=ArtifactType.STDOUT, reference="/tmp/stdout.log",
        )
        session.commit()
        run_id = run.id

    response = client.get(f"/api/v1/projects/{project_id}/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert len(body["metrics"]) == 1
    assert body["metrics"][0]["name"] == "f1"
    assert len(body["artifacts"]) == 1
    assert body["artifacts"][0]["logical_name"] == "stdout"


def test_run_list_does_not_leak_across_projects(client, session_factory, project_id, second_project_id):
    with session_factory() as session:
        exp_a = repository.register_experiment(session, project_id=project_id, name="Exp A")
        repository.create_run(session, project_id=project_id, experiment_id=exp_a.id, timeout_seconds=60)
        exp_b = repository.register_experiment(session, project_id=second_project_id, name="Exp B")
        repository.create_run(session, project_id=second_project_id, experiment_id=exp_b.id, timeout_seconds=60)
        session.commit()

    response_a = client.get(f"/api/v1/projects/{project_id}/runs")
    assert len(response_a.json()) == 1
    response_b = client.get(f"/api/v1/projects/{second_project_id}/runs")
    assert len(response_b.json()) == 1


def test_get_nonexistent_run_404(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/runs/999999")
    assert response.status_code == 404
