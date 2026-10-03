"""ORM -> Pydantic response mapping.

Pure data-transfer-object assembly — no business rule, no status
computation beyond what the ORM row already records, no database
write. Every function here takes an already-fetched SQLAlchemy `Session`
and ORM object(s) and returns the corresponding response schema. This
is the one place field-name/shape differences between the ORM and the
public API contract are reconciled (e.g. `Metric.metadata_`'s Python
attribute name vs. the `metadata` the API exposes), so route handlers
stay a one-line call.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import (
    AnalysisRecord,
    ArtifactMetadata,
    AuditEvent,
    ContributionCandidate,
    Experiment,
    LiteratureItem,
    Metric,
    NoveltyAssessment,
    ResearchGap,
    ResearchQuestion,
    ResearchProject,
    Run,
    ScientificClaim,
    ScientificReview,
)
from researchos.db.models import EvidenceSubjectType

from ..schemas.analysis import AnalysisInputResponse, AnalysisRecordResponse
from ..schemas.audit import AuditEventResponse
from ..schemas.experiments import ExperimentResponse
from ..schemas.gaps import ResearchGapResponse
from ..schemas.planning import ContributionCandidateResponse
from ..schemas.project import ProjectResponse
from ..schemas.reviews import ScientificClaimResponse, ScientificReviewResponse
from ..schemas.runs import ArtifactResponse, EnvironmentSnapshotResponse, MetricResponse, RunResponse


def to_project_response(project: ResearchProject) -> ProjectResponse:
    return ProjectResponse.model_validate(project)


def to_gap_response(session: Session, gap: ResearchGap) -> ResearchGapResponse:
    evidence_count = len(
        repository.list_evidence_links(
            session, gap.project_id, subject_type=EvidenceSubjectType.GAP_CANDIDATE, subject_id=gap.id
        )
    )
    return ResearchGapResponse(
        id=gap.id,
        project_id=gap.project_id,
        statement=gap.statement,
        status=gap.status.value,
        gap_type=gap.gap_type,
        affected_research_area=gap.affected_research_area,
        evidence_summary=gap.evidence_summary,
        confidence=gap.confidence,
        research_question_id=gap.research_question_id,
        evidence_count=evidence_count,
        created_at=gap.created_at,
        updated_at=gap.updated_at,
    )


def to_novelty_response(assessment: NoveltyAssessment):
    from ..schemas.novelty import NoveltyAssessmentResponse

    return NoveltyAssessmentResponse.model_validate(assessment)


def to_contribution_response(session: Session, contribution: ContributionCandidate) -> ContributionCandidateResponse:
    links = repository.list_contribution_candidate_questions(
        session, contribution.project_id, contribution_candidate_id=contribution.id
    )
    response = ContributionCandidateResponse.model_validate(contribution)
    response.cited_research_question_ids = [link.research_question_id for link in links]
    return response


def to_experiment_response(session: Session, experiment: Experiment) -> ExperimentResponse:
    runs = repository.list_runs(session, experiment.project_id, experiment_id=experiment.id)
    return ExperimentResponse(
        id=experiment.id,
        project_id=experiment.project_id,
        name=experiment.name,
        description=experiment.description,
        status=experiment.status.value,
        code_version=experiment.code_version,
        dataset_version=experiment.dataset_version,
        random_seed=experiment.random_seed,
        hardware=experiment.hardware,
        started_at=experiment.started_at,
        completed_at=experiment.completed_at,
        created_at=experiment.created_at,
        run_count=len(runs),
        specification_count=len(experiment.experiment_specifications),
    )


def to_artifact_response(artifact: ArtifactMetadata) -> ArtifactResponse:
    return ArtifactResponse.model_validate(artifact)


def to_metric_response(metric: Metric) -> MetricResponse:
    return MetricResponse.model_validate(metric)


def to_run_response(session: Session, run: Run, *, include_children: bool = True) -> RunResponse:
    response = RunResponse.model_validate(run)
    if include_children:
        if run.environment_snapshot_id is not None:
            snapshot = repository.get_environment_snapshot(session, run.environment_snapshot_id)
            if snapshot is not None:
                response.environment = EnvironmentSnapshotResponse.model_validate(snapshot)
        artifacts = repository.list_artifact_metadata(session, run.project_id, run_id=run.id)
        response.artifacts = [to_artifact_response(a) for a in artifacts]
        metrics = repository.list_metrics(session, run.project_id, run_id=run.id)
        response.metrics = [to_metric_response(m) for m in metrics]
    return response


def to_analysis_record_response(record: AnalysisRecord) -> AnalysisRecordResponse:
    response = AnalysisRecordResponse.model_validate(record)
    response.inputs = [AnalysisInputResponse.model_validate(i) for i in record.inputs]
    return response


def to_scientific_review_response(review: ScientificReview) -> ScientificReviewResponse:
    return ScientificReviewResponse.model_validate(review)


def to_scientific_claim_response(session: Session, claim: ScientificClaim) -> ScientificClaimResponse:
    links = repository.list_scientific_claim_analyses(session, claim.project_id, claim_id=claim.id)
    reviews = repository.list_scientific_reviews(session, claim.project_id, claim_id=claim.id)
    response = ScientificClaimResponse.model_validate(claim)
    response.supporting_analysis_record_ids = [link.analysis_record_id for link in links]
    response.reviews = [to_scientific_review_response(r) for r in reviews]
    return response


def to_audit_event_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        project_id=event.project_id,
        event_type=event.event_type,
        actor=event.actor,
        description=event.description,
        metadata=event.metadata_,
        created_at=event.created_at,
    )
