"""Companies: creation with organization-level deduplication, CSV import, project links, listing."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.lead_intelligence.domain.csv_import import CsvFormatError, parse_company_csv
from aigentix.modules.lead_intelligence.domain.domains import InvalidWebsite, parse_website
from aigentix.modules.lead_intelligence.models import Company, ResearchProjectCompany, ResearchRun
from aigentix.modules.lead_intelligence.services.projects import get_project
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import WorkflowRun

MAX_NAME_LENGTH = 200


@dataclass(frozen=True)
class LatestRun:
    run_id: uuid.UUID
    status: str
    completed_at: object
    created_at: object


def get_company(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> Company:
    company = db.scalar(
        select(Company).where(Company.id == company_id, Company.organization_id == tenant.organization_id)
    )
    if company is None:
        raise NotFound("Company not found")
    return company


def _find_existing(db: Session, tenant: TenantContext, *, domain: str | None, name: str) -> Company | None:
    query = select(Company).where(Company.organization_id == tenant.organization_id)
    if domain:
        query = query.where(Company.canonical_domain == domain)
    else:
        query = query.where(Company.canonical_domain.is_(None), func.lower(Company.name) == name.lower())
    return db.scalar(query)


def link_companies(db: Session, tenant: TenantContext, project_id: uuid.UUID, company_ids: Sequence[uuid.UUID]) -> int:
    """Link companies (all verified to belong to the tenant) to a tenant project. Idempotent."""
    get_project(db, tenant, project_id)
    ids = list(dict.fromkeys(company_ids))
    if not ids:
        return 0
    owned = set(
        db.scalars(select(Company.id).where(Company.organization_id == tenant.organization_id, Company.id.in_(ids)))
    )
    if missing := [str(i) for i in ids if i not in owned]:
        raise NotFound("Company not found", details={"company_ids": missing})
    rows = [
        {"research_project_id": project_id, "company_id": cid, "organization_id": tenant.organization_id} for cid in ids
    ]
    statement = (
        pg_insert(ResearchProjectCompany)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(ResearchProjectCompany.company_id)
    )
    # Count RETURNING rows: rowcount is not reliable for multi-row inserts.
    return len(db.execute(statement).all())


def create_company(
    db: Session,
    tenant: TenantContext,
    *,
    website: str | None,
    name: str | None,
    project_id: uuid.UUID | None = None,
) -> tuple[Company, bool]:
    """Create a company or return the existing one with the same domain (or same name when no website)."""
    clean_name = (name or "").strip()[:MAX_NAME_LENGTH]
    domain = url = None
    if website:
        try:
            parsed = parse_website(website)
        except InvalidWebsite as exc:
            raise InvalidInput(str(exc), details={"field": "website_url"}) from exc
        domain, url = parsed.canonical_domain, parsed.url
    if not clean_name and not domain:
        raise InvalidInput("Provide a website or a company name")
    clean_name = clean_name or str(domain)
    if project_id is not None:
        get_project(db, tenant, project_id)

    company = _find_existing(db, tenant, domain=domain, name=clean_name)
    created = company is None
    if company is None:
        company = Company(
            organization_id=tenant.organization_id,
            name=clean_name,
            canonical_domain=domain,
            website_url=url,
            created_by_user_id=tenant.user.id,
        )
        try:
            with db.begin_nested():
                db.add(company)
        except IntegrityError:  # concurrent insert of the same domain
            company = _find_existing(db, tenant, domain=domain, name=clean_name)
            created = False
            if company is None:
                raise
    if project_id is not None:
        link_companies(db, tenant, project_id, [company.id])
    return company, created


def latest_runs(
    db: Session, company_ids: Sequence[uuid.UUID], organization_id: uuid.UUID
) -> dict[uuid.UUID, LatestRun]:
    if not company_ids:
        return {}
    rows = db.execute(
        select(
            ResearchRun.company_id,
            WorkflowRun.id,
            WorkflowRun.status,
            WorkflowRun.completed_at,
            WorkflowRun.created_at,
        )
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .where(ResearchRun.company_id.in_(company_ids), ResearchRun.organization_id == organization_id)
        .order_by(ResearchRun.company_id, WorkflowRun.created_at.desc())
        .ext(distinct_on(ResearchRun.company_id))
    )
    return {r[0]: LatestRun(run_id=r[1], status=r[2], completed_at=r[3], created_at=r[4]) for r in rows}


def list_companies(
    db: Session,
    tenant: TenantContext,
    *,
    limit: int,
    offset: int,
    query: str | None = None,
    project_id: uuid.UUID | None = None,
) -> tuple[list[Company], int]:
    conditions = [Company.organization_id == tenant.organization_id]
    if query:
        escaped = query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.append(
            or_(
                func.lower(Company.name).like(pattern, escape="\\"), Company.canonical_domain.like(pattern, escape="\\")
            )
        )
    base = select(Company).where(*conditions)
    if project_id is not None:
        get_project(db, tenant, project_id)
        base = base.join(
            ResearchProjectCompany,
            (ResearchProjectCompany.company_id == Company.id)
            & (ResearchProjectCompany.research_project_id == project_id),
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Company.created_at.desc(), Company.id).limit(limit).offset(offset))
    return list(rows), total


# --- CSV import -----------------------------------------------------------------------------------


@dataclass
class ImportRowResult:
    line: int
    name: str
    website_url: str | None
    canonical_domain: str | None
    status: str  # new | existing | duplicate_in_file | invalid
    errors: list[str] = field(default_factory=list)
    company_id: uuid.UUID | None = None


@dataclass
class ImportReport:
    dry_run: bool
    rows: list[ImportRowResult]
    created: int = 0
    linked_to_project: int = 0

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)


def import_companies(
    db: Session,
    tenant: TenantContext,
    *,
    csv_text: str,
    dry_run: bool,
    project_id: uuid.UUID | None,
    max_rows: int,
    max_bytes: int,
) -> ImportReport:
    try:
        parsed = parse_company_csv(csv_text, max_rows=max_rows, max_bytes=max_bytes)
    except CsvFormatError as exc:
        raise InvalidInput(str(exc)) from exc
    if project_id is not None:
        get_project(db, tenant, project_id)

    domains = [r.canonical_domain for r in parsed if r.valid and r.canonical_domain]
    names = [r.name.lower() for r in parsed if r.valid and not r.canonical_domain]
    existing_by_domain = {
        c.canonical_domain: c
        for c in db.scalars(
            select(Company).where(
                Company.organization_id == tenant.organization_id, Company.canonical_domain.in_(domains)
            )
        )
    }
    existing_by_name = {
        c.name.lower(): c
        for c in db.scalars(
            select(Company).where(
                Company.organization_id == tenant.organization_id,
                Company.canonical_domain.is_(None),
                func.lower(Company.name).in_(names),
            )
        )
    }

    report = ImportReport(dry_run=dry_run, rows=[])
    for row in parsed:
        result = ImportRowResult(
            line=row.line,
            name=row.name,
            website_url=row.website_url,
            canonical_domain=row.canonical_domain,
            status="new",
            errors=list(row.errors),
        )
        if row.errors:
            result.status = "invalid"
        elif row.duplicate_of_line is not None:
            result.status = "duplicate_in_file"
            result.errors.append(f"Same company as line {row.duplicate_of_line}")
        else:
            existing = (
                existing_by_domain.get(row.canonical_domain)
                if row.canonical_domain
                else existing_by_name.get(row.name.lower())
            )
            if existing is not None:
                result.status, result.company_id = "existing", existing.id
        report.rows.append(result)

    if dry_run:
        return report
    for result in report.rows:
        if result.status != "new":
            continue
        company, created = create_company(db, tenant, website=result.website_url, name=result.name)
        result.company_id = company.id
        report.created += int(created)
    if project_id is not None:
        ids = [r.company_id for r in report.rows if r.company_id is not None]
        report.linked_to_project = link_companies(db, tenant, project_id, ids)
    return report
