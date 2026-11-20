"""Sales intelligence brief routes: request generation, list, read, human edit / approve."""

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from aigentix.api.deps import DbSession, Tenant
from aigentix.modules.sales.models import SalesBrief
from aigentix.modules.sales.schemas_ai import BriefRead, BriefUpdate, WorkflowInfo
from aigentix.modules.sales.services import briefs as service
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import WorkflowRun

router = APIRouter()


def workflow_info(run: WorkflowRun | None) -> WorkflowInfo | None:
    if run is None:
        return None
    return WorkflowInfo(
        id=run.id,
        status=run.status,
        progress=run.progress,
        current_step=run.current_step,
        error_message=run.error_message,
        attempts=run.attempts,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        estimated_cost_usd=run.estimated_cost_usd,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def brief_reads(db: Session, tenant: TenantContext, briefs: Sequence[SalesBrief]) -> list[BriefRead]:
    runs = service.runs_by_id(db, tenant, [b.workflow_run_id for b in briefs])
    result = []
    for b in briefs:
        run = runs.get(b.workflow_run_id) if b.workflow_run_id else None
        brief_status, message = service.effective_brief_status(b, run)
        result.append(
            BriefRead(
                id=b.id,
                sales_opportunity_id=b.sales_opportunity_id,
                status=brief_status,
                content=b.content,
                edited_content=b.edited_content,
                source_evidence_ids=[uuid.UUID(i) for i in b.source_evidence_ids],
                quality_flags=list(b.quality_flags),
                generation_version=b.generation_version,
                model=b.model,
                message=message,
                created_by_user_id=b.created_by_user_id,
                edited_by_user_id=b.edited_by_user_id,
                version=b.version,
                created_at=b.created_at,
                updated_at=b.updated_at,
                workflow=workflow_info(run),
            )
        )
    return result


@router.post(
    "/sales/opportunities/{deal_id}/briefs",
    response_model=BriefRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createSalesBrief",
    tags=["sales-ai"],
)
def create_brief(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> BriefRead:
    brief = service.request_brief(db, tenant, deal_id)
    db.commit()
    return brief_reads(db, tenant, [brief])[0]


@router.get(
    "/sales/opportunities/{deal_id}/briefs",
    response_model=list[BriefRead],
    operation_id="listSalesBriefs",
    tags=["sales-ai"],
)
def list_briefs(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> list[BriefRead]:
    return brief_reads(db, tenant, service.list_briefs(db, tenant, deal_id))


@router.get("/sales/briefs/{brief_id}", response_model=BriefRead, operation_id="getSalesBrief", tags=["sales-ai"])
def get_brief(db: DbSession, tenant: Tenant, brief_id: uuid.UUID) -> BriefRead:
    return brief_reads(db, tenant, [service.get_brief(db, tenant, brief_id)])[0]


@router.patch("/sales/briefs/{brief_id}", response_model=BriefRead, operation_id="updateSalesBrief", tags=["sales-ai"])
def update_brief(db: DbSession, tenant: Tenant, brief_id: uuid.UUID, body: BriefUpdate) -> BriefRead:
    brief = service.update_brief(
        db,
        tenant,
        brief_id,
        expected_version=body.expected_version,
        edited_content=body.edited_content.model_dump(exclude_none=True) if body.edited_content else None,
        status=body.status,
    )
    db.commit()
    return brief_reads(db, tenant, [brief])[0]
