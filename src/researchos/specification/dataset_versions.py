"""Dataset version service (Phase 8A): creation, deterministic
fingerprinting, and deterministic validation.

Deliberately no LLM involvement anywhere in this module: a dataset
version's factual properties (fingerprints, sample counts, split
definitions) describe *real, already-acquired or already-planned data*
supplied by the researcher/system registering it — an LLM has no way to
know a real dataset's actual sample count or content fingerprint, and
inventing one would be exactly the kind of fabricated fact this project
forbids throughout. `researchos.specification.experiment_specifications`
is the only module in this package that talks to an LLM.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import DatasetLifecycleStatus
from ..planning import orchestration
from .errors import InvalidLifecycleTransitionError
from .fingerprint import compute_dataset_fingerprints
from .types import DatasetVersionOutcome, ValidationOutcome
from .validators import get_validator


def create_dataset_version(
    project_id: int,
    dataset_record_id: int,
    *,
    actor: str,
    description: Optional[str] = None,
    source_uri: Optional[str] = None,
    format: Optional[str] = None,  # noqa: A002 - matches domain vocabulary
    sample_count: Optional[int] = None,
    split_definition: Optional[dict[str, Any]] = None,
    class_definition: Optional[list[Any]] = None,
    preprocessing_definition: Optional[dict[str, Any]] = None,
    augmentation_definition: Optional[dict[str, Any]] = None,
    supersedes_id: Optional[int] = None,
    session_factory: Optional[sessionmaker] = None,
) -> DatasetVersionOutcome:
    """Register one dataset version, deterministically fingerprinted
    from its own supplied fields. Never inspects `source_uri` as a real
    location — no file I/O, no network access, matching every other
    offline guarantee in this codebase.

    Always starts at `lifecycle_status=DRAFT`. `dataset_record_id` must
    identify an existing `DatasetRecord` in this project;
    `supersedes_id`, if given, must identify an existing DatasetVersion
    in this project belonging to the *same* `dataset_record_id` (see
    `researchos.db.repository.create_dataset_version`).
    """
    content_descriptor = {
        "source_uri": source_uri,
        "format": format,
        "sample_count": sample_count,
        "split_definition": split_definition,
        "class_definition": class_definition,
    }
    metadata_descriptor = {
        "description": description,
        "preprocessing_definition": preprocessing_definition,
        "augmentation_definition": augmentation_definition,
    }
    fingerprints = compute_dataset_fingerprints(
        content_descriptor=content_descriptor, metadata_descriptor=metadata_descriptor
    )

    with session_scope(session_factory) as session:
        dataset_version = repository.create_dataset_version(
            session,
            project_id=project_id,
            dataset_record_id=dataset_record_id,
            supersedes_id=supersedes_id,
            description=description,
            source_uri=source_uri,
            format=format,
            sample_count=sample_count,
            split_definition=split_definition,
            class_definition=class_definition,
            preprocessing_definition=preprocessing_definition,
            augmentation_definition=augmentation_definition,
            content_fingerprint=fingerprints.content_fingerprint,
            metadata_fingerprint=fingerprints.metadata_fingerprint,
            lifecycle_status=DatasetLifecycleStatus.DRAFT,
        )
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="specification.dataset_version_created",
            actor=actor,
            description=f"DatasetVersion v{dataset_version.version} registered for DatasetRecord {dataset_record_id}",
            metadata={
                "dataset_version_id": dataset_version.id,
                "dataset_record_id": dataset_record_id,
                "version": dataset_version.version,
                "supersedes_id": supersedes_id,
                "content_fingerprint": fingerprints.content_fingerprint,
                "metadata_fingerprint": fingerprints.metadata_fingerprint,
            },
        )
        dataset_version_id = dataset_version.id

    return DatasetVersionOutcome(dataset_version_id=dataset_version_id)


def validate_dataset_version(
    project_id: int,
    dataset_version_id: int,
    *,
    actor: str,
    session_factory: Optional[sessionmaker] = None,
) -> ValidationOutcome:
    """Run the validator registered for this version's own `format`
    against its stored metadata, and transition its lifecycle
    accordingly: (`DRAFT`|`INVALID`) -> `VALIDATING` -> (`VALID` or
    `INVALID`). Purely deterministic and offline — operates only on
    already-stored fields, never a real file. Raises
    `InvalidLifecycleTransitionError` if the version is already
    `APPROVED` (immutable) or `DEPRECATED`.
    """
    with session_scope(session_factory) as session:
        dataset_version = repository.get_dataset_version(session, dataset_version_id)
        orchestration.require_in_project(dataset_version, dataset_version_id, "DatasetVersion", project_id)
        if dataset_version.lifecycle_status in (DatasetLifecycleStatus.APPROVED, DatasetLifecycleStatus.DEPRECATED):
            raise InvalidLifecycleTransitionError(
                f"DatasetVersion {dataset_version_id} is {dataset_version.lifecycle_status.value} and immutable; "
                "it cannot be re-validated."
            )
        repository.update_dataset_version(
            session, dataset_version_id, lifecycle_status=DatasetLifecycleStatus.VALIDATING
        )

        validator = get_validator(dataset_version.format)
        metadata = {
            "sample_count": dataset_version.sample_count,
            "split_definition": dataset_version.split_definition,
            "class_definition": dataset_version.class_definition,
            "source_uri": dataset_version.source_uri,
        }
        outcome = validator.validate(metadata)
        new_status = DatasetLifecycleStatus.VALID if outcome.is_valid else DatasetLifecycleStatus.INVALID
        repository.update_dataset_version(
            session, dataset_version_id, lifecycle_status=new_status, validation_result=outcome.to_json()
        )
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="specification.dataset_version_validated",
            actor=actor,
            description=(
                f"DatasetVersion {dataset_version_id} validated as {new_status.value} (format={outcome.format})"
            ),
            metadata={"dataset_version_id": dataset_version_id, "outcome": outcome.to_json()},
        )

    return outcome
