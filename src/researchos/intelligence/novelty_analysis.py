"""Novelty candidate analysis service: Phase 6 spec section 6.

Compares a proposed research contribution against retrieved prior work.
This is explicitly NOT a novelty detector issuing a certain verdict —
`NoveltyCandidateStatus` never includes a bare "novel: yes", and
`HUMAN_APPROVED` (the one status representing a settled outcome) is
excluded from the LLM's schema and defensively rejected here if it
somehow appears anyway, since only a human may ever set it
(`researchos.intelligence.approval`).

The `NoveltyAssessment` row is only created after the LLM call succeeds
and its response passes shape validation (there is no "FAILED" status
concept for this entity, unlike `LiteratureAnalysis` — a call that never
got a usable response has nothing worth persisting as a row). The LLM
call itself still happens outside any `session_scope()`, so a
failure-path audit write is its own independently-committed transaction.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import ComparisonStatus, EvidenceRelationship, EvidenceSubjectType, NoveltyCandidateStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from .errors import InvalidAnalysisResponseError
from .evidence_package import DEFAULT_MAX_ABSTRACT_CHARS, DEFAULT_MAX_ITEMS, build_evidence_package
from .llm_call import call_structured, resolve_provider
from .prompts import (
    NOVELTY_ANALYSIS_PROMPT_NAME,
    NOVELTY_ANALYSIS_PROMPT_VERSION,
    NOVELTY_ANALYSIS_SCHEMA,
    build_novelty_analysis_prompt,
)
from .response_validation import require_object_response
from .types import NoveltyAnalysisOutcome


def _clamp_confidence(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0:
        return float(value)
    return None


def analyze_novelty_candidate(
    project_id: int,
    proposed_contribution: str,
    literature_item_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    research_question_id: Optional[int] = None,
    source_gap_ids: Optional[list[int]] = None,
    source_analysis_ids: Optional[list[int]] = None,
    contribution_candidate_id: Optional[int] = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_abstract_chars: int = DEFAULT_MAX_ABSTRACT_CHARS,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> NoveltyAnalysisOutcome:
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        package = build_evidence_package(
            session, project_id, literature_item_ids, max_items=max_items, max_abstract_chars=max_abstract_chars
        )
        system_text, user_text = build_novelty_analysis_prompt(package, proposed_contribution=proposed_contribution)
        included_item_ids = list(package.included_item_ids)

    allowed_ids = set(included_item_ids)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="intelligence.novelty_analysis_failed",
                actor=actor,
                description=f"Novelty analysis failed: {exc}",
                metadata={
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, NOVELTY_ANALYSIS_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("comparisons", "candidate_status"))
    except InvalidAnalysisResponseError as exc:
        _audit_failure(exc)
        raise

    candidate_status_raw = response.get("candidate_status")
    try:
        candidate_status = NoveltyCandidateStatus(candidate_status_raw)
        if candidate_status == NoveltyCandidateStatus.HUMAN_APPROVED:
            # Defense in depth: the schema already excludes this value,
            # but never trust schema enforcement alone — the LLM can
            # never approve its own output.
            candidate_status = NoveltyCandidateStatus.INSUFFICIENT_EVIDENCE
    except ValueError:
        candidate_status = NoveltyCandidateStatus.INSUFFICIENT_EVIDENCE

    with session_scope(session_factory) as session:
        assessment = repository.record_novelty_assessment(
            session,
            project_id=project_id,
            claim=proposed_contribution,
            candidate_status=candidate_status,
            research_question_id=research_question_id,
            source_gap_ids=source_gap_ids,
            source_analysis_ids=source_analysis_ids,
            contribution_candidate_id=contribution_candidate_id,
            provider=resolved_provider.provider_name,
            model=resolved_provider.model_name,
            prompt_name=NOVELTY_ANALYSIS_PROMPT_NAME,
            prompt_version=NOVELTY_ANALYSIS_PROMPT_VERSION,
            unresolved_questions=response.get("unresolved_questions"),
            novelty_risk=response.get("novelty_risk"),
            confidence=_clamp_confidence(response.get("confidence")),
            evidence=response.get("potentially_existing_elements"),
        )

        comparison_ids: list[int] = []
        rejected_count = 0
        for raw_comparison in response.get("comparisons") or []:
            if not isinstance(raw_comparison, dict):
                rejected_count += 1
                continue
            literature_item_id = raw_comparison.get("literature_item_id")
            similarity_evidence_ids = [i for i in (raw_comparison.get("similarity_evidence_ids") or []) if isinstance(i, int)]
            difference_evidence_ids = [i for i in (raw_comparison.get("difference_evidence_ids") or []) if isinstance(i, int)]
            all_cited = {literature_item_id, *similarity_evidence_ids, *difference_evidence_ids}
            if not isinstance(literature_item_id, int) or (all_cited - allowed_ids):
                # Any hallucinated reference anywhere in this comparison
                # invalidates the whole row — never partially trust it.
                rejected_count += 1
                continue

            try:
                comparison_status = ComparisonStatus(raw_comparison.get("status"))
            except ValueError:
                comparison_status = ComparisonStatus.UNCLEAR

            comparison = repository.create_novelty_comparison(
                session,
                project_id=project_id,
                novelty_assessment_id=assessment.id,
                literature_item_id=literature_item_id,
                similarity=raw_comparison.get("similarity"),
                difference=raw_comparison.get("difference"),
                status=comparison_status,
            )
            for evidence_id in similarity_evidence_ids or [literature_item_id]:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=evidence_id,
                    subject_type=EvidenceSubjectType.NOVELTY_COMPARISON,
                    subject_id=comparison.id,
                    relationship_type=EvidenceRelationship.SUPPORTS,
                )
            for evidence_id in difference_evidence_ids:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=evidence_id,
                    subject_type=EvidenceSubjectType.NOVELTY_COMPARISON,
                    subject_id=comparison.id,
                    relationship_type=EvidenceRelationship.CONTRADICTS,
                )
            comparison_ids.append(comparison.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="intelligence.novelty_analysis_completed",
            actor=actor,
            description=(
                f"Novelty analysis produced {len(comparison_ids)} comparison(s), "
                f"candidate_status={candidate_status.value}"
                + (f", {rejected_count} comparison(s) rejected" if rejected_count else "")
            ),
            metadata={
                "assessment_id": assessment.id,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": NOVELTY_ANALYSIS_PROMPT_NAME,
                "prompt_version": NOVELTY_ANALYSIS_PROMPT_VERSION,
                "candidate_status": candidate_status.value,
                "comparison_count": len(comparison_ids),
                "rejected_comparison_count": rejected_count,
            },
        )

        outcome = NoveltyAnalysisOutcome(
            assessment_id=assessment.id, comparison_ids=comparison_ids, rejected_comparison_count=rejected_count
        )

    return outcome
