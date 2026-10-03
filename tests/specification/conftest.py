"""Shared fixtures for the dataset & experiment specification layer test
suite. Same pattern as tests/db, tests/workflow, tests/evidence,
tests/intelligence, tests/planning: a fresh temporary SQLite database
per test, migrated via the real Alembic path.

The `approved_*_id` fixtures build a full, already-approved upstream
chain (gap -> question -> contribution -> methodology -> experimental
design -> dataset record -> dataset version) directly via
`researchos.db.repository`, bypassing the approval/validation services
for setup speed — those mechanics are exercised separately in
`test_approval.py`/`test_dataset_versions.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db
from researchos.db.models import DatasetLifecycleStatus, GapStatus, PlanningApprovalStatus


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
        project = repository.create_project(s, title="Fake Specification Test Project")
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
def approved_gap_id(session_factory: sessionmaker, project_id: int) -> int:
    s = session_factory()
    try:
        gap = repository.record_research_gap(
            s, project_id=project_id, statement="A validated gap.", status=GapStatus.VALIDATED,
        )
        s.commit()
        return gap.id
    finally:
        s.close()


@pytest.fixture()
def approved_question_id(session_factory: sessionmaker, project_id: int, approved_gap_id: int) -> int:
    s = session_factory()
    try:
        question = repository.create_research_question(
            s, project_id=project_id, question="How can widgets be made more durable?",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        repository.update_research_gap(s, approved_gap_id, research_question_id=question.id)
        s.commit()
        return question.id
    finally:
        s.close()


@pytest.fixture()
def approved_contribution_id(session_factory: sessionmaker, project_id: int, approved_question_id: int) -> int:
    s = session_factory()
    try:
        contribution = repository.create_contribution_candidate(
            s, project_id=project_id, title="A more durable widget alloy",
            description="A new alloy composition for widgets.", planning_status=PlanningApprovalStatus.APPROVED,
        )
        repository.link_contribution_candidate_question(
            s, project_id=project_id, contribution_candidate_id=contribution.id,
            research_question_id=approved_question_id,
        )
        s.commit()
        return contribution.id
    finally:
        s.close()


@pytest.fixture()
def approved_methodology_id(session_factory: sessionmaker, project_id: int, approved_contribution_id: int) -> int:
    s = session_factory()
    try:
        plan = repository.create_methodology_version(
            s, project_id=project_id, description="A controlled alloy-composition study.",
            planning_status=PlanningApprovalStatus.APPROVED, contribution_candidate_id=approved_contribution_id,
            contribution_candidate_version=1, contribution_candidate_status_at_generation="approved",
        )
        s.commit()
        return plan.id
    finally:
        s.close()


@pytest.fixture()
def approved_experimental_design_id(session_factory: sessionmaker, project_id: int, approved_methodology_id: int) -> int:
    s = session_factory()
    try:
        design = repository.create_experimental_design(
            s, project_id=project_id, proposed_method="Compare the new alloy against standard baselines.",
            planning_status=PlanningApprovalStatus.APPROVED, methodology_plan_id=approved_methodology_id,
            methodology_plan_version=1, methodology_plan_status_at_generation="approved",
        )
        s.commit()
        return design.id
    finally:
        s.close()


@pytest.fixture()
def dataset_record_id(session_factory: sessionmaker, project_id: int) -> int:
    s = session_factory()
    try:
        record = repository.register_dataset(
            s, project_id=project_id, name="Widget Stress Test Corpus", version="raw",
            path_or_uri="s3://fake-bucket/widget-stress-corpus/",
        )
        s.commit()
        return record.id
    finally:
        s.close()


@pytest.fixture()
def approved_dataset_version_id(session_factory: sessionmaker, project_id: int, dataset_record_id: int) -> int:
    s = session_factory()
    try:
        dataset_version = repository.create_dataset_version(
            s, project_id=project_id, dataset_record_id=dataset_record_id,
            source_uri="s3://fake-bucket/widget-stress-corpus/v1/", format="classification",
            sample_count=1000, split_definition={"train": 0.8, "val": 0.1, "test": 0.1},
            class_definition=["pass", "fail"],
            content_fingerprint="fake-content-fingerprint", metadata_fingerprint="fake-metadata-fingerprint",
            lifecycle_status=DatasetLifecycleStatus.APPROVED,
        )
        s.commit()
        return dataset_version.id
    finally:
        s.close()
