"""`LocalPythonExecutor`: the one real `ExecutionEngine` implementation
in Phase 8B-1.

Executes exactly `[python_executable, "-m", module, *arguments]` via
`subprocess.run(..., shell=False)` — never a shell string, never
`shell=True`, never string concatenation of untrusted input. The
process's environment is whatever `ExecutionRequest.environment`
supplies (the orchestrator builds this via
`researchos.execution.security.minimal_safe_environment` — never
`os.environ` passed straight through). stdout/stderr are written to
the files `ExecutionRequest.stdout_path`/`stderr_path` name, never held
only in memory and never persisted to the database.

This module re-validates the target defensively at the start of
`execute()` (see `_defensive_revalidate`) even though the orchestrator
already validates via `researchos.execution.security` before ever
constructing an `ExecutionRequest` — fail-closed if some future caller
ever manages to invoke this executor directly, bypassing the
orchestrator.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ExecutionEngine, ExecutionRequest, ExecutionResult
from .errors import InvalidExecutionTargetError
from ..db.models import RunStatus

_MODULE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")


def _defensive_revalidate(request: ExecutionRequest) -> None:
    module = request.target.module
    if not module or any(c not in _MODULE_NAME_CHARS for c in module) or module.startswith(".") or ".." in module:
        raise InvalidExecutionTargetError(f"LocalPythonExecutor refuses malformed module name {module!r}.")
    for arg in request.target.arguments:
        if not isinstance(arg, str):
            raise InvalidExecutionTargetError(f"LocalPythonExecutor refuses non-string argument {arg!r}.")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LocalPythonExecutor(ExecutionEngine):
    """Runs one `PythonModuleTarget` as a local, controlled child
    process. Not a general-purpose shell runner — see module docstring."""

    backend_name = "local_python"

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        _defensive_revalidate(request)

        python_executable = request.target.python_executable or sys.executable
        argv = [python_executable, "-m", request.target.module, *request.target.arguments]

        stdout_path = Path(request.stdout_path)
        stderr_path = Path(request.stderr_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        started_at = _utcnow()
        try:
            with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
                completed = subprocess.run(
                    argv,
                    cwd=request.working_directory,
                    env=dict(request.environment),
                    timeout=request.timeout_seconds,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                )
            finished_at = _utcnow()
            duration = (finished_at - started_at).total_seconds()
            status = RunStatus.SUCCEEDED if completed.returncode == 0 else RunStatus.FAILED
            failure_reason = None if completed.returncode == 0 else f"Process exited with code {completed.returncode}."
            return ExecutionResult(
                status=status,
                exit_code=completed.returncode,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                stdout_reference=str(stdout_path),
                stderr_reference=str(stderr_path),
                failure_reason=failure_reason,
                backend=self.backend_name,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run() already terminated (and, on timeout,
            # kills) the child process before raising this — nothing
            # further to clean up. stdout/stderr written so far remain
            # on disk at the same reference paths.
            finished_at = _utcnow()
            duration = (finished_at - started_at).total_seconds()
            return ExecutionResult(
                status=RunStatus.TIMEOUT,
                exit_code=None,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                stdout_reference=str(stdout_path),
                stderr_reference=str(stderr_path),
                failure_reason=f"Execution exceeded its {request.timeout_seconds}s timeout and was terminated.",
                backend=self.backend_name,
            )
        except OSError as exc:
            # The process never actually started (e.g. python_executable
            # does not exist, or the OS refused to launch it) — a
            # controlled failure, not an uncaught exception left to
            # propagate and strand the Run in RUNNING. exit_code stays
            # None (the process never ran to produce one), distinct from
            # a real non-zero exit.
            finished_at = _utcnow()
            duration = (finished_at - started_at).total_seconds()
            return ExecutionResult(
                status=RunStatus.FAILED,
                exit_code=None,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=duration,
                stdout_reference=str(stdout_path),
                stderr_reference=str(stderr_path),
                failure_reason=f"Process launch failed: {exc}",
                backend=self.backend_name,
            )
