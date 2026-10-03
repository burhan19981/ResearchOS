"""Normalized error hierarchy for the LLM provider layer.

Every provider implementation must catch SDK-specific exceptions and
re-raise one of these normalized types instead. Callers (future agents,
workflows, tests) should only ever need to catch these — never an
`anthropic.*` or `openai.*` exception directly.

Error messages must never include raw secret values. Use
`researchos.llm.redaction.strip_secret_from_text` when building a message
from SDK-provided text that could echo back a key.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all normalized LLM provider errors."""


class LLMConfigurationError(LLMError):
    """Missing or invalid configuration.

    Covers: no API key set, an unknown provider name requested from the
    registry, or other setup problems that exist before any network call
    is attempted.
    """


class LLMAuthenticationError(LLMError):
    """The provider rejected the supplied credentials as invalid."""


class LLMTimeoutError(LLMError):
    """A request exceeded the configured timeout."""


class LLMRateLimitError(LLMError):
    """The provider reported that the caller is being rate limited."""


class LLMProviderUnavailableError(LLMError):
    """Transient provider/network failure (connection error, 5xx, etc.)."""


class LLMMalformedResponseError(LLMError):
    """A provider response could not be parsed into the expected shape."""


class LLMUnsupportedOperationError(LLMError):
    """The requested operation is not supported by this provider."""
