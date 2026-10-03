"""Tests for _sdk_error_mapping using lightweight fake exception classes.

The mapping logic matches on exception class *name*, so fakes named to
match real Anthropic/OpenAI SDK exception classes exercise the same
branches without needing real SDK exception instances (some of which
have non-trivial constructors) and without any network access.
"""

from researchos.llm._sdk_error_mapping import normalize_sdk_exception
from researchos.llm.errors import (
    LLMAuthenticationError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class APIConnectionError(Exception):
    pass


class APITimeoutError(APIConnectionError):
    pass


class RateLimitError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class InternalServerError(Exception):
    pass


def test_timeout_like_exception_maps_to_llm_timeout_error():
    result = normalize_sdk_exception(APITimeoutError("took too long"), provider="anthropic", api_key=None)
    assert isinstance(result, LLMTimeoutError)


def test_rate_limit_like_exception_maps_to_llm_rate_limit_error():
    result = normalize_sdk_exception(RateLimitError("slow down"), provider="openai", api_key=None)
    assert isinstance(result, LLMRateLimitError)


def test_authentication_like_exception_maps_to_llm_authentication_error():
    result = normalize_sdk_exception(AuthenticationError("bad key"), provider="anthropic", api_key=None)
    assert isinstance(result, LLMAuthenticationError)


def test_connection_error_maps_to_provider_unavailable():
    result = normalize_sdk_exception(APIConnectionError("network down"), provider="openai", api_key=None)
    assert isinstance(result, LLMProviderUnavailableError)


def test_server_error_maps_to_provider_unavailable():
    result = normalize_sdk_exception(InternalServerError("500"), provider="openai", api_key=None)
    assert isinstance(result, LLMProviderUnavailableError)


def test_unrecognized_exception_falls_back_to_provider_unavailable():
    result = normalize_sdk_exception(ValueError("something odd"), provider="anthropic", api_key=None)
    assert isinstance(result, LLMProviderUnavailableError)


def test_secret_is_redacted_from_normalized_message():
    exc = AuthenticationError("failed with key sk-real-secret-abc")
    result = normalize_sdk_exception(exc, provider="openai", api_key="sk-real-secret-abc")
    assert "sk-real-secret-abc" not in str(result)
