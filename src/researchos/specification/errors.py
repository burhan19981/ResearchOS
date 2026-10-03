"""Normalized error hierarchy for the dataset & experiment specification
layer (Phase 8A).

Reuses `researchos.planning.errors`' generic types directly for
concepts identical to Phase 7's — `UnknownPlanningEntityError`,
`CrossProjectReferenceError`, `UpstreamNotApprovedError`,
`InvalidPlanningReferenceError`, `InvalidPlanningResponseError`,
`CandidateNotFoundError`, `ApprovalAlreadyDecidedError`,
`HumanOnlyActionError` — rather than duplicating them a third time.
Phase 8A is a direct continuation of the Phase 7 planning chain
(consuming its entities and reusing its generic mechanics throughout),
not an independent sibling package the way Phase 6/7 were kept apart
from each other, so this reuse is deliberate, not an oversight. Only
concepts genuinely new to Phase 8A get their own type below.
"""

from __future__ import annotations


class SpecificationError(Exception):
    """Base class for all normalized Phase 8A-specific errors (distinct
    from the reused `researchos.planning.errors.PlanningError` hierarchy,
    which is imported and used directly for shared concepts)."""


class DatasetValidationError(SpecificationError):
    """A dataset-version validation request could not be completed at
    all (e.g. malformed input) — distinct from a validation OUTCOME
    being invalid, which is a normal, non-exceptional result (see
    `researchos.specification.types.ValidationOutcome`)."""


class InvalidLifecycleTransitionError(SpecificationError):
    """An operation required a `DatasetVersion` to be in a specific
    `lifecycle_status` (e.g. `VALID` before it can be approved) and it
    was not."""


class ConfigurationValidationError(SpecificationError):
    """An `ExperimentSpecification`'s configuration failed structural
    validation — not a JSON object, or contains a key that looks like a
    credential (see `researchos.specification.experiment_specifications`'s
    secret-key deny-list check)."""
