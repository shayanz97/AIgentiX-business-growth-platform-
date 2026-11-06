"""Opportunity review: tenant-scoped reads and status transitions."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.lead_intelligence.models import (
    Evidence,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
)
from aigentix.platform.organizations.service import TenantContext

S = OpportunityStatus
ALLOWED_TRANSITIONS: dict[OpportunityStatus, frozenset[OpportunityStatus]] = {
    S.PROPOSED: frozenset({S.UNDER_REVIEW, S.APPROVED, S.REJECTED}),
    S.UNDER_REVIEW: frozenset({S.APPROVED, S.REJECTED, S.PROPOSED}),
    S.APPROVED: frozenset({S.UNDER_REVIEW, S.REJECTED}),
    S.REJECTED: frozenset({S.UNDER_REVIEW}),
}
MAX_NOTE_LENGTH = 2_000


def can_transition(current: OpportunityStatus, target: OpportunityStatus) -> bool:
    return target == current or target in ALLOWED_TRANSITIONS[current]


def get_opportunity(db: Session, tenant: TenantContext, opportunity_id: uuid.UUID) -> Opportunity:
    opportunity = db.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id, Opportunity.organization_id == tenant.organization_id
        )
    )
    if opportunity is None:
        raise NotFound("Opportunity not found")
    return opportunity


def evidence_for(
    db: Session, tenant: TenantContext, opportunity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Evidence]]:
    if not opportunity_ids:
        return {}
    rows = db.execute(
        select(OpportunityEvidence.opportunity_id, Evidence)
        .join(Evidence, Evidence.id == OpportunityEvidence.evidence_id)
        .where(
            OpportunityEvidence.opportunity_id.in_(opportunity_ids),
            OpportunityEvidence.organization_id == tenant.organization_id,
        )
        .order_by(Evidence.created_at)
    )
    grouped: dict[uuid.UUID, list[Evidence]] = {}
    for opportunity_id, evidence in rows:
        grouped.setdefault(opportunity_id, []).append(evidence)
    return grouped


def list_opportunities(
    db: Session,
    tenant: TenantContext,
    *,
    limit: int,
    offset: int,
    status: OpportunityStatus | None = None,
    company_id: uuid.UUID | None = None,
    research_run_id: uuid.UUID | None = None,
) -> tuple[list[Opportunity], int]:
    conditions = [Opportunity.organization_id == tenant.organization_id]
    if status is not None:
        conditions.append(Opportunity.status == status.value)
    if company_id is not None:
        conditions.append(Opportunity.company_id == company_id)
    if research_run_id is not None:
        conditions.append(Opportunity.research_run_id == research_run_id)
    total = db.scalar(select(func.count()).select_from(Opportunity).where(*conditions)) or 0
    rows = db.scalars(
        select(Opportunity)
        .where(*conditions)
        .order_by(Opportunity.created_at.desc(), Opportunity.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


def review_opportunity(
    db: Session,
    tenant: TenantContext,
    opportunity_id: uuid.UUID,
    *,
    status: OpportunityStatus | None,
    reviewer_note: str | None,
) -> Opportunity:
    opportunity = get_opportunity(db, tenant, opportunity_id)
    if status is None and reviewer_note is None:
        raise InvalidInput("Nothing to update")
    if status is not None:
        current = OpportunityStatus(opportunity.status)
        if not can_transition(current, status):
            raise InvalidInput(
                f"Cannot change status from {current.value} to {status.value}",
                details={"allowed": sorted(s.value for s in ALLOWED_TRANSITIONS[current])},
            )
        opportunity.status = status.value
    if reviewer_note is not None:
        opportunity.reviewer_note = reviewer_note.strip()[:MAX_NOTE_LENGTH] or None
    opportunity.reviewed_by_user_id = tenant.user.id
    opportunity.reviewed_at = utcnow()
    db.flush()
    return opportunity
