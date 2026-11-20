"""Follow-up tasks: in-app reminders only (nothing is e-mailed or sent), suggestions and dashboard counts."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.sales.domain.followup import Boundaries, DealState, Suggestion, boundaries, suggest
from aigentix.modules.sales.models import (
    ActivityType,
    SalesActivity,
    SalesBrief,
    SalesOpportunity,
    SalesTask,
    TaskStatus,
)
from aigentix.modules.sales.services.common import audit, get_deal, require_member
from aigentix.platform.organizations.service import TenantContext

CONTACT_ACTIVITIES = (
    ActivityType.CALL.value,
    ActivityType.MEETING.value,
    ActivityType.EMAIL_SENT.value,
    ActivityType.EMAIL_RECEIVED.value,
    ActivityType.LETTER_SENT.value,
)


def get_task(db: Session, tenant: TenantContext, task_id: uuid.UUID, *, for_update: bool = False) -> SalesTask:
    query = select(SalesTask).where(SalesTask.id == task_id, SalesTask.organization_id == tenant.organization_id)
    task = db.scalar(query.with_for_update() if for_update else query)
    if task is None:
        raise NotFound("Task not found")
    return task


def create_task(
    db: Session,
    tenant: TenantContext,
    *,
    deal_id: uuid.UUID,
    title: str,
    description: str,
    due_at: datetime,
    assigned_user_id: uuid.UUID | None,
    suggestion_key: str | None,
) -> SalesTask:
    deal = get_deal(db, tenant, deal_id)
    require_member(db, tenant, assigned_user_id)
    task = SalesTask(
        organization_id=tenant.organization_id,
        sales_opportunity_id=deal.id,
        assigned_user_id=assigned_user_id or tenant.user.id,
        title=title.strip(),
        description=description.strip(),
        due_at=due_at,
        status=TaskStatus.OPEN.value,
        suggestion_key=suggestion_key,
        created_by_user_id=tenant.user.id,
    )
    db.add(task)
    db.flush()
    return task


@dataclass(frozen=True)
class TaskFilters:
    view: str = "open"
    mine: bool = False
    assigned_user_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


def _view_condition(view: str, b: Boundaries) -> list[ColumnElement[bool]]:
    open_ = SalesTask.status == TaskStatus.OPEN.value
    if view == "all":
        return []
    if view == "open":
        return [open_]
    if view == "completed":
        return [SalesTask.status == TaskStatus.COMPLETED.value]
    if view == "overdue":
        return [open_, SalesTask.due_at < b.now]
    if view == "today":
        return [open_, SalesTask.due_at >= b.now, SalesTask.due_at < b.tomorrow_start]
    if view == "upcoming":
        return [open_, SalesTask.due_at >= b.tomorrow_start, SalesTask.due_at < b.upcoming_end]
    raise InvalidInput("Unknown task view")


def list_tasks(
    db: Session, tenant: TenantContext, filters: TaskFilters, tz: ZoneInfo, *, limit: int, offset: int
) -> tuple[list[SalesTask], int]:
    b = boundaries(utcnow(), tz)
    conditions = [SalesTask.organization_id == tenant.organization_id, *_view_condition(filters.view, b)]
    if filters.mine:
        conditions.append(SalesTask.assigned_user_id == tenant.user.id)
    if filters.assigned_user_id is not None:
        conditions.append(SalesTask.assigned_user_id == filters.assigned_user_id)
    if filters.deal_id is not None:
        conditions.append(SalesTask.sales_opportunity_id == filters.deal_id)
    total = db.scalar(select(func.count()).select_from(SalesTask).where(*conditions)) or 0
    rows = db.scalars(
        select(SalesTask).where(*conditions).order_by(SalesTask.due_at, SalesTask.id).limit(limit).offset(offset)
    )
    return list(rows), int(total)


def update_task(
    db: Session,
    tenant: TenantContext,
    task_id: uuid.UUID,
    *,
    title: str | None = None,
    description: str | None = None,
    due_at: datetime | None = None,
    assigned_user_id: uuid.UUID | None = None,
    set_assignee: bool = False,  # True: apply assigned_user_id even when None (unassign)
    status: str | None = None,
) -> SalesTask:
    task = get_task(db, tenant, task_id, for_update=True)
    deal = get_deal(db, tenant, task.sales_opportunity_id)
    now = utcnow()
    if title is not None:
        task.title = title.strip()
    if description is not None:
        task.description = description.strip()
    if set_assignee:
        require_member(db, tenant, assigned_user_id)
        task.assigned_user_id = assigned_user_id
    if due_at is not None and due_at != task.due_at:
        previous = task.due_at
        task.due_at = due_at
        audit(
            db,
            tenant,
            deal,
            f"Task rescheduled: {task.title}",
            task_id=str(task.id),
            previous_due_at=previous.isoformat(),
            due_at=due_at.isoformat(),
        )
    if status is not None and status != task.status:
        if status == TaskStatus.COMPLETED.value:
            task.completed_at = now
        else:
            task.completed_at = None
        task.status = status
        label = {"completed": "completed", "cancelled": "cancelled", "open": "reopened"}[status]
        audit(db, tenant, deal, f"Task {label}: {task.title}", task_id=str(task.id), status=status)
    task.updated_at = now
    db.flush()
    return task


def summary(db: Session, tenant: TenantContext, tz: ZoneInfo) -> dict[str, int]:
    b = boundaries(utcnow(), tz)
    org = SalesTask.organization_id == tenant.organization_id
    open_ = SalesTask.status == TaskStatus.OPEN.value

    def count(*conditions: ColumnElement[bool]) -> int:
        return int(db.scalar(select(func.count()).select_from(SalesTask).where(org, *conditions)) or 0)

    return {
        "overdue": count(open_, SalesTask.due_at < b.now),
        "today": count(open_, SalesTask.due_at >= b.now, SalesTask.due_at < b.tomorrow_start),
        "upcoming": count(open_, SalesTask.due_at >= b.tomorrow_start, SalesTask.due_at < b.upcoming_end),
        "open": count(open_),
        "completed_last_7_days": count(
            SalesTask.status == TaskStatus.COMPLETED.value, SalesTask.completed_at >= b.now - timedelta(days=7)
        ),
        "mine_open": count(open_, SalesTask.assigned_user_id == tenant.user.id),
    }


def deal_suggestions(db: Session, tenant: TenantContext, deal_id: uuid.UUID) -> list[tuple[Suggestion, datetime]]:
    """Deterministic suggestions from recorded state. Nothing is created; suggestions already open are omitted."""
    deal: SalesOpportunity = get_deal(db, tenant, deal_id)
    org = tenant.organization_id
    now = utcnow()
    has_brief = (
        db.scalar(
            select(SalesBrief.id)
            .where(
                SalesBrief.organization_id == org,
                SalesBrief.sales_opportunity_id == deal.id,
                SalesBrief.status.in_(["draft", "approved"]),
            )
            .limit(1)
        )
        is not None
    )
    last_contact = db.scalar(
        select(func.max(SalesActivity.occurred_at)).where(
            SalesActivity.organization_id == org,
            SalesActivity.sales_opportunity_id == deal.id,
            SalesActivity.activity_type.in_(CONTACT_ACTIVITIES),
        )
    )
    keys = frozenset(
        k
        for k in db.scalars(
            select(SalesTask.suggestion_key).where(
                SalesTask.organization_id == org,
                SalesTask.sales_opportunity_id == deal.id,
                SalesTask.status == TaskStatus.OPEN.value,
                SalesTask.suggestion_key.is_not(None),
            )
        )
        if k
    )
    state = DealState(
        stage=deal.stage if deal.status == "open" else deal.status,
        has_brief=has_brief,
        days_since_contact=(now - last_contact).days if last_contact else None,
        open_suggestion_keys=keys,
    )
    return [(s, now + timedelta(days=s.due_in_days)) for s in suggest(state)]
