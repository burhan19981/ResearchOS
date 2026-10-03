"""The execution security boundary: everything that decides whether an
`ExecutionRequest` is safe to hand to an `ExecutionEngine`.

Design principle (see docs/PHASE8B1_EXECUTION_FOUNDATION.md's Security
Model section): the PRIMARY defense is structural, not a blacklist —
`PythonModuleTarget.arguments` is always passed to `subprocess` as an
argv list with `shell=False`, so shell metacharacters are inert data,
never syntax, regardless of what this module rejects. Every check below
is real, load-bearing validation (fail-closed allowlists for module
prefixes, python executables, and the working-directory root) — not
security theater layered on top of an unsafe primitive. The
metacharacter rejection in `validate_arguments` is deliberate
defense-in-depth on top of that primary defense, not a substitute for
it: it exists so a future contributor cannot silently switch back to a
shell string without an explicit test noticing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from .config import ExecutionConfig
from .contracts import PythonModuleTarget
from .errors import ArtifactPathEscapeError, InvalidExecutionTargetError, TimeoutConfigurationError

# A dotted Python module path: identifier(.identifier)* — no path
# separators, no leading dot, no "..", no whitespace, nothing shell
# ever needs to interpret.
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# Rejected outright wherever they appear in an argument, even though
# argv-list + shell=False already makes them inert — belt-and-suspenders
# so a future refactor toward a shell string trips a loud, explicit
# error instead of silently becoming exploitable.
_SHELL_METACHARACTERS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")

# Environment variable NAMES never forwarded to a child process even if
# a caller explicitly asks — mirrors
# researchos.specification.experiment_specifications's
# _FORBIDDEN_CONFIG_KEY_SUBSTRINGS convention, applied here to the
# execution layer's own surface (env var names) rather than imported
# from it, since Phase 8A's constant is private to that module and
# describes a different surface (configuration JSON keys).
_FORBIDDEN_ENV_VAR_SUBSTRINGS = (
    "api_key", "apikey", "secret", "password", "passwd", "token", "credential", "access_key", "private_key",
)


def validate_module_name(module: str, *, allowed_module_prefixes: tuple[str, ...]) -> str:
    if not isinstance(module, str) or not _MODULE_NAME_RE.match(module):
        raise InvalidExecutionTargetError(
            f"Execution target module {module!r} is not a valid dotted Python module path."
        )
    if not allowed_module_prefixes:
        raise InvalidExecutionTargetError(
            "No execution module prefixes are configured (RESEARCHOS_EXECUTION_ALLOWED_MODULE_PREFIXES); "
            "execution is fail-closed until an operator explicitly allowlists one."
        )
    if not any(module == prefix or module.startswith(prefix + ".") for prefix in allowed_module_prefixes):
        raise InvalidExecutionTargetError(
            f"Execution target module {module!r} is not under any allowed prefix {allowed_module_prefixes!r}."
        )
    return module


def validate_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    for arg in arguments:
        if not isinstance(arg, str):
            raise InvalidExecutionTargetError(f"Execution argument {arg!r} is not a string.")
        for bad in _SHELL_METACHARACTERS:
            if bad in arg:
                raise InvalidExecutionTargetError(
                    f"Execution argument {arg!r} contains disallowed sequence {bad!r}."
                )
    return arguments


def validate_python_executable(python_executable: str | None, *, allowed_python_executables: tuple[str, ...]) -> str:
    resolved = python_executable or (allowed_python_executables[0] if allowed_python_executables else None)
    if resolved is None or resolved not in allowed_python_executables:
        raise InvalidExecutionTargetError(
            f"Python executable {python_executable!r} is not in the allowed set {allowed_python_executables!r}."
        )
    return resolved


def validate_execution_target(target: PythonModuleTarget, *, config: ExecutionConfig) -> PythonModuleTarget:
    """Structural + allowlist validation of one `PythonModuleTarget`.
    Raises `InvalidExecutionTargetError` on any violation; returns the
    (unchanged) target on success so callers can chain this into
    request assembly."""
    validate_module_name(target.module, allowed_module_prefixes=config.allowed_module_prefixes)
    validate_arguments(target.arguments)
    validate_python_executable(target.python_executable, allowed_python_executables=config.allowed_python_executables)
    return target


def validate_working_directory(working_directory: str, *, config: ExecutionConfig) -> Path:
    """The resolved working directory must lie inside
    `config.allowed_execution_root` — rejects any `..` traversal or
    absolute-path escape attempt, even a valid-looking one."""
    root = config.allowed_execution_root.resolve()
    candidate = Path(working_directory).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise InvalidExecutionTargetError(
            f"Working directory {working_directory!r} resolves outside the allowed execution root {root}."
        ) from exc
    return candidate


def validate_artifact_path(path: str | Path, *, project_id: int, run_id: int, config: ExecutionConfig) -> Path:
    """The artifact-registration boundary: `path` must resolve strictly
    inside THIS `Run`'s own workspace subtree
    (`<allowed_execution_root>/<project_id>/<run_id>/`) — never merely
    inside the shared execution root, and never trusted as given.

    `Path.resolve()` both normalizes `..` segments AND follows symlinks
    for any path component that actually exists on disk, so a symlink
    planted inside the workspace that points outside it is caught by
    the exact same containment check as a literal `../../` traversal
    attempt or an absolute path naming another run's (or another
    project's) directory — `<root>/<project_id>/<run_id>/` is scoped
    per-run, not merely per-root, so a path under a *different*
    project's or run's own subtree is rejected here too, without any
    separate cross-project check.

    Enforced by `researchos.execution.artifacts.register_artifact`
    itself, unconditionally, regardless of caller — this is the
    artifact-registration boundary's own invariant, not something a
    well-behaved caller (e.g. the orchestrator) merely happens to
    uphold today. Engine-agnostic: `config.allowed_execution_root` is
    the same per-project-per-run workspace concept any future
    `ExecutionEngine` (Docker, remote GPU, ...) would register
    artifacts under, so this check never needs to change per backend.
    """
    root = (config.allowed_execution_root / str(project_id) / str(run_id)).resolve()
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ArtifactPathEscapeError(
            f"Artifact path {str(path)!r} resolves to {candidate}, which is outside the authorized workspace "
            f"for Run {run_id} in project {project_id} ({root}). Refusing to register it."
        ) from exc
    return candidate


def validate_timeout(timeout_seconds: int, *, config: ExecutionConfig) -> int:
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise TimeoutConfigurationError(f"timeout_seconds must be an int, got {timeout_seconds!r}.")
    if not (config.min_timeout_seconds <= timeout_seconds <= config.max_timeout_seconds):
        raise TimeoutConfigurationError(
            f"timeout_seconds={timeout_seconds} is outside the allowed range "
            f"[{config.min_timeout_seconds}, {config.max_timeout_seconds}]."
        )
    return timeout_seconds


def minimal_safe_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the child process environment from an explicit minimal
    allowlist — NEVER `os.environ` passed through wholesale. Includes
    only what a Python interpreter needs to actually start (`PATH`,
    and on Windows the handful of variables Python/DLL loading itself
    depends on) plus whatever `extra` the caller explicitly supplies,
    each still checked against `_FORBIDDEN_ENV_VAR_SUBSTRINGS` so a
    caller cannot smuggle a credential through `extra` either.
    """
    import os

    base_names = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT", "COMSPEC", "TEMP", "TMP")
    environment: dict[str, str] = {
        name: os.environ[name] for name in base_names if name in os.environ
    }
    for key, value in (extra or {}).items():
        if any(bad in key.lower() for bad in _FORBIDDEN_ENV_VAR_SUBSTRINGS):
            raise InvalidExecutionTargetError(
                f"Refusing to forward environment variable {key!r} to a child process — its name looks like it "
                "may hold a credential."
            )
        environment[key] = value
    return environment
