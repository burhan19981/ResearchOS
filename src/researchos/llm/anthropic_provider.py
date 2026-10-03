"""Anthropic (Claude) provider implementation.

This is the only module in the codebase that should import `anthropic`.
Everything else depends solely on the provider-agnostic interface in
`researchos.llm.base`.

Known limitation (installed SDK: anthropic 1.6.0): `messages.create` no
longer exposes a top-level sampling `temperature` parameter — newer
Claude models are tuned via `output_config.effort` instead. If a caller
sets `GenerationRequest.temperature`, this provider emits a `RuntimeWarning`
and proceeds without it, rather than guessing at an undocumented mapping.
This should be revisited once real credentials are available to confirm
current API behavior.
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Optional

import anthropic

from ._sdk_error_mapping import normalize_sdk_exception
from .base import LLMProvider
from .config import ProviderConfig, load_anthropic_config
from .errors import LLMConfigurationError, LLMMalformedResponseError
from .retry import call_with_retries
from .types import GenerationRequest, GenerationResult, Usage


class AnthropicProvider(LLMProvider):
    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        self._config = config or load_anthropic_config()
        self._client: Optional["anthropic.Anthropic"] = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._config.model

    @classmethod
    def is_configured(cls) -> bool:
        return load_anthropic_config().is_configured

    def _get_client(self) -> "anthropic.Anthropic":
        if not self._config.is_configured:
            raise LLMConfigurationError(
                "Anthropic provider is not configured: ANTHROPIC_API_KEY is not set."
            )
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._config.api_key,
                timeout=self._config.timeout,
                max_retries=0,  # retries are handled by researchos.llm.retry
            )
        return self._client

    def _split_messages(self, request: GenerationRequest) -> tuple[Optional[str], list[dict[str, str]]]:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role != "system"
        ]
        return ("\n".join(system_parts) or None, conversation)

    def _warn_if_temperature_requested(self, request: GenerationRequest) -> None:
        if request.temperature is not None:
            warnings.warn(
                "AnthropicProvider: 'temperature' is not supported as a top-level "
                "parameter by the installed Anthropic SDK for this model family; "
                "it is being ignored for this request.",
                RuntimeWarning,
                stacklevel=3,
            )

    def _extract_text(self, response: Any) -> str:
        try:
            return "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
        except (AttributeError, TypeError) as exc:
            raise LLMMalformedResponseError(
                f"anthropic: could not parse response content: {exc}"
            ) from exc

    def generate(self, request: GenerationRequest) -> GenerationResult:
        client = self._get_client()
        system_prompt, conversation = self._split_messages(request)
        self._warn_if_temperature_requested(request)

        def _call() -> GenerationResult:
            kwargs: dict[str, Any] = dict(
                model=self._config.model,
                max_tokens=request.max_tokens or 1024,
                messages=conversation,
            )
            if system_prompt:
                kwargs["system"] = system_prompt
            if request.timeout is not None:
                kwargs["timeout"] = request.timeout

            try:
                response = client.messages.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - normalized below
                raise normalize_sdk_exception(
                    exc, provider="anthropic", api_key=self._config.api_key
                ) from exc

            text = self._extract_text(response)
            usage_obj = getattr(response, "usage", None)
            usage = Usage(
                input_tokens=getattr(usage_obj, "input_tokens", None),
                output_tokens=getattr(usage_obj, "output_tokens", None),
                total_tokens=(
                    (usage_obj.input_tokens or 0) + (usage_obj.output_tokens or 0)
                    if usage_obj is not None
                    else None
                ),
            )
            return GenerationResult(
                text=text,
                provider=self.provider_name,
                model=self._config.model,
                finish_reason=getattr(response, "stop_reason", None),
                usage=usage,
            )

        return call_with_retries(_call, max_retries=self._config.max_retries)

    def generate_structured(
        self, request: GenerationRequest, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate JSON conforming to `schema` using Anthropic's native
        `output_config.format` json_schema support."""
        client = self._get_client()
        system_prompt, conversation = self._split_messages(request)
        self._warn_if_temperature_requested(request)

        def _call() -> dict[str, Any]:
            kwargs: dict[str, Any] = dict(
                model=self._config.model,
                max_tokens=request.max_tokens or 1024,
                messages=conversation,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            if system_prompt:
                kwargs["system"] = system_prompt
            if request.timeout is not None:
                kwargs["timeout"] = request.timeout

            try:
                response = client.messages.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - normalized below
                raise normalize_sdk_exception(
                    exc, provider="anthropic", api_key=self._config.api_key
                ) from exc

            text = self._extract_text(response)
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMMalformedResponseError(
                    f"anthropic: structured response was not valid JSON: {exc}"
                ) from exc

        return call_with_retries(_call, max_retries=self._config.max_retries)
