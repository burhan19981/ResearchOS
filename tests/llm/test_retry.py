import pytest

from researchos.llm.errors import LLMAuthenticationError, LLMTimeoutError
from researchos.llm.retry import call_with_retries


def test_retries_until_success():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise LLMTimeoutError("timed out")
        return "ok"

    result = call_with_retries(flaky, max_retries=5, sleep=lambda s: None)
    assert result == "ok"
    assert calls["count"] == 3


def test_gives_up_after_max_retries():
    def always_fails():
        raise LLMTimeoutError("timed out")

    with pytest.raises(LLMTimeoutError):
        call_with_retries(always_fails, max_retries=2, sleep=lambda s: None)


def test_does_not_retry_non_retryable_errors():
    calls = {"count": 0}

    def fails_auth():
        calls["count"] += 1
        raise LLMAuthenticationError("bad key")

    with pytest.raises(LLMAuthenticationError):
        call_with_retries(fails_auth, max_retries=5, sleep=lambda s: None)

    assert calls["count"] == 1


def test_no_sleep_call_on_first_success():
    sleep_calls = []
    result = call_with_retries(lambda: "ok", max_retries=3, sleep=sleep_calls.append)
    assert result == "ok"
    assert sleep_calls == []
