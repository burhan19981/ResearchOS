"""Shared fixtures for the research planning layer test suite.

Same pattern as tests/db, tests/workflow, tests/evidence, tests/intelligence:
a fresh temporary SQLite database per test, migrated via the real
Alembic path. No test in this package makes a real LLM API call — every
service function is called with an explicit `provider=FakeLLMProvider(...)`.

The `approved_*_id` fixtures build a full, already-approved upstream
chain (gap -> question -> contribution -> methodology -> dataset
requirements) directly via `researchos.db.repository`, bypassing
`researchos.planning.approval` for setup speed — approval mechanics
themselves are exercised separately in `test_approval.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db
from researchos.db.models import (
    EvidenceRelationship,
    EvidenceSubjectType,
    GapStatus,
    PlanningApprovalStatus,
)


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
        project = repository.create_project(s, title="Fake Planning Test Project")
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
def literature_item_ids(session_factory: sessionmaker, project_id: int) -> list[int]:
    s = session_factory()
    try:
        item1 = repository.add_literature_item(
            s, project_id=project_id, title="Fake Paper One: A Study of Widgets",
            source="openalex", source_record_id="W1", abstract="This fake paper studies widgets.",
            authors="Jane Doe", year=2020, doi="10.1234/fake-planning-one", metadata_completeness=0.9,
        )
        item2 = repository.add_literature_item(
            s, project_id=project_id, title="Fake Paper Two: Widgets Revisited",
            source="crossref", source_record_id="10.1234/fake-planning-two", abstract="This fake paper revisits widgets.",
            authors="John Smith", year=2021, doi="10.1234/fake-planning-two", metadata_completeness=0.8,
        )
        s.commit()
        return [item1.id, item2.id]
    finally:
        s.close()


@pytest.fixture()
def approved_gap_id(session_factory: sessionmaker, project_id: int, literature_item_ids: list[int]) -> int:
    s = session_factory()
    try:
        gap = repository.record_research_gap(
            s, project_id=project_id, statement="A validated gap in widget research.", status=GapStatus.VALIDATED,
        )
        repository.create_evidence_link(
            s, project_id=project_id, literature_item_id=literature_item_ids[0],
            subject_type=EvidenceSubjectType.GAP_CANDIDATE, subject_id=gap.id,
            relationship_type=EvidenceRelationship.SUPPORTS,
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
def approved_dataset_requirements_id(session_factory: sessionmaker, project_id: int, approved_methodology_id: int) -> int:
    s = session_factory()
    try:
        requirements = repository.create_dataset_requirements(
            s, project_id=project_id, required_characteristics="Stress-test measurements for alloy samples.",
            planning_status=PlanningApprovalStatus.APPROVED, methodology_plan_id=approved_methodology_id,
            methodology_plan_version=1, methodology_plan_status_at_generation="approved",
        )
        s.commit()
        return requirements.id
    finally:
        s.close()
