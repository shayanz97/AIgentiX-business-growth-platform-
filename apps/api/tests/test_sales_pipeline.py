"""Sales pipeline: conversion (idempotent, duplicate-safe, eligibility), stage rules, close/reopen, metrics."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.models import LeadScore
from aigentix.modules.sales.models import SalesOpportunity, SalesStageHistory
from tests.conftest import Tenant
from tests.research_helpers import add_company, client_get
from tests.sales_helpers import convert, move, new_deal, qualified_lead


def test_convert_is_idempotent_and_duplicate_safe(tenant_a: Tenant, db: Session) -> None:
    lead = qualified_lead(tenant_a)
    scores_before = [(s.id, s.score_low) for s in db.scalars(select(LeadScore))]
    key = str(uuid.uuid4())
    first = convert(tenant_a, lead["company_id"], idempotency_key=key)
    assert first.status_code == 201, first.text
    deal = first.json()["opportunity"]
    assert deal["stage"] == "qualified"
    assert deal["status"] == "open"
    assert deal["source_lead_score_id"] == lead["score"]["id"]
    assert deal["company"]["canonical_domain"] == "kundenservice-anfrage.example"
    assert deal["estimated_value"] is None  # never invented
    retry = convert(tenant_a, lead["company_id"], idempotency_key=key)
    assert retry.status_code == 200
    assert retry.json()["opportunity"]["id"] == deal["id"]
    duplicate = convert(tenant_a, lead["company_id"])
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["details"]["existing_opportunity_id"] == deal["id"]
    additional = convert(tenant_a, lead["company_id"], allow_additional=True, title="Second project")
    assert additional.status_code == 201
    assert db.scalar(select(func.count()).select_from(SalesOpportunity)) == 2
    assert [(s.id, s.score_low) for s in db.scalars(select(LeadScore))] == scores_before  # scores untouched
    activities = client_get(tenant_a.client, f"/api/v1/sales/opportunities/{deal['id']}/activities", tenant_a.headers)
    assert activities[0]["activity_type"] == "system"
    assert "Converted" in activities[0]["description"]


def test_conversion_eligibility(tenant_a: Tenant) -> None:
    lead = qualified_lead(tenant_a, "nordwerk-hiring.example", review="needs_research")
    response = convert(tenant_a, lead["company_id"])
    assert response.status_code == 400
    assert "needs_research" in response.text
    unscored = add_company(tenant_a, "https://unscored.example/")
    tenant_a.client.patch(
        f"/api/v1/leads/{unscored['id']}/review", json={"status": "qualified_for_review"}, headers=tenant_a.headers
    )
    assert convert(tenant_a, unscored["id"]).status_code == 400
    assert convert(tenant_a, str(uuid.uuid4())).status_code == 404
    other = qualified_lead(tenant_a, "digitalwerk-solutions.example")
    bad_source = convert(tenant_a, other["company_id"], source_opportunity_id=str(uuid.uuid4()))
    assert bad_source.status_code == 404


def test_conversion_with_research_opportunity(tenant_a: Tenant) -> None:
    lead = qualified_lead(tenant_a, "digitalwerk-solutions.example")
    assert lead["opportunities"], "fixture should have research opportunities"
    opp = lead["opportunities"][0]
    response = convert(tenant_a, lead["company_id"], source_opportunity_id=opp["id"])
    assert response.status_code == 201
    deal = response.json()["opportunity"]
    assert deal["source_opportunity_id"] == opp["id"]
    assert opp["title"] in deal["title"]
    # Another research opportunity of the same company is a legitimate second deal.
    if len(lead["opportunities"]) > 1:
        second = convert(tenant_a, lead["company_id"], source_opportunity_id=lead["opportunities"][1]["id"])
        assert second.status_code == 201


def test_stage_rules_require_recorded_events(tenant_a: Tenant, db: Session) -> None:
    deal = new_deal(tenant_a)
    url = f"/api/v1/sales/opportunities/{deal['id']}"
    skip = move(tenant_a, deal, "proposal_sent")
    assert skip.status_code == 400
    assert "Allowed" in skip.text
    assert move(tenant_a, deal, "won").status_code == 400  # outcomes only via close
    deal = move(tenant_a, deal, "contact_planned").json()
    talk = move(tenant_a, deal, "in_conversation")
    assert talk.status_code == 400
    assert "contact" in talk.text
    stale = move(tenant_a, {**deal, "version": deal["version"] - 1}, "researching")
    assert stale.status_code == 409  # optimistic locking
    call = tenant_a.client.post(
        f"{url}/activities",
        json={"activity_type": "call", "description": "Intro call with the service lead"},
        headers=tenant_a.headers,
    )
    assert call.status_code == 201
    deal = client_get(tenant_a.client, url, tenant_a.headers)
    deal = move(tenant_a, deal, "in_conversation").json()
    assert deal["stage"] == "in_conversation"
    sent = move(tenant_a, deal, "proposal_sent")
    assert sent.status_code == 400
    assert "proposal" in sent.text
    future = tenant_a.client.post(
        f"{url}/activities",
        json={"activity_type": "meeting", "description": "x", "occurred_at": "2099-01-01T10:00:00Z"},
        headers=tenant_a.headers,
    )
    assert future.status_code == 400
    system = tenant_a.client.post(
        f"{url}/activities", json={"activity_type": "system", "description": "x"}, headers=tenant_a.headers
    )
    assert system.status_code == 422
    history = client_get(tenant_a.client, f"{url}/history", tenant_a.headers)
    assert [h["new_stage"] for h in history] == ["qualified", "contact_planned", "in_conversation"]
    assert db.scalar(select(func.count()).select_from(SalesStageHistory)) == 3


def test_close_reopen_and_metrics(tenant_a: Tenant, db: Session) -> None:
    deal = new_deal(tenant_a)
    url = f"/api/v1/sales/opportunities/{deal['id']}"
    deal = tenant_a.client.patch(
        url, json={"expected_version": deal["version"], "estimated_value": "12000.00"}, headers=tenant_a.headers
    ).json()
    metrics = client_get(tenant_a.client, "/api/v1/sales/metrics", tenant_a.headers)
    assert metrics["pipeline_value"] == {"EUR": "12000.00"}
    assert metrics["open_opportunities"] == 1
    assert metrics["converted_leads"] == 1
    assert metrics["qualified_leads"] == 1
    assert metrics["lead_to_opportunity_rate"] == 1.0
    assert metrics["win_rate"] is None
    lost_with_value = tenant_a.client.post(
        f"{url}/close",
        json={"expected_version": deal["version"], "outcome": "lost", "won_value": "1"},
        headers=tenant_a.headers,
    )
    assert lost_with_value.status_code == 400
    won = tenant_a.client.post(
        f"{url}/close",
        json={"expected_version": deal["version"], "outcome": "won", "won_value": "9500"},
        headers=tenant_a.headers,
    ).json()
    assert won["stage"] == won["status"] == "won"
    assert won["closed_at"]
    assert move(tenant_a, won, "researching").status_code == 400  # closed deals do not move
    metrics = client_get(tenant_a.client, "/api/v1/sales/metrics", tenant_a.headers)
    assert metrics["won_count"] == 1
    assert metrics["won_value"] == {"EUR": "9500.00"}
    assert metrics["pipeline_value"] == {}
    assert metrics["win_rate"] == 1.0
    assert metrics["opportunity_to_won_rate"] == 1.0
    no_reason = tenant_a.client.post(
        f"{url}/reopen", json={"expected_version": won["version"], "reason": ""}, headers=tenant_a.headers
    )
    assert no_reason.status_code == 422
    reopened = tenant_a.client.post(
        f"{url}/reopen",
        json={"expected_version": won["version"], "reason": "Customer withdrew the order"},
        headers=tenant_a.headers,
    ).json()
    assert reopened["status"] == "open"
    assert reopened["stage"] == "qualified"
    assert reopened["won_value"] is None
    lost = tenant_a.client.post(
        f"{url}/close",
        json={"expected_version": reopened["version"], "outcome": "lost", "lost_reason": "Budget frozen"},
        headers=tenant_a.headers,
    ).json()
    assert lost["lost_reason"] == "Budget frozen"
    history = [h["new_stage"] for h in client_get(tenant_a.client, f"{url}/history", tenant_a.headers)]
    assert history == ["qualified", "won", "qualified", "lost"]


def test_deal_list_filters_and_manual_create(tenant_a: Tenant, member_of_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    company = deal["company"]["id"]
    manual = tenant_a.client.post(
        "/api/v1/sales/opportunities",
        json={
            "company_id": company,
            "title": "Support chatbot",
            "priority": "high",
            "owner_user_id": str(member_of_a.user.id),
        },
        headers=tenant_a.headers,
    )
    assert manual.status_code == 201
    foreign_owner = tenant_a.client.post(
        "/api/v1/sales/opportunities",
        json={"company_id": company, "title": "X", "owner_user_id": str(uuid.uuid4())},
        headers=tenant_a.headers,
    )
    assert foreign_owner.status_code == 400

    def titles(query: str) -> list[str]:
        return [
            d["title"]
            for d in client_get(tenant_a.client, f"/api/v1/sales/opportunities?{query}", tenant_a.headers)["items"]
        ]

    assert "Support chatbot" in titles("priority=high")  # the converted lead is high too (from its score band)
    assert titles(f"owner_user_id={member_of_a.user.id}") == ["Support chatbot"]
    assert len(titles("stage=qualified&sort=title")) == 2
    assert titles("q=chatbot") == ["Support chatbot"]
    assert titles("status=won") == []
    bad: dict[str, Any] = {"expected_version": 1, "stage": "won"}
    assert (
        tenant_a.client.patch(
            f"/api/v1/sales/opportunities/{deal['id']}", json=bad, headers=tenant_a.headers
        ).status_code
        == 422
    )
