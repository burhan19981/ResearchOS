"""The provider-neutral execution contract: `PythonModuleTarget`,
`ExecutionRequest`, `ExecutionResult`, `ExecutionEngine`.

Nothing in this module executes anything — these are pure data types
plus one `Protocol`. The security boundary this contract exists to
enforce is structural: `PythonModuleTarget` has no field that can hold
a shell string, so there is no `execute(command: str)`-shaped API for
an LLM (or anything else) to smuggle `"python train.py && del ..."`
through. `researchos.execution.security` validates every field before
an `ExecutionRequest` is ever handed to an `ExecutionEngine`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol

from ..db.models import RunStatus

# The only RunStatus values a completed execution attempt may report.
# CREATED/QUEUED/RUNNING are transient states the orchestrator itself
# manages; an ExecutionEngine only ever reports a terminal outcome.
TERMINAL_RUN_STATUSES = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT)


@dataclass(frozen=True)
class PythonModuleTarget:
    """A structured, non-shell execution target: run `python -m
    <module> <arguments...>`. There is no field anywhere in this
    dataclass capable of holding an arbitrary shell command — `module`
    must look like a dotted Python module path and `arguments` is a
    tuple of plain strings passed as an argv list, never concatenated
    into a shell string. See `researchos.execution.security.
    validate_execution_target` for the structural + allowlist checks
    applied before this is ever used.
    """

    module: str
    arguments: tuple[str, ...] = ()
    python_executable: Optional[str] = None


@dataclass(frozen=True)
class ExecutionRequest:
    """Everything a validated `ExecutionEngine` needs to execute one
    already-approved `Run`, without touching arbitrary project state
    itself — the orchestrator assembles this after preflight passes,
    and an `ExecutionEngine` implementation receives nothing beyond
    what is listed here.
    """

    run_id: int
    target: PythonModuleTarget
    working_directory: str
    environment: Mapping[str, str]
    timeout_seconds: int
    stdout_path: str
    stderr_path: str


@dataclass(frozen=True)
class ExecutionResult:
    """The structured outcome of one `ExecutionEngine.execute()` call.
    `status` is always one of `TERMINAL_RUN_STATUSES` — an
    `ExecutionEngine` never reports `CREATED`/`QUEUED`/`RUNNING`, those
    are orchestrator-managed pre/in-flight states. `metadata` is for
    genuinely engine-specific extra facts worth keeping (e.g. a
    container id for a future `DockerExecutor`) — the domain layer
    must not depend on its shape.
    """

    status: RunStatus
    exit_code: Optional[int]
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    stdout_reference: str
    stderr_reference: str
    failure_reason: Optional[str]
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_RUN_STATUSES:
            raise ValueError(f"ExecutionResult.status must be terminal, got {self.status!r}.")


class ExecutionEngine(Protocol):
    """The stable interface every executor implements.
    `LocalPythonExecutor` (this phase) is the only real implementation;
    `DockerExecutor`/`RemoteGPUExecutor`/`SlurmExecutor`/`CloudExecutor`
    are future adapters that implement this same `Protocol` — the
    domain/orchestrator layer depends only on this interface, never on
    any concrete executor's internals.
    """

    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
