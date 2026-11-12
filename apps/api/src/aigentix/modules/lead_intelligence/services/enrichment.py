"""Enrichment runs (growth triggers, buying intent, score), signal and intent queries, first-party intent."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput
from aigentix.modules.lead_intelligence.domain.intent import first_party_key
from aigentix.modules.lead_intelligence.domain.profiles import SOLUTION_CATEGORIES
from aigentix.modules.lead_intelligence.models import (
    BusinessSignal,
    BusinessSignalEvidence,
    BuyingIntentEvidence,
    BuyingIntentSignal,
    Company,
    IntentSourceType,
    IntentStrength,
    LeadScore,
    ResearchProjectCompany,
    ResearchRun,
)
from aigentix.modules.lead_intelligence.services.projects import get_project
from aigentix.modules.lead_intelligence.services.research import MAX_COMPANIES_PER_REQUEST, RunView, _active_run_exists
from aigentix.modules.lead_intelligence.services.scoring import get_company, score_for_tenant
from aigentix.modules.lead_intelligence.workflows.constants import ENRICHMENT_WORKFLOW
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows import service as workflows
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import default_registry


@dataclass
class EnrichmentStart:
    started: list[RunView] = field(default_factory=list)
    rescored: list[tuple[uuid.UUID, LeadScore]] = field(default_factory=list)  # fresh enrichment reused
    skipped: list[tuple[uuid.UUID, str]] = field(default_factory=list)


def _fresh_enrichment(db: Session, company_id: uuid.UUID, cache_hours: float) -> bool:
    if cache_hours <= 0:
        return False
    since = utcnow() - timedelta(hours=cache_hours)
    return (
        db.scalar(
            select(func.count())
            .select_from(ResearchRun)
            .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
            .where(
                ResearchRun.company_id == company_id,
                ResearchRun.kind == "enrichment",
                WorkflowRun.status.in_([WorkflowStatus.COMPLETED.value, WorkflowStatus.PARTIAL.value]),
                WorkflowRun.completed_at >= since,
            )
        )
        or 0
    ) > 0


def start_enrichment(
    db: Session,
    tenant: TenantContext,
    *,
    company_ids: Sequence[uuid.UUID] | None,
    project_id: uuid.UUID | None,
    force: bool,
    max_attempts: int,
    cache_hours: float,
    reference: date,
) -> EnrichmentStart:
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

    result = EnrichmentStart()
    for company_id in ids:
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
        if _active_run_exists(db, company.id, "enrichment"):
            result.skipped.append((company_id, "already_running"))
            continue
        if not force and _fresh_enrichment(db, company.id, cache_hours):
            # Recent results are reused: re-score without re-crawling.
            [(score, _)] = score_for_tenant(
                db, tenant, [company.id], scoring_profile_id=None, icp_profile_id=None, reference=reference
            )
            result.rescored.append((company.id, score))
            continue
        run = workflows.enqueue(
            db,
            tenant,
            workflow_type=ENRICHMENT_WORKFLOW,
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
            kind="enrichment",
        )
        db.add(research)
        db.flush()
        result.started.append(RunView(research=research, workflow=run, company=company))
    return result


def evidence_links(db: Session, table: type, key: str, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    column = getattr(table, key)
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for owner, evidence_id in db.execute(select(column, table.evidence_id).where(column.in_(list(ids)))):  # type: ignore[attr-defined]
            result.setdefault(owner, []).append(evidence_id)
    return result


def signals_for_company(
    db: Session, tenant: TenantContext, company_id: uuid.UUID, enrichment_run_id: uuid.UUID | None
) -> list[BusinessSignal]:
    """Current signals: those observed by the latest finished enrichment run (the ones that are scored)."""
    get_company(db, tenant, company_id)
    if enrichment_run_id is None:
        return []
    return list(
        db.scalars(
            select(BusinessSignal)
            .where(
                BusinessSignal.organization_id == tenant.organization_id,
                BusinessSignal.company_id == company_id,
                BusinessSignal.enrichment_run_id == enrichment_run_id,
            )
            .order_by(BusinessSignal.occurred_on.desc().nulls_last(), BusinessSignal.signal_type, BusinessSignal.id)
        )
    )


def signal_evidence(db: Session, signals: Sequence[BusinessSignal]) -> dict[uuid.UUID, list[uuid.UUID]]:
    return evidence_links(db, BusinessSignalEvidence, "signal_id", [s.id for s in signals])


def intents_for_company(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> list[BuyingIntentSignal]:
    get_company(db, tenant, company_id)
    return list(
        db.scalars(
            select(BuyingIntentSignal)
            .where(
                BuyingIntentSignal.organization_id == tenant.organization_id,
                BuyingIntentSignal.company_id == company_id,
            )
            .order_by(BuyingIntentSignal.created_at.desc(), BuyingIntentSignal.id)
        )
    )


def intent_evidence(db: Session, intents: Sequence[BuyingIntentSignal]) -> dict[uuid.UUID, list[uuid.UUID]]:
    return evidence_links(db, BuyingIntentEvidence, "intent_id", [i.id for i in intents])


def record_first_party_intent(
    db: Session,
    tenant: TenantContext,
    company_id: uuid.UUID,
    *,
    channel: str,
    received_on: date,
    summary: str,
    solution_category: str | None,
    reference: date,
) -> tuple[BuyingIntentSignal, bool]:
    """A real inquiry the organization received from this company (entered by a member). Never auto-created."""
    company = get_company(db, tenant, company_id)
    if received_on > reference:
        raise InvalidInput("received_on cannot be in the future")
    if solution_category is not None and solution_category not in SOLUTION_CATEGORIES:
        raise InvalidInput("Unknown solution category")
    key = first_party_key(channel, received_on, summary)
    # Insert-or-ignore: concurrent identical submissions cannot race into a constraint error.
    new_id = db.scalar(
        insert(BuyingIntentSignal)
        .values(
            id=uuid.uuid4(),
            organization_id=tenant.organization_id,
            company_id=company.id,
            strength=IntentStrength.EXPLICIT.value,
            source_type=IntentSourceType.FIRST_PARTY.value,
            title=f"Inbound inquiry via {channel.replace('_', ' ')}",
            summary=summary.strip(),
            solution_category=solution_category,
            observed_on=received_on,
            reliability="high",
            dedupe_key=key,
            recorded_by_user_id=tenant.user.id,
            created_at=utcnow(),
            last_seen_at=utcnow(),
        )
        .on_conflict_do_nothing(constraint="uq_buying_intent_signals_dedupe")
        .returning(BuyingIntentSignal.id)
    )
    row = db.scalar(
        select(BuyingIntentSignal).where(
            BuyingIntentSignal.organization_id == tenant.organization_id,
            BuyingIntentSignal.company_id == company.id,
            BuyingIntentSignal.dedupe_key == key,
        )
    )
    if row is None:  # pragma: no cover - the row exists after insert-or-ignore
        raise InvalidInput("Could not record the inquiry")
    return row, new_id is not None
