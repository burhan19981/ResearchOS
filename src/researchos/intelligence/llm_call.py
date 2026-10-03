"""The one place the research intelligence layer talks to an LLM.

Uses only `researchos.llm`'s provider-agnostic abstraction — never
`anthropic`/`openai` directly, and never hard-codes one vendor. Retries,
timeouts, and rate-limit handling are already implemented inside each
provider (Phase 2); nothing here duplicates that.
"""

from __future__ import annotations

from typing import Any, Optional

from ..llm import GenerationRequest, Message, get_provider
from ..llm.base import LLMProvider

DEFAULT_TEMPERATURE = 0.0  # as deterministic as each provider supports — see docs/PHASE2_LLM_PROVIDERS.md
DEFAULT_MAX_TOKENS = 4000  # bounded output, per Phase 6 spec section 12


def resolve_provider(provider_name: str, provider: Optional[LLMProvider] = None) -> LLMProvider:
    """Returns `provider` unchanged if given (test injection point,
    mirroring `researchos.evidence`'s `adapter=` pattern), else resolves
    `provider_name` through the real registry."""
    return provider if provider is not None else get_provider(provider_name)


def call_structured(
    provider: LLMProvider,
    system_text: str,
    user_text: str,
    schema: dict[str, Any],
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """One bounded, structured-output LLM call. No secret is ever part of
    `system_text`/`user_text` — both are built entirely from prompt
    templates and persisted evidence/analysis content."""
    request = GenerationRequest(
        messages=[Message(role="system", content=system_text), Message(role="user", content=user_text)],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return provider.generate_structured(request, schema)
