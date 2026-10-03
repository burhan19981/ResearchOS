"""AnthropicProvider tests.

All network-facing calls are replaced with fakes via monkeypatching
`_get_client`; no real `anthropic` SDK network call is ever made.
"""

import pytest

from researchos.llm.anthropic_provider import AnthropicProvider
from researchos.llm.config import ProviderConfig
from researchos.llm.errors import (
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMTimeoutError,
    LLMUnsupportedOperationError,
)
from researchos.llm.types import GenerationRequest, Message


def _config(**overrides):
    base = dict(
        provider="anthropic",
        api_key="sk-ant-fake-test-key",
        model="claude-test-model",
        timeout=5.0,
        max_retries=0,
    )
    base.update(overrides)
    return ProviderConfig(**base)


def test_generate_raises_configuration_error_when_not_configured():
    provider = AnthropicProvider(config=_config(api_key=None))
    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(LLMConfigurationError):
        provider.generate(request)


def test_generate_returns_normalized_result(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class FakeTextBlock:
        type = "text"
        text = "hello from claude"

    class FakeUsage:
        input_tokens = 10
        output_tokens = 5

    class FakeResponse:
        content = [FakeTextBlock()]
        usage = FakeUsage()
        stop_reason = "end_turn"

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    result = provider.generate(request)

    assert result.text == "hello from claude"
    assert result.provider == "anthropic"
    assert result.model == "claude-test-model"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 15
    assert result.finish_reason == "end_turn"


def test_generate_normalizes_sdk_timeout_error(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class APITimeoutError(Exception):
        pass

    class FakeMessages:
        def create(self, **kwargs):
            raise APITimeoutError("took too long")

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(LLMTimeoutError):
        provider.generate(request)


def test_generate_raises_malformed_response_error_on_bad_shape(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class FakeResponse:
        content = None  # invalid shape: not iterable
        usage = None
        stop_reason = None

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(LLMMalformedResponseError):
        provider.generate(request)


def test_generate_warns_but_does_not_fail_when_temperature_requested(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class FakeTextBlock:
        type = "text"
        text = "ok"

    class FakeResponse:
        content = [FakeTextBlock()]
        usage = None
        stop_reason = "end_turn"

    class FakeMessages:
        def create(self, **kwargs):
            assert "temperature" not in kwargs
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="hi")], temperature=0.7)
    with pytest.warns(RuntimeWarning):
        result = provider.generate(request)
    assert result.text == "ok"


def test_generate_structured_parses_json(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class FakeTextBlock:
        type = "text"
        text = '{"answer": 42}'

    class FakeResponse:
        content = [FakeTextBlock()]
        usage = None
        stop_reason = "end_turn"

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["output_config"]["format"]["type"] == "json_schema"
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="give me json")])
    result = provider.generate_structured(request, schema={"type": "object"})
    assert result == {"answer": 42}


def test_generate_structured_raises_malformed_on_invalid_json(monkeypatch):
    provider = AnthropicProvider(config=_config())

    class FakeTextBlock:
        type = "text"
        text = "not json"

    class FakeResponse:
        content = [FakeTextBlock()]
        usage = None
        stop_reason = "end_turn"

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(provider, "_get_client", lambda: FakeClient())

    request = GenerationRequest(messages=[Message(role="user", content="give me json")])
    with pytest.raises(LLMMalformedResponseError):
        provider.generate_structured(request, schema={"type": "object"})


def test_base_class_default_generate_structured_is_unsupported():
    # Exercised via a provider that has not overridden the base default.
    from researchos.llm.base import LLMProvider

    class BareProvider(LLMProvider):
        @property
        def provider_name(self):
            return "bare"

        @property
        def model_name(self):
            return "n/a"

        @classmethod
        def is_configured(cls):
            return False

        def generate(self, request):
            raise NotImplementedError

    provider = BareProvider()
    with pytest.raises(LLMUnsupportedOperationError):
        provider.generate_structured(
            GenerationRequest(messages=[Message(role="user", content="hi")]), schema={}
        )
