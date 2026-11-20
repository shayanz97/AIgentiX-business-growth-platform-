"""Proposal routes (AI draft, revisions, status, Markdown export) and the service catalogue."""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy.orm import Session

from aigentix.api.deps import DbSession, Tenant
from aigentix.modules.sales.models import SalesProposal, SalesProposalRevision
from aigentix.modules.sales.routes.briefs import workflow_info
from aigentix.modules.sales.schemas_ai import (
    OfferingCreate,
    OfferingRead,
    OfferingUpdate,
    ProposalCreate,
    ProposalDetail,
    ProposalRead,
    ProposalSection,
    ProposalUpdate,
    RevisionRead,
)
from aigentix.modules.sales.services import offerings as offering_service
from aigentix.modules.sales.services import proposals as service
from aigentix.modules.sales.services.briefs import runs_by_id
from aigentix.platform.organizations.service import TenantContext

router = APIRouter()


def _fields(db: Session, tenant: TenantContext, proposals: Sequence[SalesProposal]) -> list[dict[str, Any]]:
    runs = runs_by_id(db, tenant, [p.workflow_run_id for p in proposals])
    result = []
    for p in proposals:
        run = runs.get(p.workflow_run_id) if p.workflow_run_id else None
        proposal_status, message = service.effective_proposal_status(p, run)
        result.append(
            {
                "id": p.id,
                "sales_opportunity_id": p.sales_opportunity_id,
                "brief_id": p.brief_id,
                "title": p.title,
                "status": proposal_status,
                "current_revision": p.current_revision,
                "sent_at": p.sent_at,
                "message": message,
                "created_by_user_id": p.created_by_user_id,
                "version": p.version,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
                "workflow": workflow_info(run),
            }
        )
    return result


def _sections(revision: SalesProposalRevision) -> list[ProposalSection]:
    return [ProposalSection.model_validate(s) for s in revision.sections]


def _detail(db: Session, tenant: TenantContext, proposal: SalesProposal) -> ProposalDetail:
    revision = service.current_revision(db, proposal)
    return ProposalDetail(
        **_fields(db, tenant, [proposal])[0],
        sections=_sections(revision) if revision else [],
        assumptions=list(revision.assumptions) if revision else [],
        quality_flags=list(revision.quality_flags) if revision else [],
        revision_origin=revision.origin if revision else None,
        model=revision.model if revision else None,
        generation_version=revision.generation_version if revision else None,
    )


@router.post(
    "/sales/opportunities/{deal_id}/proposals",
    response_model=ProposalRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createSalesProposal",
    tags=["sales-ai"],
)
def create_proposal(db: DbSession, tenant: Tenant, deal_id: uuid.UUID, body: ProposalCreate) -> ProposalRead:
    proposal = service.request_proposal(db, tenant, deal_id, brief_id=body.brief_id, title=body.title)
    db.commit()
    return ProposalRead(**_fields(db, tenant, [proposal])[0])


@router.get(
    "/sales/opportunities/{deal_id}/proposals",
    response_model=list[ProposalRead],
    operation_id="listSalesProposals",
    tags=["sales-ai"],
)
def list_proposals(db: DbSession, tenant: Tenant, deal_id: uuid.UUID) -> list[ProposalRead]:
    return [ProposalRead(**f) for f in _fields(db, tenant, service.list_proposals(db, tenant, deal_id))]


@router.get(
    "/sales/proposals/{proposal_id}", response_model=ProposalDetail, operation_id="getSalesProposal", tags=["sales-ai"]
)
def get_proposal(db: DbSession, tenant: Tenant, proposal_id: uuid.UUID) -> ProposalDetail:
    return _detail(db, tenant, service.get_proposal(db, tenant, proposal_id))


@router.patch(
    "/sales/proposals/{proposal_id}",
    response_model=ProposalDetail,
    operation_id="updateSalesProposal",
    tags=["sales-ai"],
)
def update_proposal(db: DbSession, tenant: Tenant, proposal_id: uuid.UUID, body: ProposalUpdate) -> ProposalDetail:
    proposal = service.update_proposal(
        db,
        tenant,
        proposal_id,
        expected_version=body.expected_version,
        title=body.title,
        sections=[s.model_dump() for s in body.sections] if body.sections is not None else None,
        assumptions=body.assumptions,
        note=body.note,
        status=body.status,
        sent_at=body.sent_at,
    )
    db.commit()
    return _detail(db, tenant, proposal)


@router.get(
    "/sales/proposals/{proposal_id}/revisions",
    response_model=list[RevisionRead],
    operation_id="listSalesProposalRevisions",
    tags=["sales-ai"],
)
def list_revisions(db: DbSession, tenant: Tenant, proposal_id: uuid.UUID) -> list[RevisionRead]:
    return [
        RevisionRead(
            id=r.id,
            revision=r.revision,
            origin=r.origin,
            sections=_sections(r),
            assumptions=list(r.assumptions),
            quality_flags=list(r.quality_flags),
            source_evidence_ids=[uuid.UUID(i) for i in r.source_evidence_ids],
            model=r.model,
            generation_version=r.generation_version,
            note=r.note,
            created_by_user_id=r.created_by_user_id,
            created_at=r.created_at,
        )
        for r in service.list_revisions(db, tenant, proposal_id)
    ]


@router.get(
    "/sales/proposals/{proposal_id}/export",
    operation_id="exportSalesProposal",
    tags=["sales-ai"],
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}}, "description": "Markdown download of the current revision"}},
)
def export_proposal(db: DbSession, tenant: Tenant, proposal_id: uuid.UUID) -> Response:
    export = service.export_markdown(db, tenant, proposal_id)
    return Response(
        content=export.content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- service catalogue ------------------------------------------------------------------------------------------


@router.get("/sales/services", response_model=list[OfferingRead], operation_id="listSalesServices", tags=["sales-ai"])
def list_services(db: DbSession, tenant: Tenant, active: bool | None = None) -> list[OfferingRead]:
    return [OfferingRead.model_validate(o) for o in offering_service.list_offerings(db, tenant, active=active)]


@router.post(
    "/sales/services",
    response_model=OfferingRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSalesService",
    tags=["sales-ai"],
)
def create_service(db: DbSession, tenant: Tenant, body: OfferingCreate) -> OfferingRead:
    offering = offering_service.create_offering(db, tenant, **body.model_dump())
    db.commit()
    return OfferingRead.model_validate(offering)


@router.patch(
    "/sales/services/{offering_id}", response_model=OfferingRead, operation_id="updateSalesService", tags=["sales-ai"]
)
def update_service(db: DbSession, tenant: Tenant, offering_id: uuid.UUID, body: OfferingUpdate) -> OfferingRead:
    offering = offering_service.update_offering(db, tenant, offering_id, body.model_dump(exclude_unset=True))
    db.commit()
    return OfferingRead.model_validate(offering)
