"""Normalized error hierarchy for the analysis & scientific review layer.

Reuses `researchos.planning.errors`' generic reference-checking types
directly (`UnknownPlanningEntityError`, `CrossProjectReferenceError`,
`UpstreamNotApprovedError`) rather than declaring a third/fourth copy
of each — the same "missing entity" / "wrong project" / "upstream not
approved" concepts every phase since 8B-1 has needed already exist
there with exactly this meaning. Only concepts genuinely new to Phase 8
are declared here.
"""

from __future__ import annotations

from ..planning.errors import (  # noqa: F401 - re-exported for `researchos.analysis` callers
    CrossProjectReferenceError,
    UnknownPlanningEntityError as MissingEntityError,
    UpstreamNotApprovedError,
)


class AnalysisError(Exception):
    """Base class for all normalized analysis-layer errors."""


class NumericSafetyError(AnalysisError):
    """A deterministic analysis operation was asked to compute over
    invalid numeric input — NaN, +-Infinity, a division by zero, an
    empty population, or fewer observations than the operation requires
    (e.g. standard deviation needs at least 2). Raised *before* any
    `AnalysisRecord` is persisted — an invalid computation attempt
    never becomes a database row (Phase 8 spec section 7); it is never
    silently coerced into a plausible-looking number."""


class InvalidAnalysisInputError(AnalysisError):
    """An `AnalysisInput`'s referenced `Run`/`Metric`/`ArtifactMetadata`
    does not exist, does not belong to the caller's project, or is
    otherwise not a valid input for the requested analysis method
    (e.g. a metric name that does not exist on the referenced Run)."""


class InvalidAnalysisResponseError(AnalysisError):
    """An LLM's structured response (candidate claim generation,
    scientific review generation) did not match the expected shape, or
    attempted to set a value only a human/deterministic path may set
    (e.g. `ScientificReviewStatus.HUMAN_APPROVED`) — rejected before
    anything is persisted, mirroring
    `researchos.planning.errors.InvalidPlanningResponseError`."""


class InsufficientObservationsError(NumericSafetyError):
    """An aggregation/statistics operation (mean, standard deviation,
    repeated-run aggregation, ...) was given fewer observations than it
    requires to produce a meaningful, well-defined result."""


class ReviewNotReadyError(AnalysisError):
    """`researchos.analysis.approval.approve_scientific_review` was
    asked to approve a `ScientificReview` that is not
    `READY_FOR_HUMAN_REVIEW` — a review must reach that state (via
    `researchos.analysis.reviews`) before a human decision on it means
    anything."""


class ClaimNotSupportedByApprovedReviewError(AnalysisError):
    """`researchos.analysis.approval.approve_scientific_claim` was
    asked to approve a `ScientificClaim` with no `HUMAN_APPROVED`
    `ScientificReview` — a claim's own approval always rests on at
    least one review whose evidence assessment a human has already
    signed off on (Phase 8 spec section 14)."""


class CandidateNotFoundError(AnalysisError):
    """No `ScientificClaim`/`ScientificReview` exists with the given id
    — the not-found error type `researchos.analysis.approval` supplies
    to `researchos.db.approval_dispatch` (own copy, mirroring
    `researchos.planning.errors.CandidateNotFoundError`)."""


class ApprovalAlreadyDecidedError(AnalysisError):
    """The `ScientificClaim`'s/`ScientificReview`'s approval has already
    been decided."""


class HumanOnlyActionError(AnalysisError):
    """An agent actor attempted an action reserved for a human —
    approving, rejecting, or requesting changes on a `ScientificClaim`
    or `ScientificReview` is always a human act; the LLM can never
    approve its own output."""


class UnknownEvidenceReferenceError(AnalysisError):
    """An LLM-generated candidate interpretation/review/claim referenced
    a `Run`/`Metric`/`AnalysisRecord`/evidence id that was not part of
    the context package it was actually given — the anti-hallucination
    guard (`researchos.analysis.validation`). Never silently accepted;
    the offending entry is rejected."""
