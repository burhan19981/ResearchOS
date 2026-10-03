"""OpenAI provider implementation.

This is the only module in the codebase that should import `openai`.
Everything else depends solely on the provider-agnostic interface in
`researchos.llm.base`.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import openai

from ._sdk_error_mapping import normalize_sdk_exception
from .base import LLMProvider
from .config import ProviderConfig, load_openai_config
from .errors import LLMConfigurationError, LLMMalformedResponseError
from .retry import call_with_retries
from .types import GenerationRequest, GenerationResult, Usage


class OpenAIProvider(LLMProvider):
    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        self._config = config or load_openai_config()
        self._client: Optional["openai.OpenAI"] = None

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._config.model

    @classmethod
    def is_configured(cls) -> bool:
        return load_openai_config().is_configured

    def _get_client(self) -> "openai.OpenAI":
        if not self._config.is_configured:
            raise LLMConfigurationError(
                "OpenAI provider is not configured: OPENAI_API_KEY is not set."
            )
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._config.api_key,
                timeout=self._config.timeout,
                max_retries=0,  # retries are handled by researchos.llm.retry
            )
        return self._client

    def _messages_payload(self, request: GenerationRequest) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in request.messages]

    def generate(self, request: GenerationRequest) -> GenerationResult:
        client = self._get_client()

        def _call() -> GenerationResult:
            kwargs: dict[str, Any] = dict(
                model=self._config.model,
                messages=self._messages_payload(request),
            )
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.timeout is not None:
                kwargs["timeout"] = request.timeout

            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - normalized below
                raise normalize_sdk_exception(
                    exc, provider="openai", api_key=self._config.api_key
                ) from exc

            try:
                choice = response.choices[0]
                text = choice.message.content or ""
            except (AttributeError, IndexError, TypeError) as exc:
                raise LLMMalformedResponseError(
                    f"openai: could not parse response content: {exc}"
                ) from exc

            usage_obj = getattr(response, "usage", None)
            usage = Usage(
                input_tokens=getattr(usage_obj, "prompt_tokens", None),
                output_tokens=getattr(usage_obj, "completion_tokens", None),
                total_tokens=getattr(usage_obj, "total_tokens", None),
            )
            return GenerationResult(
                text=text,
                provider=self.provider_name,
                model=self._config.model,
                finish_reason=getattr(choice, "finish_reason", None),
                usage=usage,
            )

        return call_with_retries(_call, max_retries=self._config.max_retries)

    def generate_structured(
        self, request: GenerationRequest, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate JSON conforming to `schema` using OpenAI's native
        `response_format={"type": "json_schema", ...}` support."""
        client = self._get_client()
        schema_name = schema.get("title", "structured_response")

        def _call() -> dict[str, Any]:
            kwargs: dict[str, Any] = dict(
                model=self._config.model,
                messages=self._messages_payload(request),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.timeout is not None:
                kwargs["timeout"] = request.timeout

            try:
                response = client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - normalized below
                raise normalize_sdk_exception(
                    exc, provider="openai", api_key=self._config.api_key
                ) from exc

            raw_text = response.choices[0].message.content or "{}"
            try:
                return json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise LLMMalformedResponseError(
                    f"openai: structured response was not valid JSON: {exc}"
                ) from exc

        return call_with_retries(_call, max_retries=self._config.max_retries)
