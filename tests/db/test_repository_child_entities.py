"""CRUD + relationship tests for the project's direct child entities:
ideas, questions, literature, gaps, novelty assessments, methodology,
and datasets.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import IntegrityConstraintError, NotFoundError
from researchos.db.models import GapStatus, IdeaStatus, MethodologyStatus


def _make_project(session: Session, title: str = "Parent Project"):
    return repository.create_project(session, title=title)


# --- ResearchIdea -----------------------------------------------------


def test_create_research_idea_and_list_by_project(session: Session):
    project = _make_project(session)
    idea = repository.create_research_idea(
        session, project_id=project.id, title="An idea", research_question="Why?"
    )
    assert idea.status == IdeaStatus.PROPOSED
    ideas = repository.list_research_ideas(session, project.id)
    assert [i.title for i in ideas] == ["An idea"]


def test_create_research_idea_rejects_nonexistent_project(session: Session):
    with pytest.raises(NotFoundError):
        repository.create_research_idea(session, project_id=999_999, title="Orphan idea")


def test_update_research_idea(session: Session):
    project = _make_project(session)
    idea = repository.create_research_idea(session, project_id=project.id, title="Idea")
    updated = repository.update_research_idea(session, idea.id, status=IdeaStatus.ACCEPTED)
    assert updated.status == IdeaStatus.ACCEPTED


# --- ResearchQuestion ---------------------------------------------------


def test_create_research_question(session: Session):
    project = _make_project(session)
    question = repository.create_research_question(
        session, project_id=project.id, question="Does X affect Y?", type="primary"
    )
    assert question.id is not None
    questions = repository.list_research_questions(session, project.id)
    assert len(questions) == 1


# --- LiteratureItem -----------------------------------------------------


def test_add_literature_item(session: Session):
    project = _make_project(session)
    item = repository.add_literature_item(
        session, project_id=project.id, title="A Paper", authors="Doe, J.", year=2020, doi="10.1234/abc"
    )
    assert item.id is not None
    items = repository.list_literature_items(session, project.id)
    assert items[0].doi == "10.1234/abc"


def test_duplicate_doi_within_same_project_is_rejected(session: Session):
    project = _make_project(session)
    repository.add_literature_item(session, project_id=project.id, title="Paper A", doi="10.1/dup")
    with pytest.raises(IntegrityConstraintError):
        repository.add_literature_item(session, project_id=project.id, title="Paper B", doi="10.1/dup")


def test_multiple_null_dois_are_allowed_within_same_project(session: Session):
    project = _make_project(session)
    repository.add_literature_item(session, project_id=project.id, title="No DOI 1")
    item2 = repository.add_literature_item(session, project_id=project.id, title="No DOI 2")
    assert item2.id is not None


def test_same_doi_allowed_across_different_projects(session: Session):
    project_a = _make_project(session, "Project A")
    project_b = _make_project(session, "Project B")
    repository.add_literature_item(session, project_id=project_a.id, title="Paper", doi="10.1/shared")
    item_b = repository.add_literature_item(session, project_id=project_b.id, title="Paper", doi="10.1/shared")
    assert item_b.id is not None


# --- ResearchGap ---------------------------------------------------------


def test_record_and_update_research_gap(session: Session):
    project = _make_project(session)
    gap = repository.record_research_gap(session, project_id=project.id, statement="Nobody has studied X")
    assert gap.status == GapStatus.CANDIDATE
    updated = repository.update_research_gap(session, gap.id, status=GapStatus.VALIDATED, confidence=0.8)
    assert updated.status == GapStatus.VALIDATED
    assert updated.confidence == 0.8


# --- NoveltyAssessment ----------------------------------------------------


def test_record_novelty_assessment(session: Session):
    project = _make_project(session)
    assessment = repository.record_novelty_assessment(
        session, project_id=project.id, claim="This approach is novel", confidence=0.6
    )
    assert assessment.assessed_at is not None
    fetched = repository.get_novelty_assessment(session, assessment.id)
    assert fetched is not None


# --- MethodologyPlan (versioning) -----------------------------------------


def test_create_methodology_version_auto_increments(session: Session):
    project = _make_project(session)
    v1 = repository.create_methodology_version(session, project_id=project.id, description="Plan v1")
    v2 = repository.create_methodology_version(session, project_id=project.id, description="Plan v2")
    assert v1.version == 1
    assert v2.version == 2
    plans = repository.list_methodology_plans(session, project.id)
    assert [p.version for p in plans] == [1, 2]


def test_methodology_version_is_scoped_per_project(session: Session):
    project_a = _make_project(session, "Project A")
    project_b = _make_project(session, "Project B")
    a_v1 = repository.create_methodology_version(session, project_id=project_a.id, description="A plan")
    b_v1 = repository.create_methodology_version(session, project_id=project_b.id, description="B plan")
    assert a_v1.version == 1
    assert b_v1.version == 1  # independent numbering per project


def test_duplicate_explicit_methodology_version_is_rejected(session: Session):
    project = _make_project(session)
    repository.create_methodology_version(session, project_id=project.id, description="v1", version=1)
    with pytest.raises(IntegrityConstraintError):
        repository.create_methodology_version(session, project_id=project.id, description="dup v1", version=1)


# --- DatasetRecord ---------------------------------------------------------


def test_register_dataset_with_split_information(session: Session):
    project = _make_project(session)
    dataset = repository.register_dataset(
        session,
        project_id=project.id,
        name="benchmark",
        version="v1",
        path_or_uri="s3://bucket/benchmark-v1",
        split_information={"train": 800, "val": 100, "test": 100},
    )
    assert dataset.split_information == {"train": 800, "val": 100, "test": 100}


def test_duplicate_dataset_name_version_within_project_is_rejected(session: Session):
    project = _make_project(session)
    repository.register_dataset(session, project_id=project.id, name="ds", version="v1", path_or_uri="/data/ds")
    with pytest.raises(IntegrityConstraintError):
        repository.register_dataset(session, project_id=project.id, name="ds", version="v1", path_or_uri="/data/ds2")
