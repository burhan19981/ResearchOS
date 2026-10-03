"""Factory/registry for obtaining LLM providers by name.

Application and agent code should depend only on `get_provider` /
`get_provider_status` (re-exported from `researchos.llm`), never on a
concrete provider class or an underlying SDK directly.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .errors import LLMConfigurationError
from .openai_provider import OpenAIProvider

_REGISTRY: Dict[str, Callable[[], LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def available_providers() -> List[str]:
    return sorted(_REGISTRY)


def get_provider(name: str) -> LLMProvider:
    """Instantiate a provider by name (e.g. "anthropic", "openai").

    Raises `LLMConfigurationError` for an unrecognized name. Does not
    verify credentials or make any network call — construction is always
    safe. Call `provider.is_configured()` or `get_provider_status()` to
    check configuration before generating.
    """
    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise LLMConfigurationError(
            f"Unknown LLM provider '{name}'. Available providers: "
            f"{', '.join(available_providers())}."
        )
    return _REGISTRY[key]()


def get_provider_status() -> Dict[str, bool]:
    """Return `{provider_name: is_configured}` for every registered provider.

    Never exposes the underlying secret values — only presence/absence.
    """
    return {name: cls.is_configured() for name, cls in _REGISTRY.items()}
