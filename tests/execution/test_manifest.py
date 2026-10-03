"""Result manifest generation: deterministic field ordering, artifact/
metric references included, no secrets, generated only after the Run
is terminal."""

from __future__ import annotations

from pathlib import Path

import json

from researchos.db import repository
from researchos.execution import approval as approval_module
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.manifest import RESULT_MANIFEST_SCHEMA_VERSION, build_result_manifest
from researchos.execution.orchestrator import execute_run, request_run


def _run_to_success(
    session_factory, project_id, experiment_id, spec_id, dataset_version_id, config, *, mode="metrics", extra_args=()
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", mode, *extra_args))
    run = request_run(
        project_id, experiment_id, spec_id, dataset_version_id, actor="agent:orchestrator", target=target,
        timeout_seconds=30, config=config, session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)
    return execute_run(
        run.id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )


def test_manifest_contains_full_provenance_chain(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    final_run = _run_to_success(
        session_factory, project_id, experiment_id, approved_experiment_specification_id,
        approved_dataset_version_id, execution_config,
    )
    s = session_factory()
    try:
        manifest = build_result_manifest(s, repository.get_run(s, final_run.id))
    finally:
        s.close()

    assert manifest["schema_version"] == RESULT_MANIFEST_SCHEMA_VERSION
    assert manifest["project_id"] == project_id
    assert manifest["experiment_id"] == experiment_id
    assert manifest["run_id"] == final_run.id
    assert manifest["specification"]["experiment_specification_id"] == approved_experiment_specification_id
    assert manifest["specification"]["configuration_hash"] == final_run.configuration_hash
    assert manifest["dataset"]["dataset_version_id"] == approved_dataset_version_id
    assert manifest["dataset"]["fingerprint"] == final_run.dataset_fingerprint
    assert manifest["environment_snapshot_id"] == final_run.environment_snapshot_id
    assert manifest["execution"]["status"] == "succeeded"
    assert manifest["execution"]["exit_code"] == 0
    assert manifest["researchos_version"]


def test_manifest_references_registered_artifacts_and_metrics(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    final_run = _run_to_success(
        session_factory, project_id, experiment_id, approved_experiment_specification_id,
        approved_dataset_version_id, execution_config, mode="metrics",
    )
    s = session_factory()
    try:
        manifest = build_result_manifest(s, repository.get_run(s, final_run.id))
    finally:
        s.close()

    artifact_names = {a["logical_name"] for a in manifest["artifacts"]}
    assert {"stdout", "stderr", "metrics_report"} <= artifact_names
    # The result_manifest artifact describing itself is excluded from its own body.
    assert "result_manifest" not in artifact_names

    metric_names = {m["name"] for m in manifest["metrics"]}
    assert {"accuracy", "epoch"} <= metric_names


def test_manifest_is_registered_as_an_artifact_and_written_to_disk(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    final_run = _run_to_success(
        session_factory, project_id, experiment_id, approved_experiment_specification_id,
        approved_dataset_version_id, execution_config,
    )
    s = session_factory()
    try:
        artifacts = repository.list_artifact_metadata(s, project_id, run_id=final_run.id)
    finally:
        s.close()
    manifest_artifacts = [a for a in artifacts if a.logical_name == "result_manifest"]
    assert len(manifest_artifacts) == 1
    manifest_artifact = manifest_artifacts[0]
    from pathlib import Path

    on_disk = json.loads(Path(manifest_artifact.reference).read_text())
    assert on_disk["run_id"] == final_run.id


def test_manifest_never_contains_secret_shaped_keys(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    final_run = _run_to_success(
        session_factory, project_id, experiment_id, approved_experiment_specification_id,
        approved_dataset_version_id, execution_config,
    )
    s = session_factory()
    try:
        manifest = build_result_manifest(s, repository.get_run(s, final_run.id))
    finally:
        s.close()
    serialized = json.dumps(manifest).lower()
    for forbidden in ("api_key", "secret", "password", "token", "credential", "private_key"):
        assert forbidden not in serialized


def test_manifest_json_is_deterministically_key_sorted(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    final_run = _run_to_success(
        session_factory, project_id, experiment_id, approved_experiment_specification_id,
        approved_dataset_version_id, execution_config,
    )
    s = session_factory()
    try:
        artifact = repository.get_artifact_metadata_by_logical_name(s, final_run.id, "result_manifest")
    finally:
        s.close()
    from pathlib import Path

    raw_text = Path(artifact.reference).read_text()
    parsed = json.loads(raw_text)
    reserialized = json.dumps(parsed, sort_keys=True, indent=2, default=str)
    assert raw_text == reserialized
