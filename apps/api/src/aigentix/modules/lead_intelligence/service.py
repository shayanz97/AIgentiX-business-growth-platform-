"""Research project use cases. Every query is scoped by the verified TenantContext."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.core.errors import NotFound
from aigentix.modules.lead_intelligence.models import ProjectStatus, ResearchProject
from aigentix.modules.lead_intelligence.schemas import ProjectCreate
from aigentix.platform.organizations.service import TenantContext


def create_project(db: Session, tenant: TenantContext, data: ProjectCreate) -> ResearchProject:
    project = ResearchProject(
        organization_id=tenant.organization_id,
        created_by_user_id=tenant.user.id,
        name=data.name,
        description=data.description,
        target_url=str(data.target_url) if data.target_url else None,
        status=ProjectStatus.DRAFT.value,
    )
    db.add(project)
    db.flush()
    return project


def list_projects(
    db: Session, tenant: TenantContext, *, limit: int, offset: int
) -> tuple[list[ResearchProject], int]:
    scope = ResearchProject.organization_id == tenant.organization_id
    total = db.scalar(select(func.count()).select_from(ResearchProject).where(scope)) or 0
    rows = db.scalars(
        select(ResearchProject)
        .where(scope)
        .order_by(ResearchProject.created_at.desc(), ResearchProject.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


def get_project(db: Session, tenant: TenantContext, project_id: uuid.UUID) -> ResearchProject:
    project = db.scalar(
        select(ResearchProject).where(
            ResearchProject.id == project_id,
            ResearchProject.organization_id == tenant.organization_id,
        )
    )
    if project is None:
        # Identical response for "missing" and "belongs to another tenant".
        raise NotFound("Project not found")
    return project
