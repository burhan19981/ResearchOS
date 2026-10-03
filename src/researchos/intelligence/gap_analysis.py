"""Gap candidate generation service: Phase 6 spec section 5.

Generates CANDIDATE research gaps from persisted evidence — never a
"confirmed" gap. Every persisted `ResearchGap` starts at
`GapStatus.CANDIDATE` and requires human approval
(`researchos.intelligence.approval`) before it means anything more than
"an LLM noticed a pattern worth a human looking at."

Like `literature_analysis`, the LLM call happens outside any
`session_scope()` so a failure-path audit write commits independently
of whatever transaction surrounds the call itself.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import EvidenceRelationship, EvidenceSubjectType, GapStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from .errors import InvalidAnalysisResponseError
from .evidence_package import DEFAULT_MAX_ABSTRACT_CHARS, DEFAULT_MAX_ITEMS, build_evidence_package
from .llm_call import call_structured, resolve_provider
from .prompts import GAP_ANALYSIS_PROMPT_NAME, GAP_ANALYSIS_PROMPT_VERSION, GAP_ANALYSIS_SCHEMA, build_gap_analysis_prompt
from .response_validation import require_object_response
from .types import GapCandidateOutcome


def _clamp_confidence(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0:
        return float(value)
    return None


def generate_gap_candidates(
    project_id: int,
    research_topic: str,
    literature_item_ids: list[int],
    *,
    actor: str,
    provider_name: str,
    research_question_id: Optional[int] = None,
    source_analysis_ids: Optional[list[int]] = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_abstract_chars: int = DEFAULT_MAX_ABSTRACT_CHARS,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> GapCandidateOutcome:
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        package = build_evidence_package(
            session, project_id, literature_item_ids, max_items=max_items, max_abstract_chars=max_abstract_chars
        )
        system_text, user_text = build_gap_analysis_prompt(package, research_topic=research_topic)
        included_item_ids = list(package.included_item_ids)
        item_count = len(package.items)
        truncated = package.truncated

    allowed_ids = set(included_item_ids)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="intelligence.gap_analysis_failed",
                actor=actor,
                description=f"Gap analysis failed: {exc}",
                metadata={
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, GAP_ANALYSIS_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("gaps",))
    except InvalidAnalysisResponseError as exc:
        _audit_failure(exc)
        raise

    with session_scope(session_factory) as session:
        gap_ids: list[int] = []
        rejected_count = 0
        for raw_gap in response.get("gaps") or []:
            if not isinstance(raw_gap, dict):
                rejected_count += 1
                continue
            statement = raw_gap.get("gap_statement")
            if not statement or not str(statement).strip():
                rejected_count += 1
                continue

            supporting_ids = [i for i in (raw_gap.get("supporting_literature_ids") or []) if isinstance(i, int)]
            contradicting_ids = [i for i in (raw_gap.get("contradicting_literature_ids") or []) if isinstance(i, int)]
            all_cited = set(supporting_ids) | set(contradicting_ids)
            hallucinated = all_cited - allowed_ids
            if hallucinated:
                rejected_count += 1
                continue
            if not supporting_ids:
                # A gap candidate with no supporting evidence at all is not
                # a usable candidate — reject rather than persist an
                # unsupported assertion framed as a "gap".
                rejected_count += 1
                continue

            gap = repository.record_research_gap(
                session,
                project_id=project_id,
                statement=str(statement),
                status=GapStatus.CANDIDATE,
                confidence=_clamp_confidence(raw_gap.get("confidence")),
                gap_type=raw_gap.get("gap_type"),
                affected_research_area=raw_gap.get("affected_research_area"),
                evidence_summary=raw_gap.get("evidence_summary"),
                prior_work_summary=raw_gap.get("prior_work_summary"),
                insufficiency_summary=raw_gap.get("insufficiency_summary"),
                missing_evidence_summary=raw_gap.get("missing_evidence_summary"),
                candidate_research_question=raw_gap.get("candidate_research_question"),
                research_question_id=research_question_id,
                source_analysis_ids=source_analysis_ids,
                provider=resolved_provider.provider_name,
                model=resolved_provider.model_name,
                prompt_name=GAP_ANALYSIS_PROMPT_NAME,
                prompt_version=GAP_ANALYSIS_PROMPT_VERSION,
            )
            for literature_item_id in supporting_ids:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=literature_item_id,
                    subject_type=EvidenceSubjectType.GAP_CANDIDATE,
                    subject_id=gap.id,
                    relationship_type=EvidenceRelationship.SUPPORTS,
                )
            for literature_item_id in contradicting_ids:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=literature_item_id,
                    subject_type=EvidenceSubjectType.GAP_CANDIDATE,
                    subject_id=gap.id,
                    relationship_type=EvidenceRelationship.CONTRADICTS,
                )
            gap_ids.append(gap.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="intelligence.gap_analysis_completed",
            actor=actor,
            description=(
                f"Gap analysis on {item_count} item(s) produced {len(gap_ids)} candidate gap(s)"
                + (f", {rejected_count} rejected" if rejected_count else "")
            ),
            metadata={
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": GAP_ANALYSIS_PROMPT_NAME,
                "prompt_version": GAP_ANALYSIS_PROMPT_VERSION,
                "included_item_ids": included_item_ids,
                "truncated": truncated,
                "gap_count": len(gap_ids),
                "rejected_candidate_count": rejected_count,
            },
        )

    return GapCandidateOutcome(gap_ids=gap_ids, rejected_candidate_count=rejected_count)
