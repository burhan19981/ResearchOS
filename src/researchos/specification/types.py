"""Data types for the dataset & experiment specification layer.
Pure dataclasses — no I/O, no database, no LLM calls.

`researchos.planning.types.PlanningContext` is reused directly (not
re-declared here) for `ExperimentSpecification` generation — it is
already fully generic (bounded `prompt_json`, `allowed_*_ids`,
`upstream_snapshots`) and Phase 8A needs nothing beyond what it already
offers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FingerprintPair:
    content_fingerprint: str
    metadata_fingerprint: str


@dataclass(frozen=True)
class ValidationOutcome:
    """The result of running one `DatasetValidator` against a dataset
    version's stored metadata. `is_valid` is `False` whenever `errors`
    is non-empty; `warnings` never affect `is_valid`."""

    is_valid: bool
    format: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "format": self.format,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DatasetVersionOutcome:
    dataset_version_id: int


@dataclass(frozen=True)
class ExperimentSpecificationGenerationOutcome:
    experiment_specification_id: int
    baseline_ids: list[int]
