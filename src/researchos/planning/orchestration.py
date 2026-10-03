"""The planning orchestrator: structural-consistency enforcement shared
by every generation service in this package (Phase 7 spec section 19).

This module does NOT, and cannot, guarantee scientific correctness. It
guarantees only:

1. Every downstream generation call receives its upstream id(s)
   explicitly — no service in this package ever infers "the latest" or
   "the pending" artifact.
2. Every referenced id must exist.
3. Every referenced entity must belong to the caller's own project —
   never silently mixed across projects.
4. Only an APPROVED (or, for the Phase 6 entities this layer builds on,
   the equivalent VALIDATED/HUMAN_APPROVED value) upstream artifact may
   ground a downstream generation.

What actually gets proposed beyond that point is still an LLM's text,
validated only for referential/structural consistency by
`researchos.planning.validation` — never checked for whether it is
scientifically sound.
"""

from __future__ import annotations

from typing import Any, Optional

from .errors import CrossProjectReferenceError, UnknownPlanningEntityError, UpstreamNotApprovedError


def require_in_project(entity: Optional[Any], entity_id: int, label: str, project_id: int) -> Any:
    """Rules 2 & 3: the referenced entity must exist and belong to
    `project_id`. Raises immediately rather than silently proceeding."""
    if entity is None:
        raise UnknownPlanningEntityError(f"{label} {entity_id} does not exist.")
    if entity.project_id != project_id:
        raise CrossProjectReferenceError(
            f"{label} {entity_id} belongs to project {entity.project_id}, not {project_id}."
        )
    return entity


def require_status(entity: Any, entity_id: int, label: str, *, status_attr: str, approved_values: tuple) -> Any:
    """Rule 4, generalized: only an upstream artifact whose
    `status_attr` is one of `approved_values` may ground downstream
    generation. Used both for this phase's own `planning_status`
    (`PlanningApprovalStatus.APPROVED`) and for the Phase 6 entities
    this layer builds on, which use their own pre-existing approved
    value (`GapStatus.VALIDATED`, `NoveltyCandidateStatus.HUMAN_APPROVED`)
    rather than a value this phase invents."""
    value = getattr(entity, status_attr)
    if value not in approved_values:
        raise UpstreamNotApprovedError(
            f"{label} {entity_id} is not approved ({status_attr}={getattr(value, 'value', value)!r}); "
            "it cannot be used to ground downstream generation."
        )
    return entity


def require_approved(entity: Any, entity_id: int, label: str) -> Any:
    """Convenience wrapper of `require_status` for this phase's own
    `PlanningApprovalStatus.APPROVED` entities."""
    from ..db.models import PlanningApprovalStatus

    return require_status(
        entity, entity_id, label, status_attr="planning_status", approved_values=(PlanningApprovalStatus.APPROVED,)
    )


def snapshot(entity: Any, *, include_version: bool = True, status_attr: str = "planning_status") -> dict[str, Any]:
    """The minimum generation-time upstream snapshot Phase 7 spec section
    15 requires: id, version (if the entity has one), and its status at
    this moment — never only the status, so a reviewer can always tell
    exactly which version of an upstream artifact a downstream plan was
    built from."""
    status = getattr(entity, status_attr, None)
    data: dict[str, Any] = {
        "id": entity.id,
        "status_at_generation": getattr(status, "value", status),
    }
    if include_version and hasattr(entity, "version"):
        data["version"] = entity.version
    return data
