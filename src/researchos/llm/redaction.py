"""Helpers for keeping secret values out of logs, exceptions, and output.

Nothing in this module ever returns a caller's original secret value.
"""

from __future__ import annotations

from typing import Optional

_VISIBLE_PREFIX = 4
_VISIBLE_SUFFIX = 2


def redact_secret(value: Optional[str]) -> str:
    """Return a masked representation of a secret, safe to log or display.

    A short prefix/suffix is kept only when the value is long enough that
    doing so cannot meaningfully help reconstruct it, so a human can tell
    two configured keys apart without recovering either one.
    """
    if not value:
        return "<not set>"
    if len(value) <= _VISIBLE_PREFIX + _VISIBLE_SUFFIX:
        return "*" * len(value)
    return f"{value[:_VISIBLE_PREFIX]}{'*' * 6}{value[-_VISIBLE_SUFFIX:]}"


def strip_secret_from_text(text: str, secret: Optional[str]) -> str:
    """Remove an exact secret value from arbitrary text (e.g. SDK error strings)."""
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")
