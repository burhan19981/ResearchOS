"""OpenAIProvider tests.

All network-facing calls are replaced with fakes via monkeypatching
`_get_client`; no real `openai` SDK network call is ever made.
"""

import pytest

from researchos.llm.config import ProviderConfig
from researchos.llm.errors import (
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMRateLimitError,
)
from researchos.llm.openai_provider import OpenAIProvider
from researchos.llm.types import GenerationRequest, Message


def _config(**overrides):
    base = dict(
        provider="openai",
        api_key="sk-fake-test-key",
        model="gpt-test-model",
        timeout=5.0,
        max_retries=0,
    )
    base.update(overrides)
    return ProviderConfig(**base)


def test_generate_raises_configuration_error_when_not_configured():
    provider = OpenAIProvider(config=_config(api_key=None))
    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(LLMConfigurationError):
        provider.generate(request)


def test_generate_returns_normalized_result(monkeypatch):
    provider = OpenAIProvider(config=_config())

    class FakeMessage:
        content = "hello from gpt"

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeUsage:
        prompt_tokens = 7
        completion_tokens = 3
        total_tokens = 10

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    result = provider.generate(request)

    assert result.text == "hello from gpt"
    assert result.provider == "openai"
    assert result.model == "gpt-test-model"
    assert result.usage.total_tokens == 10
    assert result.finish_reason == "stop"


def test_generate_normalizes_sdk_rate_limit_error(monkeypatch):
    provider = OpenAIProvider(config=_config())

    class RateLimitError(Exception):
        pass

    class FakeCompletions:
        def create(self, **kwargs):
            raise RateLimitError("slow down")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(LLMRateLimitError):
        provider.generate(request)


def test_generate_passes_temperature_through(monkeypatch):
    provider = OpenAIProvider(config=_config())
    captured = {}

    class FakeMessage:
        content = "ok"

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeResponse:
        choices = [FakeChoice()]
        usage = None

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")], temperature=0.3)
    provider.generate(request)
    assert captured["temperature"] == 0.3


def test_generate_structured_parses_json(monkeypatch):
    provider = OpenAIProvider(config=_config())

    class FakeMessage:
        content = '{"answer": 42}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["response_format"]["type"] == "json_schema"
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="give me json")])
    result = provider.generate_structured(request, schema={"type": "object"})
    assert result == {"answer": 42}


def test_generate_structured_raises_malformed_on_invalid_json(monkeypatch):
    provider = OpenAIProvider(config=_config())

    class FakeMessage:
        content = "not json"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="give me json")])
    with pytest.raises(LLMMalformedResponseError):
        provider.generate_structured(request, schema={"type": "object"})
