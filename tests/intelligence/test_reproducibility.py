"""Reproducibility tests (Phase 6 spec section 16's "Reproducibility"
category): prompt version, model/provider, evidence ids, and timestamp
must all be persisted alongside every generated analysis.
"""

from __future__ import annotations

from researchos.db import repository
from researchos.intelligence.gap_analysis import generate_gap_candidates
from researchos.intelligence.literature_analysis import run_literature_analysis
from researchos.intelligence.novelty_analysis import analyze_novelty_candidate
from researchos.intelligence.prompts import (
    GAP_ANALYSIS_PROMPT_NAME,
    GAP_ANALYSIS_PROMPT_VERSION,
    LITERATURE_ANALYSIS_PROMPT_NAME,
    LITERATURE_ANALYSIS_PROMPT_VERSION,
    NOVELTY_ANALYSIS_PROMPT_NAME,
    NOVELTY_ANALYSIS_PROMPT_VERSION,
)

from .fakes import FakeLLMProvider


def test_literature_analysis_persists_full_provenance(session_factory, project_id, literature_item_ids):
    provider = FakeLLMProvider(responses=[{"items": {}, "claims": []}], name="anthropic", model="claude-sonnet-5")
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="anthropic", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        analysis = repository.get_literature_analysis(session, outcome.analysis_id)
        assert analysis.prompt_name == LITERATURE_ANALYSIS_PROMPT_NAME
        assert analysis.prompt_version == LITERATURE_ANALYSIS_PROMPT_VERSION
        assert analysis.provider == "anthropic"
        assert analysis.model == "claude-sonnet-5"
        assert set(analysis.included_item_ids) == set(literature_item_ids)
        assert analysis.created_at is not None
    finally:
        session.close()


def test_gap_candidate_persists_full_provenance(session_factory, project_id, literature_item_ids):
    response = {"gaps": [{"gap_statement": "A gap.", "supporting_literature_ids": [literature_item_ids[0]]}]}
    provider = FakeLLMProvider(responses=[response], name="openai", model="gpt-4o-mini")
    outcome = generate_gap_candidates(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="openai", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        gap = repository.get_research_gap(session, outcome.gap_ids[0])
        assert gap.prompt_name == GAP_ANALYSIS_PROMPT_NAME
        assert gap.prompt_version == GAP_ANALYSIS_PROMPT_VERSION
        assert gap.provider == "openai"
        assert gap.model == "gpt-4o-mini"
        assert gap.created_at is not None
    finally:
        session.close()


def test_novelty_assessment_persists_full_provenance(session_factory, project_id, literature_item_ids):
    response = {"comparisons": [], "candidate_status": "not_assessed"}
    provider = FakeLLMProvider(responses=[response], name="anthropic", model="claude-sonnet-5")
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:a", provider_name="anthropic", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, outcome.assessment_id)
        assert assessment.prompt_name == NOVELTY_ANALYSIS_PROMPT_NAME
        assert assessment.prompt_version == NOVELTY_ANALYSIS_PROMPT_VERSION
        assert assessment.provider == "anthropic"
        assert assessment.model == "claude-sonnet-5"
        assert assessment.assessed_at is not None
    finally:
        session.close()


def test_evidence_item_ids_are_recorded_via_evidence_links(session_factory, project_id, literature_item_ids):
    from researchos.db.models import EvidenceSubjectType

    response = {
        "items": {},
        "claims": [
            {"claim_text": "Traceable claim.", "support_level": "supported", "evidence_item_ids": literature_item_ids}
        ],
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_evidence_links(
            session, project_id, subject_type=EvidenceSubjectType.ANALYSIS_CLAIM, subject_id=outcome.claim_ids[0]
        )
        assert {l.literature_item_id for l in links} == set(literature_item_ids)
    finally:
        session.close()
