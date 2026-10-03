"""Security tests for the dataset & experiment specification layer
(Phase 8A): secret redaction in configuration, no credentials persisted,
and no arbitrary execution capability anywhere in the package.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from researchos.specification.errors import ConfigurationValidationError
from researchos.specification.experiment_specifications import _validate_configuration

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "researchos" / "specification"

# Any call to one of these names anywhere in the package's source would
# constitute an arbitrary-execution capability this phase must not have.
_FORBIDDEN_CALL_NAMES = {
    "system", "popen", "spawn", "spawnl", "spawnv", "exec", "eval", "compile",
}
_FORBIDDEN_MODULE_ATTRS = {
    ("subprocess", "run"), ("subprocess", "call"), ("subprocess", "Popen"),
    ("subprocess", "check_call"), ("subprocess", "check_output"),
    ("os", "system"), ("os", "popen"), ("os", "spawnl"), ("os", "spawnv"),
    ("shutil", "which"),  # not forbidden per se, but flagged for review if ever added
}


def test_configuration_rejects_top_level_secret_like_key():
    with pytest.raises(ConfigurationValidationError):
        _validate_configuration({"api_key": "sk-fake"})


def test_configuration_rejects_nested_secret_like_key():
    with pytest.raises(ConfigurationValidationError):
        _validate_configuration({"training": {"auth": {"password": "hunter2"}}})


def test_configuration_rejects_secret_like_key_inside_a_list():
    with pytest.raises(ConfigurationValidationError):
        _validate_configuration({"steps": [{"name": "a"}, {"access_key": "AKIAFAKE"}]})


@pytest.mark.parametrize("benign_key", ["seed", "learning_rate_schedule", "hardware_profile", "notes"])
def test_configuration_accepts_ordinary_keys(benign_key):
    result = _validate_configuration({benign_key: "some value", "nested": {"count": 3}})
    assert benign_key in result


def test_configuration_must_be_an_object():
    with pytest.raises(ConfigurationValidationError):
        _validate_configuration(["not", "an", "object"])
    with pytest.raises(ConfigurationValidationError):
        _validate_configuration("also not an object")


# --- No arbitrary execution: static source inspection ------------------------


def _iter_source_files():
    return sorted(_PACKAGE_ROOT.glob("*.py"))


def test_package_never_imports_subprocess_os_or_shell_execution_modules():
    forbidden_modules = {"subprocess", "shlex", "pty", "multiprocessing"}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules, (
                        f"{path.name} imports forbidden module '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module.split(".")[0] not in forbidden_modules, (
                        f"{path.name} imports from forbidden module '{node.module}'"
                    )


def test_package_never_calls_exec_eval_or_process_spawning_functions():
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALL_NAMES:
                raise AssertionError(f"{path.name} calls forbidden function '{func.id}'")
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and (func.value.id, func.attr) in _FORBIDDEN_MODULE_ATTRS:
                    raise AssertionError(f"{path.name} calls forbidden '{func.value.id}.{func.attr}'")


def test_package_never_opens_arbitrary_files_or_network_sockets():
    """DatasetValidator/fingerprinting must operate purely on supplied
    in-memory data — no `open()`, no `socket`, no `urllib`/`requests`
    anywhere in this package."""
    forbidden_names = {"open", "socket"}
    forbidden_modules = {"socket", "urllib", "requests", "http", "ftplib"}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_names, f"{path.name} calls forbidden '{node.func.id}()'"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules, (
                        f"{path.name} imports forbidden module '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_modules, (
                    f"{path.name} imports from forbidden module '{node.module}'"
                )


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
