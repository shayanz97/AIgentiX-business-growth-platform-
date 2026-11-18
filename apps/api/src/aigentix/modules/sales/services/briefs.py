"""Sales briefs: request generation (worker workflow), list, human edit / approve. AI content is never overwritten:
human edits live in `edited_content`, and regeneration creates a new brief."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Conflict, InvalidInput, NotFound
from aigentix.modules.sales.agents.prompts import BRIEF_PROMPT_VERSION
from aigentix.modules.sales.config import get_sales_settings
from aigentix.modules.sales.models import BriefStatus, DealStatus, SalesBrief
from aigentix.modules.sales.services.common import audit, check_version, get_deal
from aigentix.modules.sales.workflows.constants import BRIEF_WORKFLOW
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows import service as workflows
from aigentix.platform.workflows.models import ACTIVE_STATUSES, WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import default_registry

_EDITABLE = (BriefStatus.DRAFT.value, BriefStatus.APPROVED.value)


def runs_by_id(db: Session, tenant: TenantContext, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, WorkflowRun]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = db.scalars(
        select(WorkflowRun).where(WorkflowRun.organization_id == tenant.organization_id, WorkflowRun.id.in_(wanted))
    )
    return {r.id: r for r in rows}


def run_ended_without_result(run: WorkflowRun | None) -> bool:
    """A `generating` record whose run failed / was cancelled will never be completed."""
    return run is not None and WorkflowStatus(run.status) not in ACTIVE_STATUSES


def effective_brief_status(brief: SalesBrief, run: WorkflowRun | None) -> tuple[str, str | None]:
    if brief.status == BriefStatus.GENERATING.value and run_ended_without_result(run):
        return BriefStatus.FAILED.value, brief.message or (run.error_message if run else None)
    return brief.status, brief.message


def request_brief(db: Session, tenant: TenantContext, deal_id: uuid.UUID) -> SalesBrief:
    deal = get_deal(db, tenant, deal_id, for_update=True)
    if deal.status != DealStatus.OPEN.value:
        raise InvalidInput("The deal is closed; reopen it to generate a new brief")
    generating = list(
        db.scalars(
            select(SalesBrief).where(
                SalesBrief.organization_id == tenant.organization_id,
                SalesBrief.sales_opportunity_id == deal.id,
                SalesBrief.status == BriefStatus.GENERATING.value,
            )
        )
    )
    runs = runs_by_id(db, tenant, [b.workflow_run_id for b in generating])
    for existing in generating:
        if not run_ended_without_result(runs.get(existing.workflow_run_id) if existing.workflow_run_id else None):
            raise Conflict("A brief is already being generated for this deal", details={"brief_id": str(existing.id)})
    brief = SalesBrief(
        organization_id=tenant.organization_id,
        sales_opportunity_id=deal.id,
        status=BriefStatus.GENERATING.value,
        generation_version=BRIEF_PROMPT_VERSION,
        created_by_user_id=tenant.user.id,
    )
    db.add(brief)
    db.flush()
    run = workflows.enqueue(
        db,
        tenant,
        workflow_type=BRIEF_WORKFLOW,
        registry=default_registry(),
        metadata={"brief_id": str(brief.id)},
        max_attempts=get_sales_settings().sales_max_attempts,
    )
    brief.workflow_run_id = run.id
    audit(db, tenant, deal, "Sales brief generation requested", brief_id=str(brief.id))
    db.flush()
    return brief


def get_brief(db: Session, tenant: TenantContext, brief_id: uuid.UUID, *, for_update: bool = False) -> SalesBrief:
    query = select(SalesBrief).where(SalesBrief.id == brief_id, SalesBrief.organization_id == tenant.organization_id)
    brief = db.scalar(query.with_for_update() if for_update else query)
    if brief is None:
        raise NotFound("Sales brief not found")
    return brief


def list_briefs(db: Session, tenant: TenantContext, deal_id: uuid.UUID) -> list[SalesBrief]:
    get_deal(db, tenant, deal_id)
    return list(
        db.scalars(
            select(SalesBrief)
            .where(SalesBrief.organization_id == tenant.organization_id, SalesBrief.sales_opportunity_id == deal_id)
            .order_by(SalesBrief.created_at.desc(), SalesBrief.id.desc())
        )
    )


def update_brief(
    db: Session,
    tenant: TenantContext,
    brief_id: uuid.UUID,
    *,
    expected_version: int,
    edited_content: dict[str, Any] | None,
    status: str | None,
) -> SalesBrief:
    brief = get_brief(db, tenant, brief_id, for_update=True)
    check_version(brief.version, expected_version)
    if brief.status not in _EDITABLE:
        raise InvalidInput(f"A {brief.status} brief cannot be edited or approved; generate a new brief")
    deal = get_deal(db, tenant, brief.sales_opportunity_id)
    changed = False
    if edited_content is not None:
        brief.edited_content = edited_content
        brief.edited_by_user_id = tenant.user.id
        changed = True
    if status is not None and status != brief.status:
        brief.status = status
        changed = True
        audit(
            db,
            tenant,
            deal,
            "Sales brief approved" if status == BriefStatus.APPROVED.value else "Sales brief returned to draft",
            brief_id=str(brief.id),
        )
    if changed:
        brief.version += 1
        brief.updated_at = utcnow()
    db.flush()
    return brief
