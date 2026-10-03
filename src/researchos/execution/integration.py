"""The Phase 8B-3 research experiment integration layer: the single,
opinionated entry point that turns an approved `ExperimentSpecification`
into a `Run`, deriving its `Experiment` and `DatasetVersion` links from
the specification itself rather than trusting a caller to supply them
independently and hoping they agree with what the specification was
actually grounded in. See
docs/PHASE8B3_RESEARCH_EXPERIMENT_INTEGRATION.md for the full design.

This module does not duplicate anything Phase 8B-1/8B-2 already built:
`create_run_from_specification` is a thin, validating wrapper around
`researchos.execution.orchestrator.request_run`; `prepare_run` is a
thin, non-raising wrapper around the exact same
`researchos.execution.preflight.preflight_execute` that
`orchestrator.execute_run` itself calls. Both exist so a caller can ask
"would this be accepted?" without duplicating the checklist that
answers that question — the checklist itself has exactly one home,
`researchos.execution.preflight`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import ExecutionBackend, Run
from . import orchestrator
from . import preflight as preflight_module
from .config import ExecutionConfig
from .contracts import PythonModuleTarget
from .errors import (
    CrossProjectReferenceError,
    InvalidExecutionTargetError,
    MissingEntityError,
    SpecificationMissingDatasetVersionError,
    UnlinkedSpecificationError,
)


def _derive_execution_target(
    configuration: Optional[dict[str, Any]], experiment_specification_id: int
) -> PythonModuleTarget:
    """Translate `ExperimentSpecification.configuration` into a
    `PythonModuleTarget` — the ExperimentSpecification -> ExecutionRequest
    translation this integration layer exists to perform (Phase 8B-3
    spec section 13). Convention: an optional `"execution"` key holding
    `{"module": <str>, "arguments": [<str>, ...], "python_executable":
    <str | null>}`. Deliberately just execution mechanics — no
    domain-specific vocabulary (no CV/NLP/ML field of any kind) lives
    here, matching Phase 8A's own "no ML-specific fields hardcoded into
    the schema" rule for `configuration` itself.
    """
    execution_block = (configuration or {}).get("execution")
    if not isinstance(execution_block, dict) or not isinstance(execution_block.get("module"), str):
        raise InvalidExecutionTargetError(
            f"ExperimentSpecification {experiment_specification_id}'s configuration has no valid 'execution' "
            "block (expected {'module': <str>, 'arguments': [...], 'python_executable': <str|null>}) — cannot "
            "translate it into an execution target. Pass an explicit target= to override."
        )
    arguments = execution_block.get("arguments") or []
    if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
        raise InvalidExecutionTargetError(
            f"ExperimentSpecification {experiment_specification_id}'s configuration['execution']['arguments'] "
            "must be a list of strings."
        )
    python_executable = execution_block.get("python_executable")
    if python_executable is not None and not isinstance(python_executable, str):
        raise InvalidExecutionTargetError(
            f"ExperimentSpecification {experiment_specification_id}'s configuration['execution']"
            "['python_executable'] must be a string or null."
        )
    return PythonModuleTarget(
        module=execution_block["module"], arguments=tuple(arguments), python_executable=python_executable
    )


def create_run_from_specification(
    project_id: int,
    experiment_specification_id: int,
    *,
    requested_by: str,
    timeout_seconds: int,
    target: Optional[PythonModuleTarget] = None,
    seed: Optional[int] = None,
    execution_backend: ExecutionBackend = ExecutionBackend.LOCAL_PYTHON,
    code_repository_path: Optional[str] = None,
    config: Optional[ExecutionConfig] = None,
    session_factory: Optional[sessionmaker] = None,
) -> Run:
    """The Phase 8B-3 high-level Run-creation entry point.

    Unlike `researchos.execution.orchestrator.request_run` (which
    requires the caller to separately supply `experiment_id` and
    `dataset_version_id`, and only checks them for *consistency* with
    what the specification itself recorded), this derives both
    directly from the specification's own links, so there is nothing
    for a caller to get wrong:

    - `experiment_id` <- `specification.experiment_id` — raises
      `UnlinkedSpecificationError` if unset.
    - `dataset_version_id` <- `specification.dataset_version_id` —
      raises `SpecificationMissingDatasetVersionError` if unset.
    - `target`, if omitted, is derived from
      `specification.configuration['execution']` (see
      `_derive_execution_target`) — pass an explicit `target` to
      override this for a specification that does not encode one.

    Every other validation (approval, dataset approval, configuration-
    hash consistency, execution-target/timeout security checks) is
    exactly `request_run`'s own preflight checklist — not reimplemented
    here. Appends one additional `execution.run_created_from_specification`
    audit event on top of `request_run`'s own `execution.run_requested`
    — a record specific to this higher-level entry point having been
    used, at a finer granularity than the generic creation event.
    """
    with session_scope(session_factory) as session:
        specification = repository.get_experiment_specification(session, experiment_specification_id)
        if specification is None:
            raise MissingEntityError(f"ExperimentSpecification {experiment_specification_id} does not exist.")
        if specification.project_id != project_id:
            raise CrossProjectReferenceError(
                f"ExperimentSpecification {experiment_specification_id} belongs to project "
                f"{specification.project_id}, not {project_id}."
            )
        if specification.experiment_id is None:
            raise UnlinkedSpecificationError(
                f"ExperimentSpecification {experiment_specification_id} is not linked to any Experiment "
                "(experiment_id is not set) — cannot derive which research experiment this Run belongs to."
            )
        if specification.dataset_version_id is None:
            raise SpecificationMissingDatasetVersionError(
                f"ExperimentSpecification {experiment_specification_id} has no associated DatasetVersion "
                "(dataset_version_id is not set) — cannot create a Run from it."
            )
        derived_experiment_id = specification.experiment_id
        derived_dataset_version_id = specification.dataset_version_id
        resolved_target = target or _derive_execution_target(specification.configuration, experiment_specification_id)

    run = orchestrator.request_run(
        project_id, derived_experiment_id, experiment_specification_id, derived_dataset_version_id,
        actor=requested_by, target=resolved_target, timeout_seconds=timeout_seconds, seed=seed,
        execution_backend=execution_backend, code_repository_path=code_repository_path, config=config,
        session_factory=session_factory,
    )

    with session_scope(session_factory) as session:
        repository.append_audit_event(
            session, project_id=project_id, actor=requested_by,
            event_type="execution.run_created_from_specification",
            description=f"Run #{run.id} created from ExperimentSpecification {experiment_specification_id}",
            metadata={
                "run_id": run.id, "experiment_specification_id": experiment_specification_id,
                "experiment_id": derived_experiment_id, "dataset_version_id": derived_dataset_version_id,
            },
        )

    with session_scope(session_factory) as session:
        return repository.get_run(session, run.id)


@dataclass(frozen=True)
class PrepareOutcome:
    """The result of asking "is this Run ready to execute?" without
    actually starting it. `ready=False` always carries the exact
    exception `execute_run` would itself raise (`error`) — `prepare_run`
    and `execute_run` share one preflight source of truth
    (`researchos.execution.preflight.preflight_execute`); this
    dataclass exists only so a caller can *ask* without a `try`/
    `except`, never as a second implementation of the checks."""

    ready: bool
    reasons: list[str] = field(default_factory=list)
    error: Optional[BaseException] = None


def prepare_run(run_id: int, *, actor: str = "system", session_factory: Optional[sessionmaker] = None) -> PrepareOutcome:
    """READY or BLOCKED — never raises for an ordinary "not ready yet"
    reason (a genuinely unknown `run_id` still raises
    `MissingEntityError`, since that is a caller error, not a
    readiness fact about a real `Run`). Records `execution.run_prepared`
    or `execution.run_blocked` as an audit event either way — this is
    read-only with respect to the `Run` row itself (no lifecycle
    transition happens here; only `execute_run` transitions state)."""
    with session_scope(session_factory) as session:
        run = repository.get_run(session, run_id)
        if run is None:
            raise MissingEntityError(f"Run {run_id} does not exist.")
        project_id = run.project_id

    try:
        preflight_module.preflight_execute(run, session_factory=session_factory)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: ANY preflight failure means BLOCKED
        with session_scope(session_factory) as session:
            repository.append_audit_event(
                session, project_id=project_id, actor=actor, event_type="execution.run_blocked",
                description=f"Run #{run_id} is not ready to execute: {exc}",
                metadata={"run_id": run_id, "reason": str(exc), "error_type": type(exc).__name__},
            )
        return PrepareOutcome(ready=False, reasons=[str(exc)], error=exc)

    with session_scope(session_factory) as session:
        repository.append_audit_event(
            session, project_id=project_id, actor=actor, event_type="execution.run_prepared",
            description=f"Run #{run_id} is ready to execute", metadata={"run_id": run_id},
        )
    return PrepareOutcome(ready=True)
