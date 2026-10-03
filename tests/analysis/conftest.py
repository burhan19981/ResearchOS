"""Shared fixtures for the analysis & scientific review layer test
suite. Same pattern as tests/db, tests/execution, tests/planning: a
fresh temporary SQLite database per test, migrated via the real
Alembic path. No test in this package makes a real LLM API call —
every LLM-assisted service function is called with an explicit
`provider=FakeLLMProvider(...)`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db
from researchos.db.models import MetricValueType


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "test_researchos.db"
    return f"sqlite:///{db_path.as_posix()}"


@pytest.fixture()
def engine(db_url: str):
    init_db(db_url)
    eng = create_db_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture()
def session(session_factory: sessionmaker) -> Iterator[Session]:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project_id(session_factory: sessionmaker) -> int:
    s = session_factory()
    try:
        project = repository.create_project(s, title="Fake Analysis Test Project")
        s.commit()
        return project.id
    finally:
        s.close()


@pytest.fixture()
def second_project_id(session_factory: sessionmaker) -> int:
    s = session_factory()
    try:
        project = repository.create_project(s, title="A Different Project")
        s.commit()
        return project.id
    finally:
        s.close()


@pytest.fixture()
def experiment_id(session_factory: sessionmaker, project_id: int) -> int:
    s = session_factory()
    try:
        experiment = repository.register_experiment(s, project_id=project_id, name="Fake Experiment")
        s.commit()
        return experiment.id
    finally:
        s.close()


def _make_run_with_metric(
    session_factory: sessionmaker, project_id: int, experiment_id: int, *,
    metric_name: str = "f1", value: float, unit: str = "ratio", split: str = None,
    dataset_version_id: int = None, dataset_fingerprint: str = None,
) -> int:
    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=60,
            dataset_version_id=dataset_version_id, dataset_fingerprint=dataset_fingerprint,
        )
        repository.create_metric(
            s, project_id=project_id, run_id=run.id, name=metric_name, value=value,
            value_type=MetricValueType.FLOAT, unit=unit, split=split,
        )
        s.commit()
        return run.id
    finally:
        s.close()


@pytest.fixture()
def two_comparable_run_ids(session_factory: sessionmaker, project_id: int, experiment_id: int) -> tuple[int, int]:
    """Two Runs, same (implicit None) DatasetVersion/fingerprint, each
    with one unambiguous `f1` metric — a genuinely comparable pair."""
    baseline = _make_run_with_metric(session_factory, project_id, experiment_id, value=0.80)
    comparison = _make_run_with_metric(session_factory, project_id, experiment_id, value=0.85)
    return baseline, comparison


@pytest.fixture()
def three_repeated_run_ids(session_factory: sessionmaker, project_id: int, experiment_id: int) -> list[int]:
    return [
        _make_run_with_metric(session_factory, project_id, experiment_id, value=0.80),
        _make_run_with_metric(session_factory, project_id, experiment_id, value=0.85),
        _make_run_with_metric(session_factory, project_id, experiment_id, value=0.83),
    ]


@pytest.fixture()
def analysis_record_id(session_factory: sessionmaker, project_id: int, two_comparable_run_ids: tuple[int, int]) -> int:
    from researchos.analysis.records import compare_runs

    record = compare_runs(project_id, *two_comparable_run_ids, "f1", actor="tester", session_factory=session_factory)
    return record.id


@pytest.fixture()
def claim_id(session_factory: sessionmaker, project_id: int, analysis_record_id: int) -> int:
    from researchos.analysis.claims import create_scientific_claim

    claim = create_scientific_claim(
        project_id, "Run B's F1 may be higher than Run A's under these conditions.", [analysis_record_id],
        actor="tester", session_factory=session_factory,
    )
    return claim.id


@pytest.fixture()
def ready_review_id(session_factory: sessionmaker, project_id: int, claim_id: int) -> int:
    from researchos.db.models import ScientificReviewStatus
    from researchos.analysis.reviews import create_scientific_review

    dimensions = {key: "assessed" for key in (
        "evidence_completeness", "experimental_consistency", "dataset_consistency", "metric_appropriateness",
        "baseline_adequacy", "ablation_coverage", "reproducibility", "statistical_support",
        "threats_to_validity", "claim_strength", "alternative_explanations", "missing_evidence",
    )}
    review = create_scientific_review(
        project_id, claim_id, dimensions, actor="tester",
        status=ScientificReviewStatus.READY_FOR_HUMAN_REVIEW, session_factory=session_factory,
    )
    return review.id
