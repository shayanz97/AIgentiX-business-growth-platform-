"""Helpers shared by the Sales services: tenant-scoped lookups, membership checks, optimistic locking, audit."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Conflict, InvalidInput, NotFound
from aigentix.modules.sales.models import ActivityType, SalesActivity, SalesOpportunity
from aigentix.platform.organizations.models import OrganizationMembership
from aigentix.platform.organizations.service import TenantContext


def get_deal(db: Session, tenant: TenantContext, deal_id: uuid.UUID, *, for_update: bool = False) -> SalesOpportunity:
    query = select(SalesOpportunity).where(
        SalesOpportunity.id == deal_id, SalesOpportunity.organization_id == tenant.organization_id
    )
    deal = db.scalar(query.with_for_update() if for_update else query)
    if deal is None:
        raise NotFound("Sales opportunity not found")
    return deal


def require_member(db: Session, tenant: TenantContext, user_id: uuid.UUID | None) -> None:
    """An owner / assignee must be a member of the tenant (ids of other users are rejected the same way)."""
    if user_id is None:
        return
    found = db.scalar(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == tenant.organization_id,
            OrganizationMembership.user_id == user_id,
        )
    )
    if found is None:
        raise InvalidInput("The user is not a member of this organization")


def check_version(current: int, expected: int | None) -> None:
    """Optimistic locking: updates carry the version they were based on."""
    if expected is not None and expected != current:
        raise Conflict("The record was changed by someone else. Reload and apply your change again.")


def audit(
    db: Session,
    tenant: TenantContext | None,
    deal: SalesOpportunity,
    description: str,
    *,
    user_id: uuid.UUID | None = None,
    **details: Any,
) -> SalesActivity:
    """A `system` activity: what AIgentiX or a user did through AIgentiX (not a customer interaction)."""
    activity = SalesActivity(
        organization_id=deal.organization_id,
        sales_opportunity_id=deal.id,
        activity_type=ActivityType.SYSTEM.value,
        description=description,
        details=details,
        created_by_user_id=tenant.user.id if tenant else user_id,
        occurred_at=utcnow(),
    )
    db.add(activity)
    return activity


def touch(deal: SalesOpportunity) -> None:
    deal.version += 1
    deal.updated_at = utcnow()
