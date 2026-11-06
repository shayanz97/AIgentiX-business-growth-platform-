import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.models import ResearchProject
from tests.conftest import Tenant, random_uuid


def create(t: Tenant, **payload: object) -> dict[str, object]:
    body = {"name": "Acme research", **payload}
    response = t.client.post("/api/v1/projects", json=body, headers=t.headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_create_project_persists_in_tenant(tenant_a: Tenant, db: Session) -> None:
    project = create(tenant_a, description="  First target  ", target_url="https://acme.example")
    assert project["organization_id"] == str(tenant_a.org.id)
    assert project["status"] == "draft"
    assert project["description"] == "First target"
    assert project["target_url"] == "https://acme.example/"
    assert project["created_by_user_id"] == str(tenant_a.user.id)

    row = db.scalar(select(ResearchProject).where(ResearchProject.id == project["id"]))
    assert row is not None
    assert row.organization_id == tenant_a.org.id


def test_list_projects_is_paginated_and_newest_first(tenant_a: Tenant) -> None:
    for i in range(3):
        create(tenant_a, name=f"Project {i}")
    page = tenant_a.client.get("/api/v1/projects?limit=2&offset=0", headers=tenant_a.headers).json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert [p["name"] for p in page["items"]] == ["Project 2", "Project 1"]
    page2 = tenant_a.client.get("/api/v1/projects?limit=2&offset=2", headers=tenant_a.headers).json()
    assert [p["name"] for p in page2["items"]] == ["Project 0"]


def test_get_project(tenant_a: Tenant) -> None:
    project = create(tenant_a)
    response = tenant_a.client.get(f"/api/v1/projects/{project['id']}", headers=tenant_a.headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Acme research"


def test_members_can_create_and_read_projects(tenant_a: Tenant, member_of_a: Tenant) -> None:
    project = create(member_of_a, name="Member project")
    listed = tenant_a.client.get("/api/v1/projects", headers=tenant_a.headers).json()
    assert [p["id"] for p in listed["items"]] == [project["id"]]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"name": "ok", "target_url": "javascript:alert(1)"}, "target_url"),
        ({"name": "ok", "target_url": "ftp://acme.example"}, "target_url"),
        ({"name": "ok", "organization_id": "00000000-0000-0000-0000-000000000000"}, "organization_id"),
        ({}, "name"),
    ],
)
def test_invalid_project_input_returns_422(tenant_a: Tenant, payload: dict[str, object], field: str) -> None:
    response = tenant_a.client.post("/api/v1/projects", json=payload, headers=tenant_a.headers)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any(field in err["loc"] for err in body["details"])


def test_missing_organization_header_is_rejected(tenant_a: Tenant) -> None:
    response = tenant_a.client.get("/api/v1/projects")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_input"


def test_malformed_organization_header_is_rejected(tenant_a: Tenant) -> None:
    response = tenant_a.client.get("/api/v1/projects", headers={"X-Organization-Id": "not-a-uuid"})
    assert response.status_code == 400


def test_unknown_project_returns_404(tenant_a: Tenant) -> None:
    response = tenant_a.client.get(f"/api/v1/projects/{random_uuid()}", headers=tenant_a.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- Tenant isolation --------------------------------------------------------------------------


def test_tenant_cannot_list_other_tenants_projects(tenant_a: Tenant, tenant_b: Tenant) -> None:
    create(tenant_a, name="Secret A")
    page = tenant_b.client.get("/api/v1/projects", headers=tenant_b.headers).json()
    assert page["total"] == 0
    assert page["items"] == []


def test_tenant_cannot_read_other_tenants_project_by_id(tenant_a: Tenant, tenant_b: Tenant) -> None:
    project = create(tenant_a, name="Secret A")
    response = tenant_b.client.get(f"/api/v1/projects/{project['id']}", headers=tenant_b.headers)
    # Same response as a non-existent project: no cross-tenant existence oracle.
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/projects"), ("POST", "/api/v1/projects"), ("GET", "/api/v1/workflows")],
)
def test_spoofed_organization_header_is_rejected(tenant_a: Tenant, tenant_b: Tenant, method: str, path: str) -> None:
    """Bob sends Org A's id: membership is verified server-side, so this must fail."""
    response = tenant_b.client.request(method, path, json={"name": "intrusion"}, headers=tenant_a.headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_spoofed_header_cannot_read_project_by_id(tenant_a: Tenant, tenant_b: Tenant) -> None:
    project = create(tenant_a, name="Secret A")
    response = tenant_b.client.get(f"/api/v1/projects/{project['id']}", headers=tenant_a.headers)
    assert response.status_code == 403


def test_nonexistent_organization_header_gives_same_error_as_foreign_one(tenant_b: Tenant) -> None:
    response = tenant_b.client.get("/api/v1/projects", headers={"X-Organization-Id": random_uuid()})
    assert response.status_code == 403


def test_cross_tenant_write_creates_nothing(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    tenant_b.client.post("/api/v1/projects", json={"name": "intrusion"}, headers=tenant_a.headers)
    assert db.scalars(select(ResearchProject)).all() == []
