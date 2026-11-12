"""Lead scoring service: gather stored inputs, run the deterministic engine, keep an append-only history.

Scoring never fetches websites or calls a model; changing weights or profiles only needs a re-score.
A new snapshot is stored only when something that affects the score changed (inputs, profile config or version,
or scoring version); otherwise the latest snapshot is returned.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.lead_intelligence.domain.profiles import IcpConfig, ScoringConfig
from aigentix.modules.lead_intelligence.domain.scoring import (
    SCORING_VERSION,
    FitInput,
    IntentInput,
    OpportunityInput,
    ScoringInputs,
    SignalInput,
    score_lead,
)
from aigentix.modules.lead_intelligence.models import (
    BusinessSignal,
    BusinessSignalEvidence,
    BuyingIntentEvidence,
    BuyingIntentSignal,
    Company,
    Evidence,
    IcpProfile,
    LeadScore,
    LeadScoreEvidence,
    Opportunity,
    OpportunityEvidence,
    OpportunityStatus,
    ResearchProjectCompany,
    ResearchRun,
    ScoringProfile,
)
from aigentix.modules.lead_intelligence.services import profiles
from aigentix.modules.lead_intelligence.services.projects import get_project
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus

MAX_COMPANIES_PER_SCORE_REQUEST = 500
_FINISHED = (WorkflowStatus.COMPLETED.value, WorkflowStatus.PARTIAL.value)


@dataclass(frozen=True)
class RunStates:
    research_state: str
    research_run_id: uuid.UUID | None
    enrichment_state: str
    enrichment_run: ResearchRun | None  # latest finished enrichment (its results are used)
    latest_enrichment_run: ResearchRun | None = None  # newest enrichment in any state (for display)


def _latest(db: Session, org: uuid.UUID, company_id: uuid.UUID, kind: str) -> list[tuple[ResearchRun, str]]:
    rows = db.execute(
        select(ResearchRun, WorkflowRun.status)
        .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
        .where(ResearchRun.organization_id == org, ResearchRun.company_id == company_id, ResearchRun.kind == kind)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .limit(20)
    ).all()
    return [(r[0], str(r[1])) for r in rows]


def run_states(
    db: Session, org: uuid.UUID, company_id: uuid.UUID, current_enrichment: ResearchRun | None = None
) -> RunStates:
    research = _latest(db, org, company_id, "research")
    finished = next(((r, s) for r, s in research if s in _FINISHED), None)
    if finished:
        run, status = finished
        research_state = "completed" if status == "completed" and run.ai_status == "completed" else "ai_unavailable"
        research_run_id: uuid.UUID | None = run.workflow_run_id
    else:
        research_state = "failed" if any(s == "failed" for _, s in research) else "none"
        research_run_id = None
    enrichment = _latest(db, org, company_id, "enrichment")
    done = current_enrichment or next((r for r, s in enrichment if s in _FINISHED), None)
    if done is not None:
        enrichment_state = "completed"
    else:
        enrichment_state = "failed" if any(s == "failed" for _, s in enrichment) else "none"
    newest = current_enrichment or (enrichment[0][0] if enrichment else None)
    return RunStates(research_state, research_run_id, enrichment_state, done, newest)


def _links(db: Session, table: Any, key: Any, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    result: dict[uuid.UUID, list[str]] = {}
    if not ids:
        return result
    for owner, evidence_id in db.execute(select(key, table.evidence_id).where(key.in_(ids))):
        result.setdefault(owner, []).append(str(evidence_id))
    return {k: sorted(v) for k, v in result.items()}


def gather_inputs(
    db: Session, org: uuid.UUID, company: Company, reference: date, current_enrichment: ResearchRun | None = None
) -> tuple[ScoringInputs, RunStates]:
    states = run_states(db, org, company.id, current_enrichment)
    opportunities: list[OpportunityInput] = []
    if states.research_run_id is not None:
        opps = list(
            db.scalars(
                select(Opportunity)
                .where(
                    Opportunity.research_run_id == states.research_run_id,
                    Opportunity.organization_id == org,
                    Opportunity.status != OpportunityStatus.REJECTED.value,
                )
                .order_by(Opportunity.created_at, Opportunity.id)
            )
        )
        links = _links(db, OpportunityEvidence, OpportunityEvidence.opportunity_id, [o.id for o in opps])
        opportunities = [
            OpportunityInput(
                id=str(o.id),
                title=o.title,
                text=f"{o.title} {o.proposed_ai_solution} {o.observed_context}",
                confidence=o.confidence,
                flagged=bool(o.quality_flags),
                evidence_ids=links.get(o.id, []),
            )
            for o in opps
        ]
    signal_rows = list(
        db.scalars(
            select(BusinessSignal)
            .where(BusinessSignal.organization_id == org, BusinessSignal.company_id == company.id)
            .order_by(BusinessSignal.id)
        )
    )
    signal_links = _links(db, BusinessSignalEvidence, BusinessSignalEvidence.signal_id, [s.id for s in signal_rows])
    signals = [
        SignalInput(
            id=str(s.id),
            signal_type=s.signal_type,
            title=s.title,
            occurred_on=s.occurred_on,
            date_conflict=s.date_conflict,
            confidence=s.confidence,
            mention_count=s.mention_count,
            evidence_ids=signal_links.get(s.id, []),
            text=f"{s.title} {s.summary}",
        )
        for s in signal_rows
    ]
    intent_rows = list(
        db.scalars(
            select(BuyingIntentSignal)
            .where(BuyingIntentSignal.organization_id == org, BuyingIntentSignal.company_id == company.id)
            .order_by(BuyingIntentSignal.id)
        )
    )
    intent_links = _links(db, BuyingIntentEvidence, BuyingIntentEvidence.intent_id, [i.id for i in intent_rows])
    intents = [
        IntentInput(
            id=str(i.id),
            strength=i.strength,
            source_type=i.source_type,
            title=i.title,
            observed_on=i.observed_on,
            deadline_on=i.deadline_on,
            reliability=i.reliability,
            solution_category=i.solution_category,
            evidence_ids=intent_links.get(i.id, []),
        )
        for i in intent_rows
    ]
    fit = FitInput()
    if states.enrichment_run is not None:
        facts = (states.enrichment_run.profile or {}).get("firmographics") or {}
        fit = FitInput(
            country=facts.get("country"),
            country_conflict=bool(facts.get("country_conflict")),
            country_evidence_ids=list(facts.get("country_evidence_ids", [])),
            industry_texts=list(facts.get("industry_texts", [])),
            industry_evidence_ids=list(facts.get("industry_evidence_ids", [])),
            employees=facts.get("employees"),
            size_conflict=bool(facts.get("size_conflict")),
            size_evidence_ids=list(facts.get("size_evidence_ids", [])),
        )
    inputs = ScoringInputs(
        research_state=states.research_state,
        enrichment_state=states.enrichment_state,
        opportunities=opportunities,
        signals=signals,
        intents=intents,
        fit=fit,
        reference=reference,
    )
    return inputs, states


def score_company(
    db: Session,
    org: uuid.UUID,
    company: Company,
    *,
    scoring_profile: ScoringProfile,
    icp_profile: IcpProfile,
    reference: date,
    user_id: uuid.UUID | None,
    current_enrichment: ResearchRun | None = None,
) -> tuple[LeadScore, bool]:
    """Compute and store a snapshot. Returns (score, created); an unchanged result returns the latest one.

    `current_enrichment` lets the running enrichment workflow score its own (not yet finished) results."""
    inputs, states = gather_inputs(db, org, company, reference, current_enrichment)
    icp = IcpConfig.model_validate(icp_profile.config)
    config = ScoringConfig.model_validate(scoring_profile.config)
    result = score_lead(inputs, icp, config)
    latest = db.scalar(
        select(LeadScore)
        .where(
            LeadScore.organization_id == org,
            LeadScore.company_id == company.id,
            LeadScore.scoring_profile_id == scoring_profile.id,
            LeadScore.icp_profile_id == icp_profile.id,
        )
        .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        .limit(1)
    )
    if (
        latest is not None
        and latest.inputs_hash == result.inputs_hash
        and latest.scoring_profile_version == scoring_profile.version
        and latest.icp_profile_version == icp_profile.version
    ):
        return latest, False
    score = LeadScore(
        organization_id=org,
        company_id=company.id,
        scoring_profile_id=scoring_profile.id,
        scoring_profile_version=scoring_profile.version,
        icp_profile_id=icp_profile.id,
        icp_profile_version=icp_profile.version,
        scoring_version=SCORING_VERSION,
        score_low=result.score_low,
        score_high=result.score_high,
        coverage=result.coverage,
        provisional=result.provisional,
        confidence_level=result.confidence_level,
        priority_band=result.priority_band,
        fit_excluded=result.fit_excluded,
        intent_status=result.intent_status,
        latest_trigger_on=result.latest_trigger_on,
        opportunity_categories=result.opportunity_categories,
        components=result.components_json(),
        explanation=result.explanation,
        next_step=result.next_step,
        next_step_text=result.next_step_text,
        inputs_hash=result.inputs_hash,
        profile_snapshot={
            "scoring_profile": {"name": scoring_profile.name, "config": scoring_profile.config},
            "icp_profile": {"name": icp_profile.name, "config": icp_profile.config},
            "reference_date": reference.isoformat(),
            "exclusion_reasons": result.exclusion_reasons,
        },
        research_run_id=states.research_run_id,
        enrichment_run_id=states.enrichment_run.workflow_run_id if states.enrichment_run else None,
        created_by_user_id=user_id,
    )
    db.add(score)
    db.flush()
    existing = {
        e
        for e in db.scalars(
            select(Evidence.id).where(
                Evidence.organization_id == org, Evidence.id.in_([uuid.UUID(e) for e in result.evidence_ids])
            )
        )
    }
    db.add_all(LeadScoreEvidence(lead_score_id=score.id, evidence_id=e, organization_id=org) for e in existing)
    db.flush()
    return score, True


def score_for_tenant(
    db: Session,
    tenant: TenantContext,
    company_ids: Sequence[uuid.UUID],
    *,
    scoring_profile_id: uuid.UUID | None,
    icp_profile_id: uuid.UUID | None,
    reference: date,
) -> list[tuple[LeadScore, bool]]:
    if len(company_ids) > MAX_COMPANIES_PER_SCORE_REQUEST:
        raise InvalidInput(f"At most {MAX_COMPANIES_PER_SCORE_REQUEST} companies per scoring request")
    scoring = profiles.resolve(db, tenant, ScoringProfile, scoring_profile_id)
    icp = profiles.resolve(db, tenant, IcpProfile, icp_profile_id)
    companies = list(
        db.scalars(
            select(Company)
            .where(Company.organization_id == tenant.organization_id, Company.id.in_(list(company_ids)))
            .order_by(Company.id)
        )
    )
    return [
        score_company(
            db,
            tenant.organization_id,
            c,
            scoring_profile=scoring,
            icp_profile=icp,
            reference=reference,
            user_id=tenant.user.id,
        )
        for c in companies
    ]


def project_company_ids(db: Session, tenant: TenantContext, project_id: uuid.UUID) -> list[uuid.UUID]:
    get_project(db, tenant, project_id)
    return list(
        db.scalars(
            select(ResearchProjectCompany.company_id).where(
                ResearchProjectCompany.research_project_id == project_id,
                ResearchProjectCompany.organization_id == tenant.organization_id,
            )
        )
    )


def get_company(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> Company:
    company = db.scalar(
        select(Company).where(Company.id == company_id, Company.organization_id == tenant.organization_id)
    )
    if company is None:
        raise NotFound("Company not found")
    return company


def score_history(
    db: Session, tenant: TenantContext, company_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[LeadScore], int]:
    from sqlalchemy import func

    get_company(db, tenant, company_id)
    condition = (LeadScore.organization_id == tenant.organization_id, LeadScore.company_id == company_id)
    total = db.scalar(select(func.count()).select_from(LeadScore).where(*condition)) or 0
    rows = list(
        db.scalars(
            select(LeadScore)
            .where(*condition)
            .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def score_evidence_ids(
    db: Session, tenant: TenantContext, score_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    result: dict[uuid.UUID, list[str]] = {}
    if not score_ids:
        return result
    for score_id, evidence_id in db.execute(
        select(LeadScoreEvidence.lead_score_id, LeadScoreEvidence.evidence_id).where(
            LeadScoreEvidence.organization_id == tenant.organization_id,
            LeadScoreEvidence.lead_score_id.in_(list(score_ids)),
        )
    ):
        result.setdefault(score_id, []).append(str(evidence_id))
    return {k: sorted(v) for k, v in result.items()}
