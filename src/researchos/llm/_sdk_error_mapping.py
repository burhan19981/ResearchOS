"""Shared helper for translating SDK exceptions into normalized errors.

The Anthropic and OpenAI Python SDKs expose a near-identical exception
hierarchy (`APIStatusError` / `APIConnectionError` / `APITimeoutError` /
`RateLimitError` / `AuthenticationError` / ...). Rather than importing
both SDKs' exception modules here (which would defeat the point of the
abstraction layer), this module matches on exception *class name* across
the exception's MRO. This is intentionally SDK-agnostic: it works for
either provider's real exceptions and for lightweight fakes in tests.
"""

from __future__ import annotations

from typing import Optional

from .errors import (
    LLMAuthenticationError,
    LLMError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .redaction import strip_secret_from_text

_TIMEOUT_NAMES = {"APITimeoutError", "DeadlineExceededError"}
_RATE_LIMIT_NAMES = {"RateLimitError"}
_AUTH_NAMES = {
    "AuthenticationError",
    "PermissionDeniedError",
    "CredentialsError",
    "IdentityTokenFileError",
    "WorkloadIdentityError",
    "OAuthError",
}
_UNAVAILABLE_NAMES = {
    "APIConnectionError",
    "APIStatusError",
    "APIError",
    "InternalServerError",
    "ServiceUnavailableError",
    "OverloadedError",
    "RetryableError",
    "NotFoundError",
    "BadRequestError",
    "UnprocessableEntityError",
    "ConflictError",
    "RequestTooLargeError",
}


def normalize_sdk_exception(
    exc: Exception, *, provider: str, api_key: Optional[str]
) -> LLMError:
    """Map a provider SDK exception onto a normalized `LLMError` subclass.

    `api_key` is used only to strip that exact value out of the resulting
    message text — it is never included in the returned error.
    """
    class_names = {cls.__name__ for cls in type(exc).__mro__}
    message = strip_secret_from_text(str(exc), api_key)

    if class_names & _TIMEOUT_NAMES:
        return LLMTimeoutError(f"{provider}: request timed out: {message}")
    if class_names & _RATE_LIMIT_NAMES:
        return LLMRateLimitError(f"{provider}: rate limited: {message}")
    if class_names & _AUTH_NAMES:
        return LLMAuthenticationError(f"{provider}: authentication failed: {message}")
    if class_names & _UNAVAILABLE_NAMES:
        return LLMProviderUnavailableError(f"{provider}: provider error: {message}")
    return LLMProviderUnavailableError(f"{provider}: unexpected error: {message}")
