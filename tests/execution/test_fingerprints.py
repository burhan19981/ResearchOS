"""Fingerprint determinism: environment hash and (reused, not
reimplemented) configuration hash must both be independent of key
ordering and stable for identical content."""

from __future__ import annotations

from researchos.execution.environment_snapshot import collect_environment_info, compute_environment_hash
from researchos.specification.fingerprint import compute_configuration_hash


def test_environment_hash_is_deterministic_for_identical_info():
    info = collect_environment_info()
    assert compute_environment_hash(info) == compute_environment_hash(dict(info))


def test_environment_hash_is_independent_of_key_order():
    info = {"a": 1, "b": 2, "c": {"x": 1, "y": 2}}
    reordered = {"c": {"y": 2, "x": 1}, "b": 2, "a": 1}
    assert compute_environment_hash(info) == compute_environment_hash(reordered)


def test_environment_hash_changes_when_content_changes():
    info_a = {"python_version": "3.12.0"}
    info_b = {"python_version": "3.12.1"}
    assert compute_environment_hash(info_a) != compute_environment_hash(info_b)


def test_execution_layer_reuses_phase8a_configuration_hash_function():
    # Not reimplemented: researchos.execution imports
    # researchos.specification.fingerprint.compute_configuration_hash
    # directly (see researchos.execution.preflight / orchestrator).
    from researchos.execution import preflight as preflight_module

    assert preflight_module.compute_configuration_hash is compute_configuration_hash


def test_configuration_hash_independent_of_key_order():
    a = {"seed": 1, "batch_size": 32}
    b = {"batch_size": 32, "seed": 1}
    assert compute_configuration_hash(a) == compute_configuration_hash(b)
