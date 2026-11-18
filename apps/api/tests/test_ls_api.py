"""Sprint 3 API: tenant isolation, roles, profiles, scoring history, ranking, review and export."""

import csv
import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.api.app import create_app
from aigentix.modules.lead_intelligence.models import BusinessSignal, BuyingIntentSignal, LeadScore
from tests.conftest import Tenant, random_uuid
from tests.research_helpers import add_company, client_get, enrich, latest_score, research_company, research_registry


@pytest.fixture
def enriched_a(tenant_a: Tenant) -> dict[str, Any]:
    registry = research_registry()
    run, _ = research_company(tenant_a, "kundenservice-anfrage.example", registry)
    company_id = run["company_id"]
    view = enrich(tenant_a, company_id, registry)
    project = tenant_a.client.post("/api/v1/projects", json={"name": "Pilot"}, headers=tenant_a.headers).json()
    tenant_a.client.post(
        f"/api/v1/projects/{project['id']}/companies", json={"company_ids": [company_id]}, headers=tenant_a.headers
    )
    profiles = client_get(tenant_a.client, "/api/v1/scoring-profiles", tenant_a.headers)
    return {
        "company_id": company_id,
        "project_id": project["id"],
        "view": view,
        "registry": registry,
        "scoring_profile_id": profiles[0]["id"],
        "icp_profile_id": client_get(tenant_a.client, "/api/v1/icp-profiles", tenant_a.headers)[0]["id"],
    }


def _company_urls(data: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    company, project = data["company_id"], data["project_id"]
    return [
        ("POST", f"/api/v1/companies/{company}/enrich", {}),
        ("GET", f"/api/v1/companies/{company}/signals", None),
        ("GET", f"/api/v1/companies/{company}/scores", None),
        ("POST", f"/api/v1/companies/{company}/score", {}),
        (
            "POST",
            f"/api/v1/companies/{company}/intent-signals",
            {"channel": "email", "received_on": "2026-11-01", "summary": "Asked about automation"},
        ),
        ("GET", f"/api/v1/leads/{company}", None),
        ("PATCH", f"/api/v1/leads/{company}/review", {"status": "rejected"}),
        ("POST", f"/api/v1/projects/{project}/score", {}),
        ("GET", f"/api/v1/projects/{project}/leads", None),
        ("PATCH", f"/api/v1/scoring-profiles/{data['scoring_profile_id']}", {"name": "Hijacked"}),
        ("PATCH", f"/api/v1/icp-profiles/{data['icp_profile_id']}", {"name": "Hijacked"}),
    ]


def test_new_endpoints_require_authentication(enriched_a: dict[str, Any]) -> None:
    with TestClient(create_app()) as anonymous:
        urls = [
            *_company_urls(enriched_a),
            ("GET", "/api/v1/leads/ranked", None),
            ("GET", "/api/v1/leads/export", None),
            ("GET", "/api/v1/scoring-profiles", None),
            ("GET", "/api/v1/icp-profiles", None),
            ("POST", "/api/v1/enrichment-runs", {"company_ids": [enriched_a["company_id"]]}),
        ]
        for method, url, body in urls:
            response = anonymous.request(method, url, json=body)
            assert response.status_code == 401, (method, url, response.status_code)


def test_other_tenant_gets_404(enriched_a: dict[str, Any], tenant_b: Tenant) -> None:
    for method, url, body in _company_urls(enriched_a):
        response = tenant_b.client.request(method, url, json=body, headers=tenant_b.headers)
        assert response.status_code == 404, (method, url, response.status_code, response.text)


def test_spoofed_org_header_gets_403(enriched_a: dict[str, Any], tenant_a: Tenant, tenant_b: Tenant) -> None:
    extra: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/api/v1/leads/ranked", None),
        ("GET", "/api/v1/leads/export", None),
        ("GET", "/api/v1/scoring-profiles", None),
        ("POST", "/api/v1/scoring-profiles", {"name": "X"}),
        ("POST", "/api/v1/enrichment-runs", {"company_ids": [enriched_a["company_id"]]}),
    ]
    for method, url, body in [*_company_urls(enriched_a), *extra]:
        response = tenant_b.client.request(method, url, json=body, headers=tenant_a.headers)
        assert response.status_code == 403, (method, url)


def test_lists_do_not_leak(enriched_a: dict[str, Any], tenant_b: Tenant, db: Session) -> None:
    assert client_get(tenant_b.client, "/api/v1/leads/ranked", tenant_b.headers)["total"] == 0
    export = tenant_b.client.get("/api/v1/leads/export", headers=tenant_b.headers)
    assert export.status_code == 200
    assert len(export.text.strip().splitlines()) == 1
    # Each organization gets its own default profiles.
    b_profiles = client_get(tenant_b.client, "/api/v1/scoring-profiles", tenant_b.headers)
    assert [p["id"] for p in b_profiles] != [enriched_a["scoring_profile_id"]]
    # Bulk enrichment of a foreign company id is skipped as not found, never started.
    body = {"company_ids": [enriched_a["company_id"]]}
    result = tenant_b.client.post("/api/v1/enrichment-runs", json=body, headers=tenant_b.headers).json()
    assert result["started"] == []
    assert result["skipped"][0]["reason"] == "not_found"


def test_signals_view_and_evidence(enriched_a: dict[str, Any]) -> None:
    view = enriched_a["view"]
    assert view["intent_status"] == "explicit"
    request = next(s for s in view["signals"] if s["signal_type"] == "public_project_request")
    assert request["occurred_on"] == "2026-11-03"
    assert request["deadline_on"] == "2026-12-04"
    assert request["evidence"]
    assert all(e["supporting_excerpt"] for e in request["evidence"])
    intent = view["intents"][0]
    assert intent["strength"] == "explicit"
    assert intent["source_type"] == "website"
    assert intent["evidence"]
    assert view["sources_checked"][0] == "website"


def test_member_cannot_change_profiles(enriched_a: dict[str, Any], member_of_a: Tenant) -> None:
    headers = member_of_a.headers
    assert (
        member_of_a.client.post("/api/v1/scoring-profiles", json={"name": "Mine"}, headers=headers).status_code == 403
    )
    url = f"/api/v1/scoring-profiles/{enriched_a['scoring_profile_id']}"
    assert member_of_a.client.patch(url, json={"name": "Mine"}, headers=headers).status_code == 403
    url = f"/api/v1/icp-profiles/{enriched_a['icp_profile_id']}"
    assert member_of_a.client.patch(url, json={"name": "Mine"}, headers=headers).status_code == 403
    # Members can still read profiles, score and review.
    assert member_of_a.client.get("/api/v1/scoring-profiles", headers=headers).status_code == 200
    review = {"status": "needs_research", "note": "check volumes"}
    url = f"/api/v1/leads/{enriched_a['company_id']}/review"
    assert member_of_a.client.patch(url, json=review, headers=headers).status_code == 200


def test_profile_validation_and_versioning(enriched_a: dict[str, Any], tenant_a: Tenant) -> None:
    url = f"/api/v1/scoring-profiles/{enriched_a['scoring_profile_id']}"
    bad = {"config": {"weights": {"opportunity": 50, "fit": 25, "triggers": 20, "intent": 20}}}
    response = tenant_a.client.patch(url, json=bad, headers=tenant_a.headers)
    assert response.status_code == 400
    assert "sum to 100" in response.text
    secret = "SECRET-VALUE-123"
    response = tenant_a.client.patch(url, json={"config": {"weights": secret}}, headers=tenant_a.headers)
    assert response.status_code == 400
    assert secret not in response.text
    response = tenant_a.client.patch(url, json={"config": {"unknown": 1}}, headers=tenant_a.headers)
    assert response.status_code == 400
    icp = f"/api/v1/icp-profiles/{enriched_a['icp_profile_id']}"
    response = tenant_a.client.patch(icp, json={"config": {"countries": ["Germany"]}}, headers=tenant_a.headers)
    assert response.status_code == 400

    good = {"config": {"weights": {"opportunity": 20, "fit": 20, "triggers": 20, "intent": 40}}}
    updated = tenant_a.client.patch(url, json=good, headers=tenant_a.headers).json()
    assert updated["version"] == 2
    assert updated["config"]["weights"]["intent"] == 40
    same = tenant_a.client.patch(url, json=good, headers=tenant_a.headers).json()
    assert same["version"] == 2  # unchanged config → no new version

    created = tenant_a.client.post(
        "/api/v1/scoring-profiles", json={"name": "Intent first", "is_default": True}, headers=tenant_a.headers
    )
    assert created.status_code == 201
    listed = client_get(tenant_a.client, "/api/v1/scoring-profiles", tenant_a.headers)
    assert [p["is_default"] for p in listed].count(True) == 1
    assert listed[0]["name"] == "Intent first"
    duplicate = tenant_a.client.post(
        "/api/v1/scoring-profiles", json={"name": "intent FIRST"}, headers=tenant_a.headers
    )
    assert duplicate.status_code == 409


def test_rescore_after_weight_change_without_crawling_or_ai(
    enriched_a: dict[str, Any], tenant_a: Tenant, db: Session
) -> None:
    company_id = enriched_a["company_id"]
    before = latest_score(tenant_a, company_id)
    signals_before = db.scalar(select(func.count()).select_from(BusinessSignal))
    # Same inputs and profiles → no duplicate snapshot.
    again = tenant_a.client.post(f"/api/v1/companies/{company_id}/score", json={}, headers=tenant_a.headers).json()
    assert again["new_snapshots"] == 0
    assert again["scores"][0]["id"] == before["id"]

    url = f"/api/v1/scoring-profiles/{enriched_a['scoring_profile_id']}"
    weights = {"opportunity": 10, "fit": 20, "triggers": 20, "intent": 50}
    tenant_a.client.patch(url, json={"config": {"weights": weights}}, headers=tenant_a.headers)
    project = enriched_a["project_id"]
    result = tenant_a.client.post(f"/api/v1/projects/{project}/score", json={}, headers=tenant_a.headers).json()
    assert result["scored"] == 1
    assert result["new_snapshots"] == 1
    after = latest_score(tenant_a, company_id)
    assert after["scoring_profile_version"] == before["scoring_profile_version"] + 1
    assert after["score_low"] > before["score_low"]  # explicit intent now weighs more
    # No new workflow run was started: rescoring reads stored data only.
    runs = client_get(tenant_a.client, f"/api/v1/research-runs?company_id={company_id}", tenant_a.headers)
    assert runs["total"] == 2  # the original research + enrichment
    assert db.scalar(select(func.count()).select_from(BusinessSignal)) == signals_before
    history = client_get(tenant_a.client, f"/api/v1/companies/{company_id}/scores", tenant_a.headers)
    assert history["total"] == 2
    assert history["items"][0]["id"] == after["id"]


def test_reenrichment_is_idempotent(enriched_a: dict[str, Any], tenant_a: Tenant, db: Session) -> None:
    counts = (
        db.scalar(select(func.count()).select_from(BusinessSignal)),
        db.scalar(select(func.count()).select_from(BuyingIntentSignal)),
    )
    view = enrich(tenant_a, enriched_a["company_id"], enriched_a["registry"])
    assert view["enrichment_run"]["status"] == "completed"
    assert (
        db.scalar(select(func.count()).select_from(BusinessSignal)),
        db.scalar(select(func.count()).select_from(BuyingIntentSignal)),
    ) == counts
    # The new run re-verified the evidence (new evidence rows) → a new snapshot with the same result.
    scores = list(db.scalars(select(LeadScore).order_by(LeadScore.created_at)))
    assert len(scores) == 2
    assert scores[0].score_low == scores[1].score_low
    assert scores[0].enrichment_run_id != scores[1].enrichment_run_id


def test_recent_enrichment_is_reused_unless_forced(enriched_a: dict[str, Any], tenant_a: Tenant) -> None:
    url = f"/api/v1/companies/{enriched_a['company_id']}/enrich"
    reused = tenant_a.client.post(url, json={}, headers=tenant_a.headers).json()
    assert reused["started"] == []
    assert reused["rescored"][0]["reason"] == "recently_enriched"
    forced = tenant_a.client.post(url, json={"force": True}, headers=tenant_a.headers).json()
    assert len(forced["started"]) == 1
    assert forced["started"][0]["kind"] == "enrichment"
    again = tenant_a.client.post(url, json={"force": True}, headers=tenant_a.headers).json()
    assert again["skipped"][0]["reason"] == "already_running"


def test_first_party_intent(tenant_a: Tenant) -> None:
    company = add_company(tenant_a, "https://acme-intent.example/")
    url = f"/api/v1/companies/{company['id']}/intent-signals"
    body = {"channel": "contact_form", "received_on": "2026-11-01", "summary": "Requested a demo of AI triage"}
    first = tenant_a.client.post(url, json=body, headers=tenant_a.headers)
    assert first.status_code == 201
    assert first.json()["strength"] == "explicit"
    assert tenant_a.client.post(url, json=body, headers=tenant_a.headers).status_code == 200  # deduplicated
    future = {**body, "received_on": "2027-01-01"}
    assert tenant_a.client.post(url, json=future, headers=tenant_a.headers).status_code == 400
    bad = {**body, "solution_category": "mind_reading"}
    assert tenant_a.client.post(url, json=bad, headers=tenant_a.headers).status_code == 400
    # Scored without any research: intent counts, everything else is unknown → provisional, wide bounds.
    score = tenant_a.client.post(f"/api/v1/companies/{company['id']}/score", json={}, headers=tenant_a.headers)
    s = score.json()["scores"][0]
    assert s["intent_status"] == "explicit"
    assert s["provisional"] is True
    assert s["score_low"] < s["score_high"]
    assert s["coverage"] == pytest.approx(0.2)
    assert s["next_step"] == "review_active_request"


def test_review_history_and_filters(enriched_a: dict[str, Any], tenant_a: Tenant) -> None:
    company_id = enriched_a["company_id"]
    url = f"/api/v1/leads/{company_id}/review"
    for status in ("needs_research", "qualified_for_review"):
        assert tenant_a.client.patch(url, json={"status": status}, headers=tenant_a.headers).status_code == 200
    assert tenant_a.client.patch(url, json={"status": "contacted"}, headers=tenant_a.headers).status_code == 422
    detail = client_get(tenant_a.client, f"/api/v1/leads/{company_id}", tenant_a.headers)
    assert [r["status"] for r in detail["reviews"]] == ["qualified_for_review", "needs_research"]
    assert detail["lead"]["review_status"] == "qualified_for_review"

    def ids(query: str) -> list[str]:
        page = client_get(tenant_a.client, f"/api/v1/leads/ranked?{query}", tenant_a.headers)
        return [lead["company_id"] for lead in page["items"]]

    assert ids("review_status=qualified_for_review") == [company_id]
    assert ids("review_status=new") == []
    assert ids("intent_status=explicit&signal_type=public_project_request") == [company_id]
    assert ids("intent_status=none_verified") == []
    assert ids("min_score=99") == []
    assert ids("triggered_since=2026-11-01&sort=latest_trigger") == [company_id]
    assert ids(f"project_id={enriched_a['project_id']}") == [company_id]
    assert (
        tenant_a.client.get(f"/api/v1/leads/ranked?project_id={random_uuid()}", headers=tenant_a.headers).status_code
        == 404
    )
    assert tenant_a.client.get("/api/v1/leads/ranked?sort=random", headers=tenant_a.headers).status_code == 422


def test_ranking_is_deterministic_and_export_is_formula_safe(tenant_a: Tenant) -> None:
    registry = research_registry()
    for domain in ("kleinbetrieb-minimal.example", "wachstum-ohne-intent.example", "kundenservice-anfrage.example"):
        run, _ = research_company(tenant_a, domain, registry)
        enrich(tenant_a, run["company_id"], registry)
    # A company whose name starts with a spreadsheet formula character.
    hostile = add_company(tenant_a, "https://hostile.example/", name='=HYPERLINK("http://x")')
    tenant_a.client.post(
        f"/api/v1/companies/{hostile['id']}/intent-signals",
        json={"channel": "email", "received_on": "2026-11-01", "summary": "Inquiry about support automation"},
        headers=tenant_a.headers,
    )
    tenant_a.client.post(f"/api/v1/companies/{hostile['id']}/score", json={}, headers=tenant_a.headers)

    first = client_get(tenant_a.client, "/api/v1/leads/ranked", tenant_a.headers)["items"]
    second = client_get(tenant_a.client, "/api/v1/leads/ranked", tenant_a.headers)["items"]
    assert [x["company_id"] for x in first] == [x["company_id"] for x in second]
    scores = [x["score"]["score_low"] for x in first]
    assert scores == sorted(scores, reverse=True)
    assert first[0]["canonical_domain"] == "kundenservice-anfrage.example"

    export = tenant_a.client.get("/api/v1/leads/export", headers=tenant_a.headers)
    assert export.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(export.text)))
    assert rows[0][:3] == ["rank", "company", "domain"]
    assert len(rows) == 5
    names = [r[1] for r in rows[1:]]
    assert '\'=HYPERLINK("http://x")' in names
    assert not any(n.startswith("=") for n in names)


def test_foreign_profile_ids_are_rejected(enriched_a: dict[str, Any], tenant_b: Tenant) -> None:
    for param in ("scoring_profile_id", "icp_profile_id"):
        for path in ("/api/v1/leads/ranked", "/api/v1/leads/export"):
            url = f"{path}?{param}={enriched_a[param]}"
            assert tenant_b.client.get(url, headers=tenant_b.headers).status_code == 404, url
        body = {param: enriched_a[param]}
        company = add_company(tenant_b, "https://b-company.example/")
        url = f"/api/v1/companies/{company['id']}/score"
        assert tenant_b.client.post(url, json=body, headers=tenant_b.headers).status_code == 404
