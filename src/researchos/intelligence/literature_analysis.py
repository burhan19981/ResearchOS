"""Literature analysis service: Phase 6 spec section 3.

Prepares a bounded evidence package from persisted `LiteratureItem`
rows, sends it to an LLM through the Phase 2 provider abstraction for
structured per-item dimension analysis plus zero-or-more traceable
claims, validates the response against the anti-hallucination
invariant, and persists exactly what survives validation.

The LLM call itself always happens *outside* any `session_scope()` —
each database transaction (creating the PENDING row, marking it FAILED,
and persisting a COMPLETED result) is separate and independently
committed, exactly like `researchos.evidence.service`'s pattern for the
same reason: a `session_scope()` block rolls back everything inside it
when the exception that triggered a failure-handler is re-raised, so
the failure record itself must live in its own, already-closed
transaction before that re-raise happens.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import AnalysisStatus, ClaimSupportLevel, EvidenceRelationship, EvidenceSubjectType
from ..llm import LLMError
from ..llm.base import LLMProvider
from .errors import InvalidAnalysisResponseError
from .evidence_package import DEFAULT_MAX_ABSTRACT_CHARS, DEFAULT_MAX_ITEMS, build_evidence_package
from .llm_call import call_structured, resolve_provider
from .prompts import (
    LITERATURE_ANALYSIS_PROMPT_NAME,
    LITERATURE_ANALYSIS_PROMPT_VERSION,
    LITERATURE_ANALYSIS_SCHEMA,
    build_literature_analysis_prompt,
)
from .response_validation import require_object_response
from .types import ANALYSIS_DIMENSIONS, UNKNOWN, LiteratureAnalysisOutcome


def _clean_dimension_values(value: Any) -> dict[str, str]:
    """Every one of the 13 dimensions, defaulting to "unknown" — never
    omitted, never left for a caller to guess was missing."""
    if not isinstance(value, dict):
        return {name: UNKNOWN for name in ANALYSIS_DIMENSIONS}
    cleaned: dict[str, str] = {}
    for name in ANALYSIS_DIMENSIONS:
        raw = value.get(name)
        cleaned[name] = raw if isinstance(raw, str) and raw.strip() else UNKNOWN
    return cleaned


def _clamp_confidence(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0:
        return float(value)
    return None


def run_literature_analysis(
    project_id: int,
    research_topic: str,
    literature_item_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    objective: Optional[str] = None,
    research_question_id: Optional[int] = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_abstract_chars: int = DEFAULT_MAX_ABSTRACT_CHARS,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> LiteratureAnalysisOutcome:
    """Run one literature-analysis LLM call and persist its validated result.

    Raises `EvidencePackageError` if an id in `literature_item_ids`
    doesn't resolve, `InvalidAnalysisResponseError` if the LLM's
    response has the wrong shape, and lets any `LLMError` from the
    provider layer propagate — in both failure cases, the analysis row
    is first marked `FAILED` with the error recorded, in its own
    committed transaction, before the exception propagates.
    """
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        package = build_evidence_package(
            session, project_id, literature_item_ids, max_items=max_items, max_abstract_chars=max_abstract_chars
        )
        system_text, user_text = build_literature_analysis_prompt(package, research_topic=research_topic, objective=objective)
        analysis = repository.create_literature_analysis(
            session,
            project_id=project_id,
            research_topic=research_topic,
            actor=actor,
            requested_item_ids=package.requested_item_ids,
            included_item_ids=package.included_item_ids,
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=LITERATURE_ANALYSIS_PROMPT_NAME,
            prompt_version=LITERATURE_ANALYSIS_PROMPT_VERSION,
            objective=objective,
            research_question_id=research_question_id,
            truncated=package.truncated,
            status=AnalysisStatus.PENDING,
        )
        analysis_id = analysis.id
        included_item_ids = list(package.included_item_ids)
        item_count = len(package.items)
        truncated = package.truncated

    def _mark_failed(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.update_literature_analysis(failure_session, analysis_id, status=AnalysisStatus.FAILED, error=str(exc))
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="intelligence.literature_analysis_failed",
                actor=actor,
                description=f"Literature analysis failed: {exc}",
                metadata={
                    "analysis_id": analysis_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, LITERATURE_ANALYSIS_SCHEMA)
    except LLMError as exc:
        _mark_failed(exc)
        raise

    try:
        require_object_response(response, expected_keys=("items", "claims"))
    except InvalidAnalysisResponseError as exc:
        _mark_failed(exc)
        raise

    allowed_ids = set(included_item_ids)
    clean_items: dict[str, dict[str, str]] = {}
    for key, value in (response.get("items") or {}).items():
        try:
            item_id = int(key)
        except (TypeError, ValueError):
            continue
        if item_id not in allowed_ids:
            continue  # a hallucinated key is dropped, never persisted as if it were real
        clean_items[str(item_id)] = _clean_dimension_values(value)
    result_payload = {"items": clean_items, "evidence_item_ids": sorted(allowed_ids)}

    with session_scope(session_factory) as session:
        repository.update_literature_analysis(session, analysis_id, status=AnalysisStatus.COMPLETED, result=result_payload)

        claim_ids: list[int] = []
        rejected_count = 0
        for raw_claim in response.get("claims") or []:
            claim_text = raw_claim.get("claim_text") if isinstance(raw_claim, dict) else None
            if not claim_text or not str(claim_text).strip():
                rejected_count += 1
                continue

            evidence_ids = [i for i in (raw_claim.get("evidence_item_ids") or []) if isinstance(i, int)]
            hallucinated = set(evidence_ids) - allowed_ids
            if hallucinated:
                # The core anti-hallucination guard: never silently accept
                # a claim that cites evidence outside the package it was given.
                rejected_count += 1
                continue

            if not evidence_ids:
                support_level = ClaimSupportLevel.UNSUPPORTED_CANDIDATE
            else:
                try:
                    support_level = ClaimSupportLevel(raw_claim.get("support_level"))
                except ValueError:
                    support_level = ClaimSupportLevel.PARTIALLY_SUPPORTED

            claim = repository.create_analysis_claim(
                session,
                project_id=project_id,
                analysis_id=analysis_id,
                claim_text=str(claim_text),
                provider=resolved_provider.provider_name,
                model=resolved_provider.model_name,
                claim_type=raw_claim.get("claim_type"),
                support_level=support_level,
                confidence=_clamp_confidence(raw_claim.get("confidence")),
                uncertainty=raw_claim.get("uncertainty"),
            )
            for evidence_id in evidence_ids:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=evidence_id,
                    subject_type=EvidenceSubjectType.ANALYSIS_CLAIM,
                    subject_id=claim.id,
                    relationship_type=EvidenceRelationship.CITES,
                )
            claim_ids.append(claim.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="intelligence.literature_analysis_completed",
            actor=actor,
            description=(
                f"Literature analysis on {item_count} item(s) produced {len(claim_ids)} claim(s)"
                + (f", {rejected_count} rejected (invalid/hallucinated evidence)" if rejected_count else "")
            ),
            metadata={
                "analysis_id": analysis_id,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": LITERATURE_ANALYSIS_PROMPT_NAME,
                "prompt_version": LITERATURE_ANALYSIS_PROMPT_VERSION,
                "included_item_ids": included_item_ids,
                "truncated": truncated,
                "claim_count": len(claim_ids),
                "rejected_claim_count": rejected_count,
            },
        )

    return LiteratureAnalysisOutcome(
        analysis_id=analysis_id,
        result=result_payload,
        claim_ids=claim_ids,
        rejected_claim_count=rejected_count,
        truncated=truncated,
    )
