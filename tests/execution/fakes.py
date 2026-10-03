"""FakeExecutionEngine: a deterministic, offline `ExecutionEngine` test
double. Never spawns a real process — every orchestration-level test
that does not specifically need to exercise `LocalPythonExecutor`
itself (see `test_execution_contract.py`) uses this instead, so the
vast majority of the suite runs without touching the OS at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from researchos.db.models import RunStatus
from researchos.execution.contracts import ExecutionEngine, ExecutionRequest, ExecutionResult


class FakeExecutionEngine(ExecutionEngine):
    """Configurable, deterministic: constructed with the exact
    `ExecutionResult` it should return (or a callable producing one),
    and records every `ExecutionRequest` it was called with for test
    assertions."""

    def __init__(self, result: Optional[ExecutionResult] = None) -> None:
        self._result = result
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        if self._result is not None:
            return self._result
        now = datetime.now(timezone.utc)
        return ExecutionResult(
            status=RunStatus.SUCCEEDED, exit_code=0, started_at=now, finished_at=now, duration_seconds=0.0,
            stdout_reference=request.stdout_path, stderr_reference=request.stderr_path, failure_reason=None,
            backend="fake",
        )


def make_result(
    status: RunStatus = RunStatus.SUCCEEDED, *, exit_code: Optional[int] = 0, failure_reason: Optional[str] = None,
    duration_seconds: float = 1.5, stdout_reference: str = "fake://stdout", stderr_reference: str = "fake://stderr",
) -> ExecutionResult:
    now = datetime.now(timezone.utc)
    return ExecutionResult(
        status=status, exit_code=exit_code, started_at=now, finished_at=now, duration_seconds=duration_seconds,
        stdout_reference=stdout_reference, stderr_reference=stderr_reference, failure_reason=failure_reason,
        backend="fake",
    )
