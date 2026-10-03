"""Fake LLM provider for offline analysis-layer testing.

Implements the same shape as `researchos.llm.base.LLMProvider` — every
analysis-layer test injects one of these via the `provider=` parameter
so no test ever makes a real LLM API call. Identical shape to
`tests/planning/fakes.py`/`tests/intelligence/fakes.py`, duplicated
here per-package rather than imported across test packages, matching
this repository's existing per-test-package convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from researchos.llm.errors import LLMError
from researchos.llm.types import GenerationRequest, GenerationResult


@dataclass
class FakeLLMProvider:
    """Returns queued structured responses (or raises a queued
    exception) in order, one per `generate_structured()` call."""

    responses: list[Union[dict, Exception]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    name: str = "fake"
    model: str = "fake-model-1"

    @property
    def provider_name(self) -> str:
        return self.name

    @property
    def model_name(self) -> str:
        return self.model

    @classmethod
    def is_configured(cls) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError("FakeLLMProvider.generate() is not used by the analysis layer")

    def generate_structured(self, request: GenerationRequest, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"request": request, "schema": schema})
        if not self.responses:
            raise AssertionError("FakeLLMProvider ran out of queued responses.")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def last_request(self) -> Optional[GenerationRequest]:
        return self.calls[-1]["request"] if self.calls else None
