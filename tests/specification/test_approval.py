"""Human approval integration tests (Phase 8A)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import ApprovalDecision, DatasetLifecycleStatus, PlanningApprovalStatus
from researchos.planning.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError
from researchos.specification import approval
from researchos.specification.dataset_versions import validate_dataset_version
from researchos.specification.errors import InvalidLifecycleTransitionError


def _make_draft_dataset_version(session_factory, project_id, dataset_record_id):
    s = session_factory()
    try:
        dataset_version = repository.create_dataset_version(
            s, project_id=project_id, dataset_record_id=dataset_record_id, format="generic", sample_count=10,
        )
        s.commit()
        return dataset_version.id
    finally:
        s.close()


def _make_valid_dataset_version(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    validate_dataset_version(project_id, dataset_version_id, actor="agent:registrar", session_factory=session_factory)
    return dataset_version_id


def _make_experiment_specification(session_factory, project_id):
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(s, project_id=project_id, description="A candidate spec.")
        s.commit()
        return spec.id
    finally:
        s.close()


# --- Candidates never pre-approved ------------------------------------------


def test_dataset_version_starts_as_draft_never_pre_approved(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    session = session_factory()
    try:
        dataset_version = repository.get_dataset_version(session, dataset_version_id)
        assert dataset_version.lifecycle_status == DatasetLifecycleStatus.DRAFT
    finally:
        session.close()


def test_experiment_specification_starts_as_candidate_never_pre_approved(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    session = session_factory()
    try:
        spec = repository.get_experiment_specification(session, spec_id)
        assert spec.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()


# --- Dataset version VALID precondition --------------------------------------


def test_draft_dataset_version_cannot_be_approved(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    with pytest.raises(InvalidLifecycleTransitionError):
        approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)


def test_invalid_dataset_version_cannot_be_approved(session_factory, project_id, dataset_record_id):
    session = session_factory()
    try:
        dataset_version = repository.create_dataset_version(
            session, project_id=project_id, dataset_record_id=dataset_record_id, format="classification",
            class_definition=[],  # invalid: empty
        )
        session.commit()
        dataset_version_id = dataset_version.id
    finally:
        session.close()
    validate_dataset_version(project_id, dataset_version_id, actor="agent:registrar", session_factory=session_factory)
    session = session_factory()
    try:
        assert repository.get_dataset_version(session, dataset_version_id).lifecycle_status == DatasetLifecycleStatus.INVALID
    finally:
        session.close()
    with pytest.raises(InvalidLifecycleTransitionError):
        approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)


def test_valid_dataset_version_can_be_approved(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_valid_dataset_version(session_factory, project_id, dataset_record_id)
    updated = approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)
    assert updated.lifecycle_status == DatasetLifecycleStatus.APPROVED


def test_approving_nonexistent_dataset_version_raises_not_found(session_factory, project_id):
    with pytest.raises(CandidateNotFoundError):
        approval.approve_dataset_version(999_999, actor="user:pi", session_factory=session_factory)


# --- Agent (LLM) actor blocked on every gate type ---------------------------


def test_agent_cannot_approve_dataset_version(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_valid_dataset_version(session_factory, project_id, dataset_record_id)
    with pytest.raises(HumanOnlyActionError):
        approval.approve_dataset_version(dataset_version_id, actor="agent:auto-approver", session_factory=session_factory)


def test_agent_cannot_reject_dataset_version(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    with pytest.raises(HumanOnlyActionError):
        approval.reject_dataset_version(dataset_version_id, actor="agent:x", session_factory=session_factory)


def test_agent_cannot_request_changes_on_dataset_version(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    with pytest.raises(HumanOnlyActionError):
        approval.request_changes_dataset_version(dataset_version_id, actor="agent:x", session_factory=session_factory)


def test_agent_cannot_approve_experiment_specification(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        approval.approve_experiment_specification(spec_id, actor="agent:auto-approver", session_factory=session_factory)


def test_agent_cannot_reject_experiment_specification(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        approval.reject_experiment_specification(spec_id, actor="agent:x", session_factory=session_factory)


def test_agent_cannot_request_changes_on_experiment_specification(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        approval.request_changes_experiment_specification(spec_id, actor="agent:x", session_factory=session_factory)


# --- Approval recorded correctly + audit event ------------------------------


def test_human_approval_updates_status_and_records_approval_row(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_valid_dataset_version(session_factory, project_id, dataset_record_id)
    updated = approval.approve_dataset_version(
        dataset_version_id, actor="user:pi", comment="looks solid", session_factory=session_factory
    )
    assert updated.lifecycle_status == DatasetLifecycleStatus.APPROVED
    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        matching = [a for a in approvals if a.stage == f"DATASET_VERSION_APPROVAL:{dataset_version_id}"]
        assert len(matching) == 1
        assert matching[0].decision == ApprovalDecision.APPROVED
        assert matching[0].comment == "looks solid"
    finally:
        session.close()


def test_experiment_specification_approval_generates_complete_audit_event(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    approval.approve_experiment_specification(spec_id, actor="user:pi", comment="approved", session_factory=session_factory)
    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "specification.experiment_specification_approved")
        assert event.actor == "user:pi"
        assert event.metadata_["entity_id"] == spec_id
        assert event.metadata_["previous_status"] == "candidate"
        assert event.metadata_["new_status"] == "approved"
    finally:
        session.close()


def test_dataset_version_approval_generates_complete_audit_event_with_correct_previous_status(
    session_factory, project_id, dataset_record_id
):
    dataset_version_id = _make_valid_dataset_version(session_factory, project_id, dataset_record_id)
    approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)
    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "specification.dataset_version_approved")
        assert event.metadata_["previous_status"] == "valid"
        assert event.metadata_["new_status"] == "approved"
    finally:
        session.close()


# --- Rejection is terminal; changes-requested reopens a round --------------


def test_rejected_experiment_specification_remains_rejected_and_cannot_be_reapproved(session_factory, project_id):
    spec_id = _make_experiment_specification(session_factory, project_id)
    rejected = approval.reject_experiment_specification(spec_id, actor="user:pi", session_factory=session_factory)
    assert rejected.planning_status == PlanningApprovalStatus.REJECTED
    with pytest.raises(ApprovalAlreadyDecidedError):
        approval.approve_experiment_specification(spec_id, actor="user:pi", session_factory=session_factory)


def test_changes_requested_sends_dataset_version_back_to_draft_and_allows_a_fresh_round(
    session_factory, project_id, dataset_record_id
):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    updated = approval.request_changes_dataset_version(
        dataset_version_id, actor="user:pi", comment="add split info", session_factory=session_factory
    )
    assert updated.lifecycle_status == DatasetLifecycleStatus.DRAFT

    # Not immediately approvable — must pass validation again first.
    with pytest.raises(InvalidLifecycleTransitionError):
        approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)

    validate_dataset_version(project_id, dataset_version_id, actor="agent:registrar", session_factory=session_factory)
    approved = approval.approve_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)
    assert approved.lifecycle_status == DatasetLifecycleStatus.APPROVED

    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        matching = [a for a in approvals if a.stage == f"DATASET_VERSION_APPROVAL:{dataset_version_id}"]
        assert len(matching) == 2  # the changes-requested round + the fresh approved round
    finally:
        session.close()


# --- Pending listing scoped to this layer's own prefixes --------------------


def test_get_pending_specification_approvals_lists_only_this_layers_approvals(session_factory, project_id, dataset_record_id):
    dataset_version_id = _make_draft_dataset_version(session_factory, project_id, dataset_record_id)
    session = session_factory()
    try:
        assert approval.get_pending_specification_approvals(session, project_id) == []
    finally:
        session.close()

    approval.request_changes_dataset_version(dataset_version_id, actor="user:pi", session_factory=session_factory)
    session = session_factory()
    try:
        pending = approval.get_pending_specification_approvals(session, project_id)
        assert pending == []  # changes-requested is a decided state, not pending
    finally:
        session.close()
