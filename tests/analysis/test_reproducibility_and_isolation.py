"""Categories I/J/K: reproducibility of a persisted `AnalysisRecord`'s
provenance, project isolation across every analysis-layer service, and
the immutability/security boundary (no update path for `AnalysisRecord`,
every cross-entity reference is project-checked before use)."""

from __future__ import annotations

import pytest

from researchos.analysis.approval import approve_scientific_claim, approve_scientific_review
from researchos.analysis.claims import create_scientific_claim
from researchos.analysis.comparability import check_comparability
from researchos.analysis.errors import CrossProjectReferenceError, InvalidAnalysisInputError, MissingEntityError
from researchos.analysis.records import aggregate_runs, compare_runs
from researchos.analysis.reviews import create_scientific_review
from researchos.db import repository
from researchos.db.models import ScientificReviewStatus

_DIMENSIONS = {key: "assessed" for key in (
    "evidence_completeness", "experimental_consistency", "dataset_consistency", "metric_appropriateness",
    "baseline_adequacy", "ablation_coverage", "reproducibility", "statistical_support",
    "threats_to_validity", "claim_strength", "alternative_explanations", "missing_evidence",
)}


# ===========================================================================
# Category I: reproducibility
# ===========================================================================


def test_analysis_record_captures_full_provenance(session_factory, project_id, two_comparable_run_ids):
    record = compare_runs(project_id, *two_comparable_run_ids, "f1", actor="tester", session_factory=session_factory)
    assert record.parameters["baseline_run_id"] == two_comparable_run_ids[0]
    assert record.parameters["comparison_run_id"] == two_comparable_run_ids[1]
    assert record.parameters["metric_name"] == "f1"
    assert record.software_versions.get("researchos") is not None
    assert record.created_at is not None


def test_recomputing_from_identical_inputs_is_deterministic(session_factory, project_id, two_comparable_run_ids):
    first = compare_runs(project_id, *two_comparable_run_ids, "f1", actor="tester", session_factory=session_factory)
    second = compare_runs(
        project_id, *two_comparable_run_ids, "f1", actor="tester", supersedes_id=first.id,
        session_factory=session_factory,
    )
    # Same inputs, same deterministic computation -> identical result values.
    assert first.result["absolute_difference"] == second.result["absolute_difference"]
    assert first.result["percentage_change"] == second.result["percentage_change"]


def test_analysis_record_has_no_update_function():
    """Immutability (Phase 8 spec section 9): a re-analysis is always a
    new row via `supersedes_id`, never a mutation of an existing one —
    `researchos.db.repository` deliberately exposes no
    `update_analysis_record`."""
    assert not hasattr(repository, "update_analysis_record")


# ===========================================================================
# Category J: project isolation
# ===========================================================================


def test_compare_runs_rejects_cross_project_run(session_factory, project_id, second_project_id, two_comparable_run_ids):
    baseline_id, comparison_id = two_comparable_run_ids
    with pytest.raises(CrossProjectReferenceError):
        compare_runs(second_project_id, baseline_id, comparison_id, "f1", actor="tester", session_factory=session_factory)


def test_aggregate_runs_rejects_cross_project_run(session_factory, project_id, second_project_id, three_repeated_run_ids):
    with pytest.raises(CrossProjectReferenceError):
        aggregate_runs(second_project_id, three_repeated_run_ids, "f1", actor="tester", session_factory=session_factory)


def test_create_scientific_claim_rejects_cross_project_analysis_record(session_factory, project_id, second_project_id, analysis_record_id):
    with pytest.raises(CrossProjectReferenceError):
        create_scientific_claim(
            second_project_id, "A claim citing another project's analysis.", [analysis_record_id],
            actor="tester", session_factory=session_factory,
        )


def test_create_scientific_review_rejects_cross_project_claim(session_factory, project_id, second_project_id, claim_id):
    with pytest.raises(CrossProjectReferenceError):
        create_scientific_review(
            second_project_id, claim_id, _DIMENSIONS, actor="tester",
            status=ScientificReviewStatus.DRAFT, session_factory=session_factory,
        )


def test_check_comparability_rejects_unknown_run(session_factory, project_id):
    with session_factory() as session:
        with pytest.raises(MissingEntityError):
            check_comparability(session, project_id, 1, 2, "f1")


def test_compare_runs_rejects_cross_project_supersedes_id(session_factory, project_id, second_project_id, two_comparable_run_ids):
    """`supersedes_id` is validated the same way every other referenced
    id is — a cross-project `supersedes_id` raises the same typed
    `CrossProjectReferenceError` a cross-project `Run` reference would,
    not the repository layer's generic `NotFoundError`."""
    other_run_ids = _seed_comparable_runs(session_factory, second_project_id)
    other_record = compare_runs(second_project_id, *other_run_ids, "f1", actor="tester", session_factory=session_factory)
    with pytest.raises(CrossProjectReferenceError):
        compare_runs(
            project_id, *two_comparable_run_ids, "f1", actor="tester", supersedes_id=other_record.id,
            session_factory=session_factory,
        )


def _seed_comparable_runs(session_factory, project_id):
    from researchos.db.models import MetricValueType

    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Other project experiment")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.5, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.6, value_type=MetricValueType.FLOAT)
        session.commit()
        return r1.id, r2.id


# ===========================================================================
# Category K: security / boundary
# ===========================================================================


def test_analysis_input_rejects_cross_project_metric(session_factory, project_id, second_project_id, analysis_record_id):
    from researchos.db.models import AnalysisInputType, MetricValueType

    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=second_project_id, name="Other project experiment")
        run = repository.create_run(session, project_id=second_project_id, experiment_id=experiment.id, timeout_seconds=60)
        metric = repository.create_metric(
            session, project_id=second_project_id, run_id=run.id, name="f1", value=0.5,
            value_type=MetricValueType.FLOAT,
        )
        session.commit()
        foreign_metric_id = metric.id

    with session_factory() as session:
        with pytest.raises(Exception):
            repository.create_analysis_input(
                session, project_id=project_id, analysis_record_id=analysis_record_id,
                input_type=AnalysisInputType.METRIC, input_id=foreign_metric_id,
            )


def test_approval_never_reachable_from_a_bare_create_call(session_factory, project_id, analysis_record_id):
    """A manually-authored claim/review can never come into existence
    already `APPROVED`/`HUMAN_APPROVED` — those states are reachable
    only through `researchos.analysis.approval`."""
    claim = create_scientific_claim(
        project_id, "A brand-new claim.", [analysis_record_id], actor="tester", session_factory=session_factory,
    )
    review = create_scientific_review(
        project_id, claim.id, _DIMENSIONS, actor="tester",
        status=ScientificReviewStatus.READY_FOR_HUMAN_REVIEW, session_factory=session_factory,
    )
    from researchos.db.models import ClaimApprovalStatus

    assert claim.approval_status != ClaimApprovalStatus.APPROVED
    assert review.status != ScientificReviewStatus.HUMAN_APPROVED
