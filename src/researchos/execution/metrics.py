"""Structured metric collection: validates and ingests a metrics
manifest a process writes to its own output directory — never regex
parsing of stdout, never any LLM involvement.

Deliberately NOT stdout-based: Phase 8B-2 spec section 14 explicitly
forbids fragile regex parsing of process output as a metric source.
Instead, a process executed by `LocalPythonExecutor` MAY write a JSON
file at a fixed, well-known path inside its own working directory
(`<run workspace>/output/metrics.json` — see
`researchos.execution.workspace.RunWorkspace.metrics_manifest_path`);
`researchos.execution.orchestrator` checks for that file's existence
*after* the process has already exited and, only if present, validates
and ingests it via this module. A process that reports no metrics at
all is completely normal — most executions in Phase 8B-2's generic
foundation will not produce one.

Schema (`METRICS_MANIFEST_SCHEMA_VERSION`):

```json
{
  "schema_version": "v1",
  "metrics": [
    {
      "name": "accuracy",
      "value": 0.95,
      "unit": null,
      "split": "test",
      "aggregation": "mean",
      "threshold": null,
      "evaluation_protocol": null,
      "source": null,
      "metadata": {}
    }
  ]
}
```

Compatibility policy (explicit, not left ambiguous): both the
top-level manifest object and each metric entry are validated
**strictly** — an unrecognized top-level key, an unrecognized metric
key, a missing `schema_version`, or a `schema_version` this module does
not recognize all raise `MalformedMetricsManifestError`. A future
schema version may relax this; `v1` does not, because silently
ignoring an unrecognized field in a scientific record is exactly the
kind of silent data loss this project avoids elsewhere (see
`researchos.specification.experiment_specifications`'s equally strict
configuration validation).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import Metric, MetricValueType
from .errors import InvalidMetricValueError, MalformedMetricsManifestError

METRICS_MANIFEST_SCHEMA_VERSION = "v1"

_TOP_LEVEL_KEYS = frozenset({"schema_version", "metrics"})
_METRIC_KEYS = frozenset({
    "name", "value", "unit", "split", "aggregation", "threshold", "evaluation_protocol", "source", "metadata",
})
_REQUIRED_METRIC_KEYS = frozenset({"name", "value"})


def _require_finite(value: Any, *, field: str, metric_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidMetricValueError(f"Metric {metric_name!r}: {field!r} must be a number, got {value!r}.")
    if not math.isfinite(value):
        raise InvalidMetricValueError(
            f"Metric {metric_name!r}: {field!r} must be finite (NaN/Infinity are rejected by policy), got {value!r}."
        )
    return float(value)


def validate_metrics_manifest(data: Any) -> list[dict[str, Any]]:
    """Validate a parsed metrics manifest object. Returns a list of
    normalized metric dicts (all optional keys present, defaulted to
    `None`/`{}`) on success. Raises `MalformedMetricsManifestError` for
    any structural violation, `InvalidMetricValueError` for a
    non-finite or wrongly-typed `value`/`threshold`."""
    if not isinstance(data, dict):
        raise MalformedMetricsManifestError("Metrics manifest must be a JSON object.")
    unknown_top_level = set(data.keys()) - _TOP_LEVEL_KEYS
    if unknown_top_level:
        raise MalformedMetricsManifestError(f"Metrics manifest has unrecognized top-level key(s): {sorted(unknown_top_level)}.")
    schema_version = data.get("schema_version")
    if schema_version != METRICS_MANIFEST_SCHEMA_VERSION:
        raise MalformedMetricsManifestError(
            f"Metrics manifest 'schema_version' must be {METRICS_MANIFEST_SCHEMA_VERSION!r}, got {schema_version!r}."
        )
    raw_metrics = data.get("metrics")
    if not isinstance(raw_metrics, list):
        raise MalformedMetricsManifestError("Metrics manifest 'metrics' must be a JSON array.")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_metrics):
        if not isinstance(entry, dict):
            raise MalformedMetricsManifestError(f"metrics[{index}] must be a JSON object.")
        unknown_keys = set(entry.keys()) - _METRIC_KEYS
        if unknown_keys:
            raise MalformedMetricsManifestError(f"metrics[{index}] has unrecognized key(s): {sorted(unknown_keys)}.")
        missing_keys = _REQUIRED_METRIC_KEYS - set(entry.keys())
        if missing_keys:
            raise MalformedMetricsManifestError(f"metrics[{index}] is missing required key(s): {sorted(missing_keys)}.")

        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            raise MalformedMetricsManifestError(f"metrics[{index}]['name'] must be a non-blank string.")

        raw_value = entry["value"]
        value = _require_finite(raw_value, field="value", metric_name=name)
        value_type = MetricValueType.INTEGER if (isinstance(raw_value, int) and not isinstance(raw_value, bool)) else MetricValueType.FLOAT

        threshold = entry.get("threshold")
        if threshold is not None:
            threshold = _require_finite(threshold, field="threshold", metric_name=name)

        for str_field in ("unit", "split", "aggregation", "evaluation_protocol", "source"):
            if entry.get(str_field) is not None and not isinstance(entry.get(str_field), str):
                raise MalformedMetricsManifestError(f"metrics[{index}][{str_field!r}] must be a string or null.")

        metadata = entry.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise MalformedMetricsManifestError(f"metrics[{index}]['metadata'] must be a JSON object or null.")

        normalized.append({
            "name": name,
            "value": value,
            "value_type": value_type,
            "unit": entry.get("unit"),
            "split": entry.get("split"),
            "aggregation": entry.get("aggregation"),
            "threshold": threshold,
            "evaluation_protocol": entry.get("evaluation_protocol"),
            "source": entry.get("source"),
            "metadata": metadata,
        })
    return normalized


def load_metrics_manifest(path: str | Path) -> Optional[list[dict[str, Any]]]:
    """Returns `None` if `path` does not exist (no metrics reported —
    a completely normal outcome, never an error). Raises
    `MalformedMetricsManifestError` if the file exists but is not
    valid JSON, or fails `validate_metrics_manifest`."""
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        raw_text = file_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedMetricsManifestError(f"Metrics manifest at {file_path} is not valid JSON: {exc}") from exc
    return validate_metrics_manifest(data)


def register_metrics(
    *,
    project_id: int,
    run_id: int,
    metrics: list[dict[str, Any]],
    source_artifact_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
) -> list[Metric]:
    """Persist already-validated, normalized metric dicts (as returned
    by `validate_metrics_manifest`/`load_metrics_manifest`) as `Metric`
    rows. Append-only — see `Metric`'s own docstring."""
    created_ids: list[int] = []
    with session_scope(session_factory) as session:
        for entry in metrics:
            metric = repository.create_metric(
                session,
                project_id=project_id,
                run_id=run_id,
                name=entry["name"],
                value=entry["value"],
                value_type=entry["value_type"],
                unit=entry.get("unit"),
                split=entry.get("split"),
                aggregation=entry.get("aggregation"),
                threshold=entry.get("threshold"),
                evaluation_protocol=entry.get("evaluation_protocol"),
                source=entry.get("source"),
                source_artifact_id=source_artifact_id,
                metadata=entry.get("metadata"),
            )
            created_ids.append(metric.id)

    with session_scope(session_factory) as session:
        return [repository.get_metric(session, metric_id) for metric_id in created_ids]
