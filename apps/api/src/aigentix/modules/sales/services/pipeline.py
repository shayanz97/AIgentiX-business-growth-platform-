"""Deal pipeline service: create, list, edit (optimistic locking), stage changes, close / reopen, history.

All rules live in domain/pipeline.py; this layer loads facts, enforces tenancy and records history + audit.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.sales.domain.pipeline import (
    CONTACT_ACTIVITIES,
    StageFacts,
    TransitionError,
    check_close,
    check_move,
    reopen_stage,
)
from aigentix.modules.sales.models import (
    DealStatus,
    Priority,
    SalesActivity,
    SalesOpportunity,
    SalesProposal,
    SalesStageHistory,
    Stage,
)
from aigentix.modules.sales.services.common import audit, check_version, get_deal, require_member, touch
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext

DealSort = Literal["updated", "created", "value", "close_date", "priority", "title"]


@dataclass(frozen=True)
class DealFilters:
    stage: Stage | None = None
    status: DealStatus | None = None
    owner_user_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    priority: Priority | None = None
    q: str | None = None
    closing_before: date | None = None


def _history(
    db: Session, deal: SalesOpportunity, previous: str | None, new: str, user: uuid.UUID | None, reason: str | None
) -> None:
    db.add(
        SalesStageHistory(
            organization_id=deal.organization_id,
            sales_opportunity_id=deal.id,
            previous_stage=previous,
            new_stage=new,
            changed_by_user_id=user,
            reason=reason,
        )
    )


def create_deal(
    db: Session,
    tenant: TenantContext,
    *,
    company_id: uuid.UUID,
    title: str,
    description: str = "",
    owner_user_id: uuid.UUID | None = None,
    priority: Priority = Priority.MEDIUM,
    estimated_value: Decimal | None = None,
    currency: str = "EUR",
    expected_close_date: date | None = None,
    source_opportunity_id: uuid.UUID | None = None,
    source_lead_score_id: uuid.UUID | None = None,
    conversion_key: uuid.UUID | None = None,
    reason: str = "Created",
) -> SalesOpportunity:
    if not get_lead_data_provider().company_exists(db, tenant.organization_id, company_id):
        raise NotFound("Company not found")
    require_member(db, tenant, owner_user_id)
    deal = SalesOpportunity(
        organization_id=tenant.organization_id,
        company_id=company_id,
        title=title.strip(),
        description=description.strip(),
        owner_user_id=owner_user_id or tenant.user.id,
        priority=priority.value,
        estimated_value=estimated_value,
        currency=currency.upper(),
        expected_close_date=expected_close_date,
        source_opportunity_id=source_opportunity_id,
        source_lead_score_id=source_lead_score_id,
        conversion_key=conversion_key,
        created_by_user_id=tenant.user.id,
        stage=Stage.QUALIFIED.value,
        status=DealStatus.OPEN.value,
    )
    db.add(deal)
    db.flush()
    _history(db, deal, None, Stage.QUALIFIED.value, tenant.user.id, reason)
    db.flush()
    return deal


def list_deals(
    db: Session, tenant: TenantContext, filters: DealFilters, *, sort: DealSort, limit: int, offset: int
) -> tuple[list[SalesOpportunity], int]:
    conditions: list[Any] = [SalesOpportunity.organization_id == tenant.organization_id]
    if filters.stage is not None:
        conditions.append(SalesOpportunity.stage == filters.stage.value)
    if filters.status is not None:
        conditions.append(SalesOpportunity.status == filters.status.value)
    if filters.owner_user_id is not None:
        conditions.append(SalesOpportunity.owner_user_id == filters.owner_user_id)
    if filters.company_id is not None:
        conditions.append(SalesOpportunity.company_id == filters.company_id)
    if filters.priority is not None:
        conditions.append(SalesOpportunity.priority == filters.priority.value)
    if filters.closing_before is not None:
        conditions.append(SalesOpportunity.expected_close_date <= filters.closing_before)
    if filters.q:
        pattern = "%" + filters.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(SalesOpportunity.title.ilike(pattern))
    orders: dict[str, list[Any]] = {
        "updated": [SalesOpportunity.updated_at.desc()],
        "created": [SalesOpportunity.created_at.desc()],
        "value": [SalesOpportunity.estimated_value.desc().nulls_last()],
        "close_date": [SalesOpportunity.expected_close_date.asc().nulls_last()],
        "priority": [func.array_position(["high", "medium", "low"], SalesOpportunity.priority)],
        "title": [func.lower(SalesOpportunity.title)],
    }
    order = orders[sort]
    total = db.scalar(select(func.count()).select_from(SalesOpportunity).where(*conditions)) or 0
    rows = list(
        db.scalars(
            select(SalesOpportunity)
            .where(*conditions)
            .order_by(*order, SalesOpportunity.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


_EDITABLE = {
    "title",
    "description",
    "owner_user_id",
    "priority",
    "estimated_value",
    "currency",
    "expected_close_date",
    "confirmed_requirements",
}


def update_deal(
    db: Session, tenant: TenantContext, deal_id: uuid.UUID, changes: dict[str, Any], *, expected_version: int
) -> SalesOpportunity:
    deal = get_deal(db, tenant, deal_id, for_update=True)
    check_version(deal.version, expected_version)
    unknown = set(changes) - _EDITABLE
    if unknown:
        raise InvalidInput("Use the stage, close or reopen actions to change the pipeline stage")
    if "owner_user_id" in changes:
        require_member(db, tenant, changes["owner_user_id"])
    changed = []
    for key, value in changes.items():
        if isinstance(value, Priority):
            value = value.value
        if key == "currency" and value:
            value = str(value).upper()
        if key in ("title", "description") and isinstance(value, str):
            value = value.strip()
        if getattr(deal, key) != value:
            setattr(deal, key, value)
            changed.append(key)
    if changed:
        touch(deal)
        audit(db, tenant, deal, f"Updated {', '.join(sorted(changed))}", fields=sorted(changed))
    db.flush()
    return deal


def stage_facts(db: Session, deal: SalesOpportunity) -> StageFacts:
    contact = db.scalar(
        select(
            exists().where(
                SalesActivity.sales_opportunity_id == deal.id,
                SalesActivity.activity_type.in_([a.value for a in CONTACT_ACTIVITIES]),
            )
        )
    )
    sent = db.scalar(
        select(exists().where(SalesProposal.sales_opportunity_id == deal.id, SalesProposal.sent_at.is_not(None)))
    )
    return StageFacts(has_contact_activity=bool(contact), has_sent_proposal=bool(sent))


def _rule(error: TransitionError) -> InvalidInput:
    return InvalidInput(str(error))


def change_stage(
    db: Session, tenant: TenantContext, deal_id: uuid.UUID, *, stage: Stage, reason: str | None, expected_version: int
) -> SalesOpportunity:
    deal = get_deal(db, tenant, deal_id, for_update=True)
    check_version(deal.version, expected_version)
    try:
        check_move(Stage(deal.stage), stage, stage_facts(db, deal))
    except TransitionError as exc:
        raise _rule(exc) from None
    previous = deal.stage
    deal.stage = stage.value
    _history(db, deal, previous, stage.value, tenant.user.id, reason)
    touch(deal)
    db.flush()
    return deal


def close_deal(
    db: Session,
    tenant: TenantContext,
    deal_id: uuid.UUID,
    *,
    outcome: Stage,
    expected_version: int,
    won_value: Decimal | None = None,
    lost_reason: str | None = None,
    note: str | None = None,
) -> SalesOpportunity:
    """Record a real outcome. Won value is what the user enters (never estimated); lost reason is optional."""
    deal = get_deal(db, tenant, deal_id, for_update=True)
    check_version(deal.version, expected_version)
    try:
        check_close(Stage(deal.stage), outcome)
    except TransitionError as exc:
        raise _rule(exc) from None
    if outcome == Stage.LOST and won_value is not None:
        raise InvalidInput("A lost deal has no won value")
    previous = deal.stage
    deal.stage = outcome.value
    deal.status = outcome.value
    deal.closed_at = utcnow()
    deal.won_value = won_value if outcome == Stage.WON else None
    deal.lost_reason = (lost_reason or "").strip() or None if outcome == Stage.LOST else None
    _history(db, deal, previous, outcome.value, tenant.user.id, note or deal.lost_reason)
    audit(db, tenant, deal, f"Closed as {outcome.value}", outcome=outcome.value)
    touch(deal)
    db.flush()
    return deal


def reopen_deal(
    db: Session, tenant: TenantContext, deal_id: uuid.UUID, *, reason: str, expected_version: int
) -> SalesOpportunity:
    if not reason.strip():
        raise InvalidInput("Reopening needs a reason")
    deal = get_deal(db, tenant, deal_id, for_update=True)
    check_version(deal.version, expected_version)
    if deal.status == DealStatus.OPEN.value:
        raise InvalidInput("The deal is not closed")
    stages = list(
        db.scalars(
            select(SalesStageHistory.new_stage)
            .where(SalesStageHistory.sales_opportunity_id == deal.id)
            .order_by(SalesStageHistory.changed_at, SalesStageHistory.id)
        )
    )
    target = reopen_stage(stages[:-1] if stages and stages[-1] == deal.stage else stages)
    previous = deal.stage
    deal.stage, deal.status, deal.closed_at, deal.won_value, deal.lost_reason = (
        target.value,
        DealStatus.OPEN.value,
        None,
        None,
        None,
    )
    _history(db, deal, previous, target.value, tenant.user.id, reason.strip())
    audit(db, tenant, deal, f"Reopened (was {previous})", reason=reason.strip())
    touch(deal)
    db.flush()
    return deal


def stage_history(db: Session, tenant: TenantContext, deal_id: uuid.UUID) -> list[SalesStageHistory]:
    get_deal(db, tenant, deal_id)
    return list(
        db.scalars(
            select(SalesStageHistory)
            .where(
                SalesStageHistory.sales_opportunity_id == deal_id,
                SalesStageHistory.organization_id == tenant.organization_id,
            )
            .order_by(SalesStageHistory.changed_at, SalesStageHistory.id)
        )
    )
