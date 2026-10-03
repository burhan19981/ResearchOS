"""Structured metrics: valid manifests, repeated names across splits,
integer/float/zero/negative values, NaN/Infinity rejection, malformed
manifests (missing required fields, unknown fields, bad schema
version), and append-only persistence."""

from __future__ import annotations

import json
import math

import pytest

from researchos.db import repository
from researchos.db.models import ExecutionBackend, MetricValueType
from researchos.execution.errors import InvalidMetricValueError, MalformedMetricsManifestError
from researchos.execution.metrics import (
    METRICS_MANIFEST_SCHEMA_VERSION,
    load_metrics_manifest,
    register_metrics,
    validate_metrics_manifest,
)


def _make_run(session_factory, project_id, experiment_id):
    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        s.commit()
        return run.id
    finally:
        s.close()


# --- validate_metrics_manifest -----------------------------------------------


def test_valid_manifest_normalizes_correctly():
    data = {
        "schema_version": "v1",
        "metrics": [
            {"name": "accuracy", "value": 0.95, "split": "test", "aggregation": "mean"},
            {"name": "epoch", "value": 5},
        ],
    }
    normalized = validate_metrics_manifest(data)
    assert len(normalized) == 2
    assert normalized[0]["name"] == "accuracy"
    assert normalized[0]["value"] == 0.95
    assert normalized[0]["value_type"] == MetricValueType.FLOAT
    assert normalized[1]["value_type"] == MetricValueType.INTEGER


def test_repeated_metric_name_across_splits_is_valid():
    data = {
        "schema_version": "v1",
        "metrics": [
            {"name": "accuracy", "value": 0.8, "split": "train"},
            {"name": "accuracy", "value": 0.9, "split": "val"},
            {"name": "accuracy", "value": 0.95, "split": "test"},
        ],
    }
    normalized = validate_metrics_manifest(data)
    assert len(normalized) == 3
    assert [m["split"] for m in normalized] == ["train", "val", "test"]


@pytest.mark.parametrize("value,expected_type", [
    (0, MetricValueType.INTEGER), (0.0, MetricValueType.FLOAT), (-5, MetricValueType.INTEGER),
    (-3.14, MetricValueType.FLOAT), (1000000, MetricValueType.INTEGER),
])
def test_value_kinds_accepted(value, expected_type):
    data = {"schema_version": "v1", "metrics": [{"name": "m", "value": value}]}
    normalized = validate_metrics_manifest(data)
    assert normalized[0]["value"] == value
    assert normalized[0]["value_type"] == expected_type


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_rejected(bad_value):
    data = {"schema_version": "v1", "metrics": [{"name": "m", "value": bad_value}]}
    with pytest.raises(InvalidMetricValueError):
        validate_metrics_manifest(data)


def test_non_numeric_value_rejected():
    data = {"schema_version": "v1", "metrics": [{"name": "m", "value": "not a number"}]}
    with pytest.raises(InvalidMetricValueError):
        validate_metrics_manifest(data)


def test_boolean_value_rejected_even_though_bool_is_technically_an_int():
    data = {"schema_version": "v1", "metrics": [{"name": "m", "value": True}]}
    with pytest.raises(InvalidMetricValueError):
        validate_metrics_manifest(data)


def test_non_finite_threshold_rejected():
    data = {"schema_version": "v1", "metrics": [{"name": "m", "value": 1.0, "threshold": math.nan}]}
    with pytest.raises(InvalidMetricValueError):
        validate_metrics_manifest(data)


def test_missing_schema_version_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"metrics": []})


def test_wrong_schema_version_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v99", "metrics": []})


def test_unrecognized_top_level_key_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": [], "extra_stuff": True})


def test_unrecognized_metric_key_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": [{"name": "m", "value": 1, "bogus": 1}]})


def test_missing_required_metric_field_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": [{"name": "m"}]})  # no 'value'
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": [{"value": 1}]})  # no 'name'


def test_manifest_must_be_an_object():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest(["not", "an", "object"])


def test_metrics_must_be_a_list():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": "not-a-list"})


def test_metric_entry_must_be_an_object():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": ["not-an-object"]})


def test_blank_name_rejected():
    with pytest.raises(MalformedMetricsManifestError):
        validate_metrics_manifest({"schema_version": "v1", "metrics": [{"name": "   ", "value": 1}]})


# --- load_metrics_manifest (filesystem) -------------------------------------


def test_load_metrics_manifest_returns_none_when_file_absent(tmp_path):
    assert load_metrics_manifest(tmp_path / "does_not_exist.json") is None


def test_load_metrics_manifest_parses_valid_file(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"schema_version": "v1", "metrics": [{"name": "acc", "value": 0.5}]}))
    normalized = load_metrics_manifest(path)
    assert normalized is not None
    assert normalized[0]["name"] == "acc"


def test_load_metrics_manifest_rejects_invalid_json(tmp_path):
    path = tmp_path / "metrics.json"
    path.write_text("{not valid json")
    with pytest.raises(MalformedMetricsManifestError):
        load_metrics_manifest(path)


# --- register_metrics (persistence) -----------------------------------------


def test_register_metrics_persists_all_fields(session_factory, project_id, experiment_id):
    run_id = _make_run(session_factory, project_id, experiment_id)
    normalized = validate_metrics_manifest({
        "schema_version": "v1",
        "metrics": [{
            "name": "f1", "value": 0.87, "unit": "ratio", "split": "test", "aggregation": "mean",
            "threshold": 0.8, "evaluation_protocol": "5-fold-cv", "source": "evaluation", "metadata": {"note": "ok"},
        }],
    })
    created = register_metrics(project_id=project_id, run_id=run_id, metrics=normalized, session_factory=session_factory)
    assert len(created) == 1
    metric = created[0]
    assert metric.name == "f1"
    assert metric.value == 0.87
    assert metric.unit == "ratio"
    assert metric.split == "test"
    assert metric.aggregation == "mean"
    assert metric.threshold == 0.8
    assert metric.evaluation_protocol == "5-fold-cv"
    assert metric.source == "evaluation"
    assert metric.metadata_ == {"note": "ok"}


def test_no_update_metric_function_exists_metrics_are_append_only():
    assert not hasattr(repository, "update_metric")


def test_repository_level_finiteness_guard_on_threshold_defense_in_depth(session_factory, project_id, experiment_id):
    """Even a direct repository.create_metric() call bypassing
    researchos.execution.metrics's own validation must still reject a
    non-finite threshold — a model-level @validates guard, matching
    the one already on `value`."""
    from researchos.db.errors import ValidationError
    from researchos.db.models import MetricValueType

    run_id = _make_run(session_factory, project_id, experiment_id)
    s = session_factory()
    try:
        with pytest.raises(ValidationError):
            repository.create_metric(
                s, project_id=project_id, run_id=run_id, name="m", value=1.0,
                value_type=MetricValueType.FLOAT, threshold=math.nan,
            )
    finally:
        s.close()


def test_repeated_metric_name_persists_as_separate_rows(session_factory, project_id, experiment_id):
    run_id = _make_run(session_factory, project_id, experiment_id)
    normalized = validate_metrics_manifest({
        "schema_version": "v1",
        "metrics": [
            {"name": "accuracy", "value": 0.8, "split": "train"},
            {"name": "accuracy", "value": 0.9, "split": "test"},
        ],
    })
    created = register_metrics(project_id=project_id, run_id=run_id, metrics=normalized, session_factory=session_factory)
    assert len(created) == 2
    s = session_factory()
    try:
        stored = repository.list_metrics(s, project_id, run_id=run_id, name="accuracy")
    finally:
        s.close()
    assert len(stored) == 2
