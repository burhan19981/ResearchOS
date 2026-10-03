"""Analysis records and scientific claims/reviews pages — including
the NOT_COMPARABLE display requirement (reasons shown verbatim, no
"best"/"winner" language)."""

from __future__ import annotations

from researchos.analysis.claims import create_scientific_claim
from researchos.analysis.records import compare_runs
from researchos.analysis.reviews import create_scientific_review
from researchos.db import repository
from researchos.db.models import MetricValueType, ScientificReviewStatus


def _make_comparable_runs(session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.80, value_type=MetricValueType.FLOAT, unit="ratio")
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.85, value_type=MetricValueType.FLOAT, unit="ratio")
        session.commit()
        return r1.id, r2.id


def test_analysis_list_completed_comparison(client, session_factory, project_id):
    r1, r2 = _make_comparable_runs(session_factory, project_id)
    compare_runs(project_id, r1, r2, "f1", actor="tester", session_factory=session_factory)

    response = client.get(f"/api/v1/projects/{project_id}/analysis")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "completed"
    assert body[0]["result"]["absolute_difference"] == 0.05000000000000004 or abs(body[0]["result"]["absolute_difference"] - 0.05) < 1e-6
    assert len(body[0]["inputs"]) == 4  # 2 runs + 2 metrics


def test_analysis_not_comparable_shows_reasons_verbatim(client, session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT, unit="ratio")
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.9, value_type=MetricValueType.FLOAT, unit="percent")
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    compare_runs(project_id, run1_id, run2_id, "f1", actor="tester", session_factory=session_factory)

    response = client.get(f"/api/v1/projects/{project_id}/analysis")
    body = response.json()
    assert body[0]["status"] == "not_comparable"
    assert body[0]["result"]["comparable"] is False
    assert any("unit mismatch" in reason for reason in body[0]["result"]["reasons"])
    result_text = str(body[0]["result"]).lower()
    assert "best" not in result_text
    assert "winner" not in result_text


def test_reviews_page_nests_reviews_under_claims(client, session_factory, project_id):
    r1, r2 = _make_comparable_runs(session_factory, project_id)
    record = compare_runs(project_id, r1, r2, "f1", actor="tester", session_factory=session_factory)
    claim = create_scientific_claim(
        project_id, "Run B's F1 may be higher.", [record.id], actor="tester", session_factory=session_factory,
    )
    create_scientific_review(
        project_id, claim.id, {"evidence_completeness": "partial"}, actor="tester",
        status=ScientificReviewStatus.CANDIDATE, session_factory=session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/reviews")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["claim_text"] == "Run B's F1 may be higher."
    assert body[0]["approval_status"] == "pending_review"
    assert body[0]["strength"] == "not_assessable"
    assert len(body[0]["reviews"]) == 1
    assert body[0]["reviews"][0]["status"] == "candidate"
    assert body[0]["supporting_analysis_record_ids"] == [record.id]
