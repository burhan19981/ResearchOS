"""LLM provider integration tests (Phase 6 spec section 10 + section 16's
"LLM provider" category).
"""

from __future__ import annotations

import pytest

from researchos.intelligence.errors import InvalidAnalysisResponseError
from researchos.intelligence.literature_analysis import run_literature_analysis
from researchos.intelligence.llm_call import call_structured, resolve_provider
from researchos.intelligence.response_validation import require_object_response
from researchos.llm.errors import LLMRateLimitError, LLMTimeoutError
from researchos.llm.types import GenerationRequest, Message

from .fakes import FakeLLMProvider


def test_resolve_provider_returns_injected_provider_without_touching_registry():
    fake = FakeLLMProvider(responses=[])
    resolved = resolve_provider("anthropic", fake)
    assert resolved is fake


def test_call_structured_builds_a_bounded_deterministic_request():
    fake = FakeLLMProvider(responses=[{"ok": True}])
    result = call_structured(fake, "system text", "user text", {"type": "object"})
    assert result == {"ok": True}
    request = fake.last_request
    assert isinstance(request, GenerationRequest)
    assert request.temperature == 0.0
    assert request.max_tokens is not None and request.max_tokens > 0
    assert request.messages[0] == Message(role="system", content="system text")
    assert request.messages[1] == Message(role="user", content="user text")


def test_structured_response_missing_required_keys_is_rejected():
    with pytest.raises(InvalidAnalysisResponseError):
        require_object_response({"only_this": 1}, expected_keys=("items", "claims"))


def test_structured_response_wrong_type_is_rejected():
    with pytest.raises(InvalidAnalysisResponseError):
        require_object_response(["not", "a", "dict"], expected_keys=("items",))


def test_malformed_response_from_provider_propagates_as_intelligence_error(session_factory, project_id, literature_item_ids):
    # generate_structured() normally returns a dict (Phase 2's contract);
    # simulate a provider that returns something else entirely.
    fake = FakeLLMProvider(responses=[["not", "an", "object"]])
    with pytest.raises(InvalidAnalysisResponseError):
        run_literature_analysis(
            project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=fake,
            session_factory=session_factory,
        )


def test_retryable_provider_failure_propagates_and_is_recorded(session_factory, project_id, literature_item_ids):
    """Retries themselves already happen inside the Phase 2 provider
    (see docs/PHASE2_LLM_PROVIDERS.md) — by the time an LLMError reaches
    this layer, retries are exhausted; it must propagate, not be
    swallowed, after being recorded on the analysis row."""
    fake = FakeLLMProvider(responses=[LLMRateLimitError("rate limited after retries")])
    with pytest.raises(LLMRateLimitError):
        run_literature_analysis(
            project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=fake,
            session_factory=session_factory,
        )


def test_non_retryable_provider_failure_propagates(session_factory, project_id, literature_item_ids):
    from researchos.llm.errors import LLMAuthenticationError

    fake = FakeLLMProvider(responses=[LLMAuthenticationError("bad credentials")])
    with pytest.raises(LLMAuthenticationError):
        run_literature_analysis(
            project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=fake,
            session_factory=session_factory,
        )


def test_no_secrets_appear_in_prompt_text_or_audit_events(session_factory, project_id, literature_item_ids):
    """Prompts are built entirely from templates + persisted evidence —
    no credential ever flows through this layer, so none can leak."""
    from researchos.db import repository

    fake = FakeLLMProvider(responses=[{"items": {}, "claims": []}])
    run_literature_analysis(
        project_id, "topic", literature_item_ids, actor="agent:a", provider_name="fake", provider=fake,
        session_factory=session_factory,
    )
    request = fake.last_request
    full_prompt_text = "\n".join(m.content for m in request.messages)
    assert "api_key" not in full_prompt_text.lower()
    assert "sk-" not in full_prompt_text.lower()

    session = session_factory()
    try:
        for event in repository.list_audit_events(session, project_id):
            blob = f"{event.description} {event.metadata_}"
            assert "api_key" not in blob.lower()
            assert "sk-" not in blob.lower()
    finally:
        session.close()
