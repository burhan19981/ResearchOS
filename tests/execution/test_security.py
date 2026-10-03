"""Security boundary: shell injection attempts, path traversal,
arbitrary executable attempts, environment-variable leakage — plus
AST-based static verification that no shell=True / os.system /
subprocess-with-string / provider-SDK import exists anywhere in
`researchos.execution`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from researchos.execution.config import ExecutionConfig
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.errors import InvalidExecutionTargetError
from researchos.execution.security import (
    minimal_safe_environment,
    validate_arguments,
    validate_execution_target,
    validate_module_name,
    validate_python_executable,
    validate_working_directory,
)

_CONFIG = ExecutionConfig(allowed_module_prefixes=("tests.execution",))


# --- shell injection / malicious module or argument attempts ---------------


@pytest.mark.parametrize("malicious_module", [
    "os; rm -rf /", "os && del C:\\", "tests.execution._local_target && echo pwned",
    "../../etc/passwd", "tests.execution.__init__; import os", "tests/execution/_local_target",
    "", "   ", "tests..execution", ".tests.execution",
])
def test_rejects_malicious_module_names(malicious_module):
    with pytest.raises(InvalidExecutionTargetError):
        validate_module_name(malicious_module, allowed_module_prefixes=("tests.execution",))


@pytest.mark.parametrize("malicious_arg", [
    "&& rm -rf /", "; del C:\\", "| cat /etc/passwd", "> /etc/passwd", "< /etc/shadow",
    "$(whoami)", "`whoami`", "arg1\nrm -rf /",
])
def test_rejects_shell_metacharacters_in_arguments(malicious_arg):
    with pytest.raises(InvalidExecutionTargetError):
        validate_arguments(("--flag", malicious_arg))


def test_rejects_module_not_in_allowlist():
    with pytest.raises(InvalidExecutionTargetError):
        validate_execution_target(
            PythonModuleTarget(module="subprocess", arguments=()), config=_CONFIG,
        )


def test_rejects_arbitrary_python_executable():
    with pytest.raises(InvalidExecutionTargetError):
        validate_python_executable("C:\\Windows\\System32\\cmd.exe", allowed_python_executables=("C:\\python.exe",))


def test_accepts_allowed_python_executable():
    assert validate_python_executable("C:\\python.exe", allowed_python_executables=("C:\\python.exe",)) == "C:\\python.exe"


# --- path traversal ---------------------------------------------------------


def test_rejects_working_directory_path_traversal(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "allowed")
    (config.allowed_execution_root).mkdir(parents=True)
    escaped = tmp_path / "allowed" / ".." / "escaped"
    with pytest.raises(InvalidExecutionTargetError):
        validate_working_directory(str(escaped), config=config)


def test_rejects_working_directory_entirely_outside_root(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "allowed")
    (config.allowed_execution_root).mkdir(parents=True)
    outside = tmp_path / "somewhere_else"
    with pytest.raises(InvalidExecutionTargetError):
        validate_working_directory(str(outside), config=config)


def test_accepts_working_directory_inside_root(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "allowed")
    inside = tmp_path / "allowed" / "run_1"
    inside.mkdir(parents=True)
    resolved = validate_working_directory(str(inside), config=config)
    assert resolved == inside.resolve()


# --- environment variable leakage -------------------------------------------


@pytest.mark.parametrize("secret_key", ["API_KEY", "aws_secret_access_key", "DB_PASSWORD", "AUTH_TOKEN", "PRIVATE_KEY"])
def test_minimal_safe_environment_refuses_secret_shaped_extra_vars(secret_key):
    with pytest.raises(InvalidExecutionTargetError):
        minimal_safe_environment({secret_key: "sk-fake-value"})


def test_minimal_safe_environment_never_forwards_os_environ_wholesale(monkeypatch):
    monkeypatch.setenv("SOME_RANDOM_SECRET_LOOKING_TOKEN", "should-not-appear")
    env = minimal_safe_environment()
    assert "SOME_RANDOM_SECRET_LOOKING_TOKEN" not in env


def test_minimal_safe_environment_allows_explicit_benign_extras():
    env = minimal_safe_environment({"PYTHONPATH": "C:\\synthetic-project"})
    assert env["PYTHONPATH"] == "C:\\synthetic-project"


# --- static AST verification -------------------------------------------------

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "researchos" / "execution"


def _iter_source_files():
    return sorted(_PACKAGE_ROOT.glob("*.py"))


def test_package_never_uses_shell_true():
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False, (
                    f"{path.name} passes shell= as something other than a literal False"
                )


def test_package_never_calls_os_system_or_eval_exec():
    forbidden_names = {"eval", "exec", "compile"}
    forbidden_attrs = {("os", "system"), ("os", "popen"), ("subprocess", "call")}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in forbidden_names:
                raise AssertionError(f"{path.name} calls forbidden '{func.id}'")
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if (func.value.id, func.attr) in forbidden_attrs:
                    raise AssertionError(f"{path.name} calls forbidden '{func.value.id}.{func.attr}'")


def test_package_never_imports_provider_sdks_directly():
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in ("anthropic", "openai"), (
                        f"{path.name} imports provider SDK '{alias.name}' directly"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in ("anthropic", "openai"), (
                    f"{path.name} imports from provider SDK '{node.module}' directly"
                )


def test_only_local_executor_and_git_provenance_and_environment_snapshot_import_subprocess():
    allowed = {"local_executor.py", "git_provenance.py", "environment_snapshot.py"}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_subprocess = any(
            (isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "subprocess")
            for node in ast.walk(tree)
        )
        if imports_subprocess:
            assert path.name in allowed, f"{path.name} imports subprocess but is not in the allowed set {allowed}"


# --- Phase 8B-2: artifact/metric project isolation (unauthorized access) ---


def test_cross_project_metric_creation_rejected(session_factory, project_id, second_project_id, experiment_id):
    from researchos.db import repository
    from researchos.db.errors import NotFoundError
    from researchos.db.models import ExecutionBackend, MetricValueType

    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        s.commit()
        run_id = run.id
    finally:
        s.close()

    s = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.create_metric(
                s, project_id=second_project_id, run_id=run_id, name="accuracy", value=0.9,
                value_type=MetricValueType.FLOAT,
            )
    finally:
        s.close()


def test_metrics_list_is_project_scoped(session_factory, project_id, second_project_id, experiment_id):
    from researchos.db import repository
    from researchos.db.models import ExecutionBackend, MetricValueType

    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        repository.create_metric(
            s, project_id=project_id, run_id=run.id, name="accuracy", value=0.9, value_type=MetricValueType.FLOAT,
        )
        s.commit()
    finally:
        s.close()

    s = session_factory()
    try:
        visible_from_other_project = repository.list_metrics(s, second_project_id)
    finally:
        s.close()
    assert visible_from_other_project == []


def test_stdout_stderr_manifest_paths_never_escape_the_run_workspace(tmp_path):
    from researchos.execution.config import ExecutionConfig
    from researchos.execution.workspace import prepare_run_workspace

    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace = prepare_run_workspace(1, 1, config=config)
    for path in (workspace.stdout_path, workspace.stderr_path, workspace.result_manifest_path, workspace.metrics_manifest_path):
        assert path.resolve().is_relative_to(config.allowed_execution_root.resolve())
