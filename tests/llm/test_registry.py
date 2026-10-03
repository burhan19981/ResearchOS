import pytest

from researchos.llm import LLMConfigurationError, get_provider, get_provider_status
from researchos.llm.anthropic_provider import AnthropicProvider
from researchos.llm.openai_provider import OpenAIProvider
from researchos.llm.registry import available_providers


def test_available_providers_lists_both():
    assert available_providers() == ["anthropic", "openai"]


def test_get_provider_anthropic_returns_correct_type():
    provider = get_provider("anthropic")
    assert isinstance(provider, AnthropicProvider)
    assert provider.provider_name == "anthropic"


def test_get_provider_openai_returns_correct_type():
    provider = get_provider("openai")
    assert isinstance(provider, OpenAIProvider)
    assert provider.provider_name == "openai"


def test_get_provider_is_case_insensitive_and_trims_whitespace():
    provider = get_provider(" OpenAI ")
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_unknown_name_raises_configuration_error():
    with pytest.raises(LLMConfigurationError):
        get_provider("does-not-exist")


def test_get_provider_empty_name_raises_configuration_error():
    with pytest.raises(LLMConfigurationError):
        get_provider("")


def test_get_provider_status_reports_unconfigured_by_default():
    status = get_provider_status()
    assert status == {"anthropic": False, "openai": False}


def test_get_provider_status_reflects_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    status = get_provider_status()
    assert status["anthropic"] is True
    assert status["openai"] is False


def test_get_provider_construction_never_requires_credentials():
    # Constructing a provider must succeed and must not make any network
    # call even when no credentials are configured.
    provider = get_provider("anthropic")
    assert provider.is_configured() is False
