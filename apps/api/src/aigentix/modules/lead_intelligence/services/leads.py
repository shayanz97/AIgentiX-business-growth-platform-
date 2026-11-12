"""Prioritised lead list (latest score per company for a profile pair), review workflow and CSV export."""

import csv
import io
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Select, and_, case, exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from aigentix.modules.lead_intelligence.models import (
    BusinessSignal,
    Company,
    IcpProfile,
    LeadReview,
    LeadScore,
    ResearchProjectCompany,
    ReviewStatus,
    ScoringProfile,
)
from aigentix.modules.lead_intelligence.services import profiles
from aigentix.modules.lead_intelligence.services.projects import get_project
from aigentix.modules.lead_intelligence.services.scoring import get_company
from aigentix.platform.organizations.service import TenantContext

MAX_EXPORT_ROWS = 5_000
INTENT_ORDER = {"explicit": 4, "strong": 3, "indirect": 2, "none_verified": 1, "unknown": 0}


@dataclass(frozen=True)
class LeadFilters:
    project_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    review_status: ReviewStatus | None = None
    priority_band: str | None = None
    intent_status: str | None = None
    signal_type: str | None = None
    min_score: float | None = None
    provisional: bool | None = None
    include_excluded: bool = True
    triggered_since: date | None = None
    q: str | None = None


LeadSort = Literal["score", "score_high", "coverage", "latest_trigger", "intent", "name", "scored_at"]


@dataclass(frozen=True)
class LeadRow:
    company: Company
    score: LeadScore
    review_status: str
    review_note: str | None
    reviewed_at: Any


def _latest_reviews(org: uuid.UUID) -> Any:
    return (
        select(LeadReview.company_id, LeadReview.status, LeadReview.note, LeadReview.created_at)
        .where(LeadReview.organization_id == org)
        .ext(distinct_on(LeadReview.company_id))
        .order_by(LeadReview.company_id, LeadReview.created_at.desc(), LeadReview.id.desc())
        .subquery()
    )


def _query(
    db: Session,
    tenant: TenantContext,
    filters: LeadFilters,
    scoring_profile_id: uuid.UUID | None,
    icp_profile_id: uuid.UUID | None,
    sort: str,
) -> Select[Any]:
    org = tenant.organization_id
    if filters.project_id is not None:
        get_project(db, tenant, filters.project_id)
    scoring = profiles.resolve(db, tenant, ScoringProfile, scoring_profile_id)
    icp = profiles.resolve(db, tenant, IcpProfile, icp_profile_id)
    latest_id = (
        select(LeadScore.id)
        .where(
            LeadScore.organization_id == org,
            LeadScore.scoring_profile_id == scoring.id,
            LeadScore.icp_profile_id == icp.id,
        )
        .ext(distinct_on(LeadScore.company_id))
        .order_by(LeadScore.company_id, LeadScore.created_at.desc(), LeadScore.id.desc())
        .subquery()
    )
    score = aliased(LeadScore)
    reviews = _latest_reviews(org)
    review_status = func.coalesce(reviews.c.status, ReviewStatus.NEW.value)
    query = (
        select(Company, score, review_status, reviews.c.note, reviews.c.created_at)
        .join(score, and_(score.company_id == Company.id, score.organization_id == Company.organization_id))
        .join(latest_id, latest_id.c.id == score.id)
        .outerjoin(reviews, reviews.c.company_id == Company.id)
        .where(Company.organization_id == org)
    )
    if filters.project_id is not None:
        query = query.where(
            exists().where(
                ResearchProjectCompany.company_id == Company.id,
                ResearchProjectCompany.research_project_id == filters.project_id,
                ResearchProjectCompany.organization_id == org,
            )
        )
    if filters.company_id is not None:
        query = query.where(Company.id == filters.company_id)
    if filters.review_status is not None:
        query = query.where(review_status == filters.review_status.value)
    if filters.priority_band is not None:
        query = query.where(score.priority_band == filters.priority_band)
    if filters.intent_status is not None:
        query = query.where(score.intent_status == filters.intent_status)
    if filters.min_score is not None:
        query = query.where(score.score_low >= filters.min_score)
    if filters.provisional is not None:
        query = query.where(score.provisional.is_(filters.provisional))
    if not filters.include_excluded:
        query = query.where(score.fit_excluded.is_(False))
    if filters.triggered_since is not None:
        query = query.where(score.latest_trigger_on >= filters.triggered_since)
    if filters.signal_type is not None:
        query = query.where(
            exists().where(
                BusinessSignal.company_id == Company.id,
                BusinessSignal.organization_id == org,
                BusinessSignal.signal_type == filters.signal_type,
            )
        )
    if filters.q:
        pattern = "%" + filters.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(Company.name.ilike(pattern) | Company.canonical_domain.ilike(pattern))
    return _ordered(query, sort, score)


def _ordered(query: Select[Any], sort: str, score: Any) -> Select[Any]:
    """Deterministic order: the chosen key, then conservative score, coverage, name and id as tie-breakers."""
    intent_rank = case(INTENT_ORDER, value=score.intent_status, else_=0)
    tail = [score.score_low.desc(), score.coverage.desc(), func.lower(Company.name), Company.id]
    first = {
        "score_high": [score.score_high.desc()],
        "coverage": [score.coverage.desc()],
        "latest_trigger": [score.latest_trigger_on.desc().nulls_last()],
        "intent": [intent_rank.desc()],
        "name": [func.lower(Company.name)],
        "scored_at": [score.created_at.desc()],
    }.get(sort, [])
    return query.order_by(*first, *tail)


def ranked_leads(
    db: Session,
    tenant: TenantContext,
    filters: LeadFilters,
    *,
    sort: str = "score",
    scoring_profile_id: uuid.UUID | None = None,
    icp_profile_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[LeadRow], int]:
    query = _query(db, tenant, filters, scoring_profile_id, icp_profile_id, sort)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = [
        LeadRow(company=r[0], score=r[1], review_status=str(r[2]), review_note=r[3], reviewed_at=r[4])
        for r in db.execute(query.limit(limit).offset(offset))
    ]
    return rows, total


def lead_detail(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> tuple[Company, list[LeadReview]]:
    company = get_company(db, tenant, company_id)
    reviews = list(
        db.scalars(
            select(LeadReview)
            .where(LeadReview.organization_id == tenant.organization_id, LeadReview.company_id == company_id)
            .order_by(LeadReview.created_at.desc(), LeadReview.id.desc())
            .limit(50)
        )
    )
    return company, reviews


def review_lead(
    db: Session, tenant: TenantContext, company_id: uuid.UUID, *, status: ReviewStatus, note: str | None
) -> LeadReview:
    """Append a review decision (history is kept). Any member may review; nothing is sent to the prospect."""
    company = get_company(db, tenant, company_id)
    latest = db.scalar(
        select(LeadScore.id)
        .where(LeadScore.organization_id == tenant.organization_id, LeadScore.company_id == company.id)
        .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        .limit(1)
    )
    review = LeadReview(
        organization_id=tenant.organization_id,
        company_id=company.id,
        status=status.value,
        note=note.strip() if note else None,
        lead_score_id=latest,
        reviewed_by_user_id=tenant.user.id,
    )
    db.add(review)
    db.flush()
    return review


def _cell(value: object) -> str:
    """CSV cell safe for spreadsheets: values starting with = + - @ (or tab/CR) are prefixed with a quote."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


EXPORT_COLUMNS = (
    "rank",
    "company",
    "domain",
    "score_low",
    "score_high",
    "coverage",
    "provisional",
    "priority_band",
    "intent_status",
    "latest_trigger_on",
    "fit_excluded",
    "review_status",
    "next_step",
    "opportunity_categories",
    "scored_at",
)


def export_csv(rows: Sequence[LeadRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for rank, row in enumerate(rows, start=1):
        s = row.score
        writer.writerow(
            [
                _cell(v)
                for v in (
                    rank,
                    row.company.name,
                    row.company.canonical_domain,
                    f"{s.score_low:.1f}",
                    f"{s.score_high:.1f}",
                    f"{s.coverage:.3f}",
                    "yes" if s.provisional else "no",
                    s.priority_band,
                    s.intent_status,
                    s.latest_trigger_on.isoformat() if s.latest_trigger_on else "",
                    "yes" if s.fit_excluded else "no",
                    row.review_status,
                    s.next_step_text,
                    " ".join(s.opportunity_categories),
                    s.created_at.isoformat(),
                )
            ]
        )
    return buffer.getvalue()
