"""Abstract provider interface that every LLM provider must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import GenerationRequest, GenerationResult


class LLMProvider(ABC):
    """Common interface for all LLM providers.

    Implementations must not leak SDK-specific types across this
    boundary, and must translate SDK-specific exceptions into the
    normalized errors defined in `researchos.llm.errors`.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short, stable identifier, e.g. "anthropic" or "openai"."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model this provider instance is configured to use."""

    @classmethod
    @abstractmethod
    def is_configured(cls) -> bool:
        """Whether required credentials are present, without exposing them."""

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a text completion for the given request."""

    def generate_structured(
        self, request: GenerationRequest, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate a response conforming to a JSON schema, where practical.

        The default implementation is unsupported; providers override
        this where the underlying API offers native structured/JSON
        output support.
        """
        from .errors import LLMUnsupportedOperationError

        raise LLMUnsupportedOperationError(
            f"{self.provider_name} provider does not implement generate_structured()"
        )
