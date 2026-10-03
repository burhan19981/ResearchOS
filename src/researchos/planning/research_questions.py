"""Research question generation service (Phase 7 spec section 25).

Generates CANDIDATE `ResearchQuestion` rows from one already-approved
`ResearchGap` — never a pre-approved question. `ResearchQuestion` (Phase
3) is reused directly, not duplicated with a parallel
"CandidateResearchQuestion" entity; every generated row is created with
`planning_status=PlanningApprovalStatus.CANDIDATE` regardless of
anything the LLM's response contains, since the schema this layer sends
the model never offers a status field to begin with.

Like every generation service in this package, the LLM call happens
outside any `session_scope()` so a failure-path audit write commits
independently of whatever transaction surrounds the call itself
(the same pattern `researchos.intelligence` and
`researchos.evidence.service` already established).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import EvidenceRelationship, EvidenceSubjectType, PlanningApprovalStatus
from ..llm import LLMError
from ..llm.base import LLMProvider
from . import context as context_module
from .errors import InvalidPlanningResponseError
from .llm_call import call_structured, resolve_provider
from .prompts import (
    RESEARCH_QUESTION_GENERATION_PROMPT_NAME,
    RESEARCH_QUESTION_GENERATION_PROMPT_VERSION,
    RESEARCH_QUESTION_GENERATION_SCHEMA,
    build_research_question_generation_prompt,
)
from .types import ResearchQuestionGenerationOutcome
from .validation import require_object_response, validate_no_hallucinated_references


def generate_research_questions(
    project_id: int,
    research_gap_id: int,
    *,
    actor: str,
    provider_name: str,
    max_questions: int = 3,
    provider: Optional[LLMProvider] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ResearchQuestionGenerationOutcome:
    """Propose up to `max_questions` candidate research questions from
    `research_gap_id`, which must already be `GapStatus.VALIDATED`.

    Raises `UnknownPlanningEntityError`/`CrossProjectReferenceError`/
    `UpstreamNotApprovedError` before ever calling the LLM if the gap
    doesn't qualify. Any generated question citing a literature id
    outside the gap's own evidence is dropped, never persisted.
    """
    resolved_provider = resolve_provider(provider_name, provider)

    with session_scope(session_factory) as session:
        ctx = context_module.build_research_question_context(session, project_id, research_gap_id)
        prompt_json = dict(ctx.prompt_json)
        prompt_json["max_questions"] = max_questions
        system_text, user_text = build_research_question_generation_prompt(prompt_json)

    def _audit_failure(exc: Exception) -> None:
        with session_scope(session_factory) as failure_session:
            repository.append_audit_event(
                failure_session,
                project_id=project_id,
                event_type="planning.research_question_generation_failed",
                actor=actor,
                description=f"Research question generation failed: {exc}",
                metadata={
                    "research_gap_id": research_gap_id,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                    "error": str(exc),
                },
            )

    try:
        response = call_structured(resolved_provider, system_text, user_text, RESEARCH_QUESTION_GENERATION_SCHEMA)
    except LLMError as exc:
        _audit_failure(exc)
        raise

    try:
        require_object_response(response, expected_keys=("questions",))
    except InvalidPlanningResponseError as exc:
        _audit_failure(exc)
        raise

    with session_scope(session_factory) as session:
        question_ids: list[int] = []
        rejected_count = 0
        for raw_question in (response.get("questions") or [])[:max_questions]:
            if not isinstance(raw_question, dict):
                rejected_count += 1
                continue
            question_text = raw_question.get("question")
            if not question_text or not str(question_text).strip():
                rejected_count += 1
                continue

            cited_ids = [i for i in (raw_question.get("cited_literature_item_ids") or []) if isinstance(i, int)]
            hallucinated = validate_no_hallucinated_references(
                {"cited_literature_item_ids": cited_ids}, ctx.allowed_literature_item_ids
            )
            if hallucinated:
                rejected_count += 1
                continue

            question = repository.create_research_question(
                session,
                project_id=project_id,
                question=str(question_text),
                type=raw_question.get("type"),
                hypothesis=raw_question.get("hypothesis"),
                planning_status=PlanningApprovalStatus.CANDIDATE,
            )
            for literature_item_id in cited_ids:
                repository.create_evidence_link(
                    session,
                    project_id=project_id,
                    literature_item_id=literature_item_id,
                    subject_type=EvidenceSubjectType.RESEARCH_QUESTION,
                    subject_id=question.id,
                    relationship_type=EvidenceRelationship.CITES,
                )
            question_ids.append(question.id)

        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="planning.research_question_generation_completed",
            actor=actor,
            description=(
                f"Research question generation from gap {research_gap_id} produced "
                f"{len(question_ids)} candidate(s)" + (f", {rejected_count} rejected" if rejected_count else "")
            ),
            metadata={
                "research_gap_id": research_gap_id,
                "provider": resolved_provider.provider_name,
                "model": resolved_provider.model_name,
                "prompt_name": RESEARCH_QUESTION_GENERATION_PROMPT_NAME,
                "prompt_version": RESEARCH_QUESTION_GENERATION_PROMPT_VERSION,
                "upstream_snapshots": ctx.upstream_snapshots,
                "question_count": len(question_ids),
                "rejected_count": rejected_count,
            },
        )

    return ResearchQuestionGenerationOutcome(question_ids=question_ids, rejected_count=rejected_count)
