"""Artifact registration: turns a file that already exists on disk
into one immutable `ArtifactMetadata` row, streaming-hashed (never
read fully into memory — see `researchos.execution.hashing`).

`register_artifact` is the only way `researchos.execution` creates an
`ArtifactMetadata` row. It never overwrites: a second registration
attempt with the same `(run_id, logical_name)` fails with
`DuplicateArtifactError` (translated from the table's own
`UniqueConstraint`, itself translated from
`IntegrityConstraintError` — see `researchos.db.repository.
create_artifact_metadata`'s docstring), matching Phase 8B-2 spec
section 9's "do not silently overwrite artifact records."

**Path confinement is enforced here, not merely by the caller.** Every
call validates `path` via `researchos.execution.security.
validate_artifact_path` before anything else — the resulting
`ArtifactPathEscapeError` on a `..` traversal, an absolute path
elsewhere on disk, a path under a different project's/run's own
subtree, or a symlink resolving outside the workspace is raised by
this function itself, unconditionally, regardless of what the caller
already validated. `researchos.execution.orchestrator` happening to
only ever pass already-safe, workspace-derived paths is a property of
a well-behaved caller, not the security boundary itself — the boundary
lives here.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.errors import IntegrityConstraintError
from ..db.models import ArtifactMetadata, ArtifactType
from .config import ExecutionConfig, load_execution_config
from .errors import ArtifactRegistrationError, DuplicateArtifactError, MissingArtifactFileError
from .hashing import sha256_file
from .security import validate_artifact_path


def register_artifact(
    *,
    project_id: int,
    run_id: int,
    logical_name: str,
    artifact_type: ArtifactType,
    path: str | Path,
    source: Optional[str] = None,
    description: Optional[str] = None,
    config: Optional[ExecutionConfig] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ArtifactMetadata:
    """Hash and register one artifact file that already exists on disk,
    strictly inside `Run` `run_id`'s own authorized workspace subtree.

    Raises `ArtifactPathEscapeError` (see `researchos.execution.
    security.validate_artifact_path`) if `path` resolves outside
    `<config.allowed_execution_root>/<project_id>/<run_id>/` — checked
    first, before anything else, so a rejected path never even reaches
    a filesystem existence check. Raises `MissingArtifactFileError` if
    the (already boundary-validated) path does not exist (a
    registration attempt for a file that was never actually produced
    is a caller error, not something to silently skip — callers that
    want "register only if present" behavior check `Path.is_file()`
    themselves first, as `researchos.execution.orchestrator` does for
    stdout/stderr). Raises `DuplicateArtifactError` if `(run_id,
    logical_name)` was already registered.
    """
    resolved_config = config or load_execution_config()
    validated_path = validate_artifact_path(path, project_id=project_id, run_id=run_id, config=resolved_config)

    if not validated_path.is_file():
        raise MissingArtifactFileError(
            f"Cannot register artifact {logical_name!r} for Run {run_id}: {validated_path} does not exist."
        )

    digest = sha256_file(validated_path)
    mime_type, _ = mimetypes.guess_type(validated_path.name)

    try:
        with session_scope(session_factory) as session:
            artifact = repository.create_artifact_metadata(
                session,
                project_id=project_id,
                run_id=run_id,
                logical_name=logical_name,
                artifact_type=artifact_type,
                reference=str(validated_path),
                size_bytes=digest.size_bytes,
                content_hash=digest.sha256_hex,
                mime_type=mime_type,
                source=source,
                description=description,
            )
            artifact_id = artifact.id
    except IntegrityConstraintError as exc:
        raise DuplicateArtifactError(
            f"Artifact {logical_name!r} is already registered for Run {run_id} — artifact registration is "
            "create-only; it never overwrites an existing record."
        ) from exc

    with session_scope(session_factory) as session:
        registered = repository.get_artifact_metadata(session, artifact_id)
        if registered is None:
            raise ArtifactRegistrationError(f"Artifact {artifact_id} could not be re-read after registration.")
        return registered
