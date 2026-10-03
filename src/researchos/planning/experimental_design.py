"""Experimental design generation service (Phase 7 spec section 29).

Generates one CANDIDATE `ExperimentalDesign` row from one already-
approved `MethodologyPlan`, one already-approved `DatasetRequirements`
row, and the explicit `ResearchQuestion` ids it addresses. Deliberately
distinct from the existing `Experiment`/`ExperimentResult` execution-
tracking entities (Phase 3) — this service never creates, starts, or
completes an `Experiment`; it only proposes a design a human may later
choose to implement.
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
from . import orchestration
from .errors import InvalidPlanningResponseError
from .llm_call import call_structured, resolve_provider
from .prompts import (
    EXPERIMENTAL_DESIGN_GENERATION_PROMPT_NAME,
    EXPERIMENTAL_DESIGN_GENERATION_PROMPT_VERSION,
    EXPERIMENTAL_DESIGN_GENERATION_SCHEMA,
    build_experimental_design_generation_prompt,
)
from .types import ExperimentalDesignGenerationOutcome
from .validation import require_object_response, validate_no_hallucinated_references


def generate_experimental_design(
    project_id: int,
    methodology_plan_id: int,
    dataset_requirements_id: int,
    research_question_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    supersedes_id: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ExperimentalDesignGenerationOutcome:
    """Propose one candidate experimental design implementing
    `methodology_plan_id` (must be `planning_status APPROVED`) against
    `dataset_requirements_id` (must also be APPROVED, and must have been
    generated from the same methodology plan), addressing every id in
    the explicit, non-empty `research_question_ids`.

    `supersedes_id`, if given, must identify an existing
    `ExperimentalDesign` in this project not already superseded by
    another row; the new design is then recorded as its direct successor
    (`version = supersedes.version + 1`). Without it, this call starts a
    new, independent lineage at `version=1`.

    Any `addressed_research_question_ids` the response cites outside
    the given `research_question_ids` is treated as a hallucinated
    reference: the whole response is rejected rather than partially
    trusted.
    """
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_experimental_design_context(
            session, project_id, methodology_plan_id, dataset_requirements_id, research_question_ids
        )
        if supersedes_id is not None:
            superseded = repository.get_experimental_design(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ExperimentalDesign", project_id)
        system_text, user_text = build_experimental_design_generation_prompt(ctx.prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="planning.experimental_design_generation_failed",
                actor=actor,
                description=f"Experimental design generation failed: {exc}",
                metadata={
                    "methodology_plan_id": methodology_plan_id,
                    "dataset_requirements_id": dataset_requirements_id,
                    "research_question_ids": research_question_ids,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, EXPERIMENTAL_DESIGN_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("proposed_method", "addressed_research_question_ids"))
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    proposed_method = response.get("proposed_method")
    if not proposed_method or not str(proposed_method).strip():
        exc = InvalidPlanningResponseError("Response 'proposed_method' must not be blank.")
        _audit_failure(exc)
        raise exc

    addressed_question_ids = [i for i in (response.get("addressed_research_question_ids") or []) if isinstance(i, int)]
    hallucinated = validate_no_hallucinated_references(
        {"addressed_research_question_ids": addressed_question_ids}, ctx.allowed_research_question_ids
    )
    if hallucinated or not addressed_question_ids:
        exc = InvalidPlanningResponseError(
            "Response 'addressed_research_question_ids' must be a non-empty subset of the given "
            f"research_question_ids; got hallucinated ids {sorted(hallucinated)}."
        )
        _audit_failure(exc)
        raise exc

    methodology_snapshot = ctx.upstream_snapshots["methodology_plan"]
    dataset_requirements_snapshot = ctx.upstream_snapshots["dataset_requirements"]

    with session_scope(session_factory) as session:
        design = repository.create_experimental_design(
            session,
            project_id=project_id,
            planning_status=PlanningApprovalStatus.CANDIDATE,
            proposed_method=str(proposed_method),
            baselines=response.get("baselines"),
            ablation_studies=response.get("ablation_studies"),
            evaluation_metrics=response.get("evaluation_metrics"),
            comparison_strategy=response.get("comparison_strategy"),
            reproducibility_requirements=response.get("reproducibility_requirements"),
            risks=response.get("risks"),
            supersedes_id=supersedes_id,
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=EXPERIMENTAL_DESIGN_GENERATION_PROMPT_NAME,
            prompt_version=EXPERIMENTAL_DESIGN_GENERATION_PROMPT_VERSION,
            methodology_plan_id=methodology_plan_id,
            methodology_plan_version=methodology_snapshot.get("version"),
            methodology_plan_status_at_generation=methodology_snapshot.get("status_at_generation"),
            dataset_requirements_id=dataset_requirements_id,
            dataset_requirements_status_at_generation=dataset_requirements_snapshot.get("status_at_generation"),
        )
        for question_id in addressed_question_ids:
            repository.link_experimental_design_question(
                session,
                project_id=project_id,
                experimental_design_id=design.id,
                research_question_id=question_id,
            )

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="planning.experimental_design_generation_completed",
            actor=actor,
            description=(
                f"Experimental design generated from methodology plan {methodology_plan_id} and dataset "
                f"requirements {dataset_requirements_id}"
            ),
            metadata={
                "experimental_design_id": design.id,
                "methodology_plan_id": methodology_plan_id,
                "dataset_requirements_id": dataset_requirements_id,
                "addressed_research_question_ids": addressed_question_ids,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": EXPERIMENTAL_DESIGN_GENERATION_PROMPT_NAME,
                "prompt_version": EXPERIMENTAL_DESIGN_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
            },
        )
        design_id = design.id

    return ExperimentalDesignGenerationOutcome(experimental_design_id=design_id)
