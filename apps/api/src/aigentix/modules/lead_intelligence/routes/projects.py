import uuid

from fastapi import APIRouter, status

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.modules.lead_intelligence.schemas import ProjectCreate, ProjectRead
from aigentix.modules.lead_intelligence.services import projects as service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=Page[ProjectRead], operation_id="listProjects")
def list_projects(db: DbSession, tenant: Tenant, page: Pagination) -> Page[ProjectRead]:
    items, total = service.list_projects(db, tenant, limit=page.limit, offset=page.offset)
    return Page[ProjectRead](
        items=[ProjectRead.model_validate(p) for p in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, operation_id="createProject")
def create_project(db: DbSession, tenant: Tenant, body: ProjectCreate) -> ProjectRead:
    project = service.create_project(db, tenant, body)
    db.commit()
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead, operation_id="getProject")
def get_project(db: DbSession, tenant: Tenant, project_id: uuid.UUID) -> ProjectRead:
    return ProjectRead.model_validate(service.get_project(db, tenant, project_id))
