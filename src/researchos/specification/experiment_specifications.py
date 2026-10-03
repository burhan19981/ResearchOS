"""Experiment specification generation service (Phase 8A).

Generates one CANDIDATE `ExperimentSpecification` from one already-
approved `ExperimentalDesign` and one already-approved `DatasetVersion`,
addressing the explicit `ResearchQuestion` ids given, optionally
associated with one or more already-approved `ContributionCandidate`
ids. Mirrors `researchos.planning`'s generation-service pattern exactly
— including the failure-path transaction discipline (LLM call outside
any `session_scope()`; a failure gets its own, separately-committed
audit session) — reusing `researchos.planning.llm_call`/`validation`/
`orchestration` directly rather than a third copy of each.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import PlanningApprovalStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from ..planning import orchestration
from ..planning.errors import InvalidPlanningResponseError
from ..planning.llm_call import call_structured, resolve_provider
from ..planning.validation import require_object_response, validate_no_hallucinated_references
from . import context as context_module
from .errors import ConfigurationValidationError
from .fingerprint import compute_configuration_hash
from .prompts import (
    EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_NAME,
    EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_VERSION,
    EXPERIMENT_SPECIFICATION_GENERATION_SCHEMA,
    build_experiment_specification_generation_prompt,
)
from .types import ExperimentSpecificationGenerationOutcome

_CONFIGURATION_SCHEMA_VERSION = "v1"

# Configuration keys are rejected (case-insensitive substring match) if
# they look like they might hold a credential — configuration is
# persisted and displayed as ordinary planning data, never treated as a
# secret store. Mirrors researchos.llm.redaction's spirit (never let a
# secret-shaped value flow into something logged/displayed) applied to
# a new surface (LLM-generated JSON configuration) that Phase 7 never had.
_FORBIDDEN_CONFIG_KEY_SUBSTRINGS = (
    "api_key", "apikey", "secret", "password", "passwd", "token", "credential", "access_key", "private_key",
)


def _find_forbidden_config_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if any(bad in str(key).lower() for bad in _FORBIDDEN_CONFIG_KEY_SUBSTRINGS):
                found.append(key_path)
            found.extend(_find_forbidden_config_keys(nested, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_config_keys(item, f"{path}[{index}]"))
    return found


def _validate_configuration(configuration: Any) -> dict[str, Any]:
    if not isinstance(configuration, dict):
        raise ConfigurationValidationError("configuration must be a JSON object.")
    forbidden = _find_forbidden_config_keys(configuration)
    if forbidden:
        raise ConfigurationValidationError(
            f"configuration contains key(s) that look like credentials and cannot be persisted: {forbidden}. "
            "Configuration is planning data, not a secret store."
        )
    return configuration


def generate_experiment_specification(
    project_id: int,
    experimental_design_id: int,
    dataset_version_id: int,
    research_question_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    contribution_candidate_ids: Optional[list[int]] = None,
    supersedes_id: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ExperimentSpecificationGenerationOutcome:
    """Propose one candidate experiment specification.

    Raises before any LLM call if `experimental_design_id` is not
    `planning_status APPROVED`, if `dataset_version_id` is not
    `lifecycle_status APPROVED`, if any given `contribution_candidate_ids`/
    `supersedes_id` is missing or cross-project, or if
    `research_question_ids` is empty.
    """
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_experiment_specification_context(
            session, project_id, experimental_design_id, dataset_version_id, research_question_ids
        )
        design = repository.get_experimental_design(session, experimental_design_id)
        methodology_plan_id = design.methodology_plan_id

        validated_contribution_ids: list[int] = []
        for contribution_id in contribution_candidate_ids or []:
            contribution = repository.get_contribution_candidate(session, contribution_id)
            orchestration.require_in_project(contribution, contribution_id, "ContributionCandidate", project_id)
            validated_contribution_ids.append(contribution_id)

        if supersedes_id is not None:
            superseded = repository.get_experiment_specification(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ExperimentSpecification", project_id)

        system_text, user_text = build_experiment_specification_generation_prompt(ctx.prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="specification.experiment_specification_generation_failed",
                actor=actor,
                description=f"Experiment specification generation failed: {exc}",
                metadata={
                    "experimental_design_id": experimental_design_id,
                    "dataset_version_id": dataset_version_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(
            resolved_provider, system_text, user_text, EXPERIMENT_SPECIFICATION_GENERATION_SCHEMA
        )
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(
            response, expected_keys=("description", "configuration", "addressed_research_question_ids")
        )
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    description = response.get("description")
    if not description or not str(description).strip():
        exc = InvalidPlanningResponseError("Response 'description' must not be blank.")
        _audit_failure(exc)
        raise exc

    try:
        configuration = _validate_configuration(response.get("configuration"))
    except ConfigurationValidationError as exc:
        _audit_failure(exc)
        raise

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

    configuration_hash = compute_configuration_hash(configuration)

    design_snapshot = ctx.upstream_snapshots["experimental_design"]
    dataset_snapshot = ctx.upstream_snapshots["dataset_version"]
    methodology_snapshot = ctx.upstream_snapshots.get("methodology_plan") or {}

    with session_scope(session_factory) as session:
        spec = repository.create_experiment_specification(
            session,
            project_id=project_id,
            experimental_design_id=experimental_design_id,
            methodology_plan_id=methodology_plan_id,
            dataset_version_id=dataset_version_id,
            supersedes_id=supersedes_id,
            description=str(description),
            configuration=configuration,
            configuration_schema_version=_CONFIGURATION_SCHEMA_VERSION,
            configuration_hash=configuration_hash,
            planning_status=PlanningApprovalStatus.CANDIDATE,
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_NAME,
            prompt_version=EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_VERSION,
            experimental_design_version=design_snapshot.get("version"),
            experimental_design_status_at_generation=design_snapshot.get("status_at_generation"),
            methodology_plan_version=methodology_snapshot.get("version"),
            methodology_plan_status_at_generation=methodology_snapshot.get("status_at_generation"),
            dataset_version_version=dataset_snapshot.get("version"),
            dataset_version_status_at_generation=dataset_snapshot.get("status_at_generation"),
        )
        for question_id in addressed_question_ids:
            repository.link_experiment_specification_question(
                session, project_id=project_id, experiment_specification_id=spec.id, research_question_id=question_id,
            )
        for contribution_id in validated_contribution_ids:
            repository.link_experiment_specification_contribution(
                session,
                project_id=project_id,
                experiment_specification_id=spec.id,
                contribution_candidate_id=contribution_id,
            )

        baseline_ids: list[int] = []
        for raw_baseline in response.get("baselines") or []:
            if not isinstance(raw_baseline, dict):
                continue
            name = raw_baseline.get("name")
            if not name or not str(name).strip():
                continue
            baseline = repository.create_baseline_specification(
                session,
                project_id=project_id,
                experiment_specification_id=spec.id,
                name=str(name),
                version=raw_baseline.get("version"),
                source=raw_baseline.get("source"),
                implementation_reference=raw_baseline.get("implementation_reference"),
                configuration=raw_baseline.get("configuration"),
                rationale=raw_baseline.get("rationale"),
            )
            baseline_ids.append(baseline.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="specification.experiment_specification_generation_completed",
            actor=actor,
            description=(
                f"Experiment specification generated from design {experimental_design_id} and dataset "
                f"version {dataset_version_id}"
            ),
            metadata={
                "experiment_specification_id": spec.id,
                "experimental_design_id": experimental_design_id,
                "dataset_version_id": dataset_version_id,
                "addressed_research_question_ids": addressed_question_ids,
                "contribution_candidate_ids": validated_contribution_ids,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_NAME,
                "prompt_version": EXPERIMENT_SPECIFICATION_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
                "configuration_hash": configuration_hash,
                "baseline_count": len(baseline_ids),
            },
        )
        spec_id = spec.id

    return ExperimentSpecificationGenerationOutcome(experiment_specification_id=spec_id, baseline_ids=baseline_ids)
