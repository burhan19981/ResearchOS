"""Claim validation / anti-hallucination tests (Phase 6 spec section 13
and section 18's core invariant)."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import ClaimSupportLevel
from researchos.intelligence.literature_analysis import run_literature_analysis
from researchos.intelligence.response_validation import extract_referenced_ids, validate_no_hallucinated_references

from .fakes import FakeLLMProvider


def test_claim_with_valid_literature_item_ids_is_persisted(session_factory, project_id, literature_item_ids):
    response = {
        "items": {},
        "claims": [
            {
                "claim_text": "A well-supported claim.",
                "support_level": "supported",
                "evidence_item_ids": literature_item_ids,
                "confidence": 0.9,
            }
        ],
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert len(outcome.claim_ids) == 1
    assert outcome.rejected_claim_count == 0


def test_claim_citing_unknown_literature_item_id_is_rejected(session_factory, project_id, literature_item_ids):
    response = {
        "items": {},
        "claims": [
            {
                "claim_text": "A claim citing a paper that does not exist.",
                "support_level": "supported",
                "evidence_item_ids": [999_999],
                "confidence": 0.9,
            }
        ],
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.claim_ids == []
    assert outcome.rejected_claim_count == 1

    session = session_factory()
    try:
        assert repository.list_analysis_claims(session, project_id) == []
    finally:
        session.close()


def test_claim_with_no_evidence_is_marked_unsupported_candidate(session_factory, project_id, literature_item_ids):
    response = {
        "items": {},
        "claims": [
            {"claim_text": "A claim with no cited evidence at all.", "support_level": "supported", "evidence_item_ids": []}
        ],
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert len(outcome.claim_ids) == 1

    session = session_factory()
    try:
        claim = repository.get_analysis_claim(session, outcome.claim_ids[0])
        # The model claimed "supported" but cited nothing — the service
        # must never trust that self-assessment; it is coerced.
        assert claim.support_level == ClaimSupportLevel.UNSUPPORTED_CANDIDATE
    finally:
        session.close()


def test_claim_with_blank_text_is_rejected(session_factory, project_id, literature_item_ids):
    response = {"items": {}, "claims": [{"claim_text": "   ", "support_level": "supported", "evidence_item_ids": literature_item_ids}]}
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.claim_ids == []
    assert outcome.rejected_claim_count == 1


def test_analysis_items_dict_with_hallucinated_key_is_dropped(session_factory, project_id, literature_item_ids):
    """An 'invented paper' in the per-item dimension analysis (a key not
    in the evidence package) must never be persisted as if it were real."""
    response = {"items": {"999999": {"research_topic": "invented"}}, "claims": []}
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        analysis = repository.get_literature_analysis(session, outcome.analysis_id)
        assert "999999" not in analysis.result["items"]
    finally:
        session.close()


def test_invented_doi_is_never_persisted_as_bibliographic_fact(session_factory, project_id, literature_item_ids):
    """The claim schema has no DOI field at all — an LLM cannot inject a
    fabricated DOI into an AnalysisClaim; DOIs remain solely
    LiteratureItem's authoritative field, owned by the Evidence Layer."""
    response = {
        "items": {},
        "claims": [
            {
                "claim_text": "This paper's real DOI is 10.9999/totally-invented (not actually in evidence).",
                "support_level": "supported",
                "evidence_item_ids": literature_item_ids,
                "confidence": 0.5,
            }
        ],
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    # The claim persists (it cites real evidence) but nothing about it
    # ever writes to LiteratureItem.doi — verify no LiteratureItem was
    # mutated by this call at all.
    session = session_factory()
    try:
        for item_id in literature_item_ids:
            item = repository.get_literature_item(session, item_id)
            assert item.doi != "10.9999/totally-invented"
    finally:
        session.close()
    assert len(outcome.claim_ids) == 1


def test_extract_referenced_ids_finds_ids_under_any_id_suffixed_key():
    payload = {
        "evidence_item_ids": [1, 2],
        "nested": {"literature_item_id": 3, "other_ids": [4, 5]},
        "list": [{"supporting_literature_ids": [6]}, {"contradicting_literature_ids": [7, 8]}],
    }
    assert extract_referenced_ids(payload) == {1, 2, 3, 4, 5, 6, 7, 8}


def test_validate_no_hallucinated_references_returns_only_the_offenders():
    response = {"evidence_item_ids": [1, 2, 3]}
    offending = validate_no_hallucinated_references(response, allowed_item_ids={1, 2})
    assert offending == {3}


def test_validate_no_hallucinated_references_empty_when_all_allowed():
    response = {"evidence_item_ids": [1, 2]}
    assert validate_no_hallucinated_references(response, allowed_item_ids={1, 2, 3}) == set()
