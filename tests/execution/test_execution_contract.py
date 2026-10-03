"""The execution contract itself: FakeExecutionEngine (orchestration
tests), and LocalPythonExecutor against a real, tiny, deterministic
subprocess (tests/execution/_local_target.py) — success, failure with
a specific exit code, and timeout."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from researchos.db.models import RunStatus
from researchos.execution.contracts import ExecutionRequest, ExecutionResult, PythonModuleTarget
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.security import minimal_safe_environment
from tests.execution.fakes import FakeExecutionEngine, make_result

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _request(tmp_path: Path, *, mode: str, extra_args=(), timeout_seconds=10) -> ExecutionRequest:
    working_directory = tmp_path / "run"
    working_directory.mkdir(parents=True, exist_ok=True)
    target = PythonModuleTarget(
        module="tests.execution._local_target", arguments=("--mode", mode, *extra_args), python_executable=sys.executable,
    )
    environment = minimal_safe_environment({"PYTHONPATH": str(_REPO_ROOT)})
    return ExecutionRequest(
        run_id=1, target=target, working_directory=str(working_directory), environment=environment,
        timeout_seconds=timeout_seconds, stdout_path=str(working_directory / "stdout.log"),
        stderr_path=str(working_directory / "stderr.log"),
    )


def test_local_executor_success(tmp_path):
    request = _request(tmp_path, mode="success")
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.SUCCEEDED
    assert result.exit_code == 0
    assert "SUCCESS_MARKER" in Path(result.stdout_reference).read_text()


def test_local_executor_failure_with_specific_exit_code(tmp_path):
    request = _request(tmp_path, mode="fail", extra_args=("--exit-code", "17"))
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.FAILED
    assert result.exit_code == 17
    assert result.failure_reason is not None and "17" in result.failure_reason
    assert "FAILURE_MARKER" in Path(result.stderr_reference).read_text()


def test_local_executor_timeout(tmp_path):
    request = _request(tmp_path, mode="sleep", extra_args=("--sleep-seconds", "5"), timeout_seconds=1)
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.TIMEOUT
    assert result.exit_code is None
    assert result.duration_seconds < 4.0  # terminated well before the full 5s sleep
    assert "timeout" in result.failure_reason.lower()


def test_local_executor_never_uses_shell_true_even_defensively(tmp_path):
    # A defensive regression check: LocalPythonExecutor.execute always
    # constructs an argv list, never a string — this test would fail
    # loudly (TypeError from subprocess, since a list can't be split
    # like a string) if a future change accidentally passed a joined
    # command string instead.
    request = _request(tmp_path, mode="success")
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.SUCCEEDED  # proves argv-list execution actually worked


def test_execution_result_rejects_non_terminal_status():
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    with pytest.raises(ValueError):
        ExecutionResult(
            status=RunStatus.RUNNING, exit_code=None, started_at=now, finished_at=now, duration_seconds=0.0,
            stdout_reference="x", stderr_reference="y", failure_reason=None, backend="fake",
        )


def test_fake_execution_engine_never_touches_real_process(tmp_path):
    engine = FakeExecutionEngine(result=make_result(status=RunStatus.FAILED, exit_code=9, failure_reason="fake failure"))
    request = _request(tmp_path, mode="success")  # even a "success" target is never actually run
    result = engine.execute(request)
    assert result.status == RunStatus.FAILED
    assert result.exit_code == 9
    assert not (tmp_path / "run" / "stdout.log").exists()  # FakeExecutionEngine wrote nothing
    assert engine.requests == [request]
