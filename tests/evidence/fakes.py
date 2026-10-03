"""Fake transport for offline adapter/HTTP-layer testing.

`FakeTransport` implements the same `.get()` shape as
`researchos.evidence._http.Transport` but never opens a socket — every
test in `tests/evidence/` uses this (or a stack of canned responses) so
the suite makes zero real network calls, per Phase 5's explicit
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

from researchos.evidence._http import HttpResponse
from researchos.evidence.errors import SourceTimeoutError, SourceUnavailableError


@dataclass
class FakeTransport:
    """Returns queued responses/exceptions in order, one per `.get()` call.

    Each queued item is either an `HttpResponse`, an `Exception`
    instance (raised), or a zero-arg callable (invoked, its return value
    or raised exception used) — the latter lets a test simulate "fails
    twice then succeeds" without pre-building three fixed values.
    """

    responses: list[Union[HttpResponse, Exception, Callable[[], HttpResponse]]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def get(
        self, url: str, *, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0,
    ) -> HttpResponse:
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {}), "timeout": timeout})
        if not self.responses:
            raise AssertionError("FakeTransport ran out of queued responses.")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, HttpResponse):
            return item()
        return item


def json_response(status: int, payload: Any, headers: Optional[dict[str, str]] = None) -> HttpResponse:
    import json

    return HttpResponse(status=status, headers=headers or {}, body=json.dumps(payload).encode("utf-8"))


def text_response(status: int, text: str, headers: Optional[dict[str, str]] = None) -> HttpResponse:
    return HttpResponse(status=status, headers=headers or {}, body=text.encode("utf-8"))
