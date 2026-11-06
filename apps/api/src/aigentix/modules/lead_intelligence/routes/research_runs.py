import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.lead_intelligence.config import get_research_settings
from aigentix.modules.lead_intelligence.routes.serializers import (
    evidence_reads,
    opportunity_reads,
    run_read,
    source_read,
)
from aigentix.modules.lead_intelligence.schemas import (
    LeadIntelligenceSummary,
    ResearchResults,
    ResearchRunCreate,
    ResearchRunRead,
    ResearchRunStartResult,
    SkippedCompany,
)
from aigentix.modules.lead_intelligence.services import research as service

router = APIRouter(tags=["research"])


@router.get(
    "/lead-intelligence/summary",
    response_model=LeadIntelligenceSummary,
    operation_id="getLeadIntelligenceSummary",
)
def get_summary(db: DbSession, tenant: Tenant) -> LeadIntelligenceSummary:
    return LeadIntelligenceSummary(**vars(service.summary(db, tenant)))


@router.post(
    "/research-runs",
    response_model=ResearchRunStartResult,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startResearch",
)
def start_research(db: DbSession, tenant: Tenant, body: ResearchRunCreate) -> ResearchRunStartResult:
    result = service.start_research(
        db,
        tenant,
        company_ids=body.company_ids,
        project_id=body.project_id,
        max_attempts=get_research_settings().research_max_attempts,
    )
    db.commit()
    return ResearchRunStartResult(
        started=[run_read(v) for v in result.started],
        skipped=[SkippedCompany(company_id=cid, reason=reason) for cid, reason in result.skipped],
    )


@router.get("/research-runs", response_model=Page[ResearchRunRead], operation_id="listResearchRuns")
def list_runs(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ResearchRunRead]:
    views, total = service.list_runs(
        db, tenant, limit=page.limit, offset=page.offset, company_id=company_id, project_id=project_id
    )
    return Page[ResearchRunRead](items=[run_read(v) for v in views], total=total, limit=page.limit, offset=page.offset)


@router.get("/research-runs/{run_id}", response_model=ResearchRunRead, operation_id="getResearchRun")
def get_run(db: DbSession, tenant: Tenant, run_id: uuid.UUID) -> ResearchRunRead:
    return run_read(service.get_run(db, tenant, run_id))


@router.get("/research-runs/{run_id}/results", response_model=ResearchResults, operation_id="getResearchResults")
def get_results(db: DbSession, tenant: Tenant, run_id: uuid.UUID) -> ResearchResults:
    view = service.get_run(db, tenant, run_id)
    return ResearchResults(
        run=run_read(view),
        profile=view.research.profile,
        sources=[source_read(s) for s in service.sources_for_run(db, tenant, run_id)],
        evidence=evidence_reads(db, service.evidence_for_run(db, tenant, run_id)),
        opportunities=opportunity_reads(db, tenant, service.opportunities_for_run(db, tenant, run_id)),
    )


@router.post("/research-runs/{run_id}/cancel", response_model=ResearchRunRead, operation_id="cancelResearchRun")
def cancel_run(db: DbSession, tenant: Tenant, run_id: uuid.UUID) -> ResearchRunRead:
    view = service.cancel_run(db, tenant, run_id)
    db.commit()
    return run_read(view)
