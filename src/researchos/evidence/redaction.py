"""Secret-redaction helpers, self-contained.

Deliberately duplicated from (not imported from) `researchos.llm.redaction`
— the Evidence Layer must be independent of the LLM layer; sharing this
~15-line helper would create exactly the cross-import this phase's
independence requirement rules out. Nothing here ever returns the
original secret value.
"""

from __future__ import annotations

from typing import Optional

_VISIBLE_PREFIX = 4
_VISIBLE_SUFFIX = 2


def redact_secret(value: Optional[str]) -> str:
    if not value:
        return "<not set>"
    if len(value) <= _VISIBLE_PREFIX + _VISIBLE_SUFFIX:
        return "*" * len(value)
    return f"{value[:_VISIBLE_PREFIX]}{'*' * 6}{value[-_VISIBLE_SUFFIX:]}"


def strip_secret_from_text(text: str, secret: Optional[str]) -> str:
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")
