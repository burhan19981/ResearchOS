"""Model-level validation tests (`@validates` methods in `db.models`)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import ValidationError
from researchos.db.models import ResearchProject


def test_blank_title_is_rejected(session: Session):
    with pytest.raises(ValidationError):
        repository.create_project(session, title="   ")


def test_none_like_blank_title_is_rejected_on_direct_model_construction():
    with pytest.raises(ValidationError):
        ResearchProject(title="")


def test_gap_confidence_out_of_range_is_rejected(session: Session):
    project = repository.create_project(session, title="Gap Project")
    with pytest.raises(ValidationError):
        repository.record_research_gap(
            session, project_id=project.id, statement="A gap", confidence=1.5
        )


def test_gap_confidence_negative_is_rejected(session: Session):
    project = repository.create_project(session, title="Gap Project 2")
    with pytest.raises(ValidationError):
        repository.record_research_gap(
            session, project_id=project.id, statement="A gap", confidence=-0.1
        )


def test_gap_confidence_boundary_values_are_accepted(session: Session):
    project = repository.create_project(session, title="Gap Project 3")
    low = repository.record_research_gap(session, project_id=project.id, statement="low", confidence=0.0)
    high = repository.record_research_gap(session, project_id=project.id, statement="high", confidence=1.0)
    assert low.confidence == 0.0
    assert high.confidence == 1.0


def test_novelty_confidence_out_of_range_is_rejected(session: Session):
    project = repository.create_project(session, title="Novelty Project")
    with pytest.raises(ValidationError):
        repository.record_novelty_assessment(session, project_id=project.id, claim="claim", confidence=2.0)


def test_negative_literature_year_is_rejected(session: Session):
    project = repository.create_project(session, title="Lit Project")
    with pytest.raises(ValidationError):
        repository.add_literature_item(session, project_id=project.id, title="Paper", year=-5)


def test_non_finite_metric_value_is_rejected(session: Session):
    project = repository.create_project(session, title="Exp Project")
    experiment = repository.register_experiment(session, project_id=project.id, name="exp-1")
    with pytest.raises(ValidationError):
        repository.record_experiment_result(
            session, experiment_id=experiment.id, metric_name="loss", metric_value=float("nan")
        )


def test_non_positive_methodology_version_is_rejected(session: Session):
    project = repository.create_project(session, title="Methodology Project")
    with pytest.raises(ValidationError):
        repository.create_methodology_version(
            session, project_id=project.id, description="plan", version=0
        )


def test_non_positive_manuscript_version_is_rejected(session: Session):
    project = repository.create_project(session, title="Manuscript Project")
    with pytest.raises(ValidationError):
        repository.create_manuscript(session, project_id=project.id, title="Draft", version=-1)
