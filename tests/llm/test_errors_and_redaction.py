from researchos.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMError,
    LLMMalformedResponseError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnsupportedOperationError,
)
from researchos.llm.redaction import redact_secret, strip_secret_from_text


def test_all_normalized_errors_are_llm_error_subclasses():
    for cls in (
        LLMConfigurationError,
        LLMAuthenticationError,
        LLMTimeoutError,
        LLMRateLimitError,
        LLMProviderUnavailableError,
        LLMMalformedResponseError,
        LLMUnsupportedOperationError,
    ):
        assert issubclass(cls, LLMError)


def test_redact_secret_masks_value():
    masked = redact_secret("sk-ant-super-secret-value-123")
    assert masked != "sk-ant-super-secret-value-123"
    assert "super-secret" not in masked
    assert masked.startswith("sk-a")


def test_redact_secret_handles_missing_value():
    assert redact_secret(None) == "<not set>"
    assert redact_secret("") == "<not set>"


def test_redact_secret_fully_masks_short_value():
    masked = redact_secret("abc")
    assert "abc" not in masked
    assert masked == "***"


def test_strip_secret_from_text_removes_exact_value():
    text = "Authentication failed for key sk-ant-real-secret-999"
    cleaned = strip_secret_from_text(text, "sk-ant-real-secret-999")
    assert "sk-ant-real-secret-999" not in cleaned
    assert "[REDACTED]" in cleaned


def test_strip_secret_from_text_noop_when_no_secret():
    text = "some message"
    assert strip_secret_from_text(text, None) == text
