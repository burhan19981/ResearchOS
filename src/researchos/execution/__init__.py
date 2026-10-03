"""The ResearchOS execution foundation, actual-execution subsystem, and
research-experiment integration layer (Phase 8B-1 + Phase 8B-2 + Phase
8B-3).

Converts an approved `ExperimentSpecification` + approved `DatasetVersion`
into a fully-provenanced, human-approved, actually-executed `Run`, with
its artifacts, metrics, and a generated result manifest:

    Approved ExperimentSpecification (linked to its Experiment)
    -> create_run_from_specification() -> Run (CREATED, fully provenanced)
    -> prepare_run() [READY/BLOCKED, optional] -> Human Execution Approval
    -> execute_run() -> ExecutionEngine
    -> Run (terminal: SUCCEEDED / FAILED / CANCELLED / TIMEOUT)
    -> stdout/stderr artifacts, structured metrics (if reported),
       result manifest — all registered/generated automatically

Phase 8B-3 still does **not** implement any real research experiment —
no ML training, no inference, no GPU/CUDA/Docker/Slurm/cloud execution,
no domain-specific metric/model logic of any kind, and no PPE/FastViT/
RetinaNet/YOLO anywhere in the core. `LocalPythonExecutor` is the only
real `ExecutionEngine`, and it only ever runs `python -m <allowlisted
module> <args>` as a structured, non-shell subprocess; every other
executor named in the target architecture
(`DockerExecutor`/`RemoteGPUExecutor`/`SlurmExecutor`/`CloudExecutor`)
is an interface-only extension point, not implemented here.

A successful `Run` (`SUCCEEDED`) means only "the requested executable
process completed successfully" — never a scientific conclusion. That
judgment belongs to a later Analysis/Scientific Review phase this
package never performs (see docs/PHASE8B3_RESEARCH_EXPERIMENT_INTEGRATION.md's
Scientific-vs-Execution Semantics section).

This package is a direct continuation of the Phase 7/8A chain, not an
independent sibling — it reuses `researchos.planning.orchestration`,
`researchos.planning.errors`' generic types, and
`researchos.specification.fingerprint` directly rather than
duplicating them. See docs/PHASE8B1_EXECUTION_FOUNDATION.md,
docs/PHASE8B2_ACTUAL_EXECUTION_ARTIFACTS_METRICS.md, and
docs/PHASE8B3_RESEARCH_EXPERIMENT_INTEGRATION.md for the full design.
"""

from . import approval
from .artifacts import register_artifact
from .config import ExecutionConfig, load_execution_config
from .contracts import ExecutionEngine, ExecutionRequest, ExecutionResult, PythonModuleTarget
from .errors import (
    ArtifactPathEscapeError,
    ArtifactRegistrationError,
    CrossProjectReferenceError,
    DuplicateArtifactError,
    DuplicateRunError,
    ExecutionError,
    ExecutionNotApprovedError,
    InvalidExecutionTargetError,
    InvalidMetricValueError,
    InvalidRunStateError,
    MalformedMetricsManifestError,
    MissingArtifactFileError,
    MissingEntityError,
    ProvenanceError,
    SpecificationMissingDatasetVersionError,
    TimeoutConfigurationError,
    UnlinkedSpecificationError,
    UpstreamNotApprovedError,
)
from .hashing import sha256_file
from .integration import PrepareOutcome, create_run_from_specification, prepare_run
from .local_executor import LocalPythonExecutor
from .manifest import RESULT_MANIFEST_SCHEMA_VERSION, build_result_manifest, write_result_manifest
from .metrics import METRICS_MANIFEST_SCHEMA_VERSION, load_metrics_manifest, register_metrics, validate_metrics_manifest
from .orchestrator import execute_run, request_run
from .workspace import RunWorkspace, prepare_run_workspace

__all__ = [
    "approval",
    "ExecutionConfig",
    "load_execution_config",
    "ExecutionEngine",
    "ExecutionRequest",
    "ExecutionResult",
    "PythonModuleTarget",
    "LocalPythonExecutor",
    "request_run",
    "execute_run",
    "create_run_from_specification",
    "prepare_run",
    "PrepareOutcome",
    "register_artifact",
    "sha256_file",
    "RunWorkspace",
    "prepare_run_workspace",
    "RESULT_MANIFEST_SCHEMA_VERSION",
    "build_result_manifest",
    "write_result_manifest",
    "METRICS_MANIFEST_SCHEMA_VERSION",
    "validate_metrics_manifest",
    "load_metrics_manifest",
    "register_metrics",
    "ExecutionError",
    "MissingEntityError",
    "CrossProjectReferenceError",
    "UpstreamNotApprovedError",
    "ExecutionNotApprovedError",
    "InvalidExecutionTargetError",
    "InvalidRunStateError",
    "ProvenanceError",
    "TimeoutConfigurationError",
    "DuplicateRunError",
    "ArtifactRegistrationError",
    "MissingArtifactFileError",
    "DuplicateArtifactError",
    "ArtifactPathEscapeError",
    "InvalidMetricValueError",
    "MalformedMetricsManifestError",
    "UnlinkedSpecificationError",
    "SpecificationMissingDatasetVersionError",
]
