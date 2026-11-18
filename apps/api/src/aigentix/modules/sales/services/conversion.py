"""Lead → sales opportunity conversion (explicit user action, idempotent).

Eligibility: the company belongs to the tenant, its latest lead review is `qualified_for_review` or `reviewed`
and it has a lead score. A retry with the same idempotency key returns the deal created the first time; an open
deal for the same company and research opportunity is reported instead of duplicated unless the user explicitly
asks for an additional opportunity. Lead Intelligence data is read, never modified or copied.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.errors import Conflict, InvalidInput, NotFound
from aigentix.modules.sales.models import DealStatus, Priority, SalesOpportunity
from aigentix.modules.sales.services.common import audit
from aigentix.modules.sales.services.pipeline import create_deal
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext

ELIGIBLE_REVIEW_STATUSES = ("qualified_for_review", "reviewed")


@dataclass(frozen=True)
class ConversionResult:
    deal: SalesOpportunity
    created: bool


class DuplicateDeal(Conflict):
    def __init__(self, existing: SalesOpportunity) -> None:
        super().__init__(
            "An open sales opportunity already exists for this lead and research opportunity",
            details={"existing_opportunity_id": str(existing.id)},
        )


def _priority(band: str | None) -> Priority:
    return {"high": Priority.HIGH, "medium": Priority.MEDIUM}.get(band or "", Priority.LOW)


def convert_lead(
    db: Session,
    tenant: TenantContext,
    company_id: uuid.UUID,
    *,
    idempotency_key: uuid.UUID,
    source_opportunity_id: uuid.UUID | None,
    title: str | None,
    allow_additional: bool,
) -> ConversionResult:
    org = tenant.organization_id
    previous = db.scalar(
        select(SalesOpportunity).where(
            SalesOpportunity.organization_id == org, SalesOpportunity.conversion_key == idempotency_key
        )
    )
    if previous is not None:
        if previous.company_id != company_id:
            raise InvalidInput("This idempotency key was already used for another conversion")
        return ConversionResult(previous, False)

    lead = get_lead_data_provider().snapshot(db, org, company_id)
    if lead is None:
        raise NotFound("Lead not found")
    if lead.review_status not in ELIGIBLE_REVIEW_STATUSES:
        raise InvalidInput(
            "Only leads reviewed as qualified can be converted (current review status: "
            f"{lead.review_status}). Review the lead first."
        )
    if lead.latest_score is None:
        raise InvalidInput("Score the lead before converting it")
    source = None
    if source_opportunity_id is not None:
        source = next((o for o in lead.opportunities if o.id == source_opportunity_id), None)
        if source is None:
            raise NotFound("Research opportunity not found for this company")
        if source.status == "rejected":
            raise InvalidInput("A rejected research opportunity cannot be converted")

    # Serialise conversions of the same lead (different keys, two tabs / users) so the duplicate check below
    # cannot race; the lock is released at commit.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"sales-convert:{org}:{company_id}"))))
    existing = db.scalar(
        select(SalesOpportunity)
        .where(
            SalesOpportunity.organization_id == org,
            SalesOpportunity.company_id == company_id,
            SalesOpportunity.status == DealStatus.OPEN.value,
            SalesOpportunity.source_opportunity_id.is_(None)
            if source_opportunity_id is None
            else SalesOpportunity.source_opportunity_id == source_opportunity_id,
        )
        .order_by(SalesOpportunity.created_at)
        .limit(1)
    )
    if existing is not None and not allow_additional:
        raise DuplicateDeal(existing)

    default_title = f"{lead.name}: {source.title}" if source else f"{lead.name}: AI automation"
    try:
        with db.begin_nested():
            deal = create_deal(
                db,
                tenant,
                company_id=company_id,
                title=(title or default_title)[:200],
                description=source.problem_hypothesis if source else "",
                priority=_priority(lead.latest_score.priority_band),
                source_opportunity_id=source_opportunity_id,
                source_lead_score_id=lead.latest_score.id,
                conversion_key=idempotency_key,
                reason="Converted from a qualified lead",
            )
    except IntegrityError:
        # A concurrent retry with the same key won the race: return its deal.
        winner = db.scalar(
            select(SalesOpportunity).where(
                SalesOpportunity.organization_id == org, SalesOpportunity.conversion_key == idempotency_key
            )
        )
        if winner is None:  # pragma: no cover - the constraint that failed is the key
            raise
        return ConversionResult(winner, False)
    audit(
        db,
        tenant,
        deal,
        "Converted from a qualified lead",
        lead_score_id=str(lead.latest_score.id),
        score_low=lead.latest_score.score_low,
        score_high=lead.latest_score.score_high,
        research_opportunity_id=str(source_opportunity_id) if source_opportunity_id else None,
        review_status=lead.review_status,
    )
    db.flush()
    return ConversionResult(deal, True)
