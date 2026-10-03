"""Seeds an isolated, temporary SQLite database with one small,
obviously-synthetic project (never anything resembling real research
data — see Dashboard V1 spec section 24) and starts the real FastAPI
app against it. Used by the Playwright e2e smoke test
(playwright.config.ts's `e2e:api` webServer) and for manual Dashboard
testing (`npm run e2e:api` from apps/dashboard/frontend) — never used
in production, and never imported by application code.

The seed data deliberately touches every stage of the pipeline this
project's own domain layers already model (Literature -> Gap ->
Novelty -> Planning chain -> Dataset -> Experiment Specification ->
Runs -> Metrics -> Analysis -> Scientific Claim -> Scientific Review ->
Approvals -> Audit Log) so every Dashboard page has real, non-empty
content to exercise manually — never fabricated by writing directly
into a schema the domain layer doesn't itself produce; every row here
is created through the same `researchos.db.repository`/
`researchos.analysis` functions the real application uses.
"""

from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from researchos.db import repository  # noqa: E402
from researchos.db.engine import create_db_engine  # noqa: E402
from researchos.db.migrate import init_db  # noqa: E402
from researchos.db.models import (  # noqa: E402
    ArtifactType,
    DatasetLifecycleStatus,
    EvidenceRelationship,
    EvidenceSubjectType,
    GapStatus,
    MetricValueType,
    NoveltyCandidateStatus,
    PlanningApprovalStatus,
    RunStatus,
    ScientificReviewStatus,
)

_tmp_dir = tempfile.mkdtemp(prefix="researchos_e2e_")
_db_path = Path(_tmp_dir) / "e2e.db"
_db_url = f"sqlite:///{_db_path.as_posix()}"


def _cleanup() -> None:
    try:
        _db_path.unlink(missing_ok=True)
        Path(_tmp_dir).rmdir()
    except OSError:
        pass


atexit.register(_cleanup)

init_db(_db_url)
engine = create_db_engine(_db_url)
Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# ===========================================================================
# Base seed: project, literature, gap, novelty, planning chain, dataset,
# experiment specification, runs, metrics, artifacts, approvals.
# ===========================================================================
with Session() as session:
    project = repository.create_project(
        session, title="E2E Smoke Test Project",
        description="Synthetic data for manual Dashboard testing and the Playwright smoke test — never real research.",
    )
    pid = project.id

    # --- Literature -------------------------------------------------------
    lit1 = repository.add_literature_item(
        session, project_id=pid, title="A Synthetic Survey of Widget Durability Methods",
        authors="A. Synthetic, B. Fixture", year=2023, venue="Journal of Fake Results", source="openalex",
        source_record_id="W-E2E-0001", doi="10.9999/e2e-fixture-0001", abstract="A fully synthetic abstract for Dashboard testing only.",
        citation_count=12, metadata_completeness=0.9,
    )
    lit2 = repository.add_literature_item(
        session, project_id=pid, title="Revisiting Widget Alloys: A Synthetic Follow-Up",
        authors="C. Fixture", year=2024, venue="Fake Materials Letters", source="crossref",
        source_record_id="10.9999/e2e-fixture-0002", doi="10.9999/e2e-fixture-0002", citation_count=3, metadata_completeness=0.75,
    )
    lit3 = repository.add_literature_item(
        session, project_id=pid, title="An Unrelated Synthetic Paper (Duplicate Candidate)",
        authors="D. Placeholder", year=2022, source="arxiv", source_record_id="arXiv:e2e.0003",
        metadata_completeness=0.4,
    )

    # --- Research question (also referenced by the gap/novelty below) -----
    question = repository.create_research_question(
        session, project_id=pid, question="Can a synthetic widget alloy improve durability under repeated stress?",
        planning_status=PlanningApprovalStatus.CANDIDATE,
    )

    # --- Research gap, evidence-linked to literature -----------------------
    gap = repository.record_research_gap(
        session, project_id=pid, statement="Synthetic literature does not establish durability under repeated stress cycles.",
        status=GapStatus.CANDIDATE, gap_type="methodological", affected_research_area="materials durability (synthetic)",
        evidence_summary="Two synthetic papers touch on the topic but neither tests repeated-stress durability directly.",
        research_question_id=question.id,
    )
    repository.create_evidence_link(
        session, project_id=pid, literature_item_id=lit1.id, subject_type=EvidenceSubjectType.GAP_CANDIDATE,
        subject_id=gap.id, relationship_type=EvidenceRelationship.SUPPORTS,
    )
    repository.create_evidence_link(
        session, project_id=pid, literature_item_id=lit2.id, subject_type=EvidenceSubjectType.GAP_CANDIDATE,
        subject_id=gap.id, relationship_type=EvidenceRelationship.RELATED,
    )

    # --- Novelty assessment -------------------------------------------------
    novelty = repository.record_novelty_assessment(
        session, project_id=pid, claim="A synthetic alloy formulation tested under repeated stress cycles.",
        candidate_status=NoveltyCandidateStatus.POTENTIALLY_DISTINCT, confidence=0.55,
        novelty_risk="Two synthetic papers approach the topic from an adjacent angle.",
        research_question_id=question.id,
    )

    # --- Planning chain: contribution -> methodology -> dataset requirements
    #     -> experimental design -----------------------------------------
    contribution = repository.create_contribution_candidate(
        session, project_id=pid, title="A synthetic alloy composition for repeated-stress durability",
        description="A proposed (entirely synthetic) alloy composition and stress-testing protocol.",
        contribution_type="method", planning_status=PlanningApprovalStatus.CANDIDATE,
    )
    repository.link_contribution_candidate_question(
        session, project_id=pid, contribution_candidate_id=contribution.id, research_question_id=question.id,
    )
    methodology = repository.create_methodology_version(
        session, project_id=pid, description="A controlled repeated-stress cycling study on synthetic alloy samples.",
        planning_status=PlanningApprovalStatus.CANDIDATE, methodology_type="controlled_experiment",
        components=["Sample preparation", "Repeated stress cycling", "Durability scoring"],
        assumptions=["Synthetic samples behave consistently across batches."],
        risks=["Synthetic batch variance may confound results."],
        contribution_candidate_id=contribution.id, contribution_candidate_version=contribution.version,
        contribution_candidate_status_at_generation=contribution.planning_status.value,
    )
    dataset_requirements = repository.create_dataset_requirements(
        session, project_id=pid, planning_status=PlanningApprovalStatus.CANDIDATE,
        required_characteristics="Stress-cycle measurements for synthetic alloy samples.",
        split_strategy="80/20 train/test, stratified by batch.",
        methodology_plan_id=methodology.id, methodology_plan_version=methodology.version,
        methodology_plan_status_at_generation=methodology.planning_status.value,
    )
    experimental_design = repository.create_experimental_design(
        session, project_id=pid, planning_status=PlanningApprovalStatus.CANDIDATE,
        proposed_method="Repeated-stress cycling with periodic durability scoring.",
        baselines=["Standard alloy (synthetic baseline)"], evaluation_metrics=["accuracy", "failure_cycle_count"],
        comparison_strategy="Paired comparison against the synthetic baseline alloy.",
        methodology_plan_id=methodology.id, methodology_plan_version=methodology.version,
        methodology_plan_status_at_generation=methodology.planning_status.value,
        dataset_requirements_id=dataset_requirements.id,
        dataset_requirements_status_at_generation=dataset_requirements.planning_status.value,
    )

    # --- Dataset record + version -------------------------------------------
    dataset_record = repository.register_dataset(
        session, project_id=pid, name="Synthetic Widget Stress-Cycle Dataset", version="1",
        path_or_uri="s3://e2e-fixture-bucket/synthetic-widget-dataset/", description="Entirely synthetic, generated for Dashboard testing.",
    )
    dataset_version = repository.create_dataset_version(
        session, project_id=pid, dataset_record_id=dataset_record.id, sample_count=250,
        content_fingerprint="e2efixture0000000000000000000000000000000000000000000000000000",
        lifecycle_status=DatasetLifecycleStatus.APPROVED,
        validation_result={"is_valid": True, "errors": [], "warnings": []},
    )

    # --- Experiment + experiment specification -----------------------------
    experiment = repository.register_experiment(session, project_id=pid, name="E2E Sample Experiment", hardware="synthetic-cpu-1")
    specification = repository.create_experiment_specification(
        session, project_id=pid, experiment_id=experiment.id, experimental_design_id=experimental_design.id,
        methodology_plan_id=methodology.id, dataset_version_id=dataset_version.id,
        description="Synthetic experiment specification for Dashboard manual testing.",
        configuration={"model": "synthetic-alloy-v1", "seed": 42},
        planning_status=PlanningApprovalStatus.APPROVED,
        experimental_design_version=experimental_design.version,
        experimental_design_status_at_generation=experimental_design.planning_status.value,
        methodology_plan_version=methodology.version, methodology_plan_status_at_generation=methodology.planning_status.value,
        dataset_version_version=dataset_version.version, dataset_version_status_at_generation=dataset_version.lifecycle_status.value,
    )

    # --- Runs: one not-yet-executed, two completed with comparable metrics -
    run_pending = repository.create_run(
        session, project_id=pid, experiment_id=experiment.id, experiment_specification_id=specification.id,
        dataset_version_id=dataset_version.id, timeout_seconds=600, seed=42,
    )

    run_baseline = repository.create_run(
        session, project_id=pid, experiment_id=experiment.id, experiment_specification_id=specification.id,
        dataset_version_id=dataset_version.id, timeout_seconds=600, seed=7,
        dataset_fingerprint=dataset_version.content_fingerprint,
    )
    repository.update_run_lifecycle(
        session, run_baseline.id, expected_status=RunStatus.CREATED, new_status=RunStatus.SUCCEEDED,
        exit_code=0, duration_seconds=182.4,
    )
    repository.create_metric(
        session, project_id=pid, run_id=run_baseline.id, name="accuracy", value=0.82, value_type=MetricValueType.FLOAT,
        unit="ratio", split="test",
    )
    repository.create_metric(
        session, project_id=pid, run_id=run_baseline.id, name="failure_cycle_count", value=1420, value_type=MetricValueType.INTEGER,
        unit="cycles", split="test",
    )
    repository.create_artifact_metadata(
        session, project_id=pid, run_id=run_baseline.id, logical_name="stdout", artifact_type=ArtifactType.STDOUT,
        reference=f"{_tmp_dir}/run_baseline_stdout.log", size_bytes=1024,
    )

    run_comparison = repository.create_run(
        session, project_id=pid, experiment_id=experiment.id, experiment_specification_id=specification.id,
        dataset_version_id=dataset_version.id, timeout_seconds=600, seed=13,
        dataset_fingerprint=dataset_version.content_fingerprint,
    )
    repository.update_run_lifecycle(
        session, run_comparison.id, expected_status=RunStatus.CREATED, new_status=RunStatus.SUCCEEDED,
        exit_code=0, duration_seconds=176.9,
    )
    repository.create_metric(
        session, project_id=pid, run_id=run_comparison.id, name="accuracy", value=0.85, value_type=MetricValueType.FLOAT,
        unit="ratio", split="test",
    )
    repository.create_metric(
        session, project_id=pid, run_id=run_comparison.id, name="failure_cycle_count", value=1610, value_type=MetricValueType.INTEGER,
        unit="cycles", split="test",
    )
    repository.create_artifact_metadata(
        session, project_id=pid, run_id=run_comparison.id, logical_name="stdout", artifact_type=ArtifactType.STDOUT,
        reference=f"{_tmp_dir}/run_comparison_stdout.log", size_bytes=1024,
    )
    repository.create_artifact_metadata(
        session, project_id=pid, run_id=run_comparison.id, logical_name="checkpoint", artifact_type=ArtifactType.CHECKPOINT,
        reference=f"{_tmp_dir}/run_comparison_checkpoint.bin", size_bytes=204800,
    )

    # --- Approval requests: research question + contribution --------------
    repository.create_approval_request(session, project_id=pid, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
    repository.create_approval_request(session, project_id=pid, stage=f"CONTRIBUTION_APPROVAL:{contribution.id}")

    session.commit()
    run_baseline_id, run_comparison_id = run_baseline.id, run_comparison.id

# ===========================================================================
# Analysis / Scientific Claim / Scientific Review — via the real
# researchos.analysis SERVICE functions (not bare repository calls), so
# their own AuditEvent rows are created exactly as the real application
# would create them, giving the Audit Log page real, authentic entries.
# ===========================================================================
from researchos.analysis.claims import create_scientific_claim  # noqa: E402
from researchos.analysis.records import compare_runs  # noqa: E402
from researchos.analysis.reviews import create_scientific_review  # noqa: E402

_SEED_ACTOR = "user:e2e-seed"

analysis_record = compare_runs(
    project.id, run_baseline_id, run_comparison_id, "accuracy", actor=_SEED_ACTOR, split="test", session_factory=Session,
)
claim = create_scientific_claim(
    project.id, "The comparison run's accuracy may be higher than the baseline run's under these synthetic conditions.",
    [analysis_record.id], actor=_SEED_ACTOR, claim_type="performance_comparison", confidence=0.4, session_factory=Session,
)
_REVIEW_DIMENSIONS = {
    "evidence_completeness": "Only one paired comparison is available; repeated runs would strengthen this.",
    "experimental_consistency": "Same experiment specification and dataset version for both runs.",
    "dataset_consistency": "Same DatasetVersion and content fingerprint for both runs.",
    "metric_appropriateness": "Accuracy is an appropriate synthetic proxy metric for this fixture.",
    "baseline_adequacy": "The baseline run represents the standard synthetic alloy.",
    "ablation_coverage": "No ablations were run in this synthetic fixture.",
    "reproducibility": "Both runs recorded seed, dataset fingerprint, and configuration hash.",
    "statistical_support": "Descriptive comparison only; no significance testing performed.",
    "threats_to_validity": "Single run per condition; synthetic data only.",
    "claim_strength": "Moderate — a single paired comparison, not a repeated-run study.",
    "alternative_explanations": "Random seed variation between runs has not been ruled out.",
    "missing_evidence": "Repeated runs per condition; an ablation study.",
}
review = create_scientific_review(
    project.id, claim.id, _REVIEW_DIMENSIONS, actor=_SEED_ACTOR,
    status=ScientificReviewStatus.READY_FOR_HUMAN_REVIEW,
    recommendation="A human reviewer should confirm this synthetic comparison before treating it as anything beyond a fixture.",
    session_factory=Session,
)
with Session() as session:
    repository.create_approval_request(session, project_id=project.id, stage=f"SCIENTIFIC_REVIEW_APPROVAL:{review.id}")
    session.commit()

os.environ["DATABASE_URL"] = _db_url

if __name__ == "__main__":
    import uvicorn

    print(f"\nE2E seed complete — project id: {project.id}", file=sys.stderr)
    print(f"Isolated database: {_db_url}\n", file=sys.stderr)
    uvicorn.run("researchos_api.main:app", host="127.0.0.1", port=8000, log_level="warning")
