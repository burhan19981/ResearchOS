"""The execution result manifest: one deterministic, machine-readable
JSON document summarizing everything needed to understand and attempt
to reproduce a completed `Run` — generated once, after the `Run`
reaches a terminal state, and registered as its own immutable
`RESULT_MANIFEST` artifact.

Never contains secrets and never dumps arbitrary environment
variables — every field here is either an id, a version, a hash, a
timestamp, or a reference to something already independently recorded
(an `ArtifactMetadata`/`Metric` row). `json.dumps(..., sort_keys=True,
indent=2)` keeps the field ordering deterministic; the values
themselves (timestamps, durations) are not forced to be deterministic,
since they genuinely differ run to run by nature — see the module's
Phase 8B-2 doc section for the full reasoning on "deterministic as much
as practical."
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import __version__ as researchos_version
from ..db import repository
from ..db.models import ArtifactMetadata, Metric, Run

RESULT_MANIFEST_SCHEMA_VERSION = "v1"


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None


def _artifact_entry(artifact: ArtifactMetadata) -> dict[str, Any]:
    return {
        "logical_name": artifact.logical_name,
        "artifact_type": artifact.artifact_type.value,
        "reference": artifact.reference,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.content_hash,
        "mime_type": artifact.mime_type,
    }


def _metric_entry(metric: Metric) -> dict[str, Any]:
    return {
        "name": metric.name,
        "value": metric.value,
        "value_type": metric.value_type.value,
        "unit": metric.unit,
        "split": metric.split,
        "aggregation": metric.aggregation,
        "threshold": metric.threshold,
        "evaluation_protocol": metric.evaluation_protocol,
        "source": metric.source,
    }


def build_result_manifest(session: Session, run: Run) -> dict[str, Any]:
    """Assemble the manifest dict for an already-terminal `Run`. Pure
    (no I/O) — `write_result_manifest` handles writing it to disk."""
    artifacts = repository.list_artifact_metadata(session, run.project_id, run_id=run.id)
    metrics = repository.list_metrics(session, run.project_id, run_id=run.id)

    return {
        "schema_version": RESULT_MANIFEST_SCHEMA_VERSION,
        "researchos_version": researchos_version,
        "project_id": run.project_id,
        "experiment_id": run.experiment_id,
        "run_id": run.id,
        "specification": {
            "experiment_specification_id": run.experiment_specification_id,
            "version": run.experiment_specification_version,
            "status_at_execution": run.experiment_specification_status_at_execution,
            "configuration_hash": run.configuration_hash,
        },
        "dataset": {
            "dataset_version_id": run.dataset_version_id,
            "version": run.dataset_version_version,
            "status_at_execution": run.dataset_version_status_at_execution,
            "fingerprint": run.dataset_fingerprint,
        },
        "code_provenance": {
            "repository": run.code_repository,
            "commit": run.code_commit,
            "branch": run.code_branch,
            "working_tree_clean": run.working_tree_clean,
            "unavailable_reason": run.code_provenance_unavailable_reason,
        },
        "environment_snapshot_id": run.environment_snapshot_id,
        "execution": {
            "backend": run.execution_backend.value,
            "target": run.execution_target,
            "seed": run.seed,
            "timeout_seconds": run.timeout_seconds,
            "started_at": _isoformat(run.started_at),
            "finished_at": _isoformat(run.finished_at),
            "duration_seconds": run.duration_seconds,
            "exit_code": run.exit_code,
            "status": run.status.value,
            "failure_reason": run.failure_reason,
        },
        "artifacts": [_artifact_entry(a) for a in artifacts if a.artifact_type.value != "result_manifest"],
        "metrics": [_metric_entry(m) for m in metrics],
    }


def write_result_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(manifest, sort_keys=True, indent=2, default=str), encoding="utf-8")
    return file_path
