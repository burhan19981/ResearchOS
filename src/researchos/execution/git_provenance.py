"""Provider-neutral Git code provenance: commit SHA, branch, and
working-tree cleanliness for one repository path — via fixed,
hardcoded `git` argv only.

Every `subprocess` call in this module uses a literal, hardcoded argv
list (never a caller-supplied string, never shell=True) — there is no
code path by which an LLM, a `Run`'s configuration, or any other
untrusted input reaches what command actually runs. If `repository_path`
is not a Git repository, or `git` itself is not installed, this is
represented explicitly (`CodeProvenance.available=False` with a
`reason`) — never silently fabricated, and never raised as an error
(missing code provenance is itself a valid, recordable fact about a
`Run`; see docs/PHASE8B1_EXECUTION_FOUNDATION.md's Code Provenance
section).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class CodeProvenance:
    available: bool
    repository: Optional[str]
    commit: Optional[str]
    branch: Optional[str]
    working_tree_clean: Optional[bool]
    unavailable_reason: Optional[str]


def _run_git(repository_path: str, *args: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_path,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def collect_code_provenance(repository_path: str) -> CodeProvenance:
    """Collect the actual code provenance of `repository_path`. Never
    fabricates a commit SHA: if `git` is not installed, or
    `repository_path` is not inside a Git working tree, `available` is
    `False` and `commit`/`branch`/`working_tree_clean` are all `None`,
    with `unavailable_reason` explaining why."""
    is_inside = _run_git(repository_path, "rev-parse", "--is-inside-work-tree")
    if is_inside is None:
        return CodeProvenance(
            available=False, repository=repository_path, commit=None, branch=None, working_tree_clean=None,
            unavailable_reason="git is not installed, or `repository_path` is not a Git repository.",
        )
    if is_inside.strip().lower() != "true":
        return CodeProvenance(
            available=False, repository=repository_path, commit=None, branch=None, working_tree_clean=None,
            unavailable_reason="`repository_path` is not inside a Git working tree.",
        )

    commit = _run_git(repository_path, "rev-parse", "HEAD")
    branch = _run_git(repository_path, "rev-parse", "--abbrev-ref", "HEAD")
    status = _run_git(repository_path, "status", "--porcelain")

    if commit is None:
        return CodeProvenance(
            available=False, repository=repository_path, commit=None, branch=None, working_tree_clean=None,
            unavailable_reason="`git rev-parse HEAD` failed (e.g. a repository with no commits yet).",
        )

    return CodeProvenance(
        available=True,
        repository=repository_path,
        commit=commit,
        branch=branch or None,
        working_tree_clean=(status == "") if status is not None else None,
        unavailable_reason=None,
    )
