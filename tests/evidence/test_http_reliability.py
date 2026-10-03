"""Tests #13 (rate-limit handling), #14 (timeout handling), #15 (bounded
retry limits) — all against `researchos.evidence._http.fetch()` directly,
with an injectable `sleep` so no test ever actually waits.
"""

from __future__ import annotations

import pytest

from researchos.evidence._http import fetch
from researchos.evidence.config import SourceConfig
from researchos.evidence.errors import SourceRateLimitError, SourceResponseError, SourceTimeoutError, SourceUnavailableError

from .fakes import FakeTransport, json_response

CONFIG = SourceConfig(source="test", base_url="https://example.test", timeout=5.0, max_retries=3)


def _sleep_recorder():
    calls: list[float] = []

    def _sleep(seconds: float) -> None:
        calls.append(seconds)

    return _sleep, calls


def test_timeout_is_retried_up_to_max_retries_then_raises():
    transport = FakeTransport(responses=[SourceTimeoutError("t/o")] * (CONFIG.max_retries + 1))
    sleep, calls = _sleep_recorder()

    with pytest.raises(SourceTimeoutError):
        fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)

    assert len(transport.calls) == CONFIG.max_retries + 1
    assert len(calls) == CONFIG.max_retries  # one sleep between each retry, none after the final failure


def test_timeout_succeeds_after_transient_failures():
    transport = FakeTransport(responses=[SourceTimeoutError("t/o"), SourceTimeoutError("t/o"), json_response(200, {"ok": True})])
    sleep, calls = _sleep_recorder()

    response = fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)

    assert response.status == 200
    assert len(calls) == 2


def test_rate_limit_honors_retry_after_header_then_succeeds():
    transport = FakeTransport(
        responses=[json_response(429, {"error": "slow down"}, headers={"Retry-After": "2"}), json_response(200, {"ok": True})]
    )
    sleep, calls = _sleep_recorder()

    response = fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)

    assert response.status == 200
    assert calls == [2.0]


def test_rate_limit_exhausts_retries_and_raises_rate_limit_error():
    transport = FakeTransport(responses=[json_response(429, {}) for _ in range(CONFIG.max_retries + 1)])
    sleep, _calls = _sleep_recorder()

    with pytest.raises(SourceRateLimitError):
        fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)

    assert len(transport.calls) == CONFIG.max_retries + 1


def test_retry_after_header_is_capped_at_30_seconds():
    transport = FakeTransport(
        responses=[json_response(429, {}, headers={"Retry-After": "9999"}), json_response(200, {"ok": True})]
    )
    sleep, calls = _sleep_recorder()
    fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)
    assert calls == [30.0]


def test_server_error_5xx_is_retried_then_raises_unavailable():
    transport = FakeTransport(responses=[json_response(503, {}) for _ in range(CONFIG.max_retries + 1)])
    sleep, _calls = _sleep_recorder()
    with pytest.raises(SourceUnavailableError):
        fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)


def test_non_retryable_4xx_raises_immediately_without_retry():
    transport = FakeTransport(responses=[json_response(400, {"error": "bad request"})])
    sleep, calls = _sleep_recorder()
    with pytest.raises(SourceResponseError):
        fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)
    assert len(transport.calls) == 1  # never retried
    assert calls == []


def test_404_is_returned_not_raised_by_fetch_itself():
    transport = FakeTransport(responses=[json_response(404, {"error": "not found"})])
    response = fetch(transport, CONFIG, url="https://example.test/x", sleep=lambda s: None)
    assert response.status == 404  # interpretation (NOT_FOUND vs. error) is left to the caller


def test_successful_first_attempt_never_sleeps():
    transport = FakeTransport(responses=[json_response(200, {"ok": True})])
    sleep, calls = _sleep_recorder()
    fetch(transport, CONFIG, url="https://example.test/x", sleep=sleep)
    assert calls == []


def test_retries_are_bounded_never_exceed_configured_max():
    zero_retry_config = SourceConfig(source="test", base_url="https://example.test", timeout=5.0, max_retries=0)
    transport = FakeTransport(responses=[SourceTimeoutError("t/o")])
    with pytest.raises(SourceTimeoutError):
        fetch(transport, zero_retry_config, url="https://example.test/x", sleep=lambda s: None)
    assert len(transport.calls) == 1  # no retries at all when max_retries=0
