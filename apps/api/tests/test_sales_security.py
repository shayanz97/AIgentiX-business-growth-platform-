"""Sales security: authentication, tenant isolation (404 by id, 403 spoofed header), contact data, compliance."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aigentix.api.app import create_app
from aigentix.modules.sales.models import SalesOpportunity
from tests.conftest import Tenant
from tests.research_helpers import client_get
from tests.sales_helpers import convert, new_deal, qualified_lead


@pytest.fixture
def deal_a(tenant_a: Tenant) -> dict[str, Any]:
    deal = new_deal(tenant_a)
    contact = tenant_a.client.post(
        "/api/v1/sales/contacts",
        json={
            "company_id": deal["company"]["id"],
            "name": "Erika Muster",
            "role": "Head of Customer Service",
            "business_email": "erika@kundenservice-anfrage.example",
            "source": "inbound_inquiry",
            "lawful_basis": "inbound_request",
            "lawful_basis_reference": "Inquiry e-mail of 2026-11-03, CRM note",
        },
        headers=tenant_a.headers,
    )
    assert contact.status_code == 201, contact.text
    return {"deal": deal, "contact": contact.json()}


def _urls(data: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    deal, contact = data["deal"], data["contact"]
    d, c = deal["id"], contact["id"]
    return [
        ("GET", f"/api/v1/sales/opportunities/{d}", None),
        ("PATCH", f"/api/v1/sales/opportunities/{d}", {"expected_version": deal["version"], "title": "Hijack"}),
        (
            "POST",
            f"/api/v1/sales/opportunities/{d}/stage",
            {"expected_version": deal["version"], "stage": "researching"},
        ),
        ("POST", f"/api/v1/sales/opportunities/{d}/close", {"expected_version": deal["version"], "outcome": "lost"}),
        ("POST", f"/api/v1/sales/opportunities/{d}/reopen", {"expected_version": deal["version"], "reason": "test it"}),
        ("GET", f"/api/v1/sales/opportunities/{d}/history", None),
        ("GET", f"/api/v1/sales/opportunities/{d}/activities", None),
        ("POST", f"/api/v1/sales/opportunities/{d}/activities", {"activity_type": "note", "description": "x"}),
        ("PATCH", f"/api/v1/sales/contacts/{c}", {"expected_version": contact["version"], "name": "X"}),
        (
            "POST",
            f"/api/v1/sales/contacts/{c}/reviews",
            {"channel": "email", "decision": "not_allowed", "lawful_basis": "none"},
        ),
        ("GET", f"/api/v1/sales/contacts/{c}/reviews", None),
        (
            "POST",
            f"/api/v1/leads/{deal['company']['id']}/convert",
            {"idempotency_key": str(uuid.uuid4()), "allow_additional": True},
        ),
    ]


def test_sales_endpoints_require_authentication(deal_a: dict[str, Any]) -> None:
    extra: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/api/v1/sales/opportunities", None),
        ("POST", "/api/v1/sales/opportunities", {"company_id": deal_a["deal"]["company"]["id"], "title": "x"}),
        ("GET", "/api/v1/sales/contacts", None),
        ("POST", "/api/v1/sales/suppressions", {"channel": "email", "value": "a@b.example"}),
        ("GET", "/api/v1/sales/metrics", None),
    ]
    with TestClient(create_app()) as anonymous:
        for method, url, body in [*_urls(deal_a), *extra]:
            assert anonymous.request(method, url, json=body).status_code == 401, (method, url)


def test_other_tenant_gets_404(deal_a: dict[str, Any], tenant_b: Tenant) -> None:
    for method, url, body in _urls(deal_a):
        response = tenant_b.client.request(method, url, json=body, headers=tenant_b.headers)
        assert response.status_code == 404, (method, url, response.status_code, response.text)


def test_spoofed_org_header_gets_403(deal_a: dict[str, Any], tenant_a: Tenant, tenant_b: Tenant) -> None:
    extra: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/api/v1/sales/opportunities", None),
        ("GET", "/api/v1/sales/contacts", None),
        ("GET", "/api/v1/sales/metrics", None),
    ]
    for method, url, body in [*_urls(deal_a), *extra]:
        response = tenant_b.client.request(method, url, json=body, headers=tenant_a.headers)
        assert response.status_code == 403, (method, url)


def test_lists_and_metrics_do_not_leak(deal_a: dict[str, Any], tenant_b: Tenant) -> None:
    assert client_get(tenant_b.client, "/api/v1/sales/opportunities", tenant_b.headers)["total"] == 0
    assert client_get(tenant_b.client, "/api/v1/sales/contacts", tenant_b.headers) == []
    metrics = client_get(tenant_b.client, "/api/v1/sales/metrics", tenant_b.headers)
    assert metrics["opportunities_total"] == 0
    assert metrics["qualified_leads"] == 0
    # Foreign company ids cannot be used to create deals or contacts.
    company = deal_a["deal"]["company"]["id"]
    body = {"company_id": company, "title": "Steal"}
    assert tenant_b.client.post("/api/v1/sales/opportunities", json=body, headers=tenant_b.headers).status_code == 404
    contact = {"company_id": company, "name": "X", "source": "other"}
    assert tenant_b.client.post("/api/v1/sales/contacts", json=contact, headers=tenant_b.headers).status_code == 404


def test_database_rejects_cross_tenant_links(deal_a: dict[str, Any], tenant_b: Tenant, db: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    db.add(
        SalesOpportunity(
            organization_id=tenant_b.org.id,
            company_id=uuid.UUID(deal_a["deal"]["company"]["id"]),
            title="cross-tenant",
            stage="qualified",
            status="open",
            priority="low",
            currency="EUR",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_member_can_convert_and_rejected_lead_cannot(tenant_a: Tenant, member_of_a: Tenant) -> None:
    lead = qualified_lead(tenant_a)
    assert convert(member_of_a, lead["company_id"]).status_code == 201
    rejected = qualified_lead(tenant_a, "nordwerk-hiring.example", review="rejected")
    assert convert(tenant_a, rejected["company_id"]).status_code == 400


def test_contact_compliance_flow(deal_a: dict[str, Any], tenant_a: Tenant) -> None:
    contact, deal = deal_a["contact"], deal_a["deal"]
    email = next(p for p in contact["permissions"] if p["channel"] == "email")
    assert email["allowed"] is False  # no eligibility review yet
    url = f"/api/v1/sales/contacts/{contact['id']}/reviews"
    weak = {"channel": "email", "decision": "allowed", "lawful_basis": "legitimate_interest"}
    assert tenant_a.client.post(url, json=weak, headers=tenant_a.headers).status_code == 400
    ok = {"channel": "email", "decision": "allowed", "lawful_basis": "inbound_request", "note": "Asked us to reply"}
    assert tenant_a.client.post(url, json=ok, headers=tenant_a.headers).status_code == 201
    listed = client_get(tenant_a.client, f"/api/v1/sales/contacts?company_id={deal['company']['id']}", tenant_a.headers)
    assert next(p for p in listed[0]["permissions"] if p["channel"] == "email")["allowed"] is True
    # The contact opts out: suppression wins over the review, and cannot be edited away.
    body = {"channel": "email", "value": "ERIKA@kundenservice-anfrage.example", "reason": "Unsubscribed by phone"}
    assert tenant_a.client.post("/api/v1/sales/suppressions", json=body, headers=tenant_a.headers).status_code == 201
    assert tenant_a.client.post("/api/v1/sales/suppressions", json=body, headers=tenant_a.headers).status_code == 200
    listed = client_get(tenant_a.client, "/api/v1/sales/contacts", tenant_a.headers)
    assert listed[0]["restriction_status"] == "suppressed"
    assert not any(p["allowed"] for p in listed[0]["permissions"])
    patch = {"expected_version": listed[0]["version"], "restriction_status": "unverified"}
    edited = tenant_a.client.patch(f"/api/v1/sales/contacts/{contact['id']}", json=patch, headers=tenant_a.headers)
    assert edited.json()["restriction_status"] == "suppressed"
    assert tenant_a.client.post(url, json=ok, headers=tenant_a.headers).status_code == 400
    # Recording an outbound e-mail to a suppressed contact is refused; a received e-mail is still recorded.
    activities = f"/api/v1/sales/opportunities/{deal['id']}/activities"
    sent = {"activity_type": "email_sent", "description": "Follow-up", "contact_id": contact["id"]}
    assert tenant_a.client.post(activities, json=sent, headers=tenant_a.headers).status_code == 400
    received = {"activity_type": "email_received", "description": "Customer replied", "contact_id": contact["id"]}
    assert tenant_a.client.post(activities, json=received, headers=tenant_a.headers).status_code == 201


def test_contact_validation(deal_a: dict[str, Any], tenant_a: Tenant) -> None:
    company = deal_a["deal"]["company"]["id"]
    no_reference = {"company_id": company, "name": "A", "source": "event", "lawful_basis": "explicit_consent"}
    assert (
        tenant_a.client.post("/api/v1/sales/contacts", json=no_reference, headers=tenant_a.headers).status_code == 400
    )
    bad_email = {"company_id": company, "name": "A", "source": "event", "business_email": "not-an-email"}
    response = tenant_a.client.post("/api/v1/sales/contacts", json=bad_email, headers=tenant_a.headers)
    assert response.status_code == 422
    assert "not-an-email" not in response.text  # validation errors never echo input
    scraped = {"company_id": company, "name": "A", "source": "linkedin_scrape"}
    assert tenant_a.client.post("/api/v1/sales/contacts", json=scraped, headers=tenant_a.headers).status_code == 422
