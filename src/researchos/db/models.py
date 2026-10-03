"""ORM models: the persistent schema for ResearchOS research state.

Design notes (see `docs/PHASE3_DATABASE.md` for the full rationale):

- Every table has an integer autoincrement primary key `id`. This maps
  cleanly to both SQLite (`INTEGER PRIMARY KEY`) and PostgreSQL
  (`SERIAL`/`IDENTITY`) with no code change.
- Status-like fields use Python `str` enums mapped via SQLAlchemy's
  `Enum(..., native_enum=False)`, which renders as a plain
  `VARCHAR` + `CHECK` constraint on every backend (SQLite and
  PostgreSQL alike) rather than a PostgreSQL-native `CREATE TYPE`,
  so adding a new status value later never requires an `ALTER TYPE`.
- Free-form vocabulary fields that don't yet have an approved fixed
  set of values (`current_stage`, `ResearchQuestion.type`,
  `LiteratureItem.source`, `Approval.stage`) are plain strings.
  `current_stage` and `Approval.stage` were formalized in Phase 4
  (`researchos.workflow`) entirely at the Python/application layer —
  deliberately without changing these columns' types — so this
  bullet still applies to the schema itself; see
  `docs/PHASE4_WORKFLOW.md` for what now constrains their values in
  practice.
- Structured metadata (`Experiment.configuration`, `ExperimentResult.metadata`,
  `AuditEvent.metadata`, `DatasetRecord.split_information`) uses
  SQLAlchemy's `JSON` type, which is stored safely (parameterized,
  not string-concatenated) on every backend.
- `metadata` is a reserved attribute name on declarative model classes
  (it holds the table's `MetaData`), so the Python attribute for the
  `ExperimentResult`/`AuditEvent` "metadata" column is named
  `metadata_` and mapped to the actual column name `"metadata"` via
  `mapped_column("metadata", ...)`.
- All child tables cascade-delete with their parent (`ondelete="CASCADE"`
  at the DB level, `cascade="all, delete-orphan"` at the ORM level),
  matching the ownership tree in the Phase 3 spec: deleting a
  `ResearchProject` deletes everything under it, and deleting an
  `Experiment` deletes its `ExperimentResult` rows.
"""

from __future__ import annotations

import enum
import math
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Mixins
# --------------------------------------------------------------------------


class IDMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def _require_nonblank(value: str, field_name: str) -> str:
    if value is None or not value.strip():
        from .errors import ValidationError

        raise ValidationError(f"'{field_name}' must not be blank.")
    return value


def _validate_unit_interval(value: Optional[float], field_name: str) -> Optional[float]:
    if value is None:
        return None
    if not (0.0 <= value <= 1.0):
        from .errors import ValidationError

        raise ValidationError(f"'{field_name}' must be between 0.0 and 1.0, got {value!r}.")
    return value


def _validate_finite_number(value: float, field_name: str) -> float:
    if value is None or not math.isfinite(value):
        from .errors import ValidationError

        raise ValidationError(f"'{field_name}' must be a finite number, got {value!r}.")
    return value


def _validate_positive_int(value: int, field_name: str) -> int:
    if value is None or value < 1:
        from .errors import ValidationError

        raise ValidationError(f"'{field_name}' must be a positive integer, got {value!r}.")
    return value


def _validate_nonnegative_int(value: Optional[int], field_name: str) -> Optional[int]:
    if value is not None and value < 0:
        from .errors import ValidationError

        raise ValidationError(f"'{field_name}' must not be negative, got {value!r}.")
    return value


# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    # Added in Phase 4 for the workflow engine's project-level rejection
    # action (researchos.workflow.service.reject_project) — see
    # migrations/versions/<rev>_add_project_status_rejected.py and
    # docs/PHASE4_WORKFLOW.md.
    REJECTED = "rejected"


class IdeaStatus(str, enum.Enum):
    PROPOSED = "proposed"
    EXPLORING = "exploring"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class QuestionStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    DROPPED = "dropped"


class EvidenceStatus(str, enum.Enum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"


class RecordStatus(str, enum.Enum):
    """Quality/provenance status of a retrieved evidence record.

    Added in Phase 5 (`researchos.evidence`) — distinct from
    `EvidenceStatus` above, which tracks a human's *review* of a
    literature item. This tracks the *retrieval* outcome instead.
    `SOURCE_ERROR` and `NOT_FOUND` describe a failed fetch and are
    normally never persisted as a `LiteratureItem` row (there is
    nothing concrete to store) — they exist here so adapters and the
    evidence service share one status vocabulary end to end.
    """

    VERIFIED_SOURCE_RECORD = "verified_source_record"
    PARTIAL_METADATA = "partial_metadata"
    SOURCE_ERROR = "source_error"
    NOT_FOUND = "not_found"
    DUPLICATE_CANDIDATE = "duplicate_candidate"


class MatchType(str, enum.Enum):
    """How two `LiteratureItem` records were identified as (candidate) duplicates."""

    DOI = "doi"
    SOURCE_ID = "source_id"
    TITLE_AUTHOR_YEAR = "title_author_year"


class GapStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REJECTED = "rejected"
    # Added in Phase 6 so a human reviewer can send a gap candidate back
    # for revision without either approving (VALIDATED) or rejecting it
    # outright — mirrors ApprovalDecision.CHANGES_REQUESTED. No CHECK
    # constraint exists on this column (Phase 3 predates
    # `create_constraint=True`), so this addition needs no migration.
    CHANGES_REQUESTED = "changes_requested"


class NoveltyStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED_NOVEL = "confirmed_novel"
    NOT_NOVEL = "not_novel"
    INCONCLUSIVE = "inconclusive"


class AnalysisStatus(str, enum.Enum):
    """Lifecycle of one `LiteratureAnalysis` LLM run."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ClaimSupportLevel(str, enum.Enum):
    """How well an `AnalysisClaim` is backed by the evidence it cites.

    `UNSUPPORTED_CANDIDATE` is the Phase 6 spec's explicit required
    value: a claim with no cited evidence must never be represented as
    established research knowledge.
    """

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED_CANDIDATE = "unsupported_candidate"


class ClaimApprovalStatus(str, enum.Enum):
    """Category 4 (candidate) -> category 5 (human-approved) tracker
    for one `AnalysisClaim` — see docs/PHASE6_RESEARCH_INTELLIGENCE.md."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class NoveltyCandidateStatus(str, enum.Enum):
    """Phase 6's non-authoritative novelty analysis states.

    Deliberately does not include a blunt "Novel: Yes"-style value —
    `HUMAN_APPROVED` is the only status that ever represents a settled
    outcome, and only a human (never the LLM) may set it.
    """

    NOT_ASSESSED = "not_assessed"
    POSSIBLY_ALREADY_EXISTING = "possibly_already_existing"
    PARTIALLY_DISTINCT = "partially_distinct"
    POTENTIALLY_DISTINCT = "potentially_distinct"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HUMAN_APPROVED = "human_approved"
    # The two human-decision outcomes, added for symmetry with
    # GapStatus/ClaimApprovalStatus's approval vocabulary — a human (never
    # the LLM) is the only actor who may ever set these.
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ComparisonStatus(str, enum.Enum):
    """Per-row status for one `NoveltyComparison` (candidate vs. one prior work)."""

    SIMILAR = "similar"
    PARTIALLY_DISTINCT = "partially_distinct"
    DISTINCT = "distinct"
    UNCLEAR = "unclear"


class EvidenceSubjectType(str, enum.Enum):
    """Which table an `EvidenceLink.subject_id` points into.

    Polymorphic by convention (no DB-level FK is possible across
    different target tables) — the repository layer validates that
    `subject_id` actually exists in the named table before inserting.
    """

    ANALYSIS_CLAIM = "analysis_claim"
    GAP_CANDIDATE = "gap_candidate"  # research_gaps.id
    NOVELTY_ASSESSMENT = "novelty_assessment"
    NOVELTY_COMPARISON = "novelty_comparison"
    # --- Added in Phase 7 (researchos.planning) ---
    RESEARCH_QUESTION = "research_question"
    CONTRIBUTION_CANDIDATE = "contribution_candidate"
    METHODOLOGY_PLAN = "methodology_plan"
    DATASET_REQUIREMENTS = "dataset_requirements"
    EXPERIMENTAL_DESIGN = "experimental_design"
    # --- Added in Phase 8A (researchos.specification) ---
    DATASET_VERSION = "dataset_version"
    EXPERIMENT_SPECIFICATION = "experiment_specification"
    # --- Added in Phase 8 (researchos.analysis) — a literature item
    # can itself be cited evidence for/against a scientific claim or an
    # analysis record, exactly like every other subject type here. ---
    SCIENTIFIC_CLAIM = "scientific_claim"
    ANALYSIS_RECORD = "analysis_record"


class EvidenceRelationship(str, enum.Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    RELATED = "related"
    CITES = "cites"


class PlanningApprovalStatus(str, enum.Enum):
    """Phase 7's shared candidate -> human-decision lifecycle, reused
    across every planning entity's `planning_status` column
    (`ResearchQuestion`, `ContributionCandidate`, `MethodologyPlan`,
    `DatasetRequirements`, `ExperimentalDesign`).

    Deliberately one shared enum rather than five near-identical
    entity-specific ones: unlike Phase 6's `GapStatus`/
    `NoveltyCandidateStatus` (which each had to reuse or coexist with a
    pre-existing Phase 3 value set), none of these five columns predates
    this phase, so there is no backward-compatibility reason to diverge.

    An LLM-generated planning artifact is only ever persisted as
    `CANDIDATE` — `APPROVED` is set exclusively by
    `researchos.planning.approval` (via `researchos.db.approval_dispatch`),
    which requires a human actor, exactly like Phase 6's approval flow.
    """

    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class DatasetLifecycleStatus(str, enum.Enum):
    """Phase 8A's `DatasetVersion` lifecycle — deliberately a separate
    vocabulary from `PlanningApprovalStatus`, because a dataset version
    passes through a deterministic, machine-checkable validation step
    (`DRAFT` -> `VALIDATING` -> `VALID`/`INVALID`) *before* human
    approval is even meaningful, unlike every other Phase 7 planning
    artifact (which has nothing analogous to validate before review).

    `APPROVED` means only "approved for system use under this project's
    defined process" — never "scientifically optimal" or "scientifically
    valid research evidence"; no scientific judgment is encoded here.
    Only a human, via `researchos.specification.approval` (built on
    `researchos.db.approval_dispatch`, exactly like every other Phase 6/7
    gate), may set `APPROVED`. `request_changes` sends a version back to
    `DRAFT` rather than inventing a redundant sixth state; a human
    rejection lands on `INVALID` — the same value automated validation
    failure would produce, since both mean "not fit for use," just
    reached by a different path.
    """

    DRAFT = "draft"
    VALIDATING = "validating"
    VALID = "valid"
    APPROVED = "approved"
    INVALID = "invalid"
    DEPRECATED = "deprecated"


class RunStatus(str, enum.Enum):
    """Phase 8B-1's `Run` lifecycle — a `Run` is a single execution
    instance, deliberately distinct from `PlanningApprovalStatus`/
    `DatasetLifecycleStatus`: those describe review state on a
    versioned *artifact*; this describes the actual progress of one
    real (or locally-simulated) process invocation.

    `CREATED` is the pre-approval state: a `Run` row exists (its full
    provenance is already captured) but has not been authorized to
    execute — see `researchos.execution.approval`'s docstring for why
    this state itself stands in for a separate `ExecutionRequest`
    entity. `TIMEOUT` is kept distinct from `FAILED` rather than
    folded into it because "the code raised/exited non-zero" and "we
    killed it because it exceeded its declared timeout" are different
    scientific facts a reviewer needs to tell apart at a glance,
    without inspecting `failure_reason` text.

    Terminal values: `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMEOUT` — a
    `Run` in any of these states is treated as an immutable scientific
    record by `researchos.execution` (see that package's `runs`
    module); a new execution always means a new `Run` row, never a
    reset of a terminal one.
    """

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ExecutionBackend(str, enum.Enum):
    """Which `researchos.execution.contracts.ExecutionEngine`
    implementation a `Run` executes (or is intended to execute)
    through. Only `LOCAL_PYTHON` has a real implementation in Phase
    8B-1 (`researchos.execution.local_executor.LocalPythonExecutor`);
    the rest name the target architecture from the Phase 8B-1 spec
    so `Run.execution_backend` has a stable, complete vocabulary to
    grow into, but `researchos.execution.preflight` rejects any of
    them as an unsupported backend until each gets its own real
    executor in a future phase — listing a value here is not an
    implementation commitment.
    """

    LOCAL_PYTHON = "local_python"
    DOCKER = "docker"
    REMOTE_GPU = "remote_gpu"
    SLURM = "slurm"
    CLOUD = "cloud"


class ArtifactType(str, enum.Enum):
    """What kind of thing one `ArtifactMetadata` row describes.
    Phase 8B-1 created only `STDOUT`/`STDERR` rows itself (from
    `LocalPythonExecutor`'s captured output). Phase 8B-2 additionally
    creates `RESULT_MANIFEST` (the generated, deterministic execution
    result manifest — see `researchos.execution.manifest`) and reads
    (never writes the bytes of) `METRIC_REPORT` if a process explicitly
    supplies one — ResearchOS never generates the underlying bytes of
    `CHECKPOINT`/`MODEL`/`PLOT` itself; those categories only ever
    describe files an executed process wrote on its own."""

    STDOUT = "stdout"
    STDERR = "stderr"
    CHECKPOINT = "checkpoint"
    MODEL = "model"
    PLOT = "plot"
    LOG = "log"
    METRIC_REPORT = "metric_report"
    RESULT_MANIFEST = "result_manifest"
    OTHER = "other"


class MetricValueType(str, enum.Enum):
    """Whether a `Metric.value` was originally an integer or a
    floating-point measurement — `Metric.value` itself is always
    stored as `Float` (IEEE-754 double; see `Metric`'s own docstring
    for why `Decimal` is not used), so this is the one piece of
    numeric-kind information that storage as `Float` alone would
    otherwise lose (e.g. an integer count of 5 vs. a measured 5.0)."""

    INTEGER = "integer"
    FLOAT = "float"


class AnalysisInputType(str, enum.Enum):
    """Which table one `AnalysisInput.input_id` points into — the same
    polymorphic-by-convention pattern `EvidenceSubjectType`/
    `EvidenceLink.subject_id` already established (no database-level FK
    is possible across different target tables; the repository layer
    validates existence + project ownership before inserting)."""

    RUN = "run"
    METRIC = "metric"
    ARTIFACT = "artifact"


class AnalysisRecordStatus(str, enum.Enum):
    """`COMPLETED` is an ordinary deterministic computation's outcome.
    `NOT_COMPARABLE` is itself a valid, persisted computed fact — see
    `AnalysisRecord`'s own docstring — produced specifically by a
    comparability check that found its inputs incompatible; it is not
    an error state (an invalid/malformed request never reaches
    persistence at all — see `researchos.analysis.errors`)."""

    COMPLETED = "completed"
    NOT_COMPARABLE = "not_comparable"


class ClaimStrength(str, enum.Enum):
    """How well the evidence currently linked to one `ScientificClaim`
    supports it — an evidence assessment, never a declaration of
    universal truth (Phase 8 spec section 17). Deliberately a richer,
    distinctly-named vocabulary from Phase 6's `ClaimSupportLevel`
    (`SUPPORTED`/`PARTIALLY_SUPPORTED`/`UNSUPPORTED_CANDIDATE`): that
    enum describes how well a *literature-analysis* claim is backed by
    cited literature, a different domain with no "contradicted by a
    later run" or "not yet assessed at all" concept. `NOT_ASSESSABLE`
    is the default — set only by an actual assessment, never assumed
    to mean "true until proven otherwise.\""""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTED = "contradicted"
    NOT_ASSESSABLE = "not_assessable"


class ScientificReviewStatus(str, enum.Enum):
    """A `ScientificReview`'s own lifecycle — distinct from
    `ClaimStrength` (the *outcome* a review's dimensions assess) and
    from `ClaimApprovalStatus` (the *claim's own* separate human
    decision). `DRAFT`/`CANDIDATE`/`NEEDS_MORE_EVIDENCE`/
    `READY_FOR_HUMAN_REVIEW` are all non-authoritative, LLM-or-
    deterministically-assignable states; only a human may ever set
    `HUMAN_APPROVED` (enforced by `researchos.analysis.approval`, the
    same "LLM cannot approve its own output" rule every phase's
    approval gate already enforces) or `REJECTED`."""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"


class MethodologyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ExperimentStatus(str, enum.Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ManuscriptStatus(str, enum.Enum):
    DRAFTING = "drafting"
    IN_REVIEW = "in_review"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PUBLISHED = "published"


class JournalCandidateStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    SHORTLISTED = "shortlisted"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class ApprovalDecision(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


def _enum_column(enum_cls: type[enum.Enum], *, default: enum.Enum, create_constraint: bool = False):
    """Build an enum-backed column.

    `create_constraint` defaults to False, matching every enum column
    Phase 3 originally shipped (their migrations were generated without
    it — see the Phase 4 note in `docs/PHASE4_WORKFLOW.md` on the
    discovered gap this leaves: `native_enum=False` alone renders as a
    plain `VARCHAR` with *no* database-level `CHECK` constraint, only
    ORM-side (`validate_strings=True`) validation, which a raw SQL
    write can bypass). Changing the shared default here would silently
    desynchronize every other enum column's migration history from its
    model definition, so it is opt-in per column instead;
    `ProjectStatus` passes `create_constraint=True` because Phase 4
    already has to touch its migration to add `REJECTED` and starting
    that column off correctly costs nothing extra.
    """
    return mapped_column(
        Enum(enum_cls, native_enum=False, validate_strings=True, length=32, create_constraint=create_constraint),
        default=default,
        nullable=False,
    )


# --------------------------------------------------------------------------
# Core entity: ResearchProject
# --------------------------------------------------------------------------


class ResearchProject(IDMixin, TimestampMixin, Base):
    __tablename__ = "research_projects"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    field: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[ProjectStatus] = _enum_column(ProjectStatus, default=ProjectStatus.ACTIVE, create_constraint=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    ideas: Mapped[list["ResearchIdea"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    questions: Mapped[list["ResearchQuestion"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    literature_items: Mapped[list["LiteratureItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    literature_matches: Mapped[list["LiteratureMatch"]] = relationship(cascade="all, delete-orphan")
    gaps: Mapped[list["ResearchGap"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    novelty_assessments: Mapped[list["NoveltyAssessment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    methodology_plans: Mapped[list["MethodologyPlan"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    datasets: Mapped[list["DatasetRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    manuscripts: Mapped[list["Manuscript"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    journal_candidates: Mapped[list["JournalCandidate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    # Phase 6: researchos.intelligence
    literature_analyses: Mapped[list["LiteratureAnalysis"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    analysis_claims: Mapped[list["AnalysisClaim"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    novelty_comparisons: Mapped[list["NoveltyComparison"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list["EvidenceLink"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    # Phase 7: researchos.planning
    contribution_candidates: Mapped[list["ContributionCandidate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    dataset_requirements_list: Mapped[list["DatasetRequirements"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    experimental_designs: Mapped[list["ExperimentalDesign"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    contribution_candidate_questions: Mapped[list["ContributionCandidateQuestion"]] = relationship(
        cascade="all, delete-orphan"
    )
    experimental_design_questions: Mapped[list["ExperimentalDesignQuestion"]] = relationship(
        cascade="all, delete-orphan"
    )
    # Phase 8A: researchos.specification
    dataset_versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    experiment_specifications: Mapped[list["ExperimentSpecification"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    experiment_specification_questions: Mapped[list["ExperimentSpecificationQuestion"]] = relationship(
        cascade="all, delete-orphan"
    )
    experiment_specification_contributions: Mapped[list["ExperimentSpecificationContribution"]] = relationship(
        cascade="all, delete-orphan"
    )
    # Phase 8B-1: researchos.execution. EnvironmentSnapshot is
    # deliberately NOT here — see that class's own docstring for why it
    # is not project-scoped.
    runs: Mapped[list["Run"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    artifact_metadata: Mapped[list["ArtifactMetadata"]] = relationship(cascade="all, delete-orphan")
    metrics: Mapped[list["Metric"]] = relationship(cascade="all, delete-orphan")
    # Phase 8: researchos.analysis
    analysis_records: Mapped[list["AnalysisRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    analysis_inputs: Mapped[list["AnalysisInput"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scientific_claims: Mapped[list["ScientificClaim"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scientific_claim_analyses: Mapped[list["ScientificClaimAnalysis"]] = relationship(cascade="all, delete-orphan")
    scientific_reviews: Mapped[list["ScientificReview"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


def _project_fk(*, nullable: bool = False):
    return mapped_column(
        Integer,
        ForeignKey("research_projects.id", ondelete="CASCADE"),
        nullable=nullable,
        index=True,
    )


# --------------------------------------------------------------------------
# ResearchIdea
# --------------------------------------------------------------------------


class ResearchIdea(IDMixin, TimestampMixin, Base):
    __tablename__ = "research_ideas"

    project_id: Mapped[int] = _project_fk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[IdeaStatus] = _enum_column(IdeaStatus, default=IdeaStatus.PROPOSED)

    project: Mapped["ResearchProject"] = relationship(back_populates="ideas")

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# ResearchQuestion
# --------------------------------------------------------------------------


class ResearchQuestion(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "research_questions"

    project_id: Mapped[int] = _project_fk()
    question: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[QuestionStatus] = _enum_column(QuestionStatus, default=QuestionStatus.OPEN)

    # --- Added in Phase 7 (researchos.planning). `status` above (Phase 3's
    # OPEN/ANSWERED/DROPPED) tracks the question's own research lifecycle
    # and is left untouched; `planning_status` is an independent axis —
    # whether a human has approved this question (however it was
    # authored) for use as the basis of downstream planning. Traceability
    # to the approved gap that motivated an LLM-suggested question is
    # via the existing `research_gaps.research_question_id` FK (Gap ->
    # Question) — deliberately not duplicated here with a second,
    # opposite-direction column.
    hypothesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="questions")

    @validates("question")
    def _validate_question(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# LiteratureItem
# --------------------------------------------------------------------------


class LiteratureItem(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "literature_items"
    __table_args__ = (
        UniqueConstraint("project_id", "doi", name="uq_literature_project_doi"),
        UniqueConstraint("project_id", "source", "source_record_id", name="uq_literature_project_source_record"),
    )

    project_id: Mapped[int] = _project_fk()
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    evidence_status: Mapped[EvidenceStatus] = _enum_column(EvidenceStatus, default=EvidenceStatus.UNREVIEWED)

    # --- Added in Phase 5 (researchos.evidence) ---
    source_record_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    publisher: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Only populated when the source supplies a full year-month-day date;
    # a source that only gives a year (very common) leaves this NULL and
    # relies on `year` instead, rather than fabricating a day-of-month.
    publication_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    document_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    citation_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    keywords: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    # Other sources' identifiers for the same paper mentioned in this
    # source's own metadata (e.g. an OpenAlex record's embedded DOI/PMID),
    # used for cross-source "strong identifier" duplicate detection.
    external_ids: Mapped[Optional[dict[str, str]]] = mapped_column(JSON, nullable=True)
    # The (safely trimmed) source payload this record was normalized
    # from — never destroyed even when fields above are NULL/partial.
    raw_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    record_status: Mapped[RecordStatus] = _enum_column(
        RecordStatus, default=RecordStatus.VERIFIED_SOURCE_RECORD, create_constraint=True
    )
    metadata_completeness: Mapped[Optional[float]] = mapped_column(nullable=True)
    # Set when this record has been identified as a (candidate or
    # confirmed) duplicate of another LiteratureItem in the same
    # project. NULL means this record is canonical/standalone. Clearing
    # to NULL (rather than cascading delete) if the canonical record is
    # itself deleted, since the duplicate record's own data is still valid.
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("literature_items.id", ondelete="SET NULL", name="fk_literature_items_duplicate_of_id"),
        nullable=True,
        index=True,
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="literature_items")

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("year")
    def _validate_year(self, key: str, value: Optional[int]) -> Optional[int]:
        return _validate_nonnegative_int(value, key)

    @validates("citation_count")
    def _validate_citation_count(self, key: str, value: Optional[int]) -> Optional[int]:
        return _validate_nonnegative_int(value, key)

    @validates("metadata_completeness")
    def _validate_metadata_completeness(self, key: str, value: Optional[float]) -> Optional[float]:
        return _validate_unit_interval(value, key)


class LiteratureMatch(IDMixin, CreatedAtMixin, Base):
    """A recorded (candidate or confirmed) duplicate relationship between
    two `LiteratureItem` rows, with enough information to explain why —
    see `researchos.evidence.dedup` and `docs/PHASE5_EVIDENCE.md`.

    Both records are always kept; this table never causes a `LiteratureItem`
    to be deleted or overwritten, preserving each source's provenance.
    """

    __tablename__ = "literature_matches"
    __table_args__ = (
        UniqueConstraint("literature_item_id", "matched_item_id", name="uq_literature_match_pair"),
    )

    project_id: Mapped[int] = _project_fk()
    literature_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("literature_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matched_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("literature_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_type: Mapped[MatchType] = _enum_column(
        MatchType, default=MatchType.TITLE_AUTHOR_YEAR, create_constraint=True
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @validates("confidence")
    def _validate_confidence(self, key: str, value: float) -> float:
        if value is None or not (0.0 <= value <= 1.0):
            from .errors import ValidationError

            raise ValidationError(f"'{key}' must be between 0.0 and 1.0, got {value!r}.")
        return value


# --------------------------------------------------------------------------
# ResearchGap
# --------------------------------------------------------------------------


class ResearchGap(IDMixin, TimestampMixin, Base):
    __tablename__ = "research_gaps"

    project_id: Mapped[int] = _project_fk()
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[GapStatus] = _enum_column(GapStatus, default=GapStatus.CANDIDATE)

    # --- Added in Phase 6 (researchos.intelligence) for LLM-generated gap
    # candidates. `status` above (CANDIDATE by default) already tracks
    # the candidate -> human-decision lifecycle; these columns add the
    # structured content and generation provenance a candidate needs.
    # Which literature *supports*/*contradicts* this gap lives in
    # `EvidenceLink`, not a column here — see docs/PHASE6_RESEARCH_INTELLIGENCE.md.
    gap_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    affected_research_area: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    evidence_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prior_work_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    insufficiency_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    missing_evidence_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candidate_research_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_question_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("research_questions.id", ondelete="SET NULL", name="fk_research_gaps_research_question_id"),
        nullable=True,
        index=True,
    )
    source_analysis_ids: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="gaps")

    @validates("statement")
    def _validate_statement(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("confidence")
    def _validate_confidence(self, key: str, value: Optional[float]) -> Optional[float]:
        return _validate_unit_interval(value, key)


# --------------------------------------------------------------------------
# NoveltyAssessment
# --------------------------------------------------------------------------


class NoveltyAssessment(IDMixin, Base):
    __tablename__ = "novelty_assessments"

    project_id: Mapped[int] = _project_fk()
    # `claim` is the proposed contribution being assessed for novelty —
    # kept as the original Phase 3 column name/meaning (no redundant
    # "proposed_contribution" duplicate column); see
    # docs/PHASE6_RESEARCH_INTELLIGENCE.md.
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[NoveltyStatus] = _enum_column(NoveltyStatus, default=NoveltyStatus.PENDING)
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # --- Added in Phase 6. `status` (NoveltyStatus) is Phase 3's original,
    # simple field and is left untouched for backward compatibility;
    # `candidate_status` is Phase 6's non-authoritative candidate-analysis
    # vocabulary (see NoveltyCandidateStatus) and is what
    # `researchos.intelligence` actually reads/writes. Closest-related-work
    # links and per-comparison evidence live in `NoveltyComparison` /
    # `EvidenceLink`, not columns here.
    candidate_status: Mapped[NoveltyCandidateStatus] = _enum_column(
        NoveltyCandidateStatus, default=NoveltyCandidateStatus.NOT_ASSESSED, create_constraint=True
    )
    unresolved_questions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    novelty_risk: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_question_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "research_questions.id", ondelete="SET NULL", name="fk_novelty_assessments_research_question_id"
        ),
        nullable=True,
        index=True,
    )
    source_gap_ids: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    source_analysis_ids: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # --- Added in Phase 7 (researchos.planning). Nullable, backward
    # compatible with every existing Phase 6 `NoveltyAssessment` (which
    # has no contribution). Deliberately does NOT change what this table
    # means: a `NoveltyAssessment` is still exactly Phase 6's "evidence-
    # based assessment of whether a proposed contribution appears
    # distinct from prior work". `ContributionCandidate` is a separate,
    # stable identity precisely so it can accumulate multiple
    # `NoveltyAssessment` rows over time (e.g. reassessed against an
    # expanded literature set) without ever changing id — see
    # docs/PHASE7_RESEARCH_PLANNING.md.
    contribution_candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "contribution_candidates.id",
            ondelete="SET NULL",
            name="fk_novelty_assessments_contribution_candidate_id",
        ),
        nullable=True,
        index=True,
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="novelty_assessments")
    comparisons: Mapped[list["NoveltyComparison"]] = relationship(
        back_populates="novelty_assessment", cascade="all, delete-orphan"
    )
    contribution_candidate: Mapped[Optional["ContributionCandidate"]] = relationship(
        back_populates="novelty_assessments"
    )

    @validates("claim")
    def _validate_claim(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("confidence")
    def _validate_confidence(self, key: str, value: Optional[float]) -> Optional[float]:
        return _validate_unit_interval(value, key)


# --------------------------------------------------------------------------
# Phase 6: LiteratureAnalysis, AnalysisClaim, NoveltyComparison, EvidenceLink
# --------------------------------------------------------------------------


class LiteratureAnalysis(IDMixin, CreatedAtMixin, Base):
    """One LLM analysis run over a bounded, explicitly-selected set of
    `LiteratureItem` evidence. See docs/PHASE6_RESEARCH_INTELLIGENCE.md.
    """

    __tablename__ = "literature_analyses"

    project_id: Mapped[int] = _project_fk()
    research_question_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    research_topic: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The ids the caller *asked* to include vs. what actually made it into
    # the bounded evidence package sent to the LLM — see
    # researchos.intelligence.evidence_package. `truncated=True` whenever
    # the two differ, so the analysis result always says so explicitly.
    requested_item_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    included_item_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    truncated: Mapped[bool] = mapped_column(default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[AnalysisStatus] = _enum_column(AnalysisStatus, default=AnalysisStatus.PENDING, create_constraint=True)
    # The structured per-item dimension analysis (JSON) — never free
    # prose; see researchos.intelligence.types for the expected shape.
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)

    project: Mapped["ResearchProject"] = relationship(back_populates="literature_analyses")
    claims: Mapped[list["AnalysisClaim"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")

    @validates("research_topic")
    def _validate_research_topic(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("actor")
    def _validate_actor(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


class AnalysisClaim(IDMixin, CreatedAtMixin, Base):
    """One traceable analytical statement produced by an LLM from a
    `LiteratureAnalysis` run. Evidence citations live in `EvidenceLink`
    (subject_type=ANALYSIS_CLAIM), not a column here.
    """

    __tablename__ = "analysis_claims"

    project_id: Mapped[int] = _project_fk()
    analysis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("literature_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    support_level: Mapped[ClaimSupportLevel] = _enum_column(
        ClaimSupportLevel, default=ClaimSupportLevel.UNSUPPORTED_CANDIDATE, create_constraint=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    uncertainty: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_status: Mapped[ClaimApprovalStatus] = _enum_column(
        ClaimApprovalStatus, default=ClaimApprovalStatus.PENDING_REVIEW, create_constraint=True
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="analysis_claims")
    analysis: Mapped["LiteratureAnalysis"] = relationship(back_populates="claims")

    @validates("claim_text")
    def _validate_claim_text(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("confidence")
    def _validate_confidence(self, key: str, value: Optional[float]) -> Optional[float]:
        return _validate_unit_interval(value, key)


class NoveltyComparison(IDMixin, CreatedAtMixin, Base):
    """One row of the candidate-vs-prior-work similarity matrix (Phase 6
    spec section 7): Candidate | Prior Work | Similarity | Difference |
    Evidence | Status. "Evidence" is `EvidenceLink` rows
    (subject_type=NOVELTY_COMPARISON): SUPPORTS = evidence for the
    similarity claim, CONTRADICTS = evidence for the difference claim.
    """

    __tablename__ = "novelty_comparisons"

    project_id: Mapped[int] = _project_fk()
    novelty_assessment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("novelty_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    literature_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("literature_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    similarity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ComparisonStatus] = _enum_column(
        ComparisonStatus, default=ComparisonStatus.UNCLEAR, create_constraint=True
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="novelty_comparisons")
    novelty_assessment: Mapped["NoveltyAssessment"] = relationship(back_populates="comparisons")


class EvidenceLink(IDMixin, CreatedAtMixin, Base):
    """The unified evidence-traceability structure (Phase 6 spec section
    8's "Evidence Matrix"): ties an `AnalysisClaim` / `ResearchGap` /
    `NoveltyAssessment` / `NoveltyComparison` row to the `LiteratureItem`
    evidence it is based on, with an explicit relationship type.

    `subject_id` is polymorphic (its meaning depends on `subject_type`)
    and therefore cannot be a database foreign key; the repository layer
    validates it points at a real row before inserting.
    """

    __tablename__ = "evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "subject_type", "subject_id", "literature_item_id", "relationship_type",
            name="uq_evidence_link_identity",
        ),
    )

    project_id: Mapped[int] = _project_fk()
    literature_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("literature_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[EvidenceSubjectType] = _enum_column(
        EvidenceSubjectType, default=EvidenceSubjectType.ANALYSIS_CLAIM, create_constraint=True
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    relationship_type: Mapped[EvidenceRelationship] = _enum_column(
        EvidenceRelationship, default=EvidenceRelationship.CITES, create_constraint=True
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="evidence_links")


# --------------------------------------------------------------------------
# Phase 7 (researchos.planning): ContributionCandidate,
# ContributionCandidateQuestion, MethodologyPlan (extended),
# DatasetRequirements, ExperimentalDesign, ExperimentalDesignQuestion
# --------------------------------------------------------------------------


class ContributionCandidate(IDMixin, TimestampMixin, Base):
    """A proposed scientific contribution — the thing being proposed, kept
    structurally distinct from `NoveltyAssessment` (the evidence-based
    judgment of whether it appears distinct from prior work).

    A `ContributionCandidate` has a stable identity precisely so it can
    accumulate multiple `NoveltyAssessment` rows over its lifetime (e.g.
    reassessed against an expanded literature set, or a reviewer-
    requested comparison) without its own id ever changing, and so that
    "we accept this as the direction we're pursuing"
    (`planning_status`) and "this appears distinct from prior work"
    (a `NoveltyAssessment.candidate_status`) remain two independent
    human decisions. See docs/PHASE7_RESEARCH_PLANNING.md.

    `version`/`supersedes_id` (added during the Phase 7 post-implementation
    audit remediation) give a *specific* regeneration — "this row is a
    revised version of that exact prior row" — a real, traceable lineage,
    distinct from "an unrelated, independent contribution that also
    happens to exist in this project" (which is why versioning here is
    NOT a project-wide auto-incrementing counter the way
    `MethodologyPlan.version` is: multiple independent contribution
    lineages can legitimately coexist in one project at once).
    `supersedes_id` is `UniqueConstraint`-protected so a given row can be
    superseded by at most one later version, keeping each lineage a
    simple, unbranching chain a caller can walk by following
    `supersedes_id` backward from any row.
    """

    __tablename__ = "contribution_candidates"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_contribution_candidate_supersedes"),
    )

    project_id: Mapped[int] = _project_fk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    contribution_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "contribution_candidates.id", ondelete="SET NULL", name="fk_contribution_candidates_supersedes_id"
        ),
        nullable=True,
        index=True,
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="contribution_candidates")
    novelty_assessments: Mapped[list["NoveltyAssessment"]] = relationship(back_populates="contribution_candidate")
    methodology_plans: Mapped[list["MethodologyPlan"]] = relationship(back_populates="contribution_candidate")

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("description")
    def _validate_description(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class ContributionCandidateQuestion(IDMixin, CreatedAtMixin, Base):
    """One (contribution, research question) pairing — the M:N
    traceability edge a `ContributionCandidate` declares between itself
    and the `ResearchQuestion` row(s) it addresses. Deliberately a plain
    association row with no further ORM relationships declared on either
    side (matching Phase 3/5's existing `LiteratureMatch` precedent for
    an association table involving more than one other entity type) —
    queried directly via `researchos.db.repository`, never through an
    implicit `.contribution_candidates`/`.research_questions` collection.
    """

    __tablename__ = "contribution_candidate_questions"
    __table_args__ = (
        UniqueConstraint(
            "contribution_candidate_id", "research_question_id", name="uq_contribution_candidate_question"
        ),
    )

    project_id: Mapped[int] = _project_fk()
    contribution_candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contribution_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("research_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )


# --------------------------------------------------------------------------
# MethodologyPlan
# --------------------------------------------------------------------------


class MethodologyPlan(IDMixin, TimestampMixin, Base):
    __tablename__ = "methodology_plans"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_methodology_project_version"),)

    project_id: Mapped[int] = _project_fk()
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MethodologyStatus] = _enum_column(MethodologyStatus, default=MethodologyStatus.DRAFT)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Added in Phase 7 (researchos.planning). `status` above (Phase 3's
    # DRAFT/ACTIVE/SUPERSEDED) is left untouched — it tracks *which
    # version of the project's methodology is currently in effect*.
    # `planning_status` is an independent axis: whether a human has
    # approved this specific version's content. A `DRAFT` plan is not
    # the same concept as an LLM-proposed, not-yet-reviewed candidate —
    # conflating the two would mean every regenerated draft version
    # silently counted as "approved" the moment it became ACTIVE.
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )
    methodology_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    components: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    assumptions: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    risks: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    reproducibility_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Upstream dependency + generation-time snapshot (Phase 7 spec
    # section 15): which ContributionCandidate this methodology was
    # generated from, and what its version/planning_status were AT THAT
    # TIME — so a reviewer can later tell a methodology was built on a
    # contribution that has since been revised or rejected, without the
    # system silently pretending nothing changed.
    contribution_candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "contribution_candidates.id", ondelete="SET NULL", name="fk_methodology_plans_contribution_candidate_id"
        ),
        nullable=True,
        index=True,
    )
    contribution_candidate_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contribution_candidate_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="methodology_plans")
    contribution_candidate: Mapped[Optional["ContributionCandidate"]] = relationship(
        back_populates="methodology_plans"
    )
    dataset_requirements: Mapped[list["DatasetRequirements"]] = relationship(back_populates="methodology_plan")
    experimental_designs: Mapped[list["ExperimentalDesign"]] = relationship(back_populates="methodology_plan")

    @validates("description")
    def _validate_description(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class DatasetRequirements(IDMixin, TimestampMixin, Base):
    """What the research requires from its data — a planning artifact,
    deliberately distinct from `DatasetRecord` (an actual registered/
    acquired dataset with a real `path_or_uri`). Nothing here implies a
    concrete dataset has been chosen or obtained yet.
    """

    __tablename__ = "dataset_requirements"

    project_id: Mapped[int] = _project_fk()
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )
    required_characteristics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inclusion_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exclusion_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    annotation_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    split_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    leakage_considerations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risks: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    reproducibility_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Upstream dependency + generation-time snapshot (Phase 7 spec
    # section 15).
    methodology_plan_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("methodology_plans.id", ondelete="SET NULL", name="fk_dataset_requirements_methodology_plan_id"),
        nullable=True,
        index=True,
    )
    methodology_plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    methodology_plan_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="dataset_requirements_list")
    methodology_plan: Mapped[Optional["MethodologyPlan"]] = relationship(back_populates="dataset_requirements")
    experimental_designs: Mapped[list["ExperimentalDesign"]] = relationship(back_populates="dataset_requirements")


class ExperimentalDesign(IDMixin, TimestampMixin, Base):
    """A planning artifact describing how one or more research questions
    would be tested — baselines, ablations, metrics, comparison
    strategy. Deliberately distinct from `Experiment` (Phase 3), which
    remains exclusively the execution/tracking record for an actual run;
    nothing in this phase creates, starts, or completes an `Experiment`.

    `version`/`supersedes_id` (added during the Phase 7 post-implementation
    audit remediation) work exactly like `ContributionCandidate`'s: a
    real, traceable lineage for "this design is a revised version of
    that exact prior design", distinct from an unrelated, independently-
    generated design that also happens to exist in the same project —
    see `ContributionCandidate`'s docstring for the full reasoning.
    """

    __tablename__ = "experimental_designs"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_experimental_design_supersedes"),
    )

    project_id: Mapped[int] = _project_fk()
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )
    proposed_method: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    baselines: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    ablation_studies: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    evaluation_metrics: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    comparison_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reproducibility_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risks: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("experimental_designs.id", ondelete="SET NULL", name="fk_experimental_designs_supersedes_id"),
        nullable=True,
        index=True,
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Upstream dependencies + generation-time snapshots (Phase 7 spec
    # section 15) — two independent upstream artifacts.
    methodology_plan_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("methodology_plans.id", ondelete="SET NULL", name="fk_experimental_designs_methodology_plan_id"),
        nullable=True,
        index=True,
    )
    methodology_plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    methodology_plan_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dataset_requirements_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "dataset_requirements.id",
            ondelete="SET NULL",
            name="fk_experimental_designs_dataset_requirements_id",
        ),
        nullable=True,
        index=True,
    )
    dataset_requirements_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="experimental_designs")
    methodology_plan: Mapped[Optional["MethodologyPlan"]] = relationship(back_populates="experimental_designs")
    dataset_requirements: Mapped[Optional["DatasetRequirements"]] = relationship(
        back_populates="experimental_designs"
    )

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class ExperimentalDesignQuestion(IDMixin, CreatedAtMixin, Base):
    """One (experimental design, research question) pairing — the M:N
    edge declaring which research question(s) a design addresses.
    Same plain-association-row shape as `ContributionCandidateQuestion`
    (see its docstring for why no further ORM relationships are
    declared here).
    """

    __tablename__ = "experimental_design_questions"
    __table_args__ = (
        UniqueConstraint("experimental_design_id", "research_question_id", name="uq_experimental_design_question"),
    )

    project_id: Mapped[int] = _project_fk()
    experimental_design_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experimental_designs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("research_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )


# --------------------------------------------------------------------------
# DatasetRecord
# --------------------------------------------------------------------------


class DatasetRecord(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "dataset_records"
    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_dataset_project_name_version"),)

    project_id: Mapped[int] = _project_fk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    path_or_uri: Mapped[str] = mapped_column(String(2000), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    split_information: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="datasets")
    # Phase 8A: the logical identity's immutable scientific versions.
    dataset_versions_list: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset_record", cascade="all, delete-orphan"
    )

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("path_or_uri")
    def _validate_path_or_uri(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# Phase 8A (researchos.specification): DatasetVersion, ExperimentSpecification,
# ExperimentSpecificationQuestion, ExperimentSpecificationContribution,
# BaselineSpecification
# --------------------------------------------------------------------------


class DatasetVersion(IDMixin, TimestampMixin, Base):
    """An immutable scientific version of a `DatasetRecord`'s logical
    dataset identity.

    `DatasetRecord` (Phase 3, untouched) names/registers a dataset once;
    each `DatasetVersion` is one specific, fingerprinted,
    independently-lifecycle-tracked version of it (v1, v2, v3, ...) —
    `Dataset -> v1, v2, v3` in the Phase 8A design. Versioning reuses the
    exact `supersedes_id` self-FK + `UniqueConstraint` lineage pattern
    Phase 7's post-implementation audit established for
    `ContributionCandidate`/`ExperimentalDesign` (see those classes'
    docstrings) — not reinvented here.

    `lifecycle_status` is a separate vocabulary from `PlanningApprovalStatus`
    (see `DatasetLifecycleStatus`) because a dataset version passes
    through deterministic, machine-checkable validation
    (`researchos.specification.validators`) before human approval is
    even meaningful — unlike every other Phase 7 planning artifact.
    `APPROVED` never means "scientifically valid research evidence,"
    only "approved for system use under this project's defined process."
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_dataset_version_supersedes"),
    )

    project_id: Mapped[int] = _project_fk()
    dataset_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dataset_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("dataset_versions.id", ondelete="SET NULL", name="fk_dataset_versions_supersedes_id"),
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_uri: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sample_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Structured scientific metadata as validated JSON rather than a
    # column per field, matching Phase 7's precedent for `components`/
    # `assumptions`/`risks` on MethodologyPlan/ExperimentalDesign.
    split_definition: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    class_definition: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    preprocessing_definition: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    augmentation_definition: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Deterministic, canonicalization-based fingerprints — see
    # researchos.specification.fingerprint. sha256 hex digests (64 chars).
    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    metadata_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    lifecycle_status: Mapped[DatasetLifecycleStatus] = _enum_column(
        DatasetLifecycleStatus, default=DatasetLifecycleStatus.DRAFT, create_constraint=True
    )
    # The most recent researchos.specification.validators result —
    # {"is_valid": bool, "errors": [...], "warnings": [...], "format": ...}.
    # A history of every validation run is not kept; only the current one.
    validation_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="dataset_versions")
    dataset_record: Mapped["DatasetRecord"] = relationship(back_populates="dataset_versions_list")
    experiment_specifications: Mapped[list["ExperimentSpecification"]] = relationship(
        back_populates="dataset_version"
    )

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)

    @validates("sample_count")
    def _validate_sample_count(self, key: str, value: Optional[int]) -> Optional[int]:
        return _validate_nonnegative_int(value, key)


class ExperimentSpecification(IDMixin, TimestampMixin, Base):
    """A concrete, executable configuration grounded in approved
    upstream planning artifacts — the execution-ready artifact Phase 8A
    exists to produce. Deliberately distinct from:

    - `ExperimentalDesign` (Phase 7) — the scientific design (baselines,
      ablations, metrics as a description) this specification implements.
    - `Experiment` (Phase 3) — the research experiment *concept/identity*
      a specification implements (e.g. "Baseline RetinaNet experiment").
      `experiment_id` (Phase 8B-3) is that link — nullable/`SET NULL`,
      exactly like every other upstream FK on this table, since a
      specification is not exclusively owned by its `Experiment` (it
      keeps its own project scope, approval, and version lineage
      regardless of what happens to that row). `researchos.execution.
      integration.create_run_from_specification` requires it to be set
      (raising a typed error otherwise) — a `Run` is always created for
      a specific, identified research experiment, never an anonymous one.

    `configuration` is a validated, domain-agnostic JSON document — no
    ML-specific fields (learning_rate, batch_size, epochs, ...) are
    hardcoded into the schema, since ResearchOS must support CV, NLP,
    systems research, and software engineering alike.
    `configuration_hash` is a deterministic canonical hash (see
    `researchos.specification.fingerprint`) so two specifications with
    identical configuration content but differently-ordered JSON keys
    are recognized as identical.

    Versioning reuses the exact `supersedes_id` pattern `DatasetVersion`/
    `ContributionCandidate`/`ExperimentalDesign` all use.
    """

    __tablename__ = "experiment_specifications"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_experiment_specification_supersedes"),
    )

    project_id: Mapped[int] = _project_fk()
    experiment_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("experiments.id", ondelete="SET NULL", name="fk_experiment_specifications_experiment_id"),
        nullable=True,
        index=True,
    )
    experimental_design_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "experimental_designs.id", ondelete="SET NULL", name="fk_experiment_specifications_experimental_design_id"
        ),
        nullable=True,
        index=True,
    )
    methodology_plan_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "methodology_plans.id", ondelete="SET NULL", name="fk_experiment_specifications_methodology_plan_id"
        ),
        nullable=True,
        index=True,
    )
    dataset_version_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("dataset_versions.id", ondelete="SET NULL", name="fk_experiment_specifications_dataset_version_id"),
        nullable=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "experiment_specifications.id",
            ondelete="SET NULL",
            name="fk_experiment_specifications_supersedes_id",
        ),
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    configuration: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    configuration_schema_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    configuration_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    planning_status: Mapped[PlanningApprovalStatus] = _enum_column(
        PlanningApprovalStatus, default=PlanningApprovalStatus.CANDIDATE, create_constraint=True
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Generation-time upstream snapshots (Phase 7 spec section 15
    # pattern) — three independent upstream artifacts, each a sibling
    # id/version/status_at_generation triple, never only the live FK.
    experimental_design_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experimental_design_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    methodology_plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    methodology_plan_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dataset_version_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dataset_version_status_at_generation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="experiment_specifications")
    experiment: Mapped[Optional["Experiment"]] = relationship(back_populates="experiment_specifications")
    experimental_design: Mapped[Optional["ExperimentalDesign"]] = relationship()
    methodology_plan: Mapped[Optional["MethodologyPlan"]] = relationship()
    dataset_version: Mapped[Optional["DatasetVersion"]] = relationship(back_populates="experiment_specifications")
    baselines: Mapped[list["BaselineSpecification"]] = relationship(
        back_populates="experiment_specification", cascade="all, delete-orphan"
    )

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class ExperimentSpecificationQuestion(IDMixin, CreatedAtMixin, Base):
    """One (experiment specification, research question) pairing — the
    M:N edge declaring which research question(s) a specification
    addresses. Same plain-association-row shape as
    `ContributionCandidateQuestion`/`ExperimentalDesignQuestion` (see
    their docstrings for why no further ORM relationships are declared
    here)."""

    __tablename__ = "experiment_specification_questions"
    __table_args__ = (
        UniqueConstraint(
            "experiment_specification_id", "research_question_id", name="uq_experiment_specification_question"
        ),
    )

    project_id: Mapped[int] = _project_fk()
    experiment_specification_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_specifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("research_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ExperimentSpecificationContribution(IDMixin, CreatedAtMixin, Base):
    """One (experiment specification, contribution candidate) pairing —
    the M:N edge declaring which contribution(s) a specification
    supports. A `ContributionCandidate` is not tied to exactly one
    specification, and a specification is not tied to exactly one
    contribution."""

    __tablename__ = "experiment_specification_contributions"
    __table_args__ = (
        UniqueConstraint(
            "experiment_specification_id", "contribution_candidate_id",
            name="uq_experiment_specification_contribution",
        ),
    )

    project_id: Mapped[int] = _project_fk()
    experiment_specification_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_specifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contribution_candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contribution_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )


class BaselineSpecification(IDMixin, CreatedAtMixin, Base):
    """A named baseline one `ExperimentSpecification` intends to compare
    against, with structured fields (`Phase 7`'s
    `ExperimentalDesign.baselines` is only an unstructured list of
    strings, not adequate for this). Purely descriptive planning
    metadata — Phase 8A never executes a baseline, and no specific ML
    baseline is hardcoded anywhere in ResearchOS; every baseline here is
    caller-supplied.
    """

    __tablename__ = "baseline_specifications"

    project_id: Mapped[int] = _project_fk()
    experiment_specification_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_specifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    implementation_reference: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    configuration: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    experiment_specification: Mapped["ExperimentSpecification"] = relationship(back_populates="baselines")

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# Experiment + ExperimentResult
# --------------------------------------------------------------------------


class Experiment(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "experiments"

    project_id: Mapped[int] = _project_fk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ExperimentStatus] = _enum_column(ExperimentStatus, default=ExperimentStatus.PLANNED)
    code_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dataset_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    configuration: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    random_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hardware: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="experiments")
    results: Mapped[list["ExperimentResult"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    # Phase 8B-1: researchos.execution. Experiment X -> Run 1, Run 2, ...
    runs: Mapped[list["Run"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    # Phase 8B-3: researchos.execution.integration. Not cascading — a
    # SET NULL FK, matching every other upstream link on
    # ExperimentSpecification (it is not exclusively owned by its
    # Experiment; see that class's own docstring).
    experiment_specifications: Mapped[list["ExperimentSpecification"]] = relationship(back_populates="experiment")

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


class ExperimentResult(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "experiment_results"

    experiment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deliberately no uniqueness constraint on (experiment_id, metric_name):
    # repeated measurements of the same metric (e.g. per-epoch loss) are a
    # legitimate, expected use case, not a data-integrity violation.
    metric_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    metric_unit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)

    experiment: Mapped["Experiment"] = relationship(back_populates="results")

    @validates("metric_name")
    def _validate_metric_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("metric_value")
    def _validate_metric_value(self, key: str, value: float) -> float:
        return _validate_finite_number(value, key)


# --------------------------------------------------------------------------
# Phase 8B-1 (researchos.execution): Run, EnvironmentSnapshot, ArtifactMetadata
#
# Experiment (above) remains the scientific *concept*; a Run is one
# actual execution instance of it — Experiment X -> Run 1, Run 2, Run
# 3, .... This phase deliberately does not add anything to Experiment
# itself (see docs/PHASE8B1_EXECUTION_FOUNDATION.md for why "Experiment
# != Run" is kept as two tables rather than folding Run's columns onto
# Experiment or repurposing Experiment's own pre-existing
# status/started_at/completed_at columns, which stay exactly as Phase
# 3 left them).
# --------------------------------------------------------------------------


class EnvironmentSnapshot(IDMixin, CreatedAtMixin, Base):
    """The environment ACTUALLY USED by one or more `Run`s — never the
    environment an `ExperimentSpecification` merely expects (that
    distinction is load-bearing: see
    docs/PHASE8B1_EXECUTION_FOUNDATION.md's Environment Provenance
    section). Content-addressable and deliberately NOT project-scoped:
    it describes a physical/virtual machine's software stack, which is
    a fact about the world, not about any one project, and the same
    machine's snapshot is legitimately shared by `Run`s across
    different projects rather than duplicated per project (contrast
    with every other Phase 8B-1 entity, which is caught by the
    "Project A Run -> Project B X" isolation check precisely because
    it does *not* apply here).

    `environment_hash` is a deterministic sha256 of the canonicalized
    fields below (`researchos.execution.environment_snapshot`, same
    canonicalization convention as
    `researchos.specification.fingerprint`) — collected once per
    distinct environment and reused by every `Run` that reports an
    identical one, rather than inserting a duplicate row per `Run`.
    """

    __tablename__ = "environment_snapshots"
    __table_args__ = (UniqueConstraint("environment_hash", name="uq_environment_snapshot_hash"),)

    environment_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    os_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    architecture: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    python_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pytorch_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    torchvision_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cuda_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cudnn_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gpu_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    gpu_driver_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Normalized {package_name: version} — never raw `pip freeze` text,
    # never anything resembling an environment *variable* dump (no
    # secrets live in installed-package version strings).
    package_versions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Phase 8B-2: best-effort hardware facts, never required for a CPU
    # execution to proceed — see researchos.execution.environment_snapshot.
    cpu_model: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cpu_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_memory_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    researchos_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    runs: Mapped[list["Run"]] = relationship(back_populates="environment_snapshot")

    @validates("environment_hash")
    def _validate_environment_hash(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


class Run(IDMixin, TimestampMixin, Base):
    """One actual execution instance of an `Experiment`, produced from
    one approved `ExperimentSpecification` against one approved
    `DatasetVersion`. Immutable once it reaches a terminal `RunStatus`
    (see `RunStatus`'s own docstring and
    `researchos.execution.runs`'s service-level enforcement) — a
    repeated or corrected execution is always a *new* `Run` row, never
    a mutation of this one (`Run` is not a versioned artifact the way
    `DatasetVersion`/`ExperimentSpecification` are; see
    docs/PHASE8B1_EXECUTION_FOUNDATION.md's Reproducibility Model).

    No separate `ExecutionRequest` table exists: this row itself *is*
    the execution request, created in `RunStatus.CREATED` with its
    full intended provenance already captured, and
    `researchos.execution.approval`'s `EXECUTION_APPROVAL:<run_id>`
    gate is exactly what authorizes the `CREATED -> QUEUED` transition
    that lets it actually run. A dedicated entity would be 1:1 with
    this one and consumed immediately on approval, so it was left out
    rather than added for theoretical symmetry with `DatasetVersion`/
    `ExperimentSpecification` (which are genuinely independent,
    long-lived, multiply-referenced artifacts).

    Every `_version`/`_status_at_execution` pair below is a generation-
    time-style snapshot (same pattern `ExperimentSpecification` uses
    for its own upstream artifacts) captured once, at `Run` creation —
    named `..._at_execution` rather than `..._at_generation` because
    nothing about creating a `Run` is an LLM generation step.
    """

    __tablename__ = "runs"

    project_id: Mapped[int] = _project_fk()
    experiment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_specification_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("experiment_specifications.id", ondelete="SET NULL", name="fk_runs_experiment_specification_id"),
        nullable=True,
        index=True,
    )
    dataset_version_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("dataset_versions.id", ondelete="SET NULL", name="fk_runs_dataset_version_id"),
        nullable=True,
        index=True,
    )
    environment_snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("environment_snapshots.id", ondelete="SET NULL", name="fk_runs_environment_snapshot_id"),
        nullable=True,
        index=True,
    )
    status: Mapped[RunStatus] = _enum_column(RunStatus, default=RunStatus.CREATED, create_constraint=True)
    execution_backend: Mapped[ExecutionBackend] = _enum_column(
        ExecutionBackend, default=ExecutionBackend.LOCAL_PYTHON, create_constraint=True
    )
    # A structured, validated description of what would run — never a
    # shell string. See researchos.execution.contracts.PythonModuleTarget.
    execution_target: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # --- Specification provenance snapshot (captured at Run creation) ---
    experiment_specification_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experiment_specification_status_at_execution: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    configuration_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    configuration_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # --- Dataset provenance snapshot (captured at Run creation) ---
    dataset_version_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dataset_version_status_at_execution: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    dataset_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # --- Code provenance (never fabricated; see researchos.execution.git_provenance) ---
    code_repository: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    code_commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    code_branch: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    working_tree_clean: Mapped[Optional[bool]] = mapped_column(nullable=True)
    # Set exactly when code_commit is None because it genuinely could
    # not be determined (not a git repository, git unavailable, ...) —
    # never left ambiguous between "not tracked" and "tried and failed".
    code_provenance_unavailable_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Execution outcome ---
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stdout_reference: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    stderr_reference: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="runs")
    experiment: Mapped["Experiment"] = relationship(back_populates="runs")
    experiment_specification: Mapped[Optional["ExperimentSpecification"]] = relationship()
    dataset_version: Mapped[Optional["DatasetVersion"]] = relationship()
    environment_snapshot: Mapped[Optional["EnvironmentSnapshot"]] = relationship(back_populates="runs")
    artifacts: Mapped[list["ArtifactMetadata"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="run", cascade="all, delete-orphan")

    @validates("timeout_seconds")
    def _validate_timeout_seconds(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class ArtifactMetadata(IDMixin, CreatedAtMixin, Base):
    """Metadata about one file a `Run` produced — never the file's
    bytes. `reference` is a path/URI the caller is responsible for
    actually being able to resolve later; ResearchOS itself never
    reads artifact contents back through this table, only records
    what a `Run` produced and a hash to verify it later.

    `logical_name` (Phase 8B-2) identifies one artifact within its
    `Run` — `"stdout"`, `"stderr"`, `"result_manifest"`, a caller-given
    name for a checkpoint, etc. `UniqueConstraint(run_id, logical_name)`
    makes a duplicate registration attempt a database-level integrity
    error rather than a silent overwrite — `ArtifactMetadata` rows are
    create-only; `researchos.db.repository` deliberately exposes no
    `update_artifact_metadata` function at all (see
    docs/PHASE8B2_ACTUAL_EXECUTION_ARTIFACTS_METRICS.md's Artifact
    Model section).
    """

    __tablename__ = "artifact_metadata"
    __table_args__ = (UniqueConstraint("run_id", "logical_name", name="uq_artifact_metadata_run_logical_name"),)

    project_id: Mapped[int] = _project_fk()
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    logical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_type: Mapped[ArtifactType] = _enum_column(ArtifactType, default=ArtifactType.OTHER, create_constraint=True)
    reference: Mapped[str] = mapped_column(String(2000), nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="artifacts")

    @validates("logical_name")
    def _validate_logical_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("reference")
    def _validate_reference(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("size_bytes")
    def _validate_size_bytes(self, key: str, value: Optional[int]) -> Optional[int]:
        return _validate_nonnegative_int(value, key)


class Metric(IDMixin, CreatedAtMixin, Base):
    """One structured, machine-reported measurement produced by a `Run`
    — never inferred from stdout text (see
    `researchos.execution.metrics`'s module docstring for why). Rows
    are append-only: `researchos.db.repository` exposes no
    `update_metric` function, so a correction is always a new `Metric`
    row, never a silent overwrite of a completed run's scientific
    record (Phase 8B-2 spec section 25).

    Deliberately no uniqueness constraint on `(run_id, name)`: the same
    metric name legitimately recurs across splits (`train`/`val`/
    `test`), multiple evaluation passes, or repeated measurements
    within one `Run` — exactly like `ExperimentResult.metric_name`
    (Phase 3) already established for the same reason.

    `value` is stored as `Float` (IEEE-754 double), not `Decimal`:
    metric values (accuracy, loss, latency, ...) are empirical,
    already-approximate measurements, not exact quantities like
    currency where `Decimal`'s exact base-10 arithmetic would matter —
    using `Decimal` here would falsely imply a precision the underlying
    measurement does not have. `value_type` (`MetricValueType`)
    preserves the one piece of information plain `Float` storage would
    otherwise lose: whether the caller reported an integer count (e.g.
    `epoch=5`) or a continuous measurement (e.g. `accuracy=0.953`).
    `researchos.execution.metrics.validate_metrics_manifest` rejects
    non-finite (`NaN`/`+-Infinity`) values outright at write time — see
    that module's docstring for the explicit policy.
    """

    __tablename__ = "metrics"

    project_id: Mapped[int] = _project_fk()
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    value: Mapped[float] = mapped_column(nullable=False)
    value_type: Mapped[MetricValueType] = _enum_column(
        MetricValueType, default=MetricValueType.FLOAT, create_constraint=True
    )
    unit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    split: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    aggregation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(nullable=True)
    evaluation_protocol: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_artifact_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("artifact_metadata.id", ondelete="SET NULL", name="fk_metrics_source_artifact_id"),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="metrics")
    source_artifact: Mapped[Optional["ArtifactMetadata"]] = relationship()

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("value")
    def _validate_value(self, key: str, value: float) -> float:
        return _validate_finite_number(value, key)

    @validates("threshold")
    def _validate_threshold(self, key: str, value: Optional[float]) -> Optional[float]:
        # Optional, unlike `value` — a NaN/Infinity threshold is
        # rejected exactly like a NaN/Infinity value (same rationale,
        # same helper), but omitting a threshold entirely is normal.
        if value is None:
            return None
        return _validate_finite_number(value, key)


# --------------------------------------------------------------------------
# Phase 8 (researchos.analysis): AnalysisRecord, AnalysisInput,
# ScientificClaim, ScientificClaimAnalysis, ScientificReview
#
# Distinct from Phase 6's `LiteratureAnalysis`/`AnalysisClaim`, which
# analyze *literature* — these analyze *execution facts* (Run/Metric/
# ArtifactMetadata). Distinct from Phase 3's `ExperimentResult`, which
# is a raw recorded measurement (superseded in that role by Phase
# 8B-2's `Metric` for anything execution-produced) — an
# `AnalysisRecord` is always a *computation over* already-recorded
# facts, never a fact itself.
# --------------------------------------------------------------------------


class AnalysisRecord(IDMixin, CreatedAtMixin, Base):
    """One deterministic computation over already-recorded execution
    facts (`Run`/`Metric`/`ArtifactMetadata`) — LEVEL 2 in the Phase 8
    spec's four-level model (OBSERVATION -> COMPUTATION ->
    INTERPRETATION -> SCIENTIFIC CONCLUSION). Never itself a scientific
    conclusion: "Run B's accuracy is 0.05 higher than Run A's" is
    exactly what this table records; "Run B is scientifically better"
    is not, and nothing in `researchos.analysis` ever writes that
    sentence into a database column.

    Append-only, like `Metric`/`AuditEvent` — `researchos.db.repository`
    exposes no `update_analysis_record` function. `version`/
    `supersedes_id` reuse the exact unbranching-lineage pattern
    `DatasetVersion`/`ExperimentSpecification`/`ContributionCandidate`
    all use: if an analysis is redone with different parameters or
    against changed source data, that is always a *new* `AnalysisRecord`
    row, optionally pointing `supersedes_id` at the one it replaces —
    never a mutation of the original (Phase 8 spec sections 9-10).

    `method` is a free-form string (matching this codebase's existing
    "free-form vocabulary field" convention for `ResearchQuestion.type`/
    `LiteratureItem.source` — see the design notes at the top of this
    file) rather than a fixed `CHECK`-constrained enum, since
    `researchos.analysis.numeric` is deliberately open-ended (mean,
    median, absolute/relative difference, standard deviation, ...) and
    a new deterministic method must never require a migration to add.
    `status` is the one place a real branch exists:
    `AnalysisRecordStatus.NOT_COMPARABLE` is itself a valid, persisted
    computed fact (produced by `researchos.analysis.comparability`),
    not an error — a genuinely invalid request (NaN input, empty
    population, ...) is rejected before any row is ever written (see
    `researchos.analysis.errors`), so every row that exists here
    represents a real, completed computation attempt of one kind or
    the other.
    """

    __tablename__ = "analysis_records"
    __table_args__ = (UniqueConstraint("supersedes_id", name="uq_analysis_record_supersedes"),)

    project_id: Mapped[int] = _project_fk()
    method: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    parameters: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[AnalysisRecordStatus] = _enum_column(
        AnalysisRecordStatus, default=AnalysisRecordStatus.COMPLETED, create_constraint=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("analysis_records.id", ondelete="SET NULL", name="fk_analysis_records_supersedes_id"),
        nullable=True,
        index=True,
    )
    # Reproducibility metadata (Phase 8 spec section 25) — e.g.
    # {"researchos": "0.0.1", "numpy": "..."} — deliberately a generic
    # dict, mirroring EnvironmentSnapshot.package_versions, since which
    # library (if any) a given `method` depends on varies per method.
    software_versions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="analysis_records")
    inputs: Mapped[list["AnalysisInput"]] = relationship(back_populates="analysis_record", cascade="all, delete-orphan")

    @validates("method")
    def _validate_method(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class AnalysisInput(IDMixin, CreatedAtMixin, Base):
    """One (input_type, input_id) pointing at the exact `Run`/`Metric`/
    `ArtifactMetadata` row one `AnalysisRecord` was computed from —
    polymorphic by convention, the same pattern `EvidenceLink.subject_id`
    already established (see `AnalysisInputType`). Never "the latest
    Run" or any other implicit reference (Phase 8 spec section 8):
    every input this analysis actually used is an explicit row here.
    """

    __tablename__ = "analysis_inputs"
    __table_args__ = (
        UniqueConstraint("analysis_record_id", "input_type", "input_id", name="uq_analysis_input_identity"),
    )

    project_id: Mapped[int] = _project_fk()
    analysis_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    input_type: Mapped[AnalysisInputType] = _enum_column(
        AnalysisInputType, default=AnalysisInputType.RUN, create_constraint=True
    )
    input_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="analysis_inputs")
    analysis_record: Mapped["AnalysisRecord"] = relationship(back_populates="inputs")


class ScientificClaim(IDMixin, TimestampMixin, Base):
    """A candidate (or human-approved) interpretive statement about
    what the recorded evidence may suggest — LEVEL 3 in the Phase 8
    four-level model. Distinct from Phase 6's `AnalysisClaim` (a
    *literature-synthesis* claim tied to one `LiteratureAnalysis`
    run) — this is an *experimental-evidence* claim tied to
    `AnalysisRecord`/`Run`/`Metric` evidence via
    `ScientificClaimAnalysis`/`EvidenceLink`.

    `strength` (`ClaimStrength`) is the evidence-assessment outcome a
    `ScientificReview` sets — never a declaration that the claim is
    universally true. `approval_status` reuses Phase 6's
    `ClaimApprovalStatus` directly (the same candidate -> human-decision
    shape `AnalysisClaim.approval_status` already uses) rather than a
    fourth near-identical enum — human approval of a claim is a
    completely ordinary "has a human signed off on this" gate, exactly
    like every prior phase's. An LLM may set `strength` to anything
    *except* imply approval, and may never set `approval_status` to
    `APPROVED` itself (enforced by `researchos.analysis.approval`, not
    by this column).

    Versioned exactly like `AnalysisRecord`/`DatasetVersion`: a claim
    revised in light of new evidence is a new row, `supersedes_id`
    pointing at the one it refines — the prior claim's own history is
    never overwritten.
    """

    __tablename__ = "scientific_claims"
    __table_args__ = (UniqueConstraint("supersedes_id", name="uq_scientific_claim_supersedes"),)

    project_id: Mapped[int] = _project_fk()
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    strength: Mapped[ClaimStrength] = _enum_column(ClaimStrength, default=ClaimStrength.NOT_ASSESSABLE, create_constraint=True)
    approval_status: Mapped[ClaimApprovalStatus] = _enum_column(
        ClaimApprovalStatus, default=ClaimApprovalStatus.PENDING_REVIEW, create_constraint=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("scientific_claims.id", ondelete="SET NULL", name="fk_scientific_claims_supersedes_id"),
        nullable=True,
        index=True,
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="scientific_claims")
    supporting_analyses: Mapped[list["ScientificClaimAnalysis"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ScientificReview"]] = relationship(back_populates="claim", cascade="all, delete-orphan")

    @validates("claim_text")
    def _validate_claim_text(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("confidence")
    def _validate_confidence(self, key: str, value: Optional[float]) -> Optional[float]:
        return _validate_unit_interval(value, key)

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


class ScientificClaimAnalysis(IDMixin, CreatedAtMixin, Base):
    """One (claim, analysis_record) edge — which computed analyses a
    `ScientificClaim` actually rests on. Plain association row, the
    same shape `ContributionCandidateQuestion`/`ExperimentSpecificationQuestion`
    already established (own `project_id`, two `CASCADE` FKs, a
    `UniqueConstraint` on the pair, no further ORM relationships)."""

    __tablename__ = "scientific_claim_analyses"
    __table_args__ = (
        UniqueConstraint("claim_id", "analysis_record_id", name="uq_scientific_claim_analysis"),
    )

    project_id: Mapped[int] = _project_fk()
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scientific_claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_records.id", ondelete="CASCADE"), nullable=False, index=True
    )

    claim: Mapped["ScientificClaim"] = relationship(back_populates="supporting_analyses")


class ScientificReview(IDMixin, TimestampMixin, Base):
    """Whether the evidence currently available adequately supports one
    `ScientificClaim` — NOT code review, NOT execution review, NOT
    metric calculation (Phase 8 spec section 14). `dimensions` holds
    the structured, per-dimension assessment (evidence completeness,
    experimental consistency, dataset consistency, metric
    appropriateness, baseline adequacy, ablation coverage,
    reproducibility, statistical support, threats to validity, claim
    strength, alternative explanations, missing evidence) as one
    validated JSON document — matching this codebase's established
    "structured scientific content as validated JSON, not one column
    per field" convention (`MethodologyPlan`/`ExperimentalDesign`).

    `status` (`ScientificReviewStatus`) is the review's own lifecycle,
    deliberately distinct from `ScientificClaim.approval_status` — a
    review can be `HUMAN_APPROVED` (the evidence assessment itself is
    sound) without that alone making the claim `APPROVED`; `
    researchos.analysis.claims.approve_scientific_claim` requires at
    least one `HUMAN_APPROVED` review to exist before a claim may be
    approved (Phase 8 spec section 14's own framing: review is what
    the claim approval decision is based on).
    """

    __tablename__ = "scientific_reviews"
    __table_args__ = (UniqueConstraint("supersedes_id", name="uq_scientific_review_supersedes"),)

    project_id: Mapped[int] = _project_fk()
    claim_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scientific_claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScientificReviewStatus] = _enum_column(
        ScientificReviewStatus, default=ScientificReviewStatus.DRAFT, create_constraint=True
    )
    dimensions: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("scientific_reviews.id", ondelete="SET NULL", name="fk_scientific_reviews_supersedes_id"),
        nullable=True,
        index=True,
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    prompt_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="scientific_reviews")
    claim: Mapped["ScientificClaim"] = relationship(back_populates="reviews")

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


# --------------------------------------------------------------------------
# Manuscript
# --------------------------------------------------------------------------


class Manuscript(IDMixin, TimestampMixin, Base):
    __tablename__ = "manuscripts"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_manuscript_project_version"),)

    project_id: Mapped[int] = _project_fk()
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ManuscriptStatus] = _enum_column(ManuscriptStatus, default=ManuscriptStatus.DRAFTING)
    file_path: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="manuscripts")

    @validates("title")
    def _validate_title(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("version")
    def _validate_version(self, key: str, value: int) -> int:
        return _validate_positive_int(value, key)


# --------------------------------------------------------------------------
# JournalCandidate
# --------------------------------------------------------------------------


class JournalCandidate(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "journal_candidates"

    project_id: Mapped[int] = _project_fk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[JournalCandidateStatus] = _enum_column(
        JournalCandidateStatus, default=JournalCandidateStatus.CANDIDATE
    )

    project: Mapped["ResearchProject"] = relationship(back_populates="journal_candidates")

    @validates("name")
    def _validate_name(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# Approval
# --------------------------------------------------------------------------


class Approval(IDMixin, Base):
    __tablename__ = "approvals"

    project_id: Mapped[int] = _project_fk()
    stage: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[ApprovalDecision] = _enum_column(ApprovalDecision, default=ApprovalDecision.PENDING)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="approvals")

    @validates("stage")
    def _validate_stage(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)


# --------------------------------------------------------------------------
# AuditEvent
# --------------------------------------------------------------------------


class AuditEvent(IDMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"

    project_id: Mapped[int] = _project_fk()
    event_type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)

    project: Mapped["ResearchProject"] = relationship(back_populates="audit_events")

    @validates("event_type")
    def _validate_event_type(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)

    @validates("actor")
    def _validate_actor(self, key: str, value: str) -> str:
        return _require_nonblank(value, key)
