"""ORM → API schema mapping shared by the Lead Intelligence routes."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.models import Company, Evidence, Opportunity, ResearchSource
from aigentix.modules.lead_intelligence.schemas import (
    CompanyRead,
    EvidenceRead,
    EvidenceRef,
    OpportunityRead,
    ResearchRunRead,
    SourceRead,
    StepRead,
)
from aigentix.modules.lead_intelligence.services import companies as company_service
from aigentix.modules.lead_intelligence.services import opportunities as opportunity_service
from aigentix.modules.lead_intelligence.services.research import RunView
from aigentix.modules.lead_intelligence.workflows.constants import ENRICHMENT_STEPS, STEP_NAMES
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import WorkflowStatus


def company_reads(db: Session, companies: Sequence[Company]) -> list[CompanyRead]:
    org = companies[0].organization_id if companies else None
    latest = company_service.latest_runs(db, [c.id for c in companies], org) if org else {}
    out = []
    for c in companies:
        run = latest.get(c.id)
        out.append(
            CompanyRead(
                id=c.id,
                organization_id=c.organization_id,
                name=c.name,
                canonical_domain=c.canonical_domain,
                website_url=c.website_url,
                industry=c.industry,
                location=c.location,
                short_description=c.short_description,
                created_at=c.created_at,
                updated_at=c.updated_at,
                research_status=run.status if run else None,
                latest_run_id=run.run_id if run else None,
                last_researched_at=run.completed_at if run else None,
            )
        )
    return out


def run_read(view: RunView) -> ResearchRunRead:
    wf, rr = view.workflow, view.research
    state = (wf.run_metadata or {}).get("state", {})
    done = set(state.get("done_steps", []))
    durations = state.get("step_ms", {})
    status = WorkflowStatus(wf.status)
    steps = []
    names = [n for n, _ in ENRICHMENT_STEPS] if rr.kind == "enrichment" else STEP_NAMES
    for name in names:
        if name in done:
            step_state = "done"
        elif name == wf.current_step and status in (WorkflowStatus.RUNNING, WorkflowStatus.PENDING):
            step_state = "current"
        elif status in (WorkflowStatus.COMPLETED, WorkflowStatus.PARTIAL):
            step_state = "skipped"
        else:
            step_state = "pending"
        steps.append(StepRead(name=name, state=step_state, duration_ms=durations.get(name)))
    return ResearchRunRead(
        id=wf.id,
        company_id=rr.company_id,
        company_name=view.company.name,
        project_id=rr.project_id,
        kind=rr.kind,
        status=wf.status,
        current_step=wf.current_step,
        progress=wf.progress,
        steps=steps,
        attempts=wf.attempts,
        max_attempts=wf.max_attempts,
        next_attempt_at=wf.next_attempt_at,
        error_type=wf.error_type,
        error_message=wf.error_message,
        ai_status=rr.ai_status,
        audit_summary=rr.audit_summary,
        pages_fetched=rr.pages_fetched,
        input_tokens=wf.input_tokens,
        output_tokens=wf.output_tokens,
        estimated_cost_usd=float(wf.estimated_cost_usd),
        models_used=list(state.get("models_used", [])),
        prompt_versions=dict(state.get("prompt_versions", {})),
        cancel_requested=wf.cancel_requested_at is not None,
        created_at=wf.created_at,
        started_at=wf.started_at,
        completed_at=wf.completed_at,
    )


def source_read(s: ResearchSource) -> SourceRead:
    return SourceRead(
        id=s.id,
        source_url=s.source_url,
        page_title=s.page_title,
        page_category=s.page_category,
        http_status=s.http_status,
        retrieved_at=s.retrieved_at,
        extraction_status=s.extraction_status,
        extraction_error=s.extraction_error,
        content_hash=s.content_hash,
    )


def _labels_and_urls(db: Session, run_ids: set[uuid.UUID]) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """E-labels are positions within a run's evidence list (stable: ordered by creation time, then id)."""
    labels: dict[uuid.UUID, str] = {}
    if not run_ids:
        return labels, {}
    rows = db.execute(
        select(Evidence.id, Evidence.research_run_id)
        .where(Evidence.research_run_id.in_(run_ids))
        .order_by(Evidence.research_run_id, Evidence.created_at, Evidence.id)
    )
    counters: dict[uuid.UUID, int] = {}
    for evidence_id, run_id in rows:
        counters[run_id] = counters.get(run_id, 0) + 1
        labels[evidence_id] = f"E{counters[run_id]}"
    urls = {
        row[0]: row[1]
        for row in db.execute(
            select(ResearchSource.id, ResearchSource.source_url).where(ResearchSource.research_run_id.in_(run_ids))
        )
    }
    return labels, urls


def evidence_reads(db: Session, evidence: Sequence[Evidence]) -> list[EvidenceRead]:
    labels, urls = _labels_and_urls(db, {e.research_run_id for e in evidence})
    return [
        EvidenceRead(
            id=e.id,
            label=labels.get(e.id, "E?"),
            research_run_id=e.research_run_id,
            source_id=e.source_id,
            source_url=urls.get(e.source_id),
            observed_fact=e.observed_fact,
            supporting_excerpt=e.supporting_excerpt,
            evidence_type=e.evidence_type,
            basis=e.basis,
            confidence=e.confidence,
            origin=e.origin,
            created_at=e.created_at,
        )
        for e in evidence
    ]


def opportunity_reads(
    db: Session, tenant: TenantContext, opportunities: Sequence[Opportunity]
) -> list[OpportunityRead]:
    evidence = opportunity_service.evidence_for(db, tenant, [o.id for o in opportunities])
    labels, urls = _labels_and_urls(db, {o.research_run_id for o in opportunities})
    names = {
        row[0]: row[1]
        for row in db.execute(
            select(Company.id, Company.name).where(Company.id.in_({o.company_id for o in opportunities}))
        )
    }
    return [
        OpportunityRead(
            id=o.id,
            company_id=o.company_id,
            company_name=names.get(o.company_id, ""),
            research_run_id=o.research_run_id,
            title=o.title,
            observed_context=o.observed_context,
            problem_hypothesis=o.problem_hypothesis,
            proposed_ai_solution=o.proposed_ai_solution,
            estimated_business_impact=o.estimated_business_impact,
            implementation_complexity=o.implementation_complexity,
            confidence=o.confidence,
            assumptions=o.assumptions,
            validation_questions=o.validation_questions,
            next_step=o.next_step,
            quality_flags=o.quality_flags,
            status=o.status,
            reviewer_note=o.reviewer_note,
            reviewed_by_user_id=o.reviewed_by_user_id,
            reviewed_at=o.reviewed_at,
            evidence=[
                EvidenceRef(
                    id=e.id,
                    label=labels.get(e.id, "E?"),
                    evidence_type=e.evidence_type,
                    observed_fact=e.observed_fact,
                    supporting_excerpt=e.supporting_excerpt,
                    source_url=urls.get(e.source_id),
                    basis=e.basis,
                    confidence=e.confidence,
                )
                for e in evidence.get(o.id, [])
            ],
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
        for o in opportunities
    ]
