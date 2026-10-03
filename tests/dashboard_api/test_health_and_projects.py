"""Health endpoint, project listing, and basic invalid-id handling."""

from __future__ import annotations


def test_health_reports_real_component_checks(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is True
    names = {c["name"] for c in body["components"]}
    assert names == {"database", "workflow", "evidence", "execution"}
    assert all(c["healthy"] for c in body["components"])
    assert body["version"]


def test_list_projects_empty(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    assert response.json() == []


def test_list_projects_returns_real_rows(client, project_id, second_project_id):
    response = client.get("/api/v1/projects")
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()}
    assert ids == {project_id, second_project_id}


def test_get_project(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == project_id
    assert body["title"] == "Dashboard Test Project"
    assert body["status"] == "active"


def test_get_nonexistent_project_returns_404(client):
    response = client.get("/api/v1/projects/999999")
    assert response.status_code == 404
    assert "999999" in response.json()["detail"]


def test_project_scoped_routes_reject_nonexistent_project(client):
    for path in ("overview", "pipeline", "literature", "gaps", "novelty", "planning", "experiments", "runs", "analysis", "reviews", "approvals", "audit"):
        response = client.get(f"/api/v1/projects/999999/{path}")
        assert response.status_code == 404, f"{path} did not 404 for a nonexistent project"


def test_openapi_schema_is_available(client):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "ResearchOS Dashboard API"
    assert "/api/v1/health" in schema["paths"]


def test_docs_ui_is_available(client):
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
