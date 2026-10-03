"""Deterministic fingerprinting and configuration hashing, shared by
dataset-version content/metadata fingerprints and
`ExperimentSpecification.configuration_hash` — one canonicalization
utility used twice within Phase 8A, rather than two independently
invented hashing schemes.

Canonicalization follows the exact convention already established in
`researchos.evidence.cache.make_cache_key` (`json.dumps(...,
sort_keys=True, default=str)` then `hashlib.sha256(...).hexdigest()`),
reused here rather than a new convention, so equivalent structured data
never produces a different hash merely because of dict/JSON key
ordering.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .types import FingerprintPair


def canonicalize(value: Any) -> str:
    """Deterministic JSON serialization: sorted keys, no incidental
    whitespace, non-JSON-native values coerced via `str()` so the same
    logical structure always serializes identically regardless of
    input key ordering or value types."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_fingerprint(value: Any) -> str:
    """One deterministic sha256 hex digest of `value`'s canonical form."""
    return sha256_hex(canonicalize(value))


def compute_dataset_fingerprints(
    *,
    content_descriptor: dict[str, Any],
    metadata_descriptor: dict[str, Any],
) -> FingerprintPair:
    """`content_descriptor` carries what makes this version a
    *different dataset* — `source_uri`, `format`, `sample_count`,
    `split_definition`, `class_definition` — fields that, if changed,
    mean the underlying data is different. `metadata_descriptor` carries
    descriptive information that does not itself define the data —
    `description`, `preprocessing_definition`, `augmentation_definition`.
    This split is a deliberate, documented design choice (see
    docs/PHASE8A_DATASET_EXPERIMENT_SPECIFICATION.md), not an
    accidental one.
    """
    return FingerprintPair(
        content_fingerprint=compute_fingerprint(content_descriptor),
        metadata_fingerprint=compute_fingerprint(metadata_descriptor),
    )


def compute_configuration_hash(configuration: dict[str, Any]) -> str:
    return compute_fingerprint(configuration)
