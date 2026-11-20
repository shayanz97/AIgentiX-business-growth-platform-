"""CSV export of sales data (works without any external account). Tenant-scoped, formula-injection safe.

Columns:
  opportunities: id, title, company, domain, stage, status, priority, estimated_value, currency,
                 expected_close_date, owner_user_id, won_value, lost_reason, created_at, updated_at, closed_at
  activities:    id, opportunity_id, opportunity_title, activity_type, description, occurred_at,
                 created_by_user_id, created_at
  tasks:         id, opportunity_id, opportunity_title, title, description, due_at, status, assigned_user_id,
                 completed_at, created_at

Contacts are deliberately NOT exportable: they are personal data (names, business e-mail / phone numbers) whose
handling is governed by recorded legal bases and suppressions; a bulk CSV would leave that control. Activity rows
carry no contact reference for the same reason.
"""

import csv
import io
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.errors import InvalidInput
from aigentix.modules.sales.models import (
    DealStatus,
    SalesActivity,
    SalesOpportunity,
    SalesTask,
    Stage,
    TaskStatus,
)
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext

MAX_ROWS = 10_000
ENTITIES = ("opportunities", "activities", "tasks")

OPPORTUNITY_COLUMNS = (
    "id",
    "title",
    "company",
    "domain",
    "stage",
    "status",
    "priority",
    "estimated_value",
    "currency",
    "expected_close_date",
    "owner_user_id",
    "won_value",
    "lost_reason",
    "created_at",
    "updated_at",
    "closed_at",
)
ACTIVITY_COLUMNS = (
    "id",
    "opportunity_id",
    "opportunity_title",
    "activity_type",
    "description",
    "occurred_at",
    "created_by_user_id",
    "created_at",
)
TASK_COLUMNS = (
    "id",
    "opportunity_id",
    "opportunity_title",
    "title",
    "description",
    "due_at",
    "status",
    "assigned_user_id",
    "completed_at",
    "created_at",
)


def cell(value: object) -> str:
    """CSV cell safe for spreadsheets: values starting with = + - @ (or tab/CR) are prefixed with a quote."""
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def to_csv(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([cell(v) for v in row])
    return buffer.getvalue()


def _validate(entity: str, stage: str | None, status: str | None) -> None:
    if entity not in ENTITIES:
        raise InvalidInput("Unknown export entity")
    if stage is not None and stage not in {s.value for s in Stage}:
        raise InvalidInput("Unknown stage")
    if status is not None:
        allowed = {s.value for s in TaskStatus} if entity == "tasks" else {s.value for s in DealStatus}
        if status not in allowed:
            raise InvalidInput("Unknown status for this export")


def export_csv(db: Session, tenant: TenantContext, entity: str, *, stage: str | None, status: str | None) -> str:
    """`stage` filters by deal stage for every entity; `status` is the deal status (opportunities, activities)
    or the task status (tasks)."""
    _validate(entity, stage, status)
    org = tenant.organization_id
    deal_conditions: list[Any] = [SalesOpportunity.organization_id == org]
    if stage is not None:
        deal_conditions.append(SalesOpportunity.stage == stage)
    if status is not None and entity != "tasks":
        deal_conditions.append(SalesOpportunity.status == status)
    if entity == "opportunities":
        deals = list(
            db.scalars(
                select(SalesOpportunity)
                .where(*deal_conditions)
                .order_by(SalesOpportunity.created_at, SalesOpportunity.id)
                .limit(MAX_ROWS)
            )
        )
        companies = get_lead_data_provider().company_names(db, org, {d.company_id for d in deals})
        return to_csv(
            OPPORTUNITY_COLUMNS,
            [
                (
                    d.id,
                    d.title,
                    companies[d.company_id].name if d.company_id in companies else "",
                    companies[d.company_id].canonical_domain if d.company_id in companies else "",
                    d.stage,
                    d.status,
                    d.priority,
                    d.estimated_value,
                    d.currency,
                    d.expected_close_date,
                    d.owner_user_id,
                    d.won_value,
                    d.lost_reason,
                    d.created_at,
                    d.updated_at,
                    d.closed_at,
                )
                for d in deals
            ],
        )
    if entity == "activities":
        pairs = db.execute(
            select(SalesActivity, SalesOpportunity.title)
            .join(
                SalesOpportunity,
                (SalesOpportunity.id == SalesActivity.sales_opportunity_id)
                & (SalesOpportunity.organization_id == SalesActivity.organization_id),
            )
            .where(SalesActivity.organization_id == org, *deal_conditions)
            .order_by(SalesActivity.occurred_at, SalesActivity.id)
            .limit(MAX_ROWS)
        )
        return to_csv(
            ACTIVITY_COLUMNS,
            [
                [
                    a.id,
                    a.sales_opportunity_id,
                    title,
                    a.activity_type,
                    a.description,
                    a.occurred_at,
                    a.created_by_user_id,
                    a.created_at,
                ]
                for a, title in pairs
            ],
        )
    task_conditions = [SalesTask.organization_id == org, *deal_conditions]
    if status is not None:
        task_conditions.append(SalesTask.status == status)
    task_rows = db.execute(
        select(SalesTask, SalesOpportunity.title)
        .join(
            SalesOpportunity,
            (SalesOpportunity.id == SalesTask.sales_opportunity_id)
            & (SalesOpportunity.organization_id == SalesTask.organization_id),
        )
        .where(*task_conditions)
        .order_by(SalesTask.due_at, SalesTask.id)
        .limit(MAX_ROWS)
    )
    return to_csv(
        TASK_COLUMNS,
        [
            [
                t.id,
                t.sales_opportunity_id,
                title,
                t.title,
                t.description,
                t.due_at,
                t.status,
                t.assigned_user_id,
                t.completed_at,
                t.created_at,
            ]
            for t, title in task_rows
        ],
    )
