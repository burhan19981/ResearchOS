"""Foreign-key integrity, orphan prevention, cascade delete, and
project-isolation tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import ResearchIdea


def test_repository_layer_prevents_orphan_child_before_hitting_the_db(session: Session):
    """The repository layer checks project existence itself, so a bad
    project_id fails fast with a normalized error, not a raw DB error."""
    with pytest.raises(NotFoundError):
        repository.create_research_idea(session, project_id=999_999, title="Orphan")


def test_database_itself_rejects_orphan_child_via_foreign_key_pragma(session: Session):
    """Bypass the repository layer's own existence check to prove SQLite's
    foreign_keys enforcement (PRAGMA foreign_keys=ON) is the second line
    of defense, not just an application-level convention."""
    orphan = ResearchIdea(project_id=999_999, title="Bypassed orphan")
    session.add(orphan)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_deleting_project_cascades_to_every_child_type(session: Session):
    project = repository.create_project(session, title="Full Tree Project")
    repository.create_research_idea(session, project_id=project.id, title="Idea")
    repository.create_research_question(session, project_id=project.id, question="Q?")
    repository.add_literature_item(session, project_id=project.id, title="Paper")
    repository.record_research_gap(session, project_id=project.id, statement="Gap")
    repository.record_novelty_assessment(session, project_id=project.id, claim="Claim")
    repository.create_methodology_version(session, project_id=project.id, description="Plan")
    repository.register_dataset(session, project_id=project.id, name="ds", version="v1", path_or_uri="/x")
    experiment = repository.register_experiment(session, project_id=project.id, name="exp")
    repository.record_experiment_result(session, experiment_id=experiment.id, metric_name="m", metric_value=1.0)
    repository.create_manuscript(session, project_id=project.id, title="MS")
    repository.create_journal_candidate(session, project_id=project.id, name="Journal")
    repository.create_approval_request(session, project_id=project.id, stage="review")
    repository.append_audit_event(session, project_id=project.id, event_type="e", actor="test")
    session.flush()

    project_id = project.id
    session.delete(project)
    session.flush()

    assert repository.get_project(session, project_id) is None
    assert repository.list_research_ideas(session, project_id) == []
    assert repository.list_research_questions(session, project_id) == []
    assert repository.list_literature_items(session, project_id) == []
    assert repository.list_research_gaps(session, project_id) == []
    assert repository.list_novelty_assessments(session, project_id) == []
    assert repository.list_methodology_plans(session, project_id) == []
    assert repository.list_datasets(session, project_id) == []
    assert repository.list_experiments(session, project_id) == []
    assert repository.list_manuscripts(session, project_id) == []
    assert repository.list_journal_candidates(session, project_id) == []
    assert repository.list_approvals(session, project_id) == []
    assert repository.list_audit_events(session, project_id) == []


def test_project_isolation_across_every_child_type(session: Session):
    """Records created under one project must never appear when querying
    another project's children, even with similar/identical field values."""
    project_a = repository.create_project(session, title="Project A")
    project_b = repository.create_project(session, title="Project B")

    repository.create_research_idea(session, project_id=project_a.id, title="Shared Idea Title")
    repository.create_research_idea(session, project_id=project_b.id, title="Shared Idea Title")

    ideas_a = repository.list_research_ideas(session, project_a.id)
    ideas_b = repository.list_research_ideas(session, project_b.id)

    assert len(ideas_a) == 1
    assert len(ideas_b) == 1
    assert ideas_a[0].id != ideas_b[0].id
    assert ideas_a[0].project_id == project_a.id
    assert ideas_b[0].project_id == project_b.id


def test_experiment_result_isolation_across_experiments(session: Session):
    project = repository.create_project(session, title="Two Experiments Project")
    exp_1 = repository.register_experiment(session, project_id=project.id, name="exp-1")
    exp_2 = repository.register_experiment(session, project_id=project.id, name="exp-2")

    repository.record_experiment_result(session, experiment_id=exp_1.id, metric_name="acc", metric_value=0.5)
    repository.record_experiment_result(session, experiment_id=exp_2.id, metric_name="acc", metric_value=0.9)

    results_1 = repository.list_experiment_results(session, exp_1.id)
    results_2 = repository.list_experiment_results(session, exp_2.id)
    assert [r.metric_value for r in results_1] == [0.5]
    assert [r.metric_value for r in results_2] == [0.9]
