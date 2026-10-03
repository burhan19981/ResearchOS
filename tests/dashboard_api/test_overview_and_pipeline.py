"""Overview counts and pipeline visualization — verifies every number
comes from the real database, never a hard-coded placeholder."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import MetricValueType


def test_overview_empty_project_reports_honest_zeros(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["id"] == project_id
    assert body["current_stage"] == "STAGE_01_IDEA"
    counts = body["counts"]
    assert all(v == 0 for v in counts.values())


def test_overview_reflects_real_records(client, session_factory, project_id):
    with session_factory() as session:
        repository.add_literature_item(session, project_id=project_id, title="A paper", source="openalex", source_record_id="W1")
        repository.add_literature_item(session, project_id=project_id, title="Another paper", source="openalex", source_record_id="W2")
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        run = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=run.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/overview")
    counts = response.json()["counts"]
    assert counts["literature_items"] == 2
    assert counts["experiments"] == 1
    assert counts["runs"] == 1
    assert counts["metrics"] == 1
    assert counts["research_gaps"] == 0


def test_pipeline_defaults_to_first_stage_with_no_completed_stages(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/pipeline")
    assert response.status_code == 200
    body = response.json()
    assert body["current_stage"] == "STAGE_01_IDEA"
    assert len(body["stages"]) == 20
    first = body["stages"][0]
    assert first["stage"] == "STAGE_01_IDEA"
    assert first["is_current"] is True
    assert first["is_completed"] is False
    assert all(not s["is_completed"] for s in body["stages"])


def test_pipeline_reflects_project_status(client, session_factory, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/pipeline")
    assert response.json()["project_status"] == "active"
