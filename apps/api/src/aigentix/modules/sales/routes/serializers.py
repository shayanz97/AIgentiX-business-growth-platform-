"""ORM → API mapping shared by the Sales routes."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.modules.sales.models import SalesContact, SalesOpportunity, SalesTask, TaskStatus
from aigentix.modules.sales.schemas import ChannelPermissionRead, CompanyRef, ContactRead, DealRead
from aigentix.modules.sales.services.contacts import permissions
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext


def _task_counts(db: Session, ids: Sequence[uuid.UUID]) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    if not ids:
        return {}, {}
    base = select(SalesTask.sales_opportunity_id, func.count()).where(
        SalesTask.sales_opportunity_id.in_(list(ids)), SalesTask.status == TaskStatus.OPEN.value
    )
    open_counts = {k: int(v) for k, v in db.execute(base.group_by(SalesTask.sales_opportunity_id))}
    overdue_rows = db.execute(base.where(SalesTask.due_at < utcnow()).group_by(SalesTask.sales_opportunity_id))
    overdue = {k: int(v) for k, v in overdue_rows}
    return open_counts, overdue


def deal_reads(db: Session, tenant: TenantContext, deals: Sequence[SalesOpportunity]) -> list[DealRead]:
    companies = company_refs(db, tenant, {d.company_id for d in deals})
    open_counts, overdue = _task_counts(db, [d.id for d in deals])
    return [
        DealRead(
            id=d.id,
            company=companies[d.company_id],
            source_opportunity_id=d.source_opportunity_id,
            source_lead_score_id=d.source_lead_score_id,
            title=d.title,
            description=d.description,
            owner_user_id=d.owner_user_id,
            stage=d.stage,
            status=d.status,
            priority=d.priority,
            estimated_value=d.estimated_value,
            currency=d.currency,
            expected_close_date=d.expected_close_date,
            confirmed_requirements=list(d.confirmed_requirements),
            won_value=d.won_value,
            lost_reason=d.lost_reason,
            closed_at=d.closed_at,
            version=d.version,
            open_tasks=open_counts.get(d.id, 0),
            overdue_tasks=overdue.get(d.id, 0),
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in deals
    ]


def company_refs(db: Session, tenant: TenantContext, ids: set[uuid.UUID]) -> dict[uuid.UUID, CompanyRef]:
    names = get_lead_data_provider().company_names(db, tenant.organization_id, ids)
    return {
        i: CompanyRef(id=i, name=n.name, canonical_domain=n.canonical_domain, website_url=n.website_url)
        for i, n in names.items()
    }


def contact_read(db: Session, tenant: TenantContext, c: SalesContact) -> ContactRead:
    return ContactRead(
        id=c.id,
        company_id=c.company_id,
        name=c.name,
        role=c.role,
        business_email=c.business_email,
        business_phone=c.business_phone,
        source=c.source,
        source_note=c.source_note,
        lawful_basis=c.lawful_basis,
        lawful_basis_reference=c.lawful_basis_reference,
        restriction_status=c.restriction_status,
        permissions=[
            ChannelPermissionRead(channel=p.channel, allowed=p.permission.allowed, reason=p.permission.reason)
            for p in permissions(db, tenant, c)
        ],
        version=c.version,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )
