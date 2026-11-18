"""Follow-up task routes, task suggestions, dashboard counts and CSV export. In-app reminders only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput
from aigentix.modules.sales.domain.followup import DEFAULT_TZ, Boundaries, boundaries, bucket, parse_tz
from aigentix.modules.sales.models import SalesOpportunity, SalesTask
from aigentix.modules.sales.schemas_tasks import (
    TaskCreate,
    TaskRead,
    TaskSuggestionRead,
    TaskSummaryRead,
    TaskUpdate,
    TaskView,
)
from aigentix.modules.sales.services import export as export_service
from aigentix.modules.sales.services import tasks as service
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext

router = APIRouter()

Tz = Annotated[str, Query(max_length=64, description="IANA time zone for the today / upcoming boundaries.")]


def task_reads(db: DbSession, tenant: TenantContext, tasks: list[SalesTask], b: Boundaries) -> list[TaskRead]:
    deal_ids = {t.sales_opportunity_id for t in tasks}
    deals = {}
    if deal_ids:
        deals = {
            d.id: d
            for d in db.scalars(
                select(SalesOpportunity).where(
                    SalesOpportunity.organization_id == tenant.organization_id, SalesOpportunity.id.in_(deal_ids)
                )
            )
        }
    names = get_lead_data_provider().company_names(db, tenant.organization_id, {d.company_id for d in deals.values()})
    out = []
    for t in tasks:
        deal = deals[t.sales_opportunity_id]
        company = names.get(deal.company_id)
        out.append(
            TaskRead(
                id=t.id,
                sales_opportunity_id=t.sales_opportunity_id,
                deal_title=deal.title,
                company_name=company.name if company else None,
                assigned_user_id=t.assigned_user_id,
                title=t.title,
                description=t.description,
                due_at=t.due_at,
                status=t.status,
                overdue=bucket(t.due_at, t.status, b) == "overdue",
                suggestion_key=t.suggestion_key,
                completed_at=t.completed_at,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
        )
    return out


@router.post(
    "/sales/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSalesTask",
    tags=["sales"],
)
def create_task(db: DbSession, tenant: Tenant, body: TaskCreate) -> TaskRead:
    task = service.create_task(
        db,
        tenant,
        deal_id=body.sales_opportunity_id,
        title=body.title,
        description=body.description,
        due_at=body.due_at,
        assigned_user_id=body.assigned_user_id,
        suggestion_key=body.suggestion_key,
    )
    db.commit()
    return task_reads(db, tenant, [task], boundaries(utcnow(), parse_tz(DEFAULT_TZ)))[0]


@router.get("/sales/tasks", response_model=Page[TaskRead], operation_id="listSalesTasks", tags=["sales"])
def list_tasks(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    view: TaskView = "open",
    mine: bool = False,
    assigned_user_id: uuid.UUID | None = None,
    sales_opportunity_id: uuid.UUID | None = None,
    tz: Tz = DEFAULT_TZ,
) -> Page[TaskRead]:
    zone = parse_tz(tz)
    filters = service.TaskFilters(view=view, mine=mine, assigned_user_id=assigned_user_id, deal_id=sales_opportunity_id)
    rows, total = service.list_tasks(db, tenant, filters, zone, limit=page.limit, offset=page.offset)
    items = task_reads(db, tenant, rows, boundaries(utcnow(), zone))
    return Page[TaskRead](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/sales/tasks/summary", response_model=TaskSummaryRead, operation_id="getSalesTaskSummary", tags=["sales"])
def task_summary(db: DbSession, tenant: Tenant, tz: Tz = DEFAULT_TZ) -> TaskSummaryRead:
    return TaskSummaryRead(**service.summary(db, tenant, parse_tz(tz)))


@router.patch("/sales/tasks/{task_id}", response_model=TaskRead, operation_id="updateSalesTask", tags=["sales"])
def update_task(db: DbSession, tenant: Tenant, task_id: uuid.UUID, body: TaskUpdate) -> TaskRead:
    fields = body.model_fields_set
    if not fields:
        raise InvalidInput("Nothing to change")
    task = service.update_task(
        db,
        tenant,
        task_id,
        title=body.title,
        description=body.description,
        due_at=body.due_at,
        status=body.status,
        assigned_user_id=body.assigned_user_id,
        set_assignee="assigned_user_id" in fields,
    )
    db.commit()
    return task_reads(db, tenant, [task], boundaries(utcnow(), parse_tz(DEFAULT_TZ)))[0]


@router.get(
    "/sales/opportunities/{deal_id}/task-suggestions",
    response_model=list[TaskSuggestionRead],
    operation_id="getSalesTaskSuggestions",
    tags=["sales"],
)
def task_suggestions(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> list[TaskSuggestionRead]:
    return [
        TaskSuggestionRead(key=s.key, title=s.title, reason=s.reason, suggested_due_at=due)
        for s, due in service.deal_suggestions(db, tenant, deal_id)
    ]


@router.get(
    "/sales/export",
    operation_id="exportSalesCsv",
    tags=["sales"],
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "CSV download"}},
)
def export_csv(
    db: DbSession,
    tenant: Tenant,
    entity: Annotated[str, Query(description="opportunities | activities | tasks")] = "opportunities",
    stage: str | None = None,
    deal_status: Annotated[str | None, Query(alias="status")] = None,
) -> Response:
    body = export_service.export_csv(db, tenant, entity, stage=stage, status=deal_status)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sales-{entity}.csv"', "Cache-Control": "no-store"},
    )
