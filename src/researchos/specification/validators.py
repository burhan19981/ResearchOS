"""Dataset validation contract (Phase 8A): a provider/adapter-oriented
interface rather than one hardcoded dataset format, mirroring the exact
registry shape `researchos.evidence.adapters` already established
(`get_adapter()`/`available_sources()`) for source adapters — reused as
a pattern here, not reinvented.

Validation is deterministic, offline, and operates ONLY on the
structured metadata already stored on a `DatasetVersion` row
(`sample_count`, `split_definition`, `class_definition`, ...) — never on
real files at `source_uri`. Accessing an arbitrary external location
would require an execution boundary this phase deliberately does not
build (Phase 8A explicitly excludes arbitrary/remote execution).

Only two validators are implemented: a domain-agnostic
`GenericStructuralValidator` (the default for any/unknown format) and a
`ClassificationDatasetValidator` (label sets are common across CV, NLP,
and tabular ML alike, so this is not a CV-specific format).
Format-specific validators for concrete annotation schemas (COCO, YOLO,
...) are deliberately NOT implemented — they would require hardcoding
CV-specific assumptions not yet justified by actual project usage; see
the Limitations section of docs/PHASE8A_DATASET_EXPERIMENT_SPECIFICATION.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .types import ValidationOutcome


class DatasetValidator(ABC):
    """One validation strategy for one dataset format family."""

    format_name: str

    @abstractmethod
    def validate(self, metadata: dict[str, Any]) -> ValidationOutcome:
        """`metadata` is a caller-assembled dict of a `DatasetVersion`'s
        own stored fields (`sample_count`, `split_definition`,
        `class_definition`, `source_uri`) — never a raw ORM row, never a
        real file."""


class GenericStructuralValidator(DatasetValidator):
    """The domain-agnostic default: checks internal consistency of
    whatever structured metadata was actually supplied, without
    assuming any particular dataset format. Every dataset version can
    be validated with this regardless of research domain."""

    format_name = "generic"

    def validate(self, metadata: dict[str, Any]) -> ValidationOutcome:
        errors: list[str] = []
        warnings: list[str] = []

        sample_count = metadata.get("sample_count")
        if sample_count is not None and (not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 0):
            errors.append("sample_count must be a non-negative integer.")
        elif sample_count is None:
            warnings.append("sample_count was not provided.")

        split_definition = metadata.get("split_definition")
        if split_definition is not None:
            if not isinstance(split_definition, dict) or not split_definition:
                errors.append("split_definition, if provided, must be a non-empty object.")
            else:
                numeric_values = [
                    v for v in split_definition.values() if isinstance(v, (int, float)) and not isinstance(v, bool)
                ]
                if numeric_values and len(numeric_values) == len(split_definition):
                    total = sum(numeric_values)
                    looks_like_proportions = 0.99 <= total <= 1.01
                    looks_like_counts = isinstance(sample_count, int) and abs(total - sample_count) <= 1
                    if not looks_like_proportions and not looks_like_counts:
                        warnings.append(
                            f"split_definition values sum to {total}, which is neither ~1.0 (proportions) nor "
                            "the declared sample_count (absolute counts) — verify this is intentional."
                        )
        else:
            warnings.append("split_definition was not provided.")

        if not metadata.get("source_uri"):
            warnings.append("source_uri was not provided.")

        return ValidationOutcome(is_valid=not errors, format=self.format_name, errors=errors, warnings=warnings)


class ClassificationDatasetValidator(DatasetValidator):
    """A lightweight validator for classification-style datasets — label
    sets exist across CV, NLP, and tabular ML alike, so this is not a
    CV-specific annotation format like COCO/YOLO."""

    format_name = "classification"

    def validate(self, metadata: dict[str, Any]) -> ValidationOutcome:
        base = GenericStructuralValidator().validate(metadata)
        errors = list(base.errors)
        warnings = list(base.warnings)

        class_definition = metadata.get("class_definition")
        if class_definition is None:
            errors.append("classification datasets require a non-empty class_definition.")
        elif not isinstance(class_definition, list) or not class_definition:
            errors.append("class_definition must be a non-empty list of class labels.")
        elif len(class_definition) != len({str(label) for label in class_definition}):
            errors.append("class_definition contains duplicate class labels.")

        return ValidationOutcome(is_valid=not errors, format=self.format_name, errors=errors, warnings=warnings)


_VALIDATORS: dict[str, DatasetValidator] = {
    "generic": GenericStructuralValidator(),
    "classification": ClassificationDatasetValidator(),
}


def available_formats() -> list[str]:
    return sorted(_VALIDATORS.keys())


def get_validator(format_name: Optional[str]) -> DatasetValidator:
    """Returns the validator registered for `format_name`, defaulting to
    the generic structural validator for an unknown or unspecified
    format — never silently skips validation entirely."""
    if not format_name:
        return _VALIDATORS["generic"]
    return _VALIDATORS.get(format_name.strip().lower(), _VALIDATORS["generic"])
