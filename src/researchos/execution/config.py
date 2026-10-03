"""Execution-layer configuration: the allowlists
`researchos.execution.security` enforces, and the root directory
`LocalPythonExecutor` is permitted to write output into.

Same convention as `researchos.db.config`: read from environment
variables (optionally populated from a local `.env` — never
committed), fail closed with a safe, small default rather than an
open one. Nothing here is a secret — module/executable allowlists and
a directory path are not credentials — but the same "never hardcode,
always overridable per-environment" discipline applies.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..db.config import load_dotenv_if_present

# src/researchos/execution/config.py -> parents[3] is the repository root
# (same convention as researchos.db.config / researchos.db.migrate, each
# of which computes its own copy rather than importing another module's
# private module-root constant).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXECUTION_ROOT = _PROJECT_ROOT / "data" / "execution_runs"


def _get_csv_env(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class ExecutionConfig:
    # Fail-closed by default: no module may execute until an operator
    # explicitly configures which module prefixes are allowed. This
    # phase never populates this list with anything itself — it ships
    # no real training/inference module for anything to point at.
    allowed_module_prefixes: tuple[str, ...] = field(default_factory=tuple)
    # Only the interpreter actually running ResearchOS, unless an
    # operator explicitly widens this.
    allowed_python_executables: tuple[str, ...] = field(default_factory=lambda: (sys.executable,))
    # Every Run's working directory (and, derived from it, its
    # stdout/stderr files) must resolve inside this root — never
    # outside it, even via `..` traversal.
    allowed_execution_root: Path = DEFAULT_EXECUTION_ROOT
    min_timeout_seconds: int = 1
    max_timeout_seconds: int = 24 * 60 * 60


def load_execution_config() -> ExecutionConfig:
    load_dotenv_if_present()
    allowed_module_prefixes = _get_csv_env("RESEARCHOS_EXECUTION_ALLOWED_MODULE_PREFIXES")
    allowed_python_executables = _get_csv_env("RESEARCHOS_EXECUTION_ALLOWED_PYTHON_EXECUTABLES") or (sys.executable,)
    root_override = os.environ.get("RESEARCHOS_EXECUTION_ROOT")
    allowed_execution_root = Path(root_override).resolve() if root_override else DEFAULT_EXECUTION_ROOT
    return ExecutionConfig(
        allowed_module_prefixes=allowed_module_prefixes,
        allowed_python_executables=allowed_python_executables,
        allowed_execution_root=allowed_execution_root,
    )
