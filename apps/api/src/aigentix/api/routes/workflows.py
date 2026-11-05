import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from aigentix.api.deps import DbSession, Pagination, Tenant
from aigentix.api.schemas import Page
from aigentix.platform.workflows import service
from aigentix.platform.workflows.models import WorkflowStatus

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID | None
    workflow_type: str
    status: WorkflowStatus
    metadata: dict[str, Any] = Field(validation_alias="run_metadata")
    error_type: str | None
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@router.get("", response_model=Page[WorkflowRunRead], operation_id="listWorkflowRuns")
def list_workflow_runs(
    db: DbSession,
    tenant: Tenant,
    page: Pagination,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[WorkflowRunRead]:
    items, total = service.list_runs(db, tenant, limit=page.limit, offset=page.offset, project_id=project_id)
    return Page[WorkflowRunRead](
        items=[WorkflowRunRead.model_validate(r) for r in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
