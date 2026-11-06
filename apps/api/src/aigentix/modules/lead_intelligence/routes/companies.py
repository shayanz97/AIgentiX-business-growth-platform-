import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.lead_intelligence.config import get_research_settings
from aigentix.modules.lead_intelligence.routes.serializers import (
    company_reads,
    evidence_reads,
    opportunity_reads,
    source_read,
)
from aigentix.modules.lead_intelligence.schemas import (
    CompanyCreate,
    CompanyCreateResult,
    CompanyDetail,
    CompanyImportRequest,
    CompanyImportResult,
    CompanyImportRow,
    CompanyRead,
    EvidenceRead,
    LinkResult,
    OpportunityRead,
    ProjectCompaniesAdd,
    SourceRead,
)
from aigentix.modules.lead_intelligence.services import companies as service
from aigentix.modules.lead_intelligence.services import research as research_service

router = APIRouter(tags=["companies"])
RunFilter = Annotated[uuid.UUID | None, Query(description="Research run; defaults to the latest finished run.")]


@router.get("/companies", response_model=Page[CompanyRead], operation_id="listCompanies")
def list_companies(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    q: Annotated[str | None, Query(max_length=100)] = None,
    project_id: uuid.UUID | None = None,
) -> Page[CompanyRead]:
    items, total = service.list_companies(
        db, tenant, limit=page.limit, offset=page.offset, query=q, project_id=project_id
    )
    return Page[CompanyRead](items=company_reads(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/companies",
    response_model=CompanyCreateResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCompany",
    responses={200: {"model": CompanyCreateResult, "description": "Existing company (deduplicated)"}},
)
def create_company(db: DbSession, tenant: Tenant, body: CompanyCreate, response: Response) -> CompanyCreateResult:
    company, created = service.create_company(
        db, tenant, website=body.website_url, name=body.name, project_id=body.project_id
    )
    db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return CompanyCreateResult(company=company_reads(db, [company])[0], created=created)


@router.post("/companies/import", response_model=CompanyImportResult, operation_id="importCompanies")
def import_companies(db: DbSession, tenant: Tenant, body: CompanyImportRequest) -> CompanyImportResult:
    settings = get_research_settings()
    report = service.import_companies(
        db,
        tenant,
        csv_text=body.csv_text,
        dry_run=body.dry_run,
        project_id=body.project_id,
        max_rows=settings.research_import_max_rows,
        max_bytes=settings.research_import_max_bytes,
    )
    if not body.dry_run:
        db.commit()
    return CompanyImportResult(
        dry_run=report.dry_run,
        total_rows=len(report.rows),
        new=report.count("new"),
        existing=report.count("existing"),
        duplicates=report.count("duplicate_in_file"),
        invalid=report.count("invalid"),
        created=report.created,
        linked_to_project=report.linked_to_project,
        rows=[CompanyImportRow(**vars(r)) for r in report.rows],
    )


@router.get("/companies/{company_id}", response_model=CompanyDetail, operation_id="getCompany")
def get_company(db: DbSession, tenant: Tenant, company_id: uuid.UUID) -> CompanyDetail:
    company = service.get_company(db, tenant, company_id)
    base = company_reads(db, [company])[0]
    run_id = research_service.latest_finished_run_id(db, tenant, company.id)
    profile = research_service.get_run(db, tenant, run_id).research.profile if run_id else None
    return CompanyDetail(**base.model_dump(), profile=profile, profile_run_id=run_id)


@router.get("/companies/{company_id}/sources", response_model=list[SourceRead], operation_id="listCompanySources")
def list_sources(db: DbSession, tenant: Tenant, company_id: uuid.UUID, run_id: RunFilter = None) -> list[SourceRead]:
    service.get_company(db, tenant, company_id)
    resolved = research_service.resolve_run_for_company(db, tenant, company_id, run_id)
    return [source_read(s) for s in research_service.sources_for_run(db, tenant, resolved)] if resolved else []


@router.get("/companies/{company_id}/evidence", response_model=list[EvidenceRead], operation_id="listCompanyEvidence")
def list_evidence(db: DbSession, tenant: Tenant, company_id: uuid.UUID, run_id: RunFilter = None) -> list[EvidenceRead]:
    service.get_company(db, tenant, company_id)
    resolved = research_service.resolve_run_for_company(db, tenant, company_id, run_id)
    return evidence_reads(db, research_service.evidence_for_run(db, tenant, resolved)) if resolved else []


@router.get(
    "/companies/{company_id}/opportunities",
    response_model=list[OpportunityRead],
    operation_id="listCompanyOpportunities",
)
def list_company_opportunities(
    db: DbSession, tenant: Tenant, company_id: uuid.UUID, run_id: RunFilter = None
) -> list[OpportunityRead]:
    service.get_company(db, tenant, company_id)
    resolved = research_service.resolve_run_for_company(db, tenant, company_id, run_id)
    if resolved is None:
        return []
    return opportunity_reads(db, tenant, research_service.opportunities_for_run(db, tenant, resolved))


@router.get("/projects/{project_id}/companies", response_model=Page[CompanyRead], operation_id="listProjectCompanies")
def list_project_companies(db: DbSession, tenant: Tenant, page: Pagination, project_id: uuid.UUID) -> Page[CompanyRead]:
    items, total = service.list_companies(db, tenant, limit=page.limit, offset=page.offset, project_id=project_id)
    return Page[CompanyRead](items=company_reads(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post("/projects/{project_id}/companies", response_model=LinkResult, operation_id="addProjectCompanies")
def add_project_companies(
    db: DbSession, tenant: Tenant, project_id: uuid.UUID, body: ProjectCompaniesAdd
) -> LinkResult:
    linked = service.link_companies(db, tenant, project_id, body.company_ids)
    db.commit()
    return LinkResult(linked=linked)
