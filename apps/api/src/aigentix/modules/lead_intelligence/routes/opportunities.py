import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.lead_intelligence.models import OpportunityStatus
from aigentix.modules.lead_intelligence.routes.serializers import opportunity_reads
from aigentix.modules.lead_intelligence.schemas import OpportunityRead, OpportunityUpdate
from aigentix.modules.lead_intelligence.services import opportunities as service

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=Page[OpportunityRead], operation_id="listOpportunities")
def list_opportunities(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    status: Annotated[OpportunityStatus | None, Query()] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[OpportunityRead]:
    items, total = service.list_opportunities(
        db, tenant, limit=page.limit, offset=page.offset, status=status, company_id=company_id
    )
    return Page[OpportunityRead](
        items=opportunity_reads(db, tenant, items), total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{opportunity_id}", response_model=OpportunityRead, operation_id="getOpportunity")
def get_opportunity(db: DbSession, tenant: Tenant, opportunity_id: uuid.UUID) -> OpportunityRead:
    return opportunity_reads(db, tenant, [service.get_opportunity(db, tenant, opportunity_id)])[0]


@router.patch("/{opportunity_id}", response_model=OpportunityRead, operation_id="reviewOpportunity")
def review_opportunity(
    db: DbSession, tenant: Tenant, opportunity_id: uuid.UUID, body: OpportunityUpdate
) -> OpportunityRead:
    opportunity = service.review_opportunity(
        db, tenant, opportunity_id, status=body.status, reviewer_note=body.reviewer_note
    )
    db.commit()
    return opportunity_reads(db, tenant, [opportunity])[0]
