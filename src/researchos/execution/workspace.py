"""The deterministic, project-isolated, run-isolated execution
workspace on disk.

Layout (relative to `ExecutionConfig.allowed_execution_root`):

    <allowed_execution_root>/<project_id>/<run_id>/
        input/        # reserved for future use — nothing writes here in Phase 8B-2
        output/        # LocalPythonExecutor's cwd; a process's own outputs land here
        logs/          # stdout.log, stderr.log
        artifacts/     # any other files ResearchOS itself registers as artifacts
        manifests/     # the generated result_manifest.json

Every path this module returns is validated (via
`researchos.execution.security.validate_working_directory`) to resolve
strictly inside `allowed_execution_root` — the `<project_id>/<run_id>`
segments are always built from trusted, already-loaded `Run` columns
(integers from the database), never from caller-supplied strings, so
there is no path-traversal surface here: an attacker would need to
control `Run.project_id`/`Run.id` themselves, which only
`researchos.db.repository.create_run` (itself preflight-validated) can
set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ExecutionConfig
from .security import validate_working_directory


@dataclass(frozen=True)
class RunWorkspace:
    root: Path
    input_dir: Path
    output_dir: Path
    logs_dir: Path
    artifacts_dir: Path
    manifests_dir: Path

    @property
    def stdout_path(self) -> Path:
        return self.logs_dir / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.logs_dir / "stderr.log"

    @property
    def result_manifest_path(self) -> Path:
        return self.manifests_dir / "result_manifest.json"

    @property
    def metrics_manifest_path(self) -> Path:
        return self.output_dir / "metrics.json"


def prepare_run_workspace(project_id: int, run_id: int, *, config: ExecutionConfig) -> RunWorkspace:
    """Create (if needed) and return the validated, isolated on-disk
    workspace for one `Run`. Never overwrites another run's
    directory — `<project_id>/<run_id>` is unique per `Run` row by
    construction (`run_id` is a database-assigned primary key)."""
    root = validate_working_directory(
        str(config.allowed_execution_root / str(project_id) / str(run_id)), config=config
    )
    workspace = RunWorkspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        logs_dir=root / "logs",
        artifacts_dir=root / "artifacts",
        manifests_dir=root / "manifests",
    )
    for directory in (workspace.input_dir, workspace.output_dir, workspace.logs_dir, workspace.artifacts_dir, workspace.manifests_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace
