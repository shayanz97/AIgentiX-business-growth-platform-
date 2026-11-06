from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import Tenant, login, make_user


def test_list_organizations_returns_only_own(tenant_a: Tenant, tenant_b: Tenant) -> None:
    body = tenant_a.client.get("/api/v1/organizations").json()
    assert [m["organization"]["id"] for m in body] == [str(tenant_a.org.id)]
    assert body[0]["role"] == "owner"


def test_create_organization_makes_caller_owner(client: TestClient, db: Session) -> None:
    make_user(db, "new@example.com")
    login(client, "new@example.com")
    response = client.post("/api/v1/organizations", json={"name": "  New Co  "})
    assert response.status_code == 201
    assert response.json()["role"] == "owner"
    assert response.json()["organization"]["name"] == "New Co"
    orgs = client.get("/api/v1/organizations").json()
    assert [m["organization"]["name"] for m in orgs] == ["New Co"]


def test_create_organization_validates_name(tenant_a: Tenant) -> None:
    assert tenant_a.client.post("/api/v1/organizations", json={"name": "x"}).status_code == 422


def test_owner_can_rename_organization(tenant_a: Tenant) -> None:
    response = tenant_a.client.patch(f"/api/v1/organizations/{tenant_a.org.id}", json={"name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_member_cannot_rename_organization(member_of_a: Tenant) -> None:
    response = member_of_a.client.patch(f"/api/v1/organizations/{member_of_a.org.id}", json={"name": "Hijack"})
    assert response.status_code == 403


def test_non_member_cannot_rename_or_list_members(tenant_a: Tenant, tenant_b: Tenant) -> None:
    org_a = tenant_a.org.id
    assert tenant_b.client.patch(f"/api/v1/organizations/{org_a}", json={"name": "Hijack"}).status_code == 403
    assert tenant_b.client.get(f"/api/v1/organizations/{org_a}/members").status_code == 403


def test_members_listing(tenant_a: Tenant, member_of_a: Tenant) -> None:
    response = member_of_a.client.get(f"/api/v1/organizations/{tenant_a.org.id}/members")
    assert response.status_code == 200
    assert {(m["user"]["email"], m["role"]) for m in response.json()} == {
        ("alice@a.example", "owner"),
        ("max@a.example", "member"),
    }


def test_modules_endpoint_lists_registered_modules(tenant_a: Tenant) -> None:
    modules = {m["key"]: m["status"] for m in tenant_a.client.get("/api/v1/modules").json()}
    assert modules == {
        "lead_intelligence": "available",
        "sales": "planned",
        "marketing": "planned",
        "analytics": "planned",
    }
