"""Normalized error hierarchy for the execution foundation layer.

Reuses `researchos.planning.errors`' generic reference-checking types
directly (`UnknownPlanningEntityError`, `CrossProjectReferenceError`,
`UpstreamNotApprovedError`) rather than declaring a third copy of each
— the same "missing entity" / "wrong project" / "upstream not
approved" concepts this layer's own preflight checks need already
exist there with exactly this meaning, and Phase 8A already established
the precedent of importing them directly instead of duplicating. Only
concepts genuinely new to Phase 8B-1 are declared here.
"""

from __future__ import annotations

from ..planning.errors import (  # noqa: F401 - re-exported for `researchos.execution` callers
    CrossProjectReferenceError,
    UnknownPlanningEntityError as MissingEntityError,
    UpstreamNotApprovedError,
)


class ExecutionError(Exception):
    """Base class for all normalized execution-layer errors."""


class ExecutionNotApprovedError(ExecutionError):
    """A `Run` was asked to start (`CREATED -> QUEUED`) without a
    decided, approved `EXECUTION_APPROVAL:<run_id>` gate. Distinct from
    `UpstreamNotApprovedError`: that covers the *specification* not
    being approved; this covers execution itself never having been
    separately authorized even when the specification is fine — see
    docs/PHASE8B1_EXECUTION_FOUNDATION.md's Execution Approval section
    for why the two are deliberately different gates."""


class InvalidExecutionTargetError(ExecutionError):
    """An `ExecutionRequest`'s target (module name, arguments, python
    executable, working directory, or environment) failed the
    execution-layer security boundary — e.g. a module outside the
    configured allowlist, an argument containing shell metacharacters,
    or a working directory outside the configured allowed root. Never
    raised for a scientific-content reason, only a security/structural
    one."""


class InvalidRunStateError(ExecutionError):
    """A caller attempted a `Run` lifecycle transition that is not
    valid from the `Run`'s actual current state — either the edge
    itself is not in `RunStatus`'s deterministic transition table, or
    an optimistic-concurrency check
    (`researchos.db.repository.update_run_lifecycle`'s
    `expected_status`) found the row had already moved. Terminal
    `Run`s (`SUCCEEDED`/`FAILED`/`CANCELLED`/`TIMEOUT`) can never be
    the source of any transition."""


class ProvenanceError(ExecutionError):
    """A `Run`'s required provenance is missing or internally
    inconsistent in a way that execution policy does not allow — e.g.
    a declared `configuration_hash` that does not match the
    specification's own recomputed hash. Distinct from a caller simply
    omitting optional provenance (git-unavailable code provenance is
    handled explicitly and does not raise this — see
    `researchos.execution.git_provenance`)."""


class TimeoutConfigurationError(ExecutionError):
    """A requested `timeout_seconds` value is not a valid, positive,
    boundable duration."""


class DuplicateRunError(ExecutionError):
    """A caller attempted to re-execute an already-terminal `Run`
    instead of creating a new one — see
    docs/PHASE8B1_EXECUTION_FOUNDATION.md's Idempotency section."""


# --------------------------------------------------------------------------
# Phase 8B-2: actual execution, artifacts, metrics
# --------------------------------------------------------------------------


class ArtifactRegistrationError(ExecutionError):
    """An artifact could not be registered for a reason other than a
    duplicate logical name or a missing file (e.g. the database write
    itself failed) — a storage/integrity failure distinct from the two
    more specific subclasses below."""


class MissingArtifactFileError(ArtifactRegistrationError):
    """`researchos.execution.artifacts.register_artifact` was asked to
    register a file that does not exist on disk."""


class DuplicateArtifactError(ArtifactRegistrationError):
    """An artifact with this `(run_id, logical_name)` is already
    registered — `ArtifactMetadata` rows are create-only; this is never
    silently treated as a successful re-registration."""


class ArtifactPathEscapeError(ArtifactRegistrationError):
    """`researchos.execution.artifacts.register_artifact` refused to
    register a file whose path resolves outside its `Run`'s own
    authorized workspace subtree — path traversal (`..`), an absolute
    path elsewhere on disk, a path under a different project's or
    run's own subtree, or a symlink resolving outside the workspace
    all raise this. Enforced unconditionally inside artifact
    registration itself — never only by a well-behaved caller. See
    `researchos.execution.security.validate_artifact_path`."""


class InvalidMetricValueError(ExecutionError):
    """A metric's `value`/`threshold` was not a finite number (NaN and
    +-Infinity are rejected by explicit policy — see
    `researchos.execution.metrics`'s module docstring) or not a number
    at all."""


class MalformedMetricsManifestError(ExecutionError):
    """A metrics manifest failed structural validation — wrong JSON
    shape, unrecognized schema version, unrecognized field (strict
    compatibility policy — see `researchos.execution.metrics`), or a
    missing required field. Never silently ignored or partially
    ingested: either the whole manifest validates, or none of its
    metrics are persisted."""


# --------------------------------------------------------------------------
# Phase 8B-3: research experiment integration
# --------------------------------------------------------------------------


class UnlinkedSpecificationError(ProvenanceError):
    """`researchos.execution.integration.create_run_from_specification`
    was asked to create a `Run` from an `ExperimentSpecification` whose
    `experiment_id` is not set. A `Run` is always created for a
    specific, identified research experiment — never an anonymous one —
    so this is refused rather than silently proceeding with no
    `Experiment` link, or silently inventing/guessing one."""


class SpecificationMissingDatasetVersionError(ProvenanceError):
    """`create_run_from_specification` was asked to create a `Run` from
    an `ExperimentSpecification` whose `dataset_version_id` is not set.
    Execution always requires an explicit, identified `DatasetVersion`
    — never "the latest dataset" and never none at all."""
