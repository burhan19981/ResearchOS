"""Methodology plan generation service (Phase 7 spec section 27).

Generates one CANDIDATE `MethodologyPlan` version from one already-
approved `ContributionCandidate`. Reuses the existing Phase 3
`MethodologyPlan` entity and its `create_methodology_version()`
auto-incrementing version helper directly — no second methodology
entity. `MethodologyStatus` (DRAFT/ACTIVE/SUPERSEDED) is left entirely
alone by this service; only `planning_status` is ever set here, and
always to `CANDIDATE`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import PlanningApprovalStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from . import context as context_module
from .errors import InvalidPlanningResponseError
from .llm_call import call_structured, resolve_provider
from .prompts import (
    METHODOLOGY_GENERATION_PROMPT_NAME,
    METHODOLOGY_GENERATION_PROMPT_VERSION,
    METHODOLOGY_GENERATION_SCHEMA,
    build_methodology_generation_prompt,
)
from .types import MethodologyGenerationOutcome
from .validation import require_object_response


def generate_methodology_plan(
    project_id: int,
    contribution_candidate_id: int,
    research_question_ids: Optional[list[int]] = None,
    *,
    actor: str,
    provider_name: str,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> MethodologyGenerationOutcome:
    """Propose one candidate methodology plan for
    `contribution_candidate_id`, which must already be `planning_status
    APPROVED`. If given, every id in `research_question_ids` must
    already be linked to that contribution.
    """
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_methodology_context(
            session, project_id, contribution_candidate_id, research_question_ids
        )
        system_text, user_text = build_methodology_generation_prompt(ctx.prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="planning.methodology_generation_failed",
                actor=actor,
                description=f"Methodology generation failed: {exc}",
                metadata={
                    "contribution_candidate_id": contribution_candidate_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, METHODOLOGY_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("description",))
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    description = response.get("description")
    if not description or not str(description).strip():
        exc = InvalidPlanningResponseError("Response 'description' must not be blank.")
        _audit_failure(exc)
        raise exc

    contribution_snapshot = ctx.upstream_snapshots["contribution_candidate"]

    with session_scope(session_factory) as session:
        plan = repository.create_methodology_version(
            session,
            project_id=project_id,
            description=str(description),
            planning_status=PlanningApprovalStatus.CANDIDATE,
            methodology_type=response.get("methodology_type"),
            components=response.get("components"),
            assumptions=response.get("assumptions"),
            risks=response.get("risks"),
            reproducibility_requirements=response.get("reproducibility_requirements"),
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=METHODOLOGY_GENERATION_PROMPT_NAME,
            prompt_version=METHODOLOGY_GENERATION_PROMPT_VERSION,
            contribution_candidate_id=contribution_candidate_id,
            contribution_candidate_version=contribution_snapshot.get("version"),
            contribution_candidate_status_at_generation=contribution_snapshot.get("status_at_generation"),
        )

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="planning.methodology_generation_completed",
            actor=actor,
            description=f"Methodology plan v{plan.version} generated from contribution {contribution_candidate_id}",
            metadata={
                "methodology_plan_id": plan.id,
                "contribution_candidate_id": contribution_candidate_id,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": METHODOLOGY_GENERATION_PROMPT_NAME,
                "prompt_version": METHODOLOGY_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
            },
        )
        plan_id = plan.id

    return MethodologyGenerationOutcome(methodology_plan_id=plan_id)
