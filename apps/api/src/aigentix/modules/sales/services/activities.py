"""Manually recorded sales activities (notes, calls, meetings, e-mails sent or received outside AIgentiX)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput
from aigentix.modules.sales.models import ActivityType, Channel, ContactRestriction, SalesActivity
from aigentix.modules.sales.services.common import get_deal, touch
from aigentix.modules.sales.services.contacts import get_contact, is_suppressed
from aigentix.platform.organizations.service import TenantContext

OUTBOUND_CHANNEL = {
    ActivityType.CALL: Channel.PHONE,
    ActivityType.EMAIL_SENT: Channel.EMAIL,
    ActivityType.LETTER_SENT: Channel.LETTER,
}
_CLOCK_SKEW = timedelta(minutes=5)


def record_activity(
    db: Session,
    tenant: TenantContext,
    deal_id: uuid.UUID,
    *,
    activity_type: ActivityType,
    description: str,
    occurred_at: datetime | None,
    contact_id: uuid.UUID | None,
) -> SalesActivity:
    if activity_type in (ActivityType.SYSTEM, ActivityType.PROPOSAL_SENT):
        raise InvalidInput("This activity type is recorded by AIgentiX itself (mark the proposal as sent instead)")
    deal = get_deal(db, tenant, deal_id, for_update=True)
    when = occurred_at or utcnow()
    if when > utcnow() + _CLOCK_SKEW:
        raise InvalidInput("Activities record what happened; occurred_at cannot be in the future (create a task)")
    if contact_id is not None:
        contact = get_contact(db, tenant, contact_id)
        if contact.company_id != deal.company_id:
            raise InvalidInput("The contact belongs to another company")
        channel = OUTBOUND_CHANNEL.get(activity_type)
        if channel is not None and (
            contact.restriction_status == ContactRestriction.SUPPRESSED.value
            or is_suppressed(db, tenant.organization_id, contact, channel)
        ):
            raise InvalidInput("The contact opted out of this channel (suppressed); the activity was not recorded")
    activity = SalesActivity(
        organization_id=tenant.organization_id,
        sales_opportunity_id=deal.id,
        activity_type=activity_type.value,
        description=description.strip(),
        contact_id=contact_id,
        created_by_user_id=tenant.user.id,
        occurred_at=when,
    )
    db.add(activity)
    touch(deal)
    db.flush()
    return activity


def list_activities(
    db: Session, tenant: TenantContext, deal_id: uuid.UUID, *, limit: int, offset: int, include_system: bool
) -> list[SalesActivity]:
    get_deal(db, tenant, deal_id)
    query = select(SalesActivity).where(
        SalesActivity.organization_id == tenant.organization_id, SalesActivity.sales_opportunity_id == deal_id
    )
    if not include_system:
        query = query.where(SalesActivity.activity_type != ActivityType.SYSTEM.value)
    return list(
        db.scalars(
            query.order_by(SalesActivity.occurred_at.desc(), SalesActivity.id.desc()).limit(limit).offset(offset)
        )
    )
