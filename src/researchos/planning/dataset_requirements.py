"""Dataset requirements generation service (Phase 7 spec section 28).

Generates one CANDIDATE `DatasetRequirements` row from one already-
approved `MethodologyPlan`. `DatasetRequirements` describes what the
research *needs* from its data — it never names, recommends, or implies
a specific real dataset has been chosen; that remains a separate,
later, human-driven step against the existing `DatasetRecord` entity,
which this service never creates or touches.
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
    DATASET_REQUIREMENTS_GENERATION_PROMPT_NAME,
    DATASET_REQUIREMENTS_GENERATION_PROMPT_VERSION,
    DATASET_REQUIREMENTS_GENERATION_SCHEMA,
    build_dataset_requirements_generation_prompt,
)
from .types import DatasetRequirementsGenerationOutcome
from .validation import require_object_response


def generate_dataset_requirements(
    project_id: int,
    methodology_plan_id: int,
    *,
    actor: str,
    provider_name: str,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> DatasetRequirementsGenerationOutcome:
    """Propose one candidate dataset requirements spec for
    `methodology_plan_id`, which must already be `planning_status
    APPROVED`."""
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_dataset_requirements_context(session, project_id, methodology_plan_id)
        system_text, user_text = build_dataset_requirements_generation_prompt(ctx.prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="planning.dataset_requirements_generation_failed",
                actor=actor,
                description=f"Dataset requirements generation failed: {exc}",
                metadata={
                    "methodology_plan_id": methodology_plan_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, DATASET_REQUIREMENTS_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("required_characteristics",))
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    required_characteristics = response.get("required_characteristics")
    if not required_characteristics or not str(required_characteristics).strip():
        exc = InvalidPlanningResponseError("Response 'required_characteristics' must not be blank.")
        _audit_failure(exc)
        raise exc

    methodology_snapshot = ctx.upstream_snapshots["methodology_plan"]

    with session_scope(session_factory) as session:
        requirements = repository.create_dataset_requirements(
            session,
            project_id=project_id,
            planning_status=PlanningApprovalStatus.CANDIDATE,
            required_characteristics=str(required_characteristics),
            source_requirements=response.get("source_requirements"),
            inclusion_criteria=response.get("inclusion_criteria"),
            exclusion_criteria=response.get("exclusion_criteria"),
            annotation_requirements=response.get("annotation_requirements"),
            split_strategy=response.get("split_strategy"),
            leakage_considerations=response.get("leakage_considerations"),
            risks=response.get("risks"),
            reproducibility_requirements=response.get("reproducibility_requirements"),
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=DATASET_REQUIREMENTS_GENERATION_PROMPT_NAME,
            prompt_version=DATASET_REQUIREMENTS_GENERATION_PROMPT_VERSION,
            methodology_plan_id=methodology_plan_id,
            methodology_plan_version=methodology_snapshot.get("version"),
            methodology_plan_status_at_generation=methodology_snapshot.get("status_at_generation"),
        )

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="planning.dataset_requirements_generation_completed",
            actor=actor,
            description=f"Dataset requirements generated from methodology plan {methodology_plan_id}",
            metadata={
                "dataset_requirements_id": requirements.id,
                "methodology_plan_id": methodology_plan_id,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": DATASET_REQUIREMENTS_GENERATION_PROMPT_NAME,
                "prompt_version": DATASET_REQUIREMENTS_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
            },
        )
        requirements_id = requirements.id

    return DatasetRequirementsGenerationOutcome(dataset_requirements_id=requirements_id)
