"""The ResearchOS dataset & experiment specification layer (Phase 8A).

Converts approved research planning into execution-ready, reproducible
specifications:

    Approved Planning -> DatasetVersion + ExperimentalDesign
    -> ExperimentSpecification -> Human Approval -> execution-ready artifact

Phase 8A does **not** execute experiments — no training, no inference,
no subprocess/GPU/CUDA/Docker/remote execution, no checkpoints, no
metrics, no logs from actual runs. Every artifact this layer persists
starts as a candidate and requires an explicit human decision
(`researchos.specification.approval`, built on the same
`Approval`/`AuditEvent` tables `researchos.workflow`/`researchos.intelligence`/
`researchos.planning` all use) before it means anything more than "the
system produced a proposal worth reviewing."

This package is a direct continuation of the Phase 7 planning chain,
not an independent sibling — it reuses `researchos.planning.orchestration`,
`researchos.planning.llm_call`, `researchos.planning.validation`, and
`researchos.planning.errors`' generic types directly rather than
duplicating them. See `docs/PHASE8A_DATASET_EXPERIMENT_SPECIFICATION.md`
for the full design.
"""

from . import approval
from .dataset_versions import create_dataset_version, validate_dataset_version
from .errors import (
    ConfigurationValidationError,
    DatasetValidationError,
    InvalidLifecycleTransitionError,
    SpecificationError,
)
from .experiment_specifications import generate_experiment_specification
from .fingerprint import compute_configuration_hash, compute_dataset_fingerprints
from .types import (
    DatasetVersionOutcome,
    ExperimentSpecificationGenerationOutcome,
    FingerprintPair,
    ValidationOutcome,
)
from .validators import available_formats, get_validator

__all__ = [
    "approval",
    "create_dataset_version",
    "validate_dataset_version",
    "generate_experiment_specification",
    "compute_dataset_fingerprints",
    "compute_configuration_hash",
    "get_validator",
    "available_formats",
    "DatasetVersionOutcome",
    "ValidationOutcome",
    "FingerprintPair",
    "ExperimentSpecificationGenerationOutcome",
    "SpecificationError",
    "DatasetValidationError",
    "InvalidLifecycleTransitionError",
    "ConfigurationValidationError",
]
