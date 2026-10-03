"""Scientific review creation (Phase 8 spec section 14): a manual/
deterministic path (`create_scientific_review`) and an LLM-assisted
generation path (`generate_scientific_review`).

Neither path may ever persist `ScientificReviewStatus.HUMAN_APPROVED`
or `REJECTED` — those two values are reachable only through
`researchos.analysis.approval`, the sole place a human decision is
recorded. A scientific review is an assessment of whether the *evidence*
adequately supports a claim; it is never code review, execution review,
or a re-check of any metric's arithmetic (that already happened,
deterministically, in `researchos.analysis.records`/`numeric`).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import ScientificReviewStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from ..planning import orchestration
from . import context as context_module
from .errors import InvalidAnalysisInputError, InvalidAnalysisResponseError
from .llm_call import call_structured, resolve_provider
from .prompts import (
    REVIEW_DIMENSION_KEYS,
    REVIEW_GENERATION_ALLOWED_STATUSES,
    REVIEW_GENERATION_PROMPT_NAME,
    REVIEW_GENERATION_PROMPT_VERSION,
    REVIEW_GENERATION_SCHEMA,
    build_review_generation_prompt,
)
from .types import ReviewGenerationOutcome
from .validation import require_object_response

# A manual/deterministic caller may set any status EXCEPT the two
# reserved exclusively for `researchos.analysis.approval` — mirrors
# ScientificReviewStatus's own docstring ("only a human may ever set
# HUMAN_APPROVED ... or REJECTED").
_MANUAL_ALLOWED_STATUSES = frozenset(
    {
        ScientificReviewStatus.DRAFT,
        ScientificReviewStatus.CANDIDATE,
        ScientificReviewStatus.NEEDS_MORE_EVIDENCE,
        ScientificReviewStatus.READY_FOR_HUMAN_REVIEW,
    }
)


def create_scientific_review(
    project_id: int,
    claim_id: int,
    dimensions: dict,
    *,
    actor: str,
    status: ScientificReviewStatus = ScientificReviewStatus.DRAFT,
    recommendation: Optional[str] = None,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
):
    """Manual/deterministic review authoring — no LLM involved.
    `status` must be one of DRAFT/CANDIDATE/NEEDS_MORE_EVIDENCE/
    READY_FOR_HUMAN_REVIEW; `HUMAN_APPROVED`/`REJECTED` are rejected
    here even if a caller passes them — those require
    `researchos.analysis.approval`."""
    if status not in _MANUAL_ALLOWED_STATUSES:
        raise InvalidAnalysisInputError(
            f"create_scientific_review cannot set status={status.value!r} directly; "
            "use researchos.analysis.approval for HUMAN_APPROVED/REJECTED."
        )

    with session_scope(session_factory) as session:
        claim = repository.get_scientific_claim(session, claim_id)
        orchestration.require_in_project(claim, claim_id, "ScientificClaim", project_id)
        if supersedes_id is not None:
            superseded = repository.get_scientific_review(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ScientificReview", project_id)

        review = repository.create_scientific_review(
            session,
            project_id=project_id,
            claim_id=claim_id,
            status=status,
            dimensions=dimensions,
            recommendation=recommendation,
            supersedes_id=supersedes_id,
        )
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="analysis.scientific_review_created",
            actor=actor,
            description=f"ScientificReview #{review.id} created manually for ScientificClaim #{claim_id}",
            metadata={"review_id": review.id, "claim_id": claim_id, "status": status.value},
        )
        review_id = review.id

    with session_scope(session_factory) as session:
        return repository.get_scientific_review(session, review_id)


def generate_scientific_review(
    project_id: int,
    claim_id: int,
    *,
    actor: str,
    provider_name: str,
    supersedes_id: Optional[int] = None,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ReviewGenerationOutcome:
    """LLM-assisted scientific review generation for one `claim_id`,
    grounded only in the claim's already-linked `AnalysisRecord`
    evidence (`researchos.analysis.context.build_review_context`).
    Rejects the whole response (`InvalidAnalysisResponseError`,
    audited, nothing persisted) if the model proposes a `status`
    outside `REVIEW_GENERATION_ALLOWED_STATUSES` or omits any of the
    twelve required dimensions — a malformed or over-reaching review is
    never silently coerced into a valid one."""
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_review_context(session, project_id, claim_id)
        if supersedes_id is not None:
            superseded = repository.get_scientific_review(session, supersedes_id)
            orchestration.require_in_project(superseded, supersedes_id, "ScientificReview", project_id)
        system_text, user_text = build_review_generation_prompt(ctx.prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="analysis.scientific_review_generation_failed",
                actor=actor,
                description=f"Scientific review generation failed for ScientificClaim #{claim_id}: {exc}",
                metadata={
                    "claim_id": claim_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, REVIEW_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("dimensions", "status"))
        dimensions = response["dimensions"]
        if not isinstance(dimensions, dict) or any(key not in dimensions for key in REVIEW_DIMENSION_KEYS):
            raise InvalidAnalysisResponseError(
                f"Response 'dimensions' must include all of: {', '.join(REVIEW_DIMENSION_KEYS)}."
            )
        status_raw = response["status"]
        if status_raw not in REVIEW_GENERATION_ALLOWED_STATUSES:
            raise InvalidAnalysisResponseError(
                f"Response 'status' must be one of {REVIEW_GENERATION_ALLOWED_STATUSES}, got {status_raw!r} — "
                "an LLM may never propose HUMAN_APPROVED or REJECTED."
            )
    except InvalidAnalysisResponseError as exc:
        _audit_failure(exc)
        raise

    status = ScientificReviewStatus(status_raw)

    with session_scope(session_factory) as session:
        review = repository.create_scientific_review(
            session,
            project_id=project_id,
            claim_id=claim_id,
            status=status,
            dimensions=dimensions,
            recommendation=response.get("recommendation"),
            supersedes_id=supersedes_id,
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=REVIEW_GENERATION_PROMPT_NAME,
            prompt_version=REVIEW_GENERATION_PROMPT_VERSION,
        )
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="analysis.scientific_review_completed",
            actor=actor,
            description=f"ScientificReview #{review.id} generated for ScientificClaim #{claim_id} (status={status.value})",
            metadata={
                "review_id": review.id,
                "claim_id": claim_id,
                "status": status.value,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": REVIEW_GENERATION_PROMPT_NAME,
                "prompt_version": REVIEW_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
            },
        )
        review_id = review.id

    return ReviewGenerationOutcome(review_id=review_id)
