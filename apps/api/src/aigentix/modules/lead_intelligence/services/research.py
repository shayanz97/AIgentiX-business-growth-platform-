"""Research runs: start (single or bulk), progress, results, cancellation, overview counts."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.lead_intelligence.models import (
    Company,
    Evidence,
    Opportunity,
    ResearchProjectCompany,
    ResearchRun,
    ResearchSource,
)
from aigentix.modules.lead_intelligence.services.projects import get_project
from aigentix.modules.lead_intelligence.workflows.constants import RESEARCH_WORKFLOW
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows import service as workflows
from aigentix.platform.workflows.models import ACTIVE_STATUSES, WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import default_registry

MAX_COMPANIES_PER_REQUEST = 100


@dataclass(frozen=True)
class RunView:
    research: ResearchRun
    workflow: WorkflowRun
    company: Company


@dataclass
class StartResult:
    started: list[RunView] = field(default_factory=list)
    skipped: list[tuple[uuid.UUID, str]] = field(default_factory=list)  # (company_id, reason)


def _active_run_exists(db: Session, company_id: uuid.UUID, kind: str = "research") -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(ResearchRun)
            .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
            .where(
                ResearchRun.company_id == company_id,
                ResearchRun.kind == kind,
                WorkflowRun.status.in_([s.value for s in ACTIVE_STATUSES]),
            )
        )
        or 0
    ) > 0


def start_research(
    db: Session,
    tenant: TenantContext,
    *,
    company_ids: Sequence[uuid.UUID] | None,
    project_id: uuid.UUID | None,
    max_attempts: int,
) -> StartResult:
    if project_id is not None:
        get_project(db, tenant, project_id)
    if company_ids:
        ids = list(dict.fromkeys(company_ids))
    elif project_id is not None:
        ids = list(
            db.scalars(
                select(ResearchProjectCompany.company_id).where(
                    ResearchProjectCompany.research_project_id == project_id,
                    ResearchProjectCompany.organization_id == tenant.organization_id,
                )
            )
        )
    else:
        raise InvalidInput("Provide company_ids or a project_id")
    if len(ids) > MAX_COMPANIES_PER_REQUEST:
        raise InvalidInput(f"At most {MAX_COMPANIES_PER_REQUEST} companies per request")

    result = StartResult()
    for company_id in ids:
        # Row lock serialises concurrent starts for the same company (no duplicate active jobs).
        company = db.scalar(
            select(Company)
            .where(Company.id == company_id, Company.organization_id == tenant.organization_id)
            .with_for_update()
        )
        if company is None:
            result.skipped.append((company_id, "not_found"))
            continue
        if company.website_url is None:
            result.skipped.append((company_id, "no_website"))
            continue
        if _active_run_exists(db, company.id):
            result.skipped.append((company_id, "already_running"))
            continue
        run = workflows.enqueue(
            db,
            tenant,
            workflow_type=RESEARCH_WORKFLOW,
            registry=default_registry(),
            metadata={"company_id": str(company.id)},
            max_attempts=max_attempts,
        )
        research = ResearchRun(
            workflow_run_id=run.id,
            organization_id=tenant.organization_id,
            company_id=company.id,
            project_id=project_id,
            requested_by_user_id=tenant.user.id,
        )
        db.add(research)
        db.flush()
        result.started.append(RunView(research=research, workflow=run, company=company))
    return result


def get_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> RunView:
    row = db.execute(
        select(ResearchRun, WorkflowRun, Company)
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .join(Company, Company.id == ResearchRun.company_id)
        .where(ResearchRun.workflow_run_id == run_id, ResearchRun.organization_id == tenant.organization_id)
    ).first()
    if row is None:
        raise NotFound("Research run not found")
    return RunView(research=row[0], workflow=row[1], company=row[2])


def list_runs(
    db: Session,
    tenant: TenantContext,
    *,
    limit: int,
    offset: int,
    company_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    kind: str | None = None,
) -> tuple[list[RunView], int]:
    conditions = [ResearchRun.organization_id == tenant.organization_id]
    if kind is not None:
        conditions.append(ResearchRun.kind == kind)
    if company_id is not None:
        conditions.append(ResearchRun.company_id == company_id)
    if project_id is not None:
        conditions.append(ResearchRun.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(ResearchRun).where(*conditions)) or 0
    rows = db.execute(
        select(ResearchRun, WorkflowRun, Company)
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .join(Company, Company.id == ResearchRun.company_id)
        .where(*conditions)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .limit(limit)
        .offset(offset)
    )
    return [RunView(research=r[0], workflow=r[1], company=r[2]) for r in rows], total


def cancel_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> RunView:
    view = get_run(db, tenant, run_id)
    workflows.request_cancel(db, view.workflow)
    db.refresh(view.workflow)
    return view


def latest_finished_run_id(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(ResearchRun.workflow_run_id)
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .where(
            ResearchRun.company_id == company_id,
            ResearchRun.organization_id == tenant.organization_id,
            ResearchRun.kind == "research",
            WorkflowRun.status.in_([WorkflowStatus.COMPLETED.value, WorkflowStatus.PARTIAL.value]),
        )
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )


def resolve_run_for_company(
    db: Session, tenant: TenantContext, company_id: uuid.UUID, run_id: uuid.UUID | None
) -> uuid.UUID | None:
    """The run whose results to show for a company: an explicit run (must belong to it) or the latest finished."""
    if run_id is None:
        return latest_finished_run_id(db, tenant, company_id)
    view = get_run(db, tenant, run_id)
    if view.research.company_id != company_id:
        raise NotFound("Research run not found")
    return run_id


def sources_for_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> list[ResearchSource]:
    return list(
        db.scalars(
            select(ResearchSource)
            .where(
                ResearchSource.research_run_id == run_id,
                ResearchSource.organization_id == tenant.organization_id,
            )
            .order_by(ResearchSource.retrieved_at, ResearchSource.source_url)
        )
    )


def evidence_for_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> list[Evidence]:
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.research_run_id == run_id, Evidence.organization_id == tenant.organization_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
    )


def opportunities_for_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> list[Opportunity]:
    return list(
        db.scalars(
            select(Opportunity)
            .where(Opportunity.research_run_id == run_id, Opportunity.organization_id == tenant.organization_id)
            .order_by(Opportunity.created_at, Opportunity.id)
        )
    )


@dataclass(frozen=True)
class Summary:
    total_companies: int
    research_runs: int
    companies_researched: int
    opportunities_found: int
    failed_runs: int
    active_runs: int
    opportunities_by_status: dict[str, int]


def summary(db: Session, tenant: TenantContext) -> Summary:
    org = tenant.organization_id
    run_base = (
        select(func.count())
        .select_from(ResearchRun)
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .where(ResearchRun.organization_id == org, ResearchRun.kind == "research")
    )
    by_status = dict(
        db.execute(
            select(Opportunity.status, func.count())
            .where(Opportunity.organization_id == org)
            .group_by(Opportunity.status)
        ).all()
    )
    return Summary(
        total_companies=db.scalar(select(func.count()).select_from(Company).where(Company.organization_id == org)) or 0,
        research_runs=db.scalar(run_base) or 0,
        companies_researched=db.scalar(
            select(func.count(distinct(ResearchRun.company_id)))
            .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
            .where(
                ResearchRun.organization_id == org,
                ResearchRun.kind == "research",
                WorkflowRun.status.in_([WorkflowStatus.COMPLETED.value, WorkflowStatus.PARTIAL.value]),
            )
        )
        or 0,
        opportunities_found=sum(by_status.values()),
        failed_runs=db.scalar(run_base.where(WorkflowRun.status == WorkflowStatus.FAILED.value)) or 0,
        active_runs=db.scalar(run_base.where(WorkflowRun.status.in_([s.value for s in ACTIVE_STATUSES]))) or 0,
        opportunities_by_status={str(k): int(v) for k, v in by_status.items()},
    )
