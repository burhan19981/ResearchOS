"""JSON metadata serialization/deserialization round-trip tests.

Each test commits, then reads back through a *different* session bound
to the same engine, so a pass proves data actually round-tripped through
SQLite's JSON storage — not merely that the same Python object was
handed back from an identity map.
"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from researchos.db import repository
from researchos.db.engine import session_scope


def test_experiment_configuration_round_trips(session_factory: sessionmaker):
    nested_config = {
        "lr": 0.001,
        "layers": [128, 64, 10],
        "augmentation": {"flip": True, "crop": None},
        "tags": ["baseline", "v2"],
    }
    with session_scope(session_factory) as session:
        project = repository.create_project(session, title="Serialization Project")
        experiment = repository.register_experiment(
            session, project_id=project.id, name="exp", configuration=nested_config
        )
        experiment_id = experiment.id

    with session_factory() as fresh_session:
        experiment = repository.get_experiment(fresh_session, experiment_id)
        assert experiment is not None
        assert experiment.configuration == nested_config


def test_experiment_result_metadata_round_trips(session_factory: sessionmaker):
    metadata = {"confusion_matrix": [[10, 1], [2, 9]], "notes": None, "epoch": 5}
    with session_scope(session_factory) as session:
        project = repository.create_project(session, title="Result Metadata Project")
        experiment = repository.register_experiment(session, project_id=project.id, name="exp")
        result = repository.record_experiment_result(
            session, experiment_id=experiment.id, metric_name="loss", metric_value=0.1, metadata=metadata
        )
        result_id = result.id

    with session_factory() as fresh_session:
        result = repository.get_experiment_result(fresh_session, result_id)
        assert result is not None
        assert result.metadata_ == metadata


def test_dataset_split_information_round_trips(session_factory: sessionmaker):
    splits = {"train": 1000, "val": 200, "test": 200}
    with session_scope(session_factory) as session:
        project = repository.create_project(session, title="Dataset Serialization Project")
        dataset = repository.register_dataset(
            session,
            project_id=project.id,
            name="ds",
            version="v1",
            path_or_uri="/data/ds",
            split_information=splits,
        )
        dataset_id = dataset.id

    with session_factory() as fresh_session:
        dataset = repository.get_dataset(fresh_session, dataset_id)
        assert dataset is not None
        assert dataset.split_information == splits


def test_audit_event_metadata_round_trips(session_factory: sessionmaker):
    metadata = {"ip_omitted": True, "fields_changed": ["status", "title"]}
    with session_scope(session_factory) as session:
        project = repository.create_project(session, title="Audit Serialization Project")
        repository.append_audit_event(
            session, project_id=project.id, event_type="updated", actor="system", metadata=metadata
        )
        project_id = project.id

    with session_factory() as fresh_session:
        events = repository.list_audit_events(fresh_session, project_id)
        assert events[0].metadata_ == metadata


def test_none_metadata_round_trips_as_none(session_factory: sessionmaker):
    with session_scope(session_factory) as session:
        project = repository.create_project(session, title="Null Metadata Project")
        experiment = repository.register_experiment(session, project_id=project.id, name="exp")
        experiment_id = experiment.id

    with session_factory() as fresh_session:
        experiment = repository.get_experiment(fresh_session, experiment_id)
        assert experiment.configuration is None
