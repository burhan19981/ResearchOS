"""Audit log page — read-only, chronological, project-isolated."""

from __future__ import annotations

from researchos.db import repository


def test_audit_empty_state(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/audit")
    assert response.status_code == 200
    assert response.json() == []


def test_audit_reflects_real_events_in_order(client, session_factory, project_id):
    with session_factory() as session:
        repository.append_audit_event(session, project_id=project_id, event_type="test.first", actor="user:tester", description="First event")
        repository.append_audit_event(session, project_id=project_id, event_type="test.second", actor="user:tester", description="Second event", metadata={"key": "value"})
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/audit")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["event_type"] == "test.first"
    assert body[1]["event_type"] == "test.second"
    assert body[1]["metadata"] == {"key": "value"}


def test_audit_project_isolation(client, session_factory, project_id, second_project_id):
    with session_factory() as session:
        repository.append_audit_event(session, project_id=project_id, event_type="test.a", actor="user:tester")
        repository.append_audit_event(session, project_id=second_project_id, event_type="test.b", actor="user:tester")
        session.commit()

    response_a = client.get(f"/api/v1/projects/{project_id}/audit")
    event_types_a = {e["event_type"] for e in response_a.json()}
    assert event_types_a == {"test.a"}
