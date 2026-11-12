"""Sprint 3 routes: scoring / ICP profiles, enrichment, signals, intent, scores and ranked leads."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.lead_intelligence.config import get_research_settings
from aigentix.modules.lead_intelligence.domain.profiles import ScoringConfig
from aigentix.modules.lead_intelligence.models import IcpProfile, ReviewStatus, ScoringProfile
from aigentix.modules.lead_intelligence.routes.scoring_serializers import (
    intent_reads,
    lead_read,
    score_read,
    signal_reads,
)
from aigentix.modules.lead_intelligence.routes.serializers import run_read
from aigentix.modules.lead_intelligence.scoring_schemas import (
    CompanySignals,
    EnrichmentRequest,
    EnrichmentRunCreate,
    EnrichmentSkipped,
    EnrichmentStartResult,
    FirstPartyIntentCreate,
    IntentRead,
    IntentStatus,
    LeadDetail,
    LeadRead,
    LeadReviewRead,
    LeadReviewUpdate,
    LeadScoreRead,
    PriorityBand,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    RescoredCompany,
    ScoreRequest,
    ScoreRunResult,
)
from aigentix.modules.lead_intelligence.services import enrichment as enrichment_service
from aigentix.modules.lead_intelligence.services import leads as lead_service
from aigentix.modules.lead_intelligence.services import profiles as profile_service
from aigentix.modules.lead_intelligence.services import scoring as scoring_service
from aigentix.modules.lead_intelligence.services.research import get_run

router = APIRouter()


# --- profiles ----------------------------------------------------------------------------------------


def _profile_routes[P: (IcpProfile, ScoringProfile)](path: str, model: type[P], name: str, tag: str) -> None:
    @router.get(f"/{path}", response_model=list[ProfileRead], operation_id=f"list{name}s", tags=[tag])
    def list_profiles(db: DbSession, tenant: Tenant) -> list[ProfileRead]:
        items = profile_service.list_profiles(db, tenant, model)
        db.commit()
        return [ProfileRead.model_validate(p) for p in items]

    @router.post(
        f"/{path}",
        response_model=ProfileRead,
        status_code=status.HTTP_201_CREATED,
        operation_id=f"create{name}",
        tags=[tag],
    )
    def create_profile(db: DbSession, tenant: Tenant, body: ProfileCreate) -> ProfileRead:
        profile = profile_service.create_profile(
            db,
            tenant,
            model,
            name=body.name,
            description=body.description,
            config=body.config,
            make_default=body.is_default,
        )
        db.commit()
        return ProfileRead.model_validate(profile)

    @router.patch(f"/{path}/{{profile_id}}", response_model=ProfileRead, operation_id=f"update{name}", tags=[tag])
    def update_profile(db: DbSession, tenant: Tenant, profile_id: uuid.UUID, body: ProfileUpdate) -> ProfileRead:
        profile = profile_service.update_profile(
            db,
            tenant,
            model,
            profile_id,
            name=body.name,
            description=body.description,
            config=body.config,
            make_default=body.is_default,
        )
        db.commit()
        return ProfileRead.model_validate(profile)


_profile_routes("scoring-profiles", ScoringProfile, "ScoringProfile", "scoring")
_profile_routes("icp-profiles", IcpProfile, "IcpProfile", "scoring")


# --- enrichment ------------------------------------------------------------------------------------------


def _start(
    db: DbSession, tenant: Tenant, company_ids: list[uuid.UUID] | None, project_id: uuid.UUID | None, force: bool
) -> EnrichmentStartResult:
    settings = get_research_settings()
    result = enrichment_service.start_enrichment(
        db,
        tenant,
        company_ids=company_ids,
        project_id=project_id,
        force=force,
        max_attempts=settings.research_max_attempts,
        cache_hours=settings.research_enrichment_cache_hours,
        reference=settings.reference_date(),
    )
    db.commit()
    return EnrichmentStartResult(
        started=[run_read(v) for v in result.started],
        rescored=[RescoredCompany(company_id=cid, score_id=s.id) for cid, s in result.rescored],
        skipped=[EnrichmentSkipped(company_id=cid, reason=r) for cid, r in result.skipped],
    )


@router.post(
    "/companies/{company_id}/enrich",
    response_model=EnrichmentStartResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="enrichCompany",
    tags=["enrichment"],
)
def enrich_company(
    db: DbSession, tenant: Tenant, company_id: uuid.UUID, body: EnrichmentRequest | None = None
) -> EnrichmentStartResult:
    scoring_service.get_company(db, tenant, company_id)  # 404 for foreign / unknown companies
    return _start(db, tenant, [company_id], None, bool(body and body.force))


@router.post(
    "/enrichment-runs",
    response_model=EnrichmentStartResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startEnrichment",
    tags=["enrichment"],
)
def start_enrichment(db: DbSession, tenant: Tenant, body: EnrichmentRunCreate) -> EnrichmentStartResult:
    return _start(db, tenant, body.company_ids, body.project_id, body.force)


@router.get(
    "/companies/{company_id}/signals",
    response_model=CompanySignals,
    operation_id="getCompanySignals",
    tags=["enrichment"],
)
def company_signals(db: DbSession, tenant: Tenant, company_id: uuid.UUID) -> CompanySignals:
    settings = get_research_settings()
    reference = settings.reference_date()
    scoring = profile_service.ensure_default(db, tenant.organization_id, ScoringProfile)
    config = ScoringConfig.model_validate(scoring.config)
    signals = enrichment_service.signals_for_company(db, tenant, company_id)
    intents = enrichment_service.intents_for_company(db, tenant, company_id)
    states = scoring_service.run_states(db, tenant.organization_id, company_id)
    run = None
    profile: dict[str, Any] = {}
    if states.latest_enrichment_run is not None:
        view = get_run(db, tenant, states.latest_enrichment_run.workflow_run_id)
        run = run_read(view)
    if states.enrichment_run is not None:
        profile = states.enrichment_run.profile or {}
    active = [i.strength for i in intents if i.deadline_on is None or i.deadline_on >= reference]
    intent_status: IntentStatus = "none_verified" if states.enrichment_state == "completed" else "unknown"
    for strength in ("explicit", "strong", "indirect"):
        if strength in active:
            intent_status = strength
            break
    intent_info: dict[str, Any] = profile.get("intent") or {}
    db.commit()
    return CompanySignals(
        company_id=company_id,
        intent_status=intent_status,
        signals=signal_reads(
            db,
            tenant,
            signals,
            enrichment_service.signal_evidence(db, signals),
            reference=reference,
            config=config,
        ),
        intents=intent_reads(db, tenant, intents, enrichment_service.intent_evidence(db, intents), reference=reference),
        enrichment_run=run,
        sources_checked=list(intent_info.get("sources_checked", [])),
        ignored=list(intent_info.get("ignored", [])),
    )


@router.post(
    "/companies/{company_id}/intent-signals",
    response_model=IntentRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="recordFirstPartyIntent",
    tags=["enrichment"],
    responses={200: {"model": IntentRead, "description": "Already recorded (deduplicated)"}},
)
def record_intent(
    db: DbSession, tenant: Tenant, company_id: uuid.UUID, body: FirstPartyIntentCreate, response: Response
) -> IntentRead:
    reference = get_research_settings().reference_date()
    row, created = enrichment_service.record_first_party_intent(
        db,
        tenant,
        company_id,
        channel=body.channel,
        received_on=body.received_on,
        summary=body.summary,
        solution_category=body.solution_category,
        reference=reference,
    )
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return intent_reads(db, tenant, [row], {}, reference=reference)[0]


# --- scores ----------------------------------------------------------------------------------------------


@router.get(
    "/companies/{company_id}/scores",
    response_model=Page[LeadScoreRead],
    operation_id="listCompanyScores",
    tags=["scoring"],
)
def company_scores(db: DbSession, tenant: Tenant, company_id: uuid.UUID, page: Pagination) -> Page[LeadScoreRead]:
    rows, total = scoring_service.score_history(db, tenant, company_id, limit=page.limit, offset=page.offset)
    return Page[LeadScoreRead](items=[score_read(s) for s in rows], total=total, limit=page.limit, offset=page.offset)


def _score(db: DbSession, tenant: Tenant, ids: list[uuid.UUID], body: ScoreRequest | None) -> ScoreRunResult:
    results = scoring_service.score_for_tenant(
        db,
        tenant,
        ids,
        scoring_profile_id=body.scoring_profile_id if body else None,
        icp_profile_id=body.icp_profile_id if body else None,
        reference=get_research_settings().reference_date(),
    )
    db.commit()
    return ScoreRunResult(
        scored=len(results),
        new_snapshots=sum(1 for _, new in results if new),
        scores=[score_read(s) for s, _ in results],
    )


@router.post(
    "/companies/{company_id}/score", response_model=ScoreRunResult, operation_id="scoreCompany", tags=["scoring"]
)
def score_company(
    db: DbSession, tenant: Tenant, company_id: uuid.UUID, body: ScoreRequest | None = None
) -> ScoreRunResult:
    scoring_service.get_company(db, tenant, company_id)
    return _score(db, tenant, [company_id], body)


@router.post(
    "/projects/{project_id}/score", response_model=ScoreRunResult, operation_id="scoreProject", tags=["scoring"]
)
def score_project(
    db: DbSession, tenant: Tenant, project_id: uuid.UUID, body: ScoreRequest | None = None
) -> ScoreRunResult:
    """Re-score every company of the project from stored data (no crawling, no AI calls)."""
    return _score(db, tenant, scoring_service.project_company_ids(db, tenant, project_id), body)


# --- leads -------------------------------------------------------------------------------------------------


def _filters(
    project_id: uuid.UUID | None = None,
    review_status: ReviewStatus | None = None,
    priority_band: PriorityBand | None = None,
    intent_status: IntentStatus | None = None,
    signal_type: Annotated[str | None, Query(max_length=40)] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    provisional: bool | None = None,
    include_excluded: bool = True,
    triggered_since: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> lead_service.LeadFilters:
    return lead_service.LeadFilters(
        project_id=project_id,
        review_status=review_status,
        priority_band=priority_band,
        intent_status=intent_status,
        signal_type=signal_type,
        min_score=min_score,
        provisional=provisional,
        include_excluded=include_excluded,
        triggered_since=triggered_since,
        q=q,
    )


Filters = Annotated[lead_service.LeadFilters, Depends(_filters)]
Sort = Annotated[lead_service.LeadSort, Query()]


@router.get("/leads/ranked", response_model=Page[LeadRead], operation_id="listRankedLeads", tags=["leads"])
def ranked_leads(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    filters: Filters,
    sort: Sort = "score",
    scoring_profile_id: uuid.UUID | None = None,
    icp_profile_id: uuid.UUID | None = None,
) -> Page[LeadRead]:
    rows, total = lead_service.ranked_leads(
        db,
        tenant,
        filters,
        sort=sort,
        scoring_profile_id=scoring_profile_id,
        icp_profile_id=icp_profile_id,
        limit=page.limit,
        offset=page.offset,
    )
    db.commit()
    return Page[LeadRead](items=[lead_read(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/leads/export",
    operation_id="exportLeads",
    tags=["leads"],
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Shortlist as CSV"}},
)
def export_leads(
    db: DbSession,
    tenant: Tenant,
    filters: Filters,
    sort: Sort = "score",
    scoring_profile_id: uuid.UUID | None = None,
    icp_profile_id: uuid.UUID | None = None,
) -> Response:
    rows, _ = lead_service.ranked_leads(
        db,
        tenant,
        filters,
        sort=sort,
        scoring_profile_id=scoring_profile_id,
        icp_profile_id=icp_profile_id,
        limit=lead_service.MAX_EXPORT_ROWS,
        offset=0,
    )
    db.commit()
    return Response(
        content=lead_service.export_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="aigentix-leads.csv"'},
    )


@router.get(
    "/projects/{project_id}/leads", response_model=Page[LeadRead], operation_id="listProjectLeads", tags=["leads"]
)
def project_leads(
    db: DbSession, tenant: Tenant, project_id: uuid.UUID, page: Pagination, filters: Filters, sort: Sort = "score"
) -> Page[LeadRead]:
    scoped = lead_service.LeadFilters(**{**vars(filters), "project_id": project_id})
    rows, total = lead_service.ranked_leads(db, tenant, scoped, sort=sort, limit=page.limit, offset=page.offset)
    db.commit()
    return Page[LeadRead](items=[lead_read(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/leads/{company_id}", response_model=LeadDetail, operation_id="getLead", tags=["leads"])
def get_lead(db: DbSession, tenant: Tenant, company_id: uuid.UUID) -> LeadDetail:
    company, reviews = lead_service.lead_detail(db, tenant, company_id)
    rows, _ = lead_service.ranked_leads(db, tenant, lead_service.LeadFilters(company_id=company.id), limit=1, offset=0)
    db.commit()
    return LeadDetail(
        lead=lead_read(rows[0]) if rows else None,
        reviews=[LeadReviewRead.model_validate(r) for r in reviews],
    )


@router.patch("/leads/{company_id}/review", response_model=LeadReviewRead, operation_id="reviewLead", tags=["leads"])
def review_lead(db: DbSession, tenant: Tenant, company_id: uuid.UUID, body: LeadReviewUpdate) -> LeadReviewRead:
    review = lead_service.review_lead(db, tenant, company_id, status=body.status, note=body.note)
    db.commit()
    return LeadReviewRead.model_validate(review)
