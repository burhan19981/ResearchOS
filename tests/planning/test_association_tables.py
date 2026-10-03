"""Association-table constraints for `contribution_candidate_questions`
and `experimental_design_questions` (Phase 7 spec sections 8 & 13):
reject a duplicate pair, a cross-project pair, and a missing endpoint.
"""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.errors import IntegrityConstraintError, NotFoundError


# --- contribution_candidate_questions ---------------------------------------


def test_link_contribution_question_rejects_duplicate_pair(session_factory, project_id, approved_contribution_id, approved_question_id):
    session = session_factory()
    try:
        # The fixture chain already links these once; linking again must fail.
        with pytest.raises(IntegrityConstraintError):
            repository.link_contribution_candidate_question(
                session, project_id=project_id, contribution_candidate_id=approved_contribution_id,
                research_question_id=approved_question_id,
            )
    finally:
        session.close()


def test_link_contribution_question_rejects_cross_project_question(
    session_factory, project_id, second_project_id, approved_contribution_id
):
    session = session_factory()
    try:
        other_question = repository.create_research_question(
            session, project_id=second_project_id, question="Other project's question?"
        )
        session.commit()
        with pytest.raises(NotFoundError):
            repository.link_contribution_candidate_question(
                session, project_id=project_id, contribution_candidate_id=approved_contribution_id,
                research_question_id=other_question.id,
            )
    finally:
        session.close()


def test_link_contribution_question_rejects_missing_contribution(session_factory, project_id, approved_question_id):
    session = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.link_contribution_candidate_question(
                session, project_id=project_id, contribution_candidate_id=999_999,
                research_question_id=approved_question_id,
            )
    finally:
        session.close()


def test_link_contribution_question_rejects_missing_question(session_factory, project_id, approved_contribution_id):
    session = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.link_contribution_candidate_question(
                session, project_id=project_id, contribution_candidate_id=approved_contribution_id,
                research_question_id=999_999,
            )
    finally:
        session.close()


# --- experimental_design_questions ------------------------------------------


def test_link_experimental_design_question_rejects_duplicate_pair(session_factory, project_id, approved_question_id):
    session = session_factory()
    try:
        design = repository.create_experimental_design(session, project_id=project_id, proposed_method="A method.")
        session.commit()
        repository.link_experimental_design_question(
            session, project_id=project_id, experimental_design_id=design.id,
            research_question_id=approved_question_id,
        )
        session.commit()
        with pytest.raises(IntegrityConstraintError):
            repository.link_experimental_design_question(
                session, project_id=project_id, experimental_design_id=design.id,
                research_question_id=approved_question_id,
            )
    finally:
        session.close()


def test_link_experimental_design_question_rejects_cross_project_design(
    session_factory, project_id, second_project_id, approved_question_id
):
    session = session_factory()
    try:
        other_design = repository.create_experimental_design(session, project_id=second_project_id, proposed_method="A method.")
        session.commit()
        with pytest.raises(NotFoundError):
            repository.link_experimental_design_question(
                session, project_id=project_id, experimental_design_id=other_design.id,
                research_question_id=approved_question_id,
            )
    finally:
        session.close()
