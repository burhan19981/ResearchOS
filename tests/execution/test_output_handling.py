"""stdout/stderr capture: empty output, large output (never held
entirely in memory — streamed straight to file by LocalPythonExecutor),
and binary-safe capture."""

from __future__ import annotations

import sys
from pathlib import Path

from researchos.db.models import RunStatus
from researchos.execution.contracts import ExecutionRequest, PythonModuleTarget
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.security import minimal_safe_environment

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _request(tmp_path: Path, *, mode: str, extra_args=(), timeout_seconds=30) -> ExecutionRequest:
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


def test_empty_stdout_and_stderr_produce_empty_but_present_files(tmp_path):
    request = _request(tmp_path, mode="echo", extra_args=("--message", ""))
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.SUCCEEDED
    stdout_path = Path(result.stdout_reference)
    stderr_path = Path(result.stderr_reference)
    assert stdout_path.is_file()
    assert stderr_path.is_file()
    assert stderr_path.read_bytes() == b""


def test_large_stdout_is_fully_captured_without_truncation(tmp_path):
    lines = 20000
    request = _request(tmp_path, mode="large_output", extra_args=("--lines", str(lines)))
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.SUCCEEDED
    content = Path(result.stdout_reference).read_text()
    written_lines = content.splitlines()
    assert len(written_lines) == lines
    assert written_lines[0].startswith("line 00000000")
    assert written_lines[-1].startswith(f"line {lines - 1:08d}")


def test_binary_stdout_is_captured_byte_for_byte(tmp_path):
    request = _request(tmp_path, mode="binary_stdout")
    result = LocalPythonExecutor().execute(request)
    assert result.status == RunStatus.SUCCEEDED
    content = Path(result.stdout_reference).read_bytes()
    assert content == bytes(range(256)) * 4
