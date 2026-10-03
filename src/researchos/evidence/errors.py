"""Normalized error hierarchy for the evidence/literature layer.

Deliberately self-contained: nothing here imports from `researchos.llm`
or `researchos.workflow` — the Evidence Layer is independent, per
`docs/PHASE5_EVIDENCE.md`. Every adapter translates its own
source-specific failures (HTTP errors, malformed JSON/XML, etc.) into
one of these, so callers never need to know which transport or parsing
library a given source adapter happens to use.
"""

from __future__ import annotations


class EvidenceError(Exception):
    """Base class for all normalized evidence-layer errors."""


class SourceConfigurationError(EvidenceError):
    """A source adapter is missing required configuration (e.g. no base URL)."""


class SourceTimeoutError(EvidenceError):
    """A request to a source exceeded its configured timeout."""


class SourceRateLimitError(EvidenceError):
    """A source reported that the caller is being rate limited (HTTP 429)."""


class SourceUnavailableError(EvidenceError):
    """Transient source failure: connection error, DNS failure, or 5xx response."""


class SourceResponseError(EvidenceError):
    """A source returned a response that could not be parsed/understood
    (malformed JSON/XML, an unexpected shape, or a non-transient 4xx)."""


class SourceNotFoundError(EvidenceError):
    """`get_by_id()` found no record for the given identifier (HTTP 404)."""


class UnsupportedFilterError(EvidenceError):
    """A requested search filter is not supported by this source adapter."""
