"""Contribution candidate generation service (Phase 7 spec section 26).

Generates CANDIDATE `ContributionCandidate` rows from one or more
already-approved `ResearchQuestion` rows. `ContributionCandidate` is
deliberately a distinct entity from `NoveltyAssessment` — see
docs/PHASE7_RESEARCH_PLANNING.md for the full reasoning — so this
service never touches `NoveltyAssessment` at all; novelty assessment of
a generated contribution remains `researchos.intelligence`'s
`analyze_novelty_candidate()`, run separately, afterward, against a
`ContributionCandidate.id`.

This service never claims a generated contribution is novel — that
would collapse exactly the distinction this phase was designed to keep.
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
    CONTRIBUTION_GENERATION_PROMPT_NAME,
    CONTRIBUTION_GENERATION_PROMPT_VERSION,
    CONTRIBUTION_GENERATION_SCHEMA,
    build_contribution_generation_prompt,
)
from .types import ContributionGenerationOutcome
from .validation import require_object_response, validate_no_hallucinated_references


def generate_contribution_candidates(
    project_id: int,
    research_question_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    max_candidates: int = 3,
    supersedes_id: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ContributionGenerationOutcome:
    """Propose up to `max_candidates` candidate contributions addressing
    the explicitly-given `research_question_ids`, all of which must
    already be `planning_status APPROVED`.

    `supersedes_id`, if given, must identify an existing
    `ContributionCandidate` in this project not already superseded by
    another row — this call then produces exactly ONE new candidate (a
    revised version of that specific prior row, `version =
    supersedes.version + 1`), regardless of `max_candidates`, since a
    targeted regeneration of one specific prior artifact only ever
    produces its one replacement. Without `supersedes_id`, every
    generated candidate starts its own new, independent lineage at
    `version=1`.

    A generated contribution citing no `cited_research_question_ids`
    from the given set, or citing an id outside it, is rejected — never
    persisted as an unsupported assertion.
    """
    resolved_provider = resolve_provider(provider_name, provider)
    if supersedes_id is not None:
        max_candidates = 1

    with session_scope(session_factory) as session:
        ctx = context_module.build_contribution_context(session, project_id, research_question_ids)
        if supersedes_id is not None:
            superseded = repository.get_contribution_candidate(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ContributionCandidate", project_id)
        prompt_json = dict(ctx.prompt_json)
        prompt_json["max_candidates"] = max_candidates
        system_text, user_text = build_contribution_generation_prompt(prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="planning.contribution_generation_failed",
                actor=actor,
                description=f"Contribution generation failed: {exc}",
                metadata={
                    "research_question_ids": research_question_ids,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, CONTRIBUTION_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("contributions",))
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    with session_scope(session_factory) as session:
        contribution_ids: list[int] = []
        rejected_count = 0
        for raw_contribution in (response.get("contributions") or [])[:max_candidates]:
            if not isinstance(raw_contribution, dict):
                rejected_count += 1
                continue
            title = raw_contribution.get("title")
            description = raw_contribution.get("description")
            if not title or not str(title).strip() or not description or not str(description).strip():
                rejected_count += 1
                continue

            cited_question_ids = [
                i for i in (raw_contribution.get("cited_research_question_ids") or []) if isinstance(i, int)
            ]
            hallucinated = validate_no_hallucinated_references(
                {"cited_research_question_ids": cited_question_ids}, ctx.allowed_research_question_ids
            )
            if hallucinated or not cited_question_ids:
                # A contribution with no valid supporting research question
                # is not a usable candidate — reject rather than persist an
                # unsupported assertion.
                rejected_count += 1
                continue

            contribution = repository.create_contribution_candidate(
                session,
                project_id=project_id,
                title=str(title),
                description=str(description),
                contribution_type=raw_contribution.get("contribution_type"),
                planning_status=PlanningApprovalStatus.CANDIDATE,
                supersedes_id=supersedes_id if not contribution_ids else None,
                provider=resolved_provider.provider_name,
                model=resolved_provider.model_name,
                prompt_name=CONTRIBUTION_GENERATION_PROMPT_NAME,
                prompt_version=CONTRIBUTION_GENERATION_PROMPT_VERSION,
            )
            for question_id in cited_question_ids:
                repository.link_contribution_candidate_question(
                    session,
                    project_id=project_id,
                    contribution_candidate_id=contribution.id,
                    research_question_id=question_id,
                )
            contribution_ids.append(contribution.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="planning.contribution_generation_completed",
            actor=actor,
            description=(
                f"Contribution generation from {len(research_question_ids)} research question(s) produced "
                f"{len(contribution_ids)} candidate(s)" + (f", {rejected_count} rejected" if rejected_count else "")
            ),
            metadata={
                "research_question_ids": research_question_ids,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": CONTRIBUTION_GENERATION_PROMPT_NAME,
                "prompt_version": CONTRIBUTION_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
                "contribution_count": len(contribution_ids),
                "rejected_count": rejected_count,
            },
        )

    return ContributionGenerationOutcome(contribution_ids=contribution_ids, rejected_count=rejected_count)
