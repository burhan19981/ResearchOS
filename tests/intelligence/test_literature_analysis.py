"""Literature analysis service tests."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import AnalysisStatus, ClaimSupportLevel
from researchos.intelligence.literature_analysis import run_literature_analysis
from researchos.llm.errors import LLMRateLimitError, LLMTimeoutError

from .fakes import FakeLLMProvider


def _dimensions_stub(**overrides):
    base = {
        "research_topic": "unknown", "problem_addressed": "unknown", "task": "unknown", "dataset": "unknown",
        "methodology": "unknown", "model_architecture": "unknown", "evaluation_metrics": "unknown",
        "reported_limitations": "unknown", "stated_future_work": "unknown", "contribution_type": "unknown",
        "domain_application": "unknown", "key_findings": "unknown", "evidence_limitations": "unknown",
    }
    base.update(overrides)
    return base


def test_valid_evidence_package_produces_completed_analysis(session_factory, project_id, literature_item_ids):
    response = {
        "items": {str(literature_item_ids[0]): _dimensions_stub(research_topic="widgets")},
        "claims": [
            {
                "claim_text": "Widgets are studied in Fake Paper One.",
                "claim_type": "finding",
                "support_level": "supported",
                "evidence_item_ids": [literature_item_ids[0]],
                "confidence": 0.8,
                "uncertainty": None,
            }
        ],
    }
    provider = FakeLLMProvider(responses=[response])

    outcome = run_literature_analysis(
        project_id, "widgets", literature_item_ids, actor="agent:lit-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )

    assert outcome.rejected_claim_count == 0
    assert len(outcome.claim_ids) == 1

    session = session_factory()
    try:
        analysis = repository.get_literature_analysis(session, outcome.analysis_id)
        assert analysis.status == AnalysisStatus.COMPLETED
        assert analysis.provider == "fake"
        assert analysis.model == "fake-model-1"
        assert analysis.prompt_name == "literature_analysis"
        assert analysis.prompt_version == "v1"
        assert set(analysis.included_item_ids) == set(literature_item_ids)
        assert analysis.result["items"][str(literature_item_ids[0])]["research_topic"] == "widgets"
    finally:
        session.close()


def test_missing_dimension_values_default_to_unknown(session_factory, project_id, literature_item_ids):
    response = {"items": {str(literature_item_ids[0]): {"research_topic": "widgets"}}, "claims": []}
    provider = FakeLLMProvider(responses=[response])

    outcome = run_literature_analysis(
        project_id, "widgets", literature_item_ids, actor="agent:lit-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )

    session = session_factory()
    try:
        analysis = repository.get_literature_analysis(session, outcome.analysis_id)
        item_result = analysis.result["items"][str(literature_item_ids[0])]
        assert item_result["research_topic"] == "widgets"
        assert item_result["problem_addressed"] == "unknown"
        assert item_result["dataset"] == "unknown"
    finally:
        session.close()


def test_incomplete_metadata_still_produces_a_result(session_factory, project_id):
    s = session_factory()
    try:
        item = repository.add_literature_item(s, project_id=project_id, title="Sparse Paper")
        s.commit()
        item_id = item.id
    finally:
        s.close()

    response = {"items": {str(item_id): _dimensions_stub()}, "claims": []}
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", [item_id], actor="agent:lit-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.rejected_claim_count == 0


def test_evidence_truncation_is_reflected_on_the_analysis_record(session_factory, project_id):
    ids = []
    s = session_factory()
    try:
        for i in range(3):
            item = repository.add_literature_item(s, project_id=project_id, title=f"Paper {i}")
            ids.append(item.id)
        s.commit()
    finally:
        s.close()

    response = {"items": {}, "claims": []}
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", ids, actor="agent:lit-bot", provider_name="fake", provider=provider,
        max_items=1, session_factory=session_factory,
    )
    assert outcome.truncated is True

    session = session_factory()
    try:
        analysis = repository.get_literature_analysis(session, outcome.analysis_id)
        assert analysis.truncated is True
        assert len(analysis.included_item_ids) == 1
        assert len(analysis.requested_item_ids) == 3
    finally:
        session.close()


def test_deterministic_package_construction_same_inputs_same_included_ids(session_factory, project_id, literature_item_ids):
    response = {"items": {}, "claims": []}
    provider_a = FakeLLMProvider(responses=[dict(response)])
    provider_b = FakeLLMProvider(responses=[dict(response)])

    outcome_a = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider_a,
        session_factory=session_factory,
    )
    outcome_b = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:b", provider_name="fake", provider=provider_b,
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        a = repository.get_literature_analysis(session, outcome_a.analysis_id)
        b = repository.get_literature_analysis(session, outcome_b.analysis_id)
        assert a.included_item_ids == b.included_item_ids
    finally:
        session.close()


def test_project_isolation_analyses_are_scoped(session_factory, project_id, literature_item_ids):
    from researchos.db.engine import session_scope

    with session_scope(session_factory) as s:
        other = repository.create_project(s, title="Fake Other Project")
        other_id = other.id

    response = {"items": {}, "claims": []}
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        assert repository.list_literature_analyses(session, project_id)
        assert repository.list_literature_analyses(session, other_id) == []
    finally:
        session.close()


def test_llm_failure_marks_analysis_failed_and_reraises(session_factory, project_id, literature_item_ids):
    provider = FakeLLMProvider(responses=[LLMTimeoutError("simulated timeout")])
    with pytest.raises(LLMTimeoutError):
        run_literature_analysis(
            project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        analyses = repository.list_literature_analyses(session, project_id)
        assert len(analyses) == 1
        assert analyses[0].status == AnalysisStatus.FAILED
        assert "simulated timeout" in analyses[0].error
        events = repository.list_audit_events(session, project_id)
        assert any(e.event_type == "intelligence.literature_analysis_failed" for e in events)
    finally:
        session.close()
