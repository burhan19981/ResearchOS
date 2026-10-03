"""Tests for Manuscript, JournalCandidate, Approval, and AuditEvent."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import ApprovalDecision, ManuscriptStatus


def test_create_manuscript_auto_versions(session: Session):
    project = repository.create_project(session, title="Manuscript Project")
    v1 = repository.create_manuscript(session, project_id=project.id, title="Draft")
    v2 = repository.create_manuscript(session, project_id=project.id, title="Draft revised")
    assert v1.version == 1
    assert v2.version == 2


def test_update_manuscript_status(session: Session):
    project = repository.create_project(session, title="Manuscript Project 2")
    manuscript = repository.create_manuscript(session, project_id=project.id, title="Draft")
    updated = repository.update_manuscript(session, manuscript.id, status=ManuscriptStatus.SUBMITTED)
    assert updated.status == ManuscriptStatus.SUBMITTED


def test_create_journal_candidate(session: Session):
    project = repository.create_project(session, title="Journal Project")
    candidate = repository.create_journal_candidate(
        session, project_id=project.id, name="Journal of Fake Results", scope="general"
    )
    assert candidate.id is not None
    candidates = repository.list_journal_candidates(session, project.id)
    assert len(candidates) == 1


def test_approval_request_and_decision_lifecycle(session: Session):
    project = repository.create_project(session, title="Approval Project")
    approval = repository.create_approval_request(session, project_id=project.id, stage="idea_review")
    assert approval.decision == ApprovalDecision.PENDING
    assert approval.decided_at is None

    decided = repository.record_approval_decision(
        session, approval.id, decision=ApprovalDecision.APPROVED, comment="Looks good"
    )
    assert decided.decision == ApprovalDecision.APPROVED
    assert decided.decided_at is not None
    assert decided.comment == "Looks good"


def test_record_approval_decision_raises_not_found_for_missing_id(session: Session):
    with pytest.raises(NotFoundError):
        repository.record_approval_decision(session, 999_999, decision=ApprovalDecision.APPROVED)


def test_append_audit_event_and_list(session: Session):
    project = repository.create_project(session, title="Audit Project")
    repository.append_audit_event(
        session,
        project_id=project.id,
        event_type="project_created",
        actor="system",
        metadata={"source": "test-suite"},
    )
    repository.append_audit_event(
        session, project_id=project.id, event_type="idea_added", actor="system"
    )
    events = repository.list_audit_events(session, project.id)
    assert [e.event_type for e in events] == ["project_created", "idea_added"]
    assert events[0].metadata_ == {"source": "test-suite"}


def test_audit_event_requires_nonblank_actor(session: Session):
    from researchos.db.errors import ValidationError

    project = repository.create_project(session, title="Audit Project 2")
    with pytest.raises(ValidationError):
        repository.append_audit_event(session, project_id=project.id, event_type="x", actor="   ")
