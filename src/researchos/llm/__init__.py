"""Provider-agnostic LLM integration layer for ResearchOS.

Application and agent code should import from this package only — never
from `anthropic` or `openai` directly — so LLM providers can be added,
removed, or swapped without touching call sites. See
`docs/PHASE2_LLM_PROVIDERS.md` for the full design.
"""

from .base import LLMProvider
from .errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMError,
    LLMMalformedResponseError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnsupportedOperationError,
)
from .registry import available_providers, get_provider, get_provider_status
from .types import GenerationRequest, GenerationResult, Message, Usage

__all__ = [
    "LLMProvider",
    "LLMError",
    "LLMConfigurationError",
    "LLMAuthenticationError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMProviderUnavailableError",
    "LLMMalformedResponseError",
    "LLMUnsupportedOperationError",
    "get_provider",
    "get_provider_status",
    "available_providers",
    "Message",
    "GenerationRequest",
    "GenerationResult",
    "Usage",
]
