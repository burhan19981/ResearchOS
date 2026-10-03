"""EvidenceLink validation for the five new Phase 7 EvidenceSubjectType
members — mirrors tests/intelligence's existing coverage for the four
Phase 6 subject types, extended to the new ones."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import EvidenceRelationship, EvidenceSubjectType


@pytest.mark.parametrize(
    "subject_type,make_subject_id",
    [
        (EvidenceSubjectType.RESEARCH_QUESTION, "approved_question_id"),
        (EvidenceSubjectType.CONTRIBUTION_CANDIDATE, "approved_contribution_id"),
        (EvidenceSubjectType.METHODOLOGY_PLAN, "approved_methodology_id"),
        (EvidenceSubjectType.DATASET_REQUIREMENTS, "approved_dataset_requirements_id"),
    ],
)
def test_evidence_link_accepts_a_real_subject_of_the_right_type(
    session_factory, project_id, literature_item_ids, subject_type, make_subject_id, request
):
    subject_id = request.getfixturevalue(make_subject_id)
    session = session_factory()
    try:
        link = repository.create_evidence_link(
            session, project_id=project_id, literature_item_id=literature_item_ids[0],
            subject_type=subject_type, subject_id=subject_id, relationship_type=EvidenceRelationship.CITES,
        )
        assert link.subject_type == subject_type
        assert link.subject_id == subject_id
    finally:
        session.close()


def test_evidence_link_for_experimental_design(session_factory, project_id, literature_item_ids):
    session = session_factory()
    try:
        design = repository.create_experimental_design(session, project_id=project_id, proposed_method="A method.")
        session.commit()
        link = repository.create_evidence_link(
            session, project_id=project_id, literature_item_id=literature_item_ids[0],
            subject_type=EvidenceSubjectType.EXPERIMENTAL_DESIGN, subject_id=design.id,
        )
        assert link.subject_id == design.id
    finally:
        session.close()


@pytest.mark.parametrize(
    "wrong_subject_type",
    [
        EvidenceSubjectType.CONTRIBUTION_CANDIDATE,
        EvidenceSubjectType.METHODOLOGY_PLAN,
        EvidenceSubjectType.DATASET_REQUIREMENTS,
        EvidenceSubjectType.EXPERIMENTAL_DESIGN,
    ],
)
def test_evidence_link_rejects_a_subject_id_that_does_not_exist_in_the_claimed_table(
    session_factory, project_id, literature_item_ids, approved_question_id, wrong_subject_type
):
    """A cross-table id collision must be rejected — an id that is real
    in `research_questions` but not in the table `wrong_subject_type`
    actually names must never be silently accepted."""
    session = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.create_evidence_link(
                session, project_id=project_id, literature_item_id=literature_item_ids[0],
                subject_type=wrong_subject_type, subject_id=approved_question_id,
            )
    finally:
        session.close()


def test_evidence_link_rejects_subject_from_a_different_project(
    session_factory, project_id, second_project_id, literature_item_ids
):
    session = session_factory()
    try:
        other_project_question = repository.create_research_question(
            session, project_id=second_project_id, question="Other project's question?"
        )
        session.commit()
        with pytest.raises(NotFoundError):
            repository.create_evidence_link(
                session, project_id=project_id, literature_item_id=literature_item_ids[0],
                subject_type=EvidenceSubjectType.RESEARCH_QUESTION, subject_id=other_project_question.id,
            )
    finally:
        session.close()
