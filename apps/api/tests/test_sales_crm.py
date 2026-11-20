"""CRM export: provider contract (mock), owner-only + confirmation, idempotency, failures, contact eligibility."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.modules.sales.config import SalesSettings
from aigentix.modules.sales.integrations import crm as registry
from aigentix.modules.sales.integrations.crm import CompanyPayload, DealPayload, MockCRMProvider
from aigentix.modules.sales.models import ExternalCRMMapping
from aigentix.modules.sales.services.crm import sanitize_error
from tests.conftest import Tenant, random_uuid
from tests.sales_helpers import new_deal


@pytest.fixture
def mock_crm(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockCRMProvider]:
    """Enable the mock provider for one test only (settings function patched, adapter cache reset)."""
    settings = SalesSettings(environment="test", sales_crm_providers="mock")
    monkeypatch.setattr(registry, "get_sales_settings", lambda: settings)
    registry.reset_providers()
    provider = registry.get_crm_provider("mock")
    assert isinstance(provider, MockCRMProvider)
    yield provider
    registry.reset_providers()


def _export(t: Tenant, ids: list[str], provider: str = "mock", **extra: Any) -> Any:
    body = {"opportunity_ids": ids, "confirm": True, **extra}
    return t.client.post(f"/api/v1/sales/crm/{provider}/export", json=body, headers=t.headers)


def _mappings(t: Tenant, **params: Any) -> list[dict[str, Any]]:
    response = t.client.get("/api/v1/sales/crm/mappings", params=params, headers=t.headers)
    assert response.status_code == 200
    return response.json()["items"]  # type: ignore[no-any-return]


# --- unit ----------------------------------------------------------------------------------------------------


def test_mock_provider_is_idempotent_and_deterministic() -> None:
    p = MockCRMProvider()
    company = CompanyPayload("c-1", "Acme", "acme.example", None)
    first = p.upsert_company(company, None)
    assert first == MockCRMProvider().upsert_company(company, None)  # deterministic
    assert p.upsert_company(CompanyPayload("c-1", "Acme GmbH", None, None), first) == first  # update, same id
    assert len(p.records) == 1
    assert p.records[first]["payload"].name == "Acme GmbH"
    assert p.calls == [("company", None), ("company", first)]
    deal = DealPayload("d-1", "t", "qualified", "open", "medium", None, "EUR", None, None, None, first)
    assert p.upsert_deal(deal, None).startswith("mock-deal-")
    with pytest.raises(registry.CRMProviderError):
        p.upsert_company(company, "mock-company-unknown")


def test_registry_only_serves_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    registry.reset_providers()
    assert registry.get_crm_provider("mock") is None  # not configured by default
    for names in ("hubspot", "pipedrive"):
        settings = SalesSettings(environment="test", sales_crm_providers=names)
        assert registry.get_crm_provider(names, settings) is None  # documented, not implemented
    with pytest.raises(ValueError, match="mock"):
        SalesSettings(environment="production", sales_crm_providers="mock")


def test_error_sanitising_hides_secrets() -> None:
    err = registry.CRMProviderError("401 Unauthorized: Bearer sk-live-123456 token=abc")
    cleaned = sanitize_error(err)
    assert "sk-live" not in cleaned
    assert "abc" not in cleaned
    assert sanitize_error(RuntimeError("password=hunter2")) == "Unexpected provider error (RuntimeError)"
    assert len(sanitize_error(registry.CRMProviderError("x" * 2000))) <= 500


# --- API -----------------------------------------------------------------------------------------------------


def test_providers_empty_by_default(tenant_a: Tenant) -> None:
    registry.reset_providers()
    body = tenant_a.client.get("/api/v1/sales/crm/providers", headers=tenant_a.headers).json()
    assert body["providers"] == []
    assert "No live CRM provider" in body["note"]


def test_providers_lists_mock_with_health(tenant_a: Tenant, mock_crm: MockCRMProvider) -> None:
    body = tenant_a.client.get("/api/v1/sales/crm/providers", headers=tenant_a.headers).json()
    assert body["providers"] == [
        {"name": "mock", "status": "ok", "detail": mock_crm.health().detail, "test_double": True}
    ]


def test_unconfigured_provider_is_404_never_pretended(tenant_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    registry.reset_providers()
    for name in ("mock", "hubspot", "pipedrive", "nope"):
        assert _export(tenant_a, [deal["id"]], name).status_code == 404
    assert _mappings(tenant_a) == []


def test_export_requires_owner_and_confirmation(
    tenant_a: Tenant, member_of_a: Tenant, mock_crm: MockCRMProvider
) -> None:
    deal = new_deal(tenant_a)
    assert _export(member_of_a, [deal["id"]]).status_code == 403
    no_confirm = _export(tenant_a, [deal["id"]], confirm=False)
    assert no_confirm.status_code == 400
    missing = tenant_a.client.post(
        "/api/v1/sales/crm/mock/export", json={"opportunity_ids": [deal["id"]]}, headers=tenant_a.headers
    )
    assert missing.status_code == 422
    assert (
        tenant_a.client.post(
            "/api/v1/sales/crm/mock/export", json={"opportunity_ids": [], "confirm": True}, headers=tenant_a.headers
        ).status_code
        == 422
    )
    too_many = _export(tenant_a, [random_uuid() for _ in range(51)])
    assert too_many.status_code == 422
    assert mock_crm.calls == []  # nothing reached the provider
    assert _mappings(tenant_a) == []


def test_export_success_and_idempotent_reexport(tenant_a: Tenant, mock_crm: MockCRMProvider, db: Session) -> None:
    deal = new_deal(tenant_a)
    first = _export(tenant_a, [deal["id"]])
    assert first.status_code == 200, first.text
    item = first.json()["items"][0]
    assert item["status"] == "synced"
    assert item["company"]["status"] == "synced"
    assert item["deal"]["external_entity_id"].startswith("mock-deal-")
    mappings = _mappings(tenant_a)
    assert {m["local_entity_type"] for m in mappings} == {"company", "deal"}
    assert all(m["sync_status"] == "synced" and m["external_entity_id"] and m["last_synced_at"] for m in mappings)
    # Re-export: same external ids, update calls (ext id passed), no duplicate mappings.
    second = _export(tenant_a, [deal["id"], deal["id"]]).json()["items"]
    assert len(second) == 1  # duplicates in one request are collapsed
    assert second[0]["deal"]["external_entity_id"] == item["deal"]["external_entity_id"]
    assert second[0]["company"]["external_entity_id"] == item["company"]["external_entity_id"]
    assert [c for c in mock_crm.calls if c[0] == "deal"][-1][1] == item["deal"]["external_entity_id"]
    assert db.scalar(select(func.count()).select_from(ExternalCRMMapping)) == 2
    assert len(mock_crm.records) == 2
    assert len(_mappings(tenant_a, local_entity_type="deal")) == 1
    assert _mappings(tenant_a, provider="hubspot") == []
    audits = tenant_a.client.get(
        f"/api/v1/sales/opportunities/{deal['id']}/activities", headers=tenant_a.headers
    ).json()
    assert sum("Exported to CRM" in a["description"] for a in audits if a["activity_type"] == "system") == 2
    assert (
        tenant_a.client.get("/api/v1/sales/crm/mappings?local_entity_type=bogus", headers=tenant_a.headers).status_code
        == 422
    )


def test_provider_failure_is_failed_mapping_never_synced(tenant_a: Tenant, mock_crm: MockCRMProvider) -> None:
    deal = new_deal(tenant_a)
    mock_crm.fail_on = {"deal"}
    item = _export(tenant_a, [deal["id"]]).json()["items"][0]
    assert item["status"] == "failed"
    assert item["company"]["status"] == "synced"
    assert item["deal"]["status"] == "failed"
    assert item["deal"]["error"]
    by_type = {m["local_entity_type"]: m for m in _mappings(tenant_a)}
    assert by_type["deal"]["sync_status"] == "failed"
    assert by_type["deal"]["external_entity_id"] is None
    assert by_type["deal"]["last_error"]
    # Company failure: the deal is not attempted.
    mock_crm.fail_on = {"company"}
    other = new_deal(tenant_a, domain="digitalwerk-solutions.example")
    failed = _export(tenant_a, [other["id"]]).json()["items"][0]
    assert failed["status"] == "failed"
    assert failed["deal"] is None
    # Recovery: a later export succeeds and updates the same mapping.
    mock_crm.fail_on = set()
    ok = _export(tenant_a, [deal["id"]]).json()["items"][0]
    assert ok["status"] == "synced"
    assert len([m for m in _mappings(tenant_a, local_entity_type="deal")]) == 1


def test_unexpected_provider_exception_is_failed(
    tenant_a: Tenant, mock_crm: MockCRMProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    deal = new_deal(tenant_a)

    def boom(*_: Any) -> str:
        raise RuntimeError("secret-token-xyz exploded")

    monkeypatch.setattr(mock_crm, "upsert_company", boom)
    item = _export(tenant_a, [deal["id"]]).json()["items"][0]
    assert item["status"] == "failed"
    assert "secret-token" not in item["company"]["error"]
    assert "secret-token" not in str(_mappings(tenant_a))


def test_suppressed_and_restricted_contacts_never_exported(tenant_a: Tenant, mock_crm: MockCRMProvider) -> None:
    deal = new_deal(tenant_a)
    company_id = deal["company"]["id"]

    def contact(name: str, email: str) -> dict[str, Any]:
        response = tenant_a.client.post(
            "/api/v1/sales/contacts",
            json={"company_id": company_id, "name": name, "business_email": email, "source": "business_card"},
            headers=tenant_a.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()  # type: ignore[no-any-return]

    fine = contact("Fine Person", "fine@kunde.example")
    unreviewed = contact("Not Reviewed", "unreviewed@kunde.example")
    optout = contact("Opt Out", "optout@kunde.example")
    # Only a contact a person reviewed as contactable leaves AIgentiX (here: letter, legitimate interest).
    review = {"channel": "letter", "decision": "allowed", "lawful_basis": "legitimate_interest"}
    reviewed = tenant_a.client.post(
        f"/api/v1/sales/contacts/{fine['id']}/reviews", json=review, headers=tenant_a.headers
    )
    assert reviewed.status_code == 201, reviewed.text
    restricted = contact("Restricted One", "restricted@kunde.example")
    assert tenant_a.client.post(
        "/api/v1/sales/suppressions",
        json={"channel": "email", "value": "optout@kunde.example"},
        headers=tenant_a.headers,
    ).status_code in (200, 201)
    patched = tenant_a.client.patch(
        f"/api/v1/sales/contacts/{restricted['id']}",
        json={"expected_version": restricted["version"], "restriction_status": "restricted"},
        headers=tenant_a.headers,
    )
    assert patched.status_code == 200, patched.text
    without = _export(tenant_a, [deal["id"]]).json()["items"][0]
    assert without["contacts"] == []  # contacts only on request
    assert not any(c[0] == "contact" for c in mock_crm.calls)
    item = _export(tenant_a, [deal["id"]], include_contacts=True).json()["items"][0]
    assert [c["local_entity_id"] for c in item["contacts"]] == [fine["id"]]
    assert item["skipped_contacts"] == 3
    exported = {m["local_entity_id"] for m in _mappings(tenant_a, local_entity_type="contact")}
    assert exported == {fine["id"]}
    assert optout["id"] not in exported
    assert unreviewed["id"] not in exported
    blob = str([r["payload"] for r in mock_crm.records.values()])
    assert "optout@" not in blob
    assert "restricted@" not in blob


def test_cross_tenant_export_and_mappings(tenant_a: Tenant, tenant_b: Tenant, mock_crm: MockCRMProvider) -> None:
    deal = new_deal(tenant_a)
    assert _export(tenant_a, [deal["id"]]).status_code == 200
    assert _export(tenant_b, [deal["id"]]).status_code == 404
    assert _mappings(tenant_b) == []
    assert len(mock_crm.records) == 2  # tenant_b's attempt reached nothing


ENDPOINTS = [
    ("GET", "/api/v1/sales/crm/providers"),
    ("POST", "/api/v1/sales/crm/mock/export"),
    ("GET", "/api/v1/sales/crm/mappings"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_auth_required(client: Any, method: str, path: str) -> None:
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_spoofed_org_header_gets_403(tenant_a: Tenant, tenant_b: Tenant, method: str, path: str) -> None:
    body = {"opportunity_ids": [random_uuid()], "confirm": True}
    assert tenant_b.client.request(method, path, json=body, headers=tenant_a.headers).status_code == 403


def test_external_id_collision_is_failed_and_mappings_are_committed(
    tenant_a: Tenant, mock_crm: MockCRMProvider, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider returning an id already mapped to another record fails that entity (never overwrites), and
    mappings written before the failure are kept (committed per external write)."""
    first = new_deal(tenant_a)
    second_lead = tenant_a.client.post(
        "/api/v1/sales/opportunities",
        json={"company_id": first["company"]["id"], "title": "Second deal"},
        headers=tenant_a.headers,
    ).json()
    assert _export(tenant_a, [first["id"]]).status_code == 200
    taken = next(m["external_entity_id"] for m in _mappings(tenant_a, local_entity_type="deal"))
    monkeypatch.setattr(mock_crm, "upsert_deal", lambda payload, external_id: taken)
    item = _export(tenant_a, [second_lead["id"]]).json()["items"][0]
    assert item["deal"]["status"] == "failed"
    assert "already mapped" in item["deal"]["error"]
    deals = _mappings(tenant_a, local_entity_type="deal")
    assert sorted(m["sync_status"] for m in deals) == ["failed", "synced"]
    assert db.scalar(select(func.count()).select_from(ExternalCRMMapping)) == 3  # company + 2 deals
