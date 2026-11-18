"""Deterministic sales metrics (definitions in docs/SPRINT_4_PLAN.md). No forecasting, no estimated values:
deals without a value are counted separately and excluded from value sums."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.modules.sales.domain.pipeline import PIPELINE
from aigentix.modules.sales.models import DealStatus, SalesOpportunity, SalesProposal, SalesTask, TaskStatus
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext


@dataclass
class SalesMetrics:
    qualified_leads: int
    converted_leads: int
    lead_to_opportunity_rate: float | None
    opportunities_total: int
    open_opportunities: int
    opportunities_by_stage: dict[str, int]
    pipeline_value: dict[str, Decimal]  # per currency, open deals with a value
    open_without_value: int
    won_count: int
    lost_count: int
    won_value: dict[str, Decimal]
    won_without_value: int
    opportunity_to_won_rate: float | None
    win_rate: float | None
    overdue_tasks: int
    open_tasks: int
    proposals_drafted: int
    proposals_sent: int
    definitions: dict[str, str] = field(default_factory=dict)


DEFINITIONS = {
    "qualified_leads": "Companies whose latest lead review is qualified_for_review or reviewed, plus converted ones.",
    "converted_leads": "Distinct companies with at least one sales opportunity.",
    "lead_to_opportunity_rate": "converted_leads / qualified_leads (null when there are none).",
    "pipeline_value": "Sum of estimated_value of open deals that have a value, per currency.",
    "won_value": "Sum of the won value recorded at close, per currency.",
    "opportunity_to_won_rate": "won / all opportunities.",
    "win_rate": "won / (won + lost).",
    "overdue_tasks": "Open tasks whose due time has passed.",
    "proposals_sent": "Proposals a person marked as sent (drafts are not counted as sent).",
}


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def sales_metrics(db: Session, tenant: TenantContext) -> SalesMetrics:
    org = tenant.organization_id
    deals = SalesOpportunity.organization_id == org
    by_stage = {s.value: 0 for s in PIPELINE}
    by_stage.update(
        {
            k: int(v)
            for k, v in db.execute(
                select(SalesOpportunity.stage, func.count()).where(deals).group_by(SalesOpportunity.stage)
            )
        }
    )
    total = sum(by_stage.values())
    converted_ids = set(db.scalars(select(SalesOpportunity.company_id).where(deals).distinct()))
    qualified = get_lead_data_provider().qualified_company_ids(db, org) | converted_ids

    def sums(status: DealStatus, column: Any) -> dict[str, Decimal]:
        rows = db.execute(
            select(SalesOpportunity.currency, func.sum(column))
            .where(deals, SalesOpportunity.status == status.value, column.is_not(None))
            .group_by(SalesOpportunity.currency)
        )
        return {str(c): Decimal(str(v)) for c, v in rows if v is not None}

    def count(*conditions: object) -> int:
        return db.scalar(select(func.count()).select_from(SalesOpportunity).where(deals, *conditions)) or 0  # type: ignore[arg-type]

    won = count(SalesOpportunity.status == DealStatus.WON.value)
    lost = count(SalesOpportunity.status == DealStatus.LOST.value)
    tasks = (SalesTask.organization_id == org, SalesTask.status == TaskStatus.OPEN.value)
    proposals = SalesProposal.organization_id == org
    return SalesMetrics(
        qualified_leads=len(qualified),
        converted_leads=len(converted_ids),
        lead_to_opportunity_rate=_ratio(len(converted_ids), len(qualified)),
        opportunities_total=total,
        open_opportunities=count(SalesOpportunity.status == DealStatus.OPEN.value),
        opportunities_by_stage=by_stage,
        pipeline_value=sums(DealStatus.OPEN, SalesOpportunity.estimated_value),
        open_without_value=count(
            SalesOpportunity.status == DealStatus.OPEN.value, SalesOpportunity.estimated_value.is_(None)
        ),
        won_count=won,
        lost_count=lost,
        won_value=sums(DealStatus.WON, SalesOpportunity.won_value),
        won_without_value=count(SalesOpportunity.status == DealStatus.WON.value, SalesOpportunity.won_value.is_(None)),
        opportunity_to_won_rate=_ratio(won, total),
        win_rate=_ratio(won, won + lost),
        overdue_tasks=db.scalar(select(func.count()).select_from(SalesTask).where(*tasks, SalesTask.due_at < utcnow()))
        or 0,
        open_tasks=db.scalar(select(func.count()).select_from(SalesTask).where(*tasks)) or 0,
        proposals_drafted=db.scalar(select(func.count()).select_from(SalesProposal).where(proposals)) or 0,
        proposals_sent=db.scalar(
            select(func.count()).select_from(SalesProposal).where(proposals, SalesProposal.sent_at.is_not(None))
        )
        or 0,
        definitions=DEFINITIONS,
    )
