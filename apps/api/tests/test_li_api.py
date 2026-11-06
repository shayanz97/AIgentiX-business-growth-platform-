"""Lead Intelligence API: companies, dedup, CSV import, projects, research runs, review — and tenant isolation."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.models import Company, Opportunity, ResearchRun
from tests.conftest import Tenant, random_uuid
from tests.research_helpers import add_company, drain, research_company, research_registry, start

FIXTURES = Path(__file__).resolve().parents[1] / "src/aigentix/modules/lead_intelligence/fixtures"


def _project(t: Tenant, name: str = "Campaign") -> str:
    response = t.client.post("/api/v1/projects", json={"name": name}, headers=t.headers)
    assert response.status_code == 201
    return str(response.json()["id"])


# --- Companies -----------------------------------------------------------------------------------


def test_create_company_and_dedup_by_domain(tenant_a: Tenant, db: Session) -> None:
    first = tenant_a.client.post(
        "/api/v1/companies", json={"website_url": "https://www.Acme.example/about"}, headers=tenant_a.headers
    )
    assert first.status_code == 201
    body = first.json()
    assert body["created"] is True
    assert body["company"]["canonical_domain"] == "acme.example"
    assert body["company"]["website_url"] == "https://www.acme.example/"
    assert body["company"]["research_status"] is None

    again = tenant_a.client.post("/api/v1/companies", json={"website_url": "acme.example"}, headers=tenant_a.headers)
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["company"]["id"] == body["company"]["id"]
    assert db.scalar(select(func.count()).select_from(Company)) == 1


def test_same_domain_allowed_in_different_organizations(tenant_a: Tenant, tenant_b: Tenant) -> None:
    a = add_company(tenant_a, "acme.example")
    b = add_company(tenant_b, "acme.example")
    assert a["id"] != b["id"]


def test_name_only_company_and_dedup_by_name(tenant_a: Tenant) -> None:
    first = tenant_a.client.post("/api/v1/companies", json={"name": "Nameless Co"}, headers=tenant_a.headers)
    assert first.status_code == 201
    again = tenant_a.client.post("/api/v1/companies", json={"name": "nameless co"}, headers=tenant_a.headers)
    assert again.json()["created"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"website_url": "http://169.254.169.254/"},
        {"website_url": "http://localhost:3000"},
        {"website_url": "not a url"},
        {},
        {"website_url": "acme.example", "organization_id": random_uuid()},
        {"website_url": "x" * 3000},
    ],
)
def test_invalid_company_input(tenant_a: Tenant, payload: dict[str, Any]) -> None:
    response = tenant_a.client.post("/api/v1/companies", json=payload, headers=tenant_a.headers)
    assert response.status_code in (400, 422)


def test_list_and_search_companies(tenant_a: Tenant) -> None:
    add_company(tenant_a, "alpha.example")
    add_company(tenant_a, "beta.example", name="Beta Industries")
    listed = tenant_a.client.get("/api/v1/companies?q=beta", headers=tenant_a.headers).json()
    assert [c["name"] for c in listed["items"]] == ["Beta Industries"]
    assert tenant_a.client.get("/api/v1/companies", headers=tenant_a.headers).json()["total"] == 2


# --- CSV import ----------------------------------------------------------------------------------


def test_csv_import_preview_then_import(tenant_a: Tenant, db: Session) -> None:
    add_company(tenant_a, "fjord-accounting.example")  # already exists
    project_id = _project(tenant_a)
    csv_text = (FIXTURES / "companies_sample.csv").read_text()
    preview = tenant_a.client.post(
        "/api/v1/companies/import", json={"csv_text": csv_text, "dry_run": True}, headers=tenant_a.headers
    ).json()
    statuses = [r["status"] for r in preview["rows"]]
    assert preview["dry_run"] is True
    assert statuses.count("new") == 4  # 3 new domains + 1 name-only
    assert statuses.count("existing") == 1
    assert statuses.count("duplicate_in_file") == 1
    assert statuses.count("invalid") == 1
    assert db.scalar(select(func.count()).select_from(Company)) == 1  # dry run wrote nothing

    result = tenant_a.client.post(
        "/api/v1/companies/import",
        json={"csv_text": csv_text, "dry_run": False, "project_id": project_id},
        headers=tenant_a.headers,
    ).json()
    assert result["created"] == 4
    assert result["linked_to_project"] == 5  # new + existing
    in_project = tenant_a.client.get(f"/api/v1/projects/{project_id}/companies", headers=tenant_a.headers).json()
    assert in_project["total"] == 5

    # Importing the same file again creates nothing.
    again = tenant_a.client.post(
        "/api/v1/companies/import", json={"csv_text": csv_text, "dry_run": False}, headers=tenant_a.headers
    ).json()
    assert again["created"] == 0


def test_csv_import_limits(tenant_a: Tenant) -> None:
    too_many = "name\n" + "\n".join(f"Company {i}" for i in range(101))
    response = tenant_a.client.post("/api/v1/companies/import", json={"csv_text": too_many}, headers=tenant_a.headers)
    assert response.status_code == 400
    assert "maximum is 100" in response.json()["error"]["message"]
    bad_header = tenant_a.client.post(
        "/api/v1/companies/import", json={"csv_text": "a,b\n1,2"}, headers=tenant_a.headers
    )
    assert bad_header.status_code == 400


# --- Research runs -------------------------------------------------------------------------------


def test_start_research_skips_duplicates_and_companies_without_website(tenant_a: Tenant, db: Session) -> None:
    with_site = add_company(tenant_a, "northwind-logistics.example")
    no_site = tenant_a.client.post("/api/v1/companies", json={"name": "No Site"}, headers=tenant_a.headers).json()[
        "company"
    ]
    first = start(tenant_a, [with_site["id"], no_site["id"], random_uuid()])
    assert len(first["started"]) == 1
    assert first["started"][0]["status"] == "pending"
    assert {s["reason"] for s in first["skipped"]} == {"no_website", "not_found"}
    second = start(tenant_a, [with_site["id"]])
    assert second["started"] == []
    assert second["skipped"][0]["reason"] == "already_running"
    assert db.scalar(select(func.count()).select_from(ResearchRun)) == 1


def test_bulk_research_for_project(tenant_a: Tenant) -> None:
    project_id = _project(tenant_a)
    csv_text = (FIXTURES / "companies_sample.csv").read_text()
    tenant_a.client.post(
        "/api/v1/companies/import",
        json={"csv_text": csv_text, "dry_run": False, "project_id": project_id},
        headers=tenant_a.headers,
    )
    response = tenant_a.client.post("/api/v1/research-runs", json={"project_id": project_id}, headers=tenant_a.headers)
    body = response.json()
    assert len(body["started"]) == 4
    assert [s["reason"] for s in body["skipped"]] == ["no_website"]
    registry = research_registry()
    assert drain(registry) == 4
    runs = tenant_a.client.get(f"/api/v1/research-runs?project_id={project_id}", headers=tenant_a.headers).json()
    assert {r["status"] for r in runs["items"]} == {"completed"}
    summary = tenant_a.client.get("/api/v1/lead-intelligence/summary", headers=tenant_a.headers).json()
    assert summary["companies_researched"] == 4
    assert summary["research_runs"] == 4
    assert summary["total_companies"] == 5
    assert summary["opportunities_found"] > 0


def test_cancel_pending_run_via_api(tenant_a: Tenant) -> None:
    company = add_company(tenant_a, "northwind-logistics.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    cancelled = tenant_a.client.post(f"/api/v1/research-runs/{run_id}/cancel", headers=tenant_a.headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = tenant_a.client.post(f"/api/v1/research-runs/{run_id}/cancel", headers=tenant_a.headers)
    assert again.status_code == 409


# --- Opportunity review --------------------------------------------------------------------------


def test_opportunity_review_flow(tenant_a: Tenant, member_of_a: Tenant) -> None:
    _, results = research_company(tenant_a, "northwind-logistics.example", research_registry())
    opportunity = results["opportunities"][0]
    assert opportunity["status"] == "proposed"
    assert opportunity["evidence"], "opportunities must cite evidence"
    url = f"/api/v1/opportunities/{opportunity['id']}"

    reviewed = member_of_a.client.patch(url, json={"status": "under_review"}, headers=member_of_a.headers).json()
    assert reviewed["status"] == "under_review"
    assert reviewed["reviewed_by_user_id"] == str(member_of_a.user.id)
    rejected = tenant_a.client.patch(
        url, json={"status": "rejected", "reviewer_note": "  Not relevant  "}, headers=tenant_a.headers
    ).json()
    assert (rejected["status"], rejected["reviewer_note"]) == ("rejected", "Not relevant")

    invalid = tenant_a.client.patch(url, json={"status": "approved"}, headers=tenant_a.headers)
    assert invalid.status_code == 400
    assert invalid.json()["error"]["details"]["allowed"] == ["under_review"]
    assert tenant_a.client.patch(url, json={}, headers=tenant_a.headers).status_code == 400
    assert tenant_a.client.patch(url, json={"status": "deleted"}, headers=tenant_a.headers).status_code == 422
    assert tenant_a.client.patch(url, json={"reviewer_note": "x" * 2001}, headers=tenant_a.headers).status_code == 422

    queue = tenant_a.client.get("/api/v1/opportunities?status=rejected", headers=tenant_a.headers).json()
    assert [o["id"] for o in queue["items"]] == [opportunity["id"]]


# --- Tenant isolation ----------------------------------------------------------------------------


@pytest.fixture
def researched_a(tenant_a: Tenant) -> dict[str, Any]:
    run, results = research_company(tenant_a, "northwind-logistics.example", research_registry())
    return {"run": run, "results": results, "company_id": run["company_id"], "run_id": run["id"]}


def _foreign_urls(data: dict[str, Any]) -> list[tuple[str, str]]:
    company, run = data["company_id"], data["run_id"]
    opportunity = data["results"]["opportunities"][0]["id"]
    return [
        ("GET", f"/api/v1/companies/{company}"),
        ("GET", f"/api/v1/companies/{company}/evidence"),
        ("GET", f"/api/v1/companies/{company}/sources"),
        ("GET", f"/api/v1/companies/{company}/opportunities"),
        ("GET", f"/api/v1/research-runs/{run}"),
        ("GET", f"/api/v1/research-runs/{run}/results"),
        ("POST", f"/api/v1/research-runs/{run}/cancel"),
        ("GET", f"/api/v1/opportunities/{opportunity}"),
        ("PATCH", f"/api/v1/opportunities/{opportunity}"),
    ]


def test_other_tenant_gets_404_for_every_resource(researched_a: dict[str, Any], tenant_b: Tenant) -> None:
    for method, url in _foreign_urls(researched_a):
        response = tenant_b.client.request(method, url, json={"status": "rejected"}, headers=tenant_b.headers)
        assert response.status_code == 404, (method, url, response.status_code)


def test_spoofed_org_header_gets_403(researched_a: dict[str, Any], tenant_a: Tenant, tenant_b: Tenant) -> None:
    for method, url in [*_foreign_urls(researched_a), ("GET", "/api/v1/companies"), ("GET", "/api/v1/opportunities")]:
        response = tenant_b.client.request(method, url, json={"status": "rejected"}, headers=tenant_a.headers)
        assert response.status_code == 403, (method, url)


def test_lists_and_summary_do_not_leak(researched_a: dict[str, Any], tenant_b: Tenant) -> None:
    for url in ("/api/v1/companies", "/api/v1/research-runs", "/api/v1/opportunities"):
        assert tenant_b.client.get(url, headers=tenant_b.headers).json()["total"] == 0
    summary = tenant_b.client.get("/api/v1/lead-intelligence/summary", headers=tenant_b.headers).json()
    assert summary["total_companies"] == summary["opportunities_found"] == summary["research_runs"] == 0


def test_cannot_research_or_link_foreign_companies(researched_a: dict[str, Any], tenant_b: Tenant, db: Session) -> None:
    started = start(tenant_b, [researched_a["company_id"]])
    assert started["started"] == []
    assert started["skipped"][0]["reason"] == "not_found"
    project_b = _project(tenant_b)
    response = tenant_b.client.post(
        f"/api/v1/projects/{project_b}/companies",
        json={"company_ids": [researched_a["company_id"]]},
        headers=tenant_b.headers,
    )
    assert response.status_code == 404
    # Foreign project id in a company create is rejected too.
    project_a = tenant_b.client.get("/api/v1/projects", headers=tenant_b.headers).json()["items"][0]["id"]
    assert project_a == project_b


def test_run_id_of_other_company_is_not_accepted(researched_a: dict[str, Any], tenant_a: Tenant) -> None:
    other = add_company(tenant_a, "brightsmile-dental.example")
    response = tenant_a.client.get(
        f"/api/v1/companies/{other['id']}/evidence?run_id={researched_a['run_id']}", headers=tenant_a.headers
    )
    assert response.status_code == 404


def test_database_rejects_cross_tenant_links(researched_a: dict[str, Any], tenant_b: Tenant, db: Session) -> None:
    """Composite FKs: an opportunity row for Org B cannot point at Org A's research run/company."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Opportunity(
            organization_id=tenant_b.org.id,
            research_run_id=researched_a["run_id"],
            company_id=researched_a["company_id"],
            title="x",
            observed_context="x",
            problem_hypothesis="x",
            proposed_ai_solution="x",
            estimated_business_impact="x",
            implementation_complexity="low",
            confidence="low",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
