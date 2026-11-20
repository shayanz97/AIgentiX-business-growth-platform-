"""Lead Intelligence's implementation of the platform `LeadDataProvider` contract (read-only, org-scoped).

Other modules (Sales) read companies, evidence, research opportunities, triggers, intent and score snapshots
through this adapter; they never import Lead Intelligence code or write its tables.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.models import (
    BusinessSignalEvidence,
    BuyingIntentEvidence,
    BuyingIntentSignal,
    Company,
    Evidence,
    IcpProfile,
    LeadReview,
    LeadScore,
    Opportunity,
    OpportunityEvidence,
    ResearchSource,
    ReviewStatus,
    ScoringProfile,
)
from aigentix.modules.lead_intelligence.services.scoring import current_signals, run_states
from aigentix.platform.leads import (
    CompanyName,
    EvidenceItem,
    IntentItem,
    LeadSnapshot,
    ResearchOpportunity,
    ScoreSnapshot,
    SignalItem,
)
from aigentix.platform.workflows.models import WorkflowRun

MAX_EVIDENCE = 80
QUALIFIED_STATUSES = (ReviewStatus.QUALIFIED_FOR_REVIEW.value, ReviewStatus.REVIEWED.value)


def _score(s: LeadScore) -> ScoreSnapshot:
    return ScoreSnapshot(
        id=s.id,
        score_low=s.score_low,
        score_high=s.score_high,
        coverage=s.coverage,
        provisional=s.provisional,
        priority_band=s.priority_band,
        intent_status=s.intent_status,
        next_step=s.next_step,
        scoring_version=s.scoring_version,
        created_at=s.created_at,
    )


def _links(db: Session, column: Any, table: Any, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for owner, evidence_id in db.execute(select(column, table.evidence_id).where(column.in_(list(ids)))):
            result.setdefault(owner, []).append(evidence_id)
    return result


class LeadIntelligenceData:
    def company_exists(self, db: Session, organization_id: uuid.UUID, company_id: uuid.UUID) -> bool:
        return (
            db.scalar(select(Company.id).where(Company.id == company_id, Company.organization_id == organization_id))
            is not None
        )

    def company_names(
        self, db: Session, organization_id: uuid.UUID, company_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, CompanyName]:
        if not company_ids:
            return {}
        rows = db.execute(
            select(Company.id, Company.name, Company.canonical_domain, Company.website_url).where(
                Company.organization_id == organization_id, Company.id.in_(list(company_ids))
            )
        )
        return {r[0]: CompanyName(name=r[1], canonical_domain=r[2], website_url=r[3]) for r in rows}

    def _review_status(self, db: Session, org: uuid.UUID, company_id: uuid.UUID) -> str:
        status = db.scalar(
            select(LeadReview.status)
            .where(LeadReview.organization_id == org, LeadReview.company_id == company_id)
            .order_by(LeadReview.created_at.desc(), LeadReview.id.desc())
            .limit(1)
        )
        return status or ReviewStatus.NEW.value

    def _latest_score(self, db: Session, org: uuid.UUID, company_id: uuid.UUID) -> LeadScore | None:
        """Latest snapshot for the default profile pair; otherwise the latest snapshot of any pair."""
        scoring = db.scalar(
            select(ScoringProfile.id).where(ScoringProfile.organization_id == org, ScoringProfile.is_default)
        )
        icp = db.scalar(select(IcpProfile.id).where(IcpProfile.organization_id == org, IcpProfile.is_default))
        base = (
            select(LeadScore)
            .where(LeadScore.organization_id == org, LeadScore.company_id == company_id)
            .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
            .limit(1)
        )
        preferred = (
            db.scalar(base.where(LeadScore.scoring_profile_id == scoring, LeadScore.icp_profile_id == icp))
            if scoring and icp
            else None
        )
        return preferred or db.scalar(base)

    def score(self, db: Session, organization_id: uuid.UUID, score_id: uuid.UUID) -> ScoreSnapshot | None:
        row = db.scalar(select(LeadScore).where(LeadScore.id == score_id, LeadScore.organization_id == organization_id))
        return _score(row) if row else None

    def snapshot(self, db: Session, organization_id: uuid.UUID, company_id: uuid.UUID) -> LeadSnapshot | None:
        org = organization_id
        company = db.scalar(select(Company).where(Company.id == company_id, Company.organization_id == org))
        if company is None:
            return None
        states = run_states(db, org, company_id)
        research_completed_at = (
            db.scalar(select(WorkflowRun.completed_at).where(WorkflowRun.id == states.research_run_id))
            if states.research_run_id
            else None
        )
        opportunities: list[ResearchOpportunity] = []
        evidence_ids: list[uuid.UUID] = []
        if states.research_run_id is not None:
            opps = list(
                db.scalars(
                    select(Opportunity)
                    .where(Opportunity.organization_id == org, Opportunity.research_run_id == states.research_run_id)
                    .order_by(Opportunity.created_at, Opportunity.id)
                )
            )
            links = _links(db, OpportunityEvidence.opportunity_id, OpportunityEvidence, [o.id for o in opps])
            opportunities = [
                ResearchOpportunity(
                    id=o.id,
                    title=o.title,
                    status=o.status,
                    confidence=o.confidence,
                    observed_context=o.observed_context,
                    problem_hypothesis=o.problem_hypothesis,
                    proposed_ai_solution=o.proposed_ai_solution,
                    estimated_business_impact=o.estimated_business_impact,
                    validation_questions=list(o.validation_questions),
                    quality_flags=list(o.quality_flags),
                    evidence_ids=links.get(o.id, []),
                )
                for o in opps
            ]
            evidence_ids += [e for o in opportunities for e in o.evidence_ids]
            evidence_ids += list(
                db.scalars(
                    select(Evidence.id)
                    .where(Evidence.organization_id == org, Evidence.research_run_id == states.research_run_id)
                    .order_by(Evidence.created_at, Evidence.id)
                )
            )
        signals: list[SignalItem] = []
        if states.enrichment_run is not None:
            rows = current_signals(db, org, company_id, states.enrichment_run.workflow_run_id)
            links = _links(db, BusinessSignalEvidence.signal_id, BusinessSignalEvidence, [s.id for s in rows])
            signals = [
                SignalItem(
                    id=s.id,
                    signal_type=s.signal_type,
                    title=s.title,
                    occurred_on=s.occurred_on,
                    date_conflict=s.date_conflict,
                    evidence_ids=links.get(s.id, []),
                )
                for s in rows
            ]
            evidence_ids += [e for s in signals for e in s.evidence_ids]
        intent_rows = list(
            db.scalars(
                select(BuyingIntentSignal)
                .where(BuyingIntentSignal.organization_id == org, BuyingIntentSignal.company_id == company_id)
                .order_by(BuyingIntentSignal.created_at, BuyingIntentSignal.id)
            )
        )
        intent_links = _links(db, BuyingIntentEvidence.intent_id, BuyingIntentEvidence, [i.id for i in intent_rows])
        intents = [
            IntentItem(
                id=i.id,
                strength=i.strength,
                source_type=i.source_type,
                title=i.title,
                observed_on=i.observed_on,
                deadline_on=i.deadline_on,
                evidence_ids=intent_links.get(i.id, []),
            )
            for i in intent_rows
        ]
        evidence_ids += [e for i in intents for e in i.evidence_ids]
        wanted = list(dict.fromkeys(evidence_ids))[:MAX_EVIDENCE]
        evidence = self._evidence(db, org, wanted)
        score = self._latest_score(db, org, company_id)
        return LeadSnapshot(
            company_id=company.id,
            name=company.name,
            canonical_domain=company.canonical_domain,
            website_url=company.website_url,
            industry=company.industry,
            location=company.location,
            description=company.short_description,
            review_status=self._review_status(db, org, company_id),
            research_completed_at=research_completed_at,
            latest_score=_score(score) if score else None,
            opportunities=opportunities,
            evidence=evidence,
            signals=signals,
            intents=intents,
        )

    def _evidence(self, db: Session, org: uuid.UUID, ids: list[uuid.UUID]) -> list[EvidenceItem]:
        if not ids:
            return []
        rows = {
            e.id: (e, url, retrieved)
            for e, url, retrieved in db.execute(
                select(Evidence, ResearchSource.source_url, ResearchSource.retrieved_at)
                .join(ResearchSource, ResearchSource.id == Evidence.source_id)
                .where(Evidence.organization_id == org, Evidence.id.in_(ids))
            )
        }
        return [
            EvidenceItem(
                id=e.id,
                evidence_type=e.evidence_type,
                observed_fact=e.observed_fact,
                excerpt=e.supporting_excerpt,
                source_url=url,
                retrieved_at=retrieved,
                basis=e.basis,
                origin=e.origin,
            )
            for e, url, retrieved in (rows[i] for i in ids if i in rows)
        ]

    def qualified_company_ids(self, db: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
        latest = (
            select(LeadReview.company_id, LeadReview.status)
            .where(LeadReview.organization_id == organization_id)
            .ext(distinct_on(LeadReview.company_id))
            .order_by(LeadReview.company_id, LeadReview.created_at.desc(), LeadReview.id.desc())
            .subquery()
        )
        return set(db.scalars(select(latest.c.company_id).where(latest.c.status.in_(QUALIFIED_STATUSES))))
