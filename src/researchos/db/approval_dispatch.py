"""Generic approval-dispatch mechanics shared by any layer that gates its
own candidate/status entities through Phase 4's `Approval`/`AuditEvent`
tables, without introducing a parallel approval system.

`researchos.workflow` (Phase 4) remains the sole authority over the
underlying `Approval`/`ApprovalDecision`/`AuditEvent` tables and
`is_human_actor` — this module only factors out the small, repeated
"which entity, which stage-key prefix, which status to set on approve/
reject/request-changes" bookkeeping that both
`researchos.intelligence.approval` (Phase 6) and
`researchos.planning.approval` (Phase 7) would otherwise each have to
duplicate. It contains no domain knowledge of any specific entity type —
callers supply that via `EntitySpec`, including their own exception
classes, so each layer's public error surface is completely unaffected
by this extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Type

from sqlalchemy.orm import Session, sessionmaker

from . import repository
from .engine import session_scope
from .models import Approval, ApprovalDecision
from ..workflow.policy import is_human_actor


@dataclass(frozen=True)
class EntitySpec:
    """Everything the generic dispatcher needs to know about one
    candidate/status entity type, supplied entirely by the caller.

    `status_attr` names the ONE attribute on the entity that actually
    holds its approval-relevant status (e.g. `"approval_status"` for
    `AnalysisClaim`, `"candidate_status"` for `NoveltyAssessment`,
    `"planning_status"` for every Phase 7 planning entity) — declared
    explicitly by the caller rather than guessed by checking a fixed
    priority list of common attribute names. `NoveltyAssessment` is the
    reason this is explicit rather than guessed: it has *two* status-like
    columns (Phase 3's original `status`/`NoveltyStatus`, which never
    changes, and Phase 6's `candidate_status`/`NoveltyCandidateStatus`,
    which is what an approval decision actually updates) — a
    priority-guessing lookup previously picked the wrong one for
    `previous_status` in that entity's audit-event metadata (found and
    fixed during the Phase 7 post-implementation audit)."""

    label: str
    stage_prefix: str
    status_attr: str
    get: Callable[[Session, int], Optional[Any]]
    update_status: Callable[[Session, int, Any], Any]
    approved_value: Any
    rejected_value: Any
    changes_requested_value: Any
    not_found_error: Type[Exception]
    already_decided_error: Type[Exception]
    human_only_error: Type[Exception]


def stage_key(spec: EntitySpec, entity_id: int) -> str:
    return f"{spec.stage_prefix}:{entity_id}"


def _get_or_create_pending_approval(session: Session, project_id: int, key: str, spec: EntitySpec) -> Approval:
    existing = repository.get_approval_by_stage(session, project_id, key)
    if existing is None:
        return repository.create_approval_request(session, project_id=project_id, stage=key)
    if existing.decision == ApprovalDecision.PENDING:
        return existing
    if existing.decision == ApprovalDecision.CHANGES_REQUESTED:
        # A changes-requested round is not terminal — open a fresh pending
        # round for the same candidate, exactly as a human revising and
        # resubmitting would expect.
        return repository.create_approval_request(session, project_id=project_id, stage=key)
    raise spec.already_decided_error(f"Approval for '{key}' was already decided ({existing.decision.value}).")


def decide(
    spec: EntitySpec,
    entity_id: int,
    actor: str,
    comment: Optional[str],
    *,
    decision: ApprovalDecision,
    new_status: Any,
    event_type: str,
    session_factory: Optional[sessionmaker],
    extra_metadata: Optional[Callable[[Session, Any], dict[str, Any]]] = None,
) -> Any:
    """Atomically decide one pending approval for one entity: the
    `Approval` row's decision, the entity's own status field, and an
    `AuditEvent` all commit together or not at all.

    `extra_metadata`, if given, is called with `(session, entity)` after
    the entity's status has been updated, and its return value is merged
    into the audit event's metadata — used by callers that want to
    record additional context (e.g. cited evidence ids) specific to
    their entity type.
    """
    with session_scope(session_factory) as session:
        if not is_human_actor(actor):
            raise spec.human_only_error(
                f"'{actor}' cannot decide this approval — the LLM cannot approve its own "
                "output; approval decisions must be made by a human."
            )
        entity = spec.get(session, entity_id)
        if entity is None:
            raise spec.not_found_error(f"{spec.label} {entity_id} does not exist.")
        project_id = entity.project_id
        previous_status = getattr(entity, spec.status_attr)

        key = stage_key(spec, entity_id)
        approval = _get_or_create_pending_approval(session, project_id, key, spec)
        repository.record_approval_decision(session, approval.id, decision=decision, comment=comment)
        updated_entity = spec.update_status(session, entity_id, new_status)

        metadata: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": spec.label,
            "approval_id": approval.id,
            "decision": decision.value,
            "previous_status": str(previous_status.value if hasattr(previous_status, "value") else previous_status),
            "new_status": str(new_status.value if hasattr(new_status, "value") else new_status),
            "comment": comment,
        }
        if extra_metadata is not None:
            metadata.update(extra_metadata(session, updated_entity))

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type=event_type,
            actor=actor,
            description=f"{decision.value} {spec.label} #{entity_id}" + (f": {comment}" if comment else ""),
            metadata=metadata,
        )
    return updated_entity


def pending_for_prefixes(session: Session, project_id: int, prefixes: tuple[str, ...]) -> list[Approval]:
    """All pending approvals in a project whose stage key starts with one
    of `prefixes` — the shared implementation behind each layer's own
    "pending approvals for this layer" listing."""
    all_pending = [a for a in repository.list_approvals(session, project_id) if a.decision == ApprovalDecision.PENDING]
    return [a for a in all_pending if any(a.stage.startswith(f"{prefix}:") for prefix in prefixes)]
