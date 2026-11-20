"""Deal pipeline routes: conversion, deals, stage changes, history, activities, contacts, metrics."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.sales.models import ActivityType, Channel, DealStatus, Priority, Stage
from aigentix.modules.sales.routes.serializers import contact_read, deal_reads
from aigentix.modules.sales.schemas import (
    ActivityCreate,
    ActivityRead,
    ContactCreate,
    ContactRead,
    ContactReviewCreate,
    ContactReviewRead,
    ContactUpdate,
    ConversionRequest,
    ConversionResult,
    DealClose,
    DealCreate,
    DealRead,
    DealReopen,
    DealUpdate,
    SalesMetricsRead,
    StageChange,
    StageHistoryRead,
    SuppressionCreate,
    SuppressionResult,
)
from aigentix.modules.sales.services import activities as activity_service
from aigentix.modules.sales.services import contacts as contact_service
from aigentix.modules.sales.services import conversion as conversion_service
from aigentix.modules.sales.services import metrics as metrics_service
from aigentix.modules.sales.services import pipeline as service
from aigentix.modules.sales.services.common import get_deal

router = APIRouter()


def _one(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> DealRead:
    return deal_reads(db, tenant, [get_deal(db, tenant, deal_id)])[0]


@router.post(
    "/leads/{company_id}/convert",
    response_model=ConversionResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="convertLead",
    tags=["sales"],
    responses={200: {"model": ConversionResult, "description": "Retry: the deal created by this key"}},
)
def convert_lead(
    db: DbSession, tenant: Tenant, company_id: uuid.UUID, body: ConversionRequest, response: Response
) -> ConversionResult:
    result = conversion_service.convert_lead(
        db,
        tenant,
        company_id,
        idempotency_key=body.idempotency_key,
        source_opportunity_id=body.source_opportunity_id,
        title=body.title,
        allow_additional=body.allow_additional,
    )
    db.commit()
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return ConversionResult(created=result.created, opportunity=deal_reads(db, tenant, [result.deal])[0])


@router.post(
    "/sales/opportunities",
    response_model=DealRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSalesOpportunity",
    tags=["sales"],
)
def create_deal(db: DbSession, tenant: Tenant, body: DealCreate) -> DealRead:
    deal = service.create_deal(db, tenant, **body.model_dump())
    db.commit()
    return deal_reads(db, tenant, [deal])[0]


@router.get(
    "/sales/opportunities", response_model=Page[DealRead], operation_id="listSalesOpportunities", tags=["sales"]
)
def list_deals(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    stage: Stage | None = None,
    deal_status: Annotated[DealStatus | None, Query(alias="status")] = None,
    owner_user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    priority: Priority | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    closing_before: date | None = None,
    sort: service.DealSort = "updated",
) -> Page[DealRead]:
    filters = service.DealFilters(
        stage=stage,
        status=deal_status,
        owner_user_id=owner_user_id,
        company_id=company_id,
        priority=priority,
        q=q,
        closing_before=closing_before,
    )
    rows, total = service.list_deals(db, tenant, filters, sort=sort, limit=page.limit, offset=page.offset)
    return Page[DealRead](items=deal_reads(db, tenant, rows), total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/sales/opportunities/{deal_id}", response_model=DealRead, operation_id="getSalesOpportunity", tags=["sales"]
)
def get_deal_route(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> DealRead:
    return _one(db, tenant, deal_id)


@router.patch(
    "/sales/opportunities/{deal_id}", response_model=DealRead, operation_id="updateSalesOpportunity", tags=["sales"]
)
def update_deal(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: DealUpdate) -> DealRead:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    deal = service.update_deal(db, tenant, deal_id, changes, expected_version=body.expected_version)
    db.commit()
    return deal_reads(db, tenant, [deal])[0]


@router.post(
    "/sales/opportunities/{deal_id}/stage",
    response_model=DealRead,
    operation_id="changeSalesStage",
    tags=["sales"],
)
def change_stage(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: StageChange) -> DealRead:
    deal = service.change_stage(
        db, tenant, deal_id, stage=body.stage, reason=body.reason, expected_version=body.expected_version
    )
    db.commit()
    return deal_reads(db, tenant, [deal])[0]


@router.post(
    "/sales/opportunities/{deal_id}/close",
    response_model=DealRead,
    operation_id="closeSalesOpportunity",
    tags=["sales"],
)
def close_deal(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: DealClose) -> DealRead:
    deal = service.close_deal(
        db,
        tenant,
        deal_id,
        outcome=Stage(body.outcome),
        expected_version=body.expected_version,
        won_value=body.won_value,
        lost_reason=body.lost_reason,
        note=body.note,
    )
    db.commit()
    return deal_reads(db, tenant, [deal])[0]


@router.post(
    "/sales/opportunities/{deal_id}/reopen",
    response_model=DealRead,
    operation_id="reopenSalesOpportunity",
    tags=["sales"],
)
def reopen_deal(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: DealReopen) -> DealRead:
    deal = service.reopen_deal(db, tenant, deal_id, reason=body.reason, expected_version=body.expected_version)
    db.commit()
    return deal_reads(db, tenant, [deal])[0]


@router.get(
    "/sales/opportunities/{deal_id}/history",
    response_model=list[StageHistoryRead],
    operation_id="getSalesStageHistory",
    tags=["sales"],
)
def history(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> list[StageHistoryRead]:
    return [StageHistoryRead.model_validate(h) for h in service.stage_history(db, tenant, deal_id)]


@router.post(
    "/sales/opportunities/{deal_id}/activities",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="recordSalesActivity",
    tags=["sales"],
)
def record_activity(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: ActivityCreate) -> ActivityRead:
    activity = activity_service.record_activity(
        db,
        tenant,
        deal_id,
        activity_type=ActivityType(body.activity_type),
        description=body.description,
        occurred_at=body.occurred_at,
        contact_id=body.contact_id,
    )
    db.commit()
    return ActivityRead.model_validate(activity)


@router.get(
    "/sales/opportunities/{deal_id}/activities",
    response_model=list[ActivityRead],
    operation_id="listSalesActivities",
    tags=["sales"],
)
def list_activities(
    db: DbSession, tenant: Tenant, deal_id: uuid.UUID, page: Pagination, include_system: bool = True
) -> list[ActivityRead]:
    rows = activity_service.list_activities(
        db, tenant, deal_id, limit=page.limit, offset=page.offset, include_system=include_system
    )
    return [ActivityRead.model_validate(a) for a in rows]


# --- contacts & compliance ------------------------------------------------------------------------------


@router.post(
    "/sales/contacts",
    response_model=ContactRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSalesContact",
    tags=["sales-contacts"],
)
def create_contact(db: DbSession, tenant: Tenant, body: ContactCreate) -> ContactRead:
    contact = contact_service.create_contact(db, tenant, **body.model_dump())
    db.commit()
    return contact_read(db, tenant, contact)


@router.get(
    "/sales/contacts", response_model=list[ContactRead], operation_id="listSalesContacts", tags=["sales-contacts"]
)
def list_contacts(db: DbSession, tenant: Tenant, company_id: uuid.UUID | None = None) -> list[ContactRead]:
    return [contact_read(db, tenant, c) for c in contact_service.list_contacts(db, tenant, company_id=company_id)]


@router.patch(
    "/sales/contacts/{contact_id}",
    response_model=ContactRead,
    operation_id="updateSalesContact",
    tags=["sales-contacts"],
)
def update_contact(db: DbSession, tenant: Tenant, contact_id: uuid.UUID, body: ContactUpdate) -> ContactRead:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    contact = contact_service.update_contact(db, tenant, contact_id, changes, expected_version=body.expected_version)
    db.commit()
    return contact_read(db, tenant, contact)


@router.post(
    "/sales/contacts/{contact_id}/reviews",
    response_model=ContactReviewRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="reviewSalesContact",
    tags=["sales-contacts"],
)
def review_contact(
    db: DbSession, tenant: Tenant, contact_id: uuid.UUID, body: ContactReviewCreate
) -> ContactReviewRead:
    review = contact_service.review_contact(
        db,
        tenant,
        contact_id,
        channel=body.channel,
        decision=body.decision,
        lawful_basis=body.lawful_basis,
        note=body.note,
    )
    db.commit()
    return ContactReviewRead.model_validate(review)


@router.get(
    "/sales/contacts/{contact_id}/reviews",
    response_model=list[ContactReviewRead],
    operation_id="listSalesContactReviews",
    tags=["sales-contacts"],
)
def list_reviews(db: DbSession, tenant: Tenant, contact_id: uuid.UUID) -> list[ContactReviewRead]:
    return [ContactReviewRead.model_validate(r) for r in contact_service.reviews_for(db, tenant, contact_id)]


@router.post(
    "/sales/suppressions",
    response_model=SuppressionResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="addSalesSuppression",
    tags=["sales-contacts"],
)
def add_suppression(db: DbSession, tenant: Tenant, body: SuppressionCreate, response: Response) -> SuppressionResult:
    created = contact_service.add_suppression(
        db, tenant, channel=Channel(body.channel), value=body.value, reason=body.reason
    )
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return SuppressionResult(created=created)


@router.get("/sales/metrics", response_model=SalesMetricsRead, operation_id="getSalesMetrics", tags=["sales"])
def metrics(db: DbSession, tenant: Tenant) -> SalesMetricsRead:
    return SalesMetricsRead(**vars(metrics_service.sales_metrics(db, tenant)))
