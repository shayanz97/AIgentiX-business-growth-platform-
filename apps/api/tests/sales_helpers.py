"""Shared helpers for Sales tests: a researched, enriched, scored and qualified lead, and a converted deal."""

import uuid
from typing import Any

from tests.conftest import Tenant
from tests.research_helpers import client_get, enrich, research_company, research_registry


def qualified_lead(
    t: Tenant, domain: str = "kundenservice-anfrage.example", *, review: str = "qualified_for_review"
) -> dict[str, Any]:
    """Research + enrich a fixture company and review it; returns {company_id, opportunities, score}."""
    registry = research_registry()
    run, results = research_company(t, domain, registry)
    company_id = run["company_id"]
    enrich(t, company_id, registry)
    response = t.client.patch(f"/api/v1/leads/{company_id}/review", json={"status": review}, headers=t.headers)
    assert response.status_code == 200, response.text
    return {
        "company_id": company_id,
        "opportunities": results["opportunities"],
        "score": client_get(t.client, f"/api/v1/companies/{company_id}/scores", t.headers)["items"][0],
    }


def convert(t: Tenant, company_id: str, **body: Any) -> Any:
    payload = {"idempotency_key": str(uuid.uuid4()), **body}
    return t.client.post(f"/api/v1/leads/{company_id}/convert", json=payload, headers=t.headers)


def new_deal(t: Tenant, **lead_kwargs: Any) -> dict[str, Any]:
    lead = qualified_lead(t, **lead_kwargs)
    response = convert(t, lead["company_id"])
    assert response.status_code == 201, response.text
    return response.json()["opportunity"]  # type: ignore[no-any-return]


def move(t: Tenant, deal: dict[str, Any], stage: str, **extra: Any) -> Any:
    body = {"expected_version": deal["version"], "stage": stage, **extra}
    return t.client.post(f"/api/v1/sales/opportunities/{deal['id']}/stage", json=body, headers=t.headers)
