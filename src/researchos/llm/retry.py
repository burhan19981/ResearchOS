"""Minimal retry helper for transient LLM provider failures.

Kept dependency-free (no `tenacity`/`backoff`) since Phase 2 only needs a
small, predictable amount of retry logic. `fn` must already translate SDK
exceptions into normalized `LLMError` subclasses before this helper sees
them — see `researchos.llm._sdk_error_mapping`.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from .errors import LLMProviderUnavailableError, LLMRateLimitError, LLMTimeoutError

T = TypeVar("T")

_RETRYABLE = (LLMTimeoutError, LLMRateLimitError, LLMProviderUnavailableError)


def call_with_retries(
    fn: Callable[[], T],
    *,
    max_retries: int,
    base_delay_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying on transient normalized errors with linear backoff.

    Non-retryable errors (configuration, authentication, malformed
    response, unsupported operation) propagate immediately.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except _RETRYABLE:
            if attempt >= max_retries:
                raise
            sleep(base_delay_seconds * (attempt + 1))
            attempt += 1
