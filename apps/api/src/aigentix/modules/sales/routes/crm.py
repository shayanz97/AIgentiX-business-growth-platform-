"""CRM export routes: explicit, owner-confirmed, one-way. No live provider is bundled."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.sales.schemas_tasks import (
    CRMEntityResult,
    CRMExportItem,
    CRMExportRequest,
    CRMExportResult,
    CRMMappingRead,
    CRMProviderRead,
    CRMProvidersRead,
)
from aigentix.modules.sales.services import crm as service

router = APIRouter()

NOTE = (
    "No live CRM provider is bundled with AIgentiX; HubSpot and Pipedrive adapters are future work. "
    "Exports happen only on explicit, owner-confirmed request. CSV export works without any account."
)


@router.get("/sales/crm/providers", response_model=CRMProvidersRead, operation_id="listCrmProviders", tags=["sales"])
def list_providers(tenant: Tenant) -> CRMProvidersRead:
    return CRMProvidersRead(
        providers=[
            CRMProviderRead(name=n, status=s, detail=d, test_double=t) for n, s, d, t in service.provider_overview()
        ],
        note=NOTE,
    )


def _entity(r: service.EntityResult) -> CRMEntityResult:
    return CRMEntityResult(
        local_entity_type=r.local_entity_type,
        local_entity_id=r.local_entity_id,
        status=r.status,
        external_entity_id=r.external_entity_id,
        error=r.error,
    )


@router.post("/sales/crm/{provider}/export", response_model=CRMExportResult, operation_id="exportToCrm", tags=["sales"])
def export_to_crm(db: DbSession, tenant: Tenant, provider: str, body: CRMExportRequest) -> CRMExportResult:
    results = service.export_deals(
        db,
        tenant,
        provider,
        opportunity_ids=body.opportunity_ids,
        confirm=body.confirm,
        include_contacts=body.include_contacts,
    )
    db.commit()
    return CRMExportResult(
        provider=provider.strip().lower(),
        items=[
            CRMExportItem(
                opportunity_id=r.opportunity_id,
                status=r.status,
                company=_entity(r.company),
                deal=_entity(r.deal) if r.deal else None,
                contacts=[_entity(c) for c in r.contacts],
                skipped_contacts=r.skipped_contacts,
            )
            for r in results
        ],
    )


@router.get("/sales/crm/mappings", response_model=Page[CRMMappingRead], operation_id="listCrmMappings", tags=["sales"])
def list_mappings(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    provider: Annotated[str | None, Query(max_length=40)] = None,
    local_entity_type: Literal["company", "contact", "deal"] | None = None,
) -> Page[CRMMappingRead]:
    rows, total = service.list_mappings(
        db, tenant, provider=provider, local_entity_type=local_entity_type, limit=page.limit, offset=page.offset
    )
    items = [CRMMappingRead.model_validate(r) for r in rows]
    return Page[CRMMappingRead](items=items, total=total, limit=page.limit, offset=page.offset)
