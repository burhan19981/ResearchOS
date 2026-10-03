"""Scientific claim creation (Phase 8 spec sections 15-19): a manual/
deterministic path (`create_scientific_claim`) and an LLM-assisted
candidate-generation path (`generate_candidate_claim`).

Both paths always persist `approval_status=ClaimApprovalStatus.
PENDING_REVIEW` — neither ever sets `APPROVED` itself. A
`ScientificClaim` is not scientific truth merely because it exists, and
never becomes one merely because an LLM produced it (Phase 8 spec
section 16); `researchos.analysis.approval.approve_scientific_claim` is
the only path that may ever move a claim to `APPROVED`, and only after
at least one linked `ScientificReview` is itself `HUMAN_APPROVED`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import ClaimApprovalStatus, ClaimStrength
from ..llm import LLMError
from ..llm.base import LLMProvider
from ..planning import orchestration
from . import context as context_module
from .errors import InvalidAnalysisInputError, InvalidAnalysisResponseError
from .llm_call import call_structured, resolve_provider
from .prompts import (
    CLAIM_GENERATION_PROMPT_NAME,
    CLAIM_GENERATION_PROMPT_VERSION,
    CLAIM_GENERATION_SCHEMA,
    build_claim_generation_prompt,
)
from .types import ClaimGenerationOutcome
from .validation import require_object_response, validate_no_hallucinated_references


def create_scientific_claim(
    project_id: int,
    claim_text: str,
    supporting_analysis_record_ids: list[int],
    *,
    actor: str,
    claim_type: Optional[str] = None,
    confidence: Optional[float] = None,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
):
    """Manual/deterministic claim authoring — no LLM involved. Requires
    at least one `supporting_analysis_record_id`, each of which must
    already exist in this project: a claim resting on no evidence at
    all is never a usable claim (Phase 8 spec section 15)."""
    if not supporting_analysis_record_ids:
        raise InvalidAnalysisInputError("create_scientific_claim requires at least one supporting_analysis_record_id.")

    with session_scope(session_factory) as session:
        for analysis_record_id in supporting_analysis_record_ids:
            record = repository.get_analysis_record(session, analysis_record_id)
            orchestration.require_in_project(record, analysis_record_id, "AnalysisRecord", project_id)
        if supersedes_id is not None:
            superseded = repository.get_scientific_claim(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ScientificClaim", project_id)

        claim = repository.create_scientific_claim(
            session,
            project_id=project_id,
            claim_text=claim_text,
            claim_type=claim_type,
            strength=ClaimStrength.NOT_ASSESSABLE,
            approval_status=ClaimApprovalStatus.PENDING_REVIEW,
            confidence=confidence,
            supersedes_id=supersedes_id,
        )
        for analysis_record_id in supporting_analysis_record_ids:
            repository.link_scientific_claim_analysis(
                session, project_id=project_id, claim_id=claim.id, analysis_record_id=analysis_record_id
            )
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="analysis.claim_created",
            actor=actor,
            description=f"ScientificClaim #{claim.id} created manually from {len(supporting_analysis_record_ids)} analysis record(s)",
            metadata={"claim_id": claim.id, "supporting_analysis_record_ids": supporting_analysis_record_ids},
        )
        claim_id = claim.id

    with session_scope(session_factory) as session:
        return repository.get_scientific_claim(session, claim_id)


def generate_candidate_claim(
    project_id: int,
    analysis_record_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    max_claims: int = 3,
    supersedes_id: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ClaimGenerationOutcome:
    """Propose up to `max_claims` candidate `ScientificClaim` rows
    interpreting the explicitly-given `analysis_record_ids`. Mirrors
    `researchos.planning.contributions.generate_contribution_candidates`
    exactly. A generated claim citing no
    `supporting_analysis_record_ids` from the given set, or citing an
    id outside it, is rejected — never persisted as an unsupported
    assertion (Phase 8 spec section 20)."""
    resolved_provider = resolve_provider(provider_name, provider)
    if supersedes_id is not None:
        max_claims = 1

    with session_scope(session_factory) as session:
        ctx = context_module.build_claim_context(session, project_id, analysis_record_ids)
        if supersedes_id is not None:
            superseded = repository.get_scientific_claim(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ScientificClaim", project_id)
        prompt_json = dict(ctx.prompt_json)
        prompt_json["max_claims"] = max_claims
        system_text, user_text = build_claim_generation_prompt(prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="analysis.claim_generation_failed",
                actor=actor,
                description=f"Candidate claim generation failed: {exc}",
                metadata={
                    "analysis_record_ids": analysis_record_ids,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, CLAIM_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("candidate_claims",))
    except InvalidAnalysisResponseError as exc:
        _audit_failure(exc)
        raise

    with session_scope(session_factory) as session:
        claim_ids: list[int] = []
        rejected_count = 0
        for raw_claim in (response.get("candidate_claims") or [])[:max_claims]:
            if not isinstance(raw_claim, dict):
                rejected_count += 1
                continue
            claim_text = raw_claim.get("claim_text")
            if not claim_text or not str(claim_text).strip():
                rejected_count += 1
                continue

            supporting_ids = [i for i in (raw_claim.get("supporting_analysis_record_ids") or []) if isinstance(i, int)]
            hallucinated = validate_no_hallucinated_references(
                {"supporting_analysis_record_ids": supporting_ids}, ctx.allowed_analysis_record_ids
            )
            if hallucinated or not supporting_ids:
                # A claim resting on no valid supplied evidence is not a
                # usable candidate — reject rather than persist an
                # unsupported assertion.
                rejected_count += 1
                continue

            confidence = raw_claim.get("confidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                confidence = None

            claim = repository.create_scientific_claim(
                session,
                project_id=project_id,
                claim_text=str(claim_text),
                claim_type=raw_claim.get("claim_type"),
                strength=ClaimStrength.NOT_ASSESSABLE,
                approval_status=ClaimApprovalStatus.PENDING_REVIEW,
                confidence=confidence,
                supersedes_id=supersedes_id if not claim_ids else None,
                provider=resolved_provider.provider_name,
                model=resolved_provider.model_name,
                prompt_name=CLAIM_GENERATION_PROMPT_NAME,
                prompt_version=CLAIM_GENERATION_PROMPT_VERSION,
            )
            for analysis_record_id in supporting_ids:
                repository.link_scientific_claim_analysis(
                    session, project_id=project_id, claim_id=claim.id, analysis_record_id=analysis_record_id
                )
            claim_ids.append(claim.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="analysis.claim_generation_completed",
            actor=actor,
            description=(
                f"Candidate claim generation from {len(analysis_record_ids)} analysis record(s) produced "
                f"{len(claim_ids)} candidate(s)" + (f", {rejected_count} rejected" if rejected_count else "")
            ),
            metadata={
                "analysis_record_ids": analysis_record_ids,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": CLAIM_GENERATION_PROMPT_NAME,
                "prompt_version": CLAIM_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
                "observations": response.get("observations"),
                "missing_evidence": response.get("missing_evidence"),
                "threats_to_validity": response.get("threats_to_validity"),
                "alternative_explanations": response.get("alternative_explanations"),
                "claim_count": len(claim_ids),
                "rejected_count": rejected_count,
            },
        )

    return ClaimGenerationOutcome(claim_ids=claim_ids, rejected_count=rejected_count)
