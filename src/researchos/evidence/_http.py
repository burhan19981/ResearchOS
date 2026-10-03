"""HTTP transport with timeout/retry/backoff/rate-limit handling.

Uses only the Python standard library (`urllib`) — no new dependency —
per the Phase 5 instruction to prefer the standard library where
practical. Every adapter goes through `fetch()` so timeout, retry, and
rate-limit behavior is implemented exactly once, not duplicated four
times.

The real network call lives entirely inside `UrllibTransport.get()`.
Tests inject a fake `Transport` (see `tests/evidence/fakes.py`) so no
adapter test ever makes a real request — `fetch()` itself is
transport-agnostic and equally exercised by real and fake transports.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol

from .config import SourceConfig
from .errors import SourceRateLimitError, SourceResponseError, SourceTimeoutError, SourceUnavailableError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


class Transport(Protocol):
    def get(
        self, url: str, *, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0,
    ) -> HttpResponse: ...


class UrllibTransport:
    """The real transport: `urllib.request`, nothing more."""

    def get(
        self, url: str, *, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0,
    ) -> HttpResponse:
        full_url = url
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            separator = "&" if "?" in url else "?"
            full_url = f"{url}{separator}{query}"

        request = urllib.request.Request(full_url, headers=dict(headers or {}), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(status=response.status, headers=dict(response.headers), body=response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            return HttpResponse(status=exc.code, headers=dict(exc.headers or {}), body=body)
        except socket.timeout as exc:
            raise SourceTimeoutError(f"Request to {url} timed out after {timeout}s.") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise SourceTimeoutError(f"Request to {url} timed out after {timeout}s.") from exc
            raise SourceUnavailableError(f"Could not reach {url}: {exc.reason}") from exc


def default_transport() -> Transport:
    return UrllibTransport()


def _retry_after_seconds(response: HttpResponse) -> Optional[float]:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return min(float(raw), _MAX_BACKOFF_SECONDS)
    except ValueError:
        return None


def fetch(
    transport: Transport,
    config: SourceConfig,
    *,
    url: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """GET `url` with bounded retry-with-backoff on transient failures.

    Retries (up to `config.max_retries` additional attempts) on: a
    timeout, HTTP 429 (honoring `Retry-After` when present, capped at
    30s), and HTTP 5xx. Any other 4xx raises `SourceResponseError`
    immediately (not retried — retrying a client error we caused
    ourselves wastes the source's rate-limit budget for nothing). A 2xx
    or a plain 404 is returned as-is for the caller to interpret (404
    means different things to `search()` vs. `get_by_id()`).
    """
    attempt = 0
    last_status: Optional[int] = None
    while True:
        try:
            response = transport.get(url, params=params, headers=headers, timeout=config.timeout)
        except (SourceTimeoutError, SourceUnavailableError):
            if attempt >= config.max_retries:
                raise
            sleep(min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS))
            attempt += 1
            continue

        if response.status < 400 or response.status == 404:
            return response

        last_status = response.status
        if response.status not in _RETRYABLE_STATUS:
            raise SourceResponseError(
                f"{config.source}: request to {url} failed with HTTP {response.status}."
            )
        if attempt >= config.max_retries:
            break

        delay = _retry_after_seconds(response)
        if delay is None:
            delay = min(0.5 * (2**attempt), _MAX_BACKOFF_SECONDS)
        sleep(delay)
        attempt += 1

    if last_status == 429:
        raise SourceRateLimitError(f"{config.source}: rate limited (HTTP 429) after {attempt} attempt(s).")
    raise SourceUnavailableError(f"{config.source}: HTTP {last_status} after {attempt} attempt(s).")
