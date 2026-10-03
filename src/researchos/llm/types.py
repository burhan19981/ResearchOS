"""Provider-agnostic data types for the LLM abstraction layer.

Nothing in this module depends on the Anthropic or OpenAI SDKs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    """A provider-agnostic request to generate a completion.

    `temperature` is honored only where the target provider's current API
    supports direct sampling-temperature control; see each provider
    module's docstring for known gaps.
    """

    messages: list[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
