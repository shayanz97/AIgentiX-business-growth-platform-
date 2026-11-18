"""ORM → API mapping for signals, intent, scores and leads."""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.domain.dates import freshness
from aigentix.modules.lead_intelligence.domain.profiles import ScoringConfig
from aigentix.modules.lead_intelligence.models import (
    BusinessSignal,
    BuyingIntentSignal,
    Evidence,
    LeadScore,
)
from aigentix.modules.lead_intelligence.routes.serializers import _labels_and_urls
from aigentix.modules.lead_intelligence.schemas import EvidenceRef
from aigentix.modules.lead_intelligence.scoring_schemas import (
    ComponentRead,
    IntentRead,
    LeadRead,
    LeadScoreRead,
    SignalRead,
)
from aigentix.modules.lead_intelligence.services.leads import LeadRow
from aigentix.platform.organizations.service import TenantContext


def evidence_refs(db: Session, tenant: TenantContext, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, EvidenceRef]:
    wanted = set(ids)
    if not wanted:
        return {}
    evidence = list(
        db.scalars(select(Evidence).where(Evidence.organization_id == tenant.organization_id, Evidence.id.in_(wanted)))
    )
    labels, urls = _labels_and_urls(db, {e.research_run_id for e in evidence})
    return {
        e.id: EvidenceRef(
            id=e.id,
            label=labels.get(e.id, "E?"),
            evidence_type=e.evidence_type,
            observed_fact=e.observed_fact,
            supporting_excerpt=e.supporting_excerpt,
            source_url=urls.get(e.source_id),
            basis=e.basis,
            confidence=e.confidence,
        )
        for e in evidence
    }


def signal_reads(
    db: Session,
    tenant: TenantContext,
    signals: Sequence[BusinessSignal],
    links: dict[uuid.UUID, list[uuid.UUID]],
    *,
    reference: date,
    config: ScoringConfig,
) -> list[SignalRead]:
    refs = evidence_refs(db, tenant, (e for ids in links.values() for e in ids))
    bands = config.freshness_bands.model_dump()
    return [
        SignalRead(
            id=s.id,
            company_id=s.company_id,
            signal_type=s.signal_type,
            title=s.title,
            summary=s.summary,
            occurred_on=s.occurred_on,
            date_precision=s.date_precision,
            date_conflict=s.date_conflict,
            date_candidates=s.date_candidates,
            deadline_on=s.deadline_on,
            freshness="unknown" if s.date_conflict else freshness(s.occurred_on, reference, bands),
            confidence=s.confidence,
            relevance=s.relevance,
            origin=s.origin,
            mention_count=s.mention_count,
            source_urls=s.source_urls,
            details=s.details,
            evidence=[refs[e] for e in links.get(s.id, []) if e in refs],
            first_seen_at=s.first_seen_at,
            last_seen_at=s.last_seen_at,
        )
        for s in signals
    ]


def intent_reads(
    db: Session,
    tenant: TenantContext,
    intents: Sequence[BuyingIntentSignal],
    links: dict[uuid.UUID, list[uuid.UUID]],
    *,
    reference: date,
) -> list[IntentRead]:
    refs = evidence_refs(db, tenant, (e for ids in links.values() for e in ids))
    return [
        IntentRead(
            id=i.id,
            company_id=i.company_id,
            strength=i.strength,
            source_type=i.source_type,
            title=i.title,
            summary=i.summary,
            solution_category=i.solution_category,
            observed_on=i.observed_on,
            deadline_on=i.deadline_on,
            active=i.deadline_on is None or i.deadline_on >= reference,
            external_ref=i.external_ref,
            source_url=i.source_url,
            reliability=i.reliability,
            evidence=[refs[e] for e in links.get(i.id, []) if e in refs],
            created_at=i.created_at,
        )
        for i in intents
    ]


def score_read(score: LeadScore, evidence_ids: list[str] | None = None) -> LeadScoreRead:
    snapshot = score.profile_snapshot or {}
    ids = evidence_ids
    if ids is None:
        ids = sorted({e for c in score.components for cr in c.get("criteria", []) for e in cr.get("evidence_ids", [])})
    return LeadScoreRead(
        id=score.id,
        company_id=score.company_id,
        scoring_profile_id=score.scoring_profile_id,
        scoring_profile_version=score.scoring_profile_version,
        icp_profile_id=score.icp_profile_id,
        icp_profile_version=score.icp_profile_version,
        scoring_version=score.scoring_version,
        score_low=score.score_low,
        score_high=score.score_high,
        coverage=score.coverage,
        provisional=score.provisional,
        confidence_level=score.confidence_level,
        priority_band=score.priority_band,
        fit_excluded=score.fit_excluded,
        exclusion_reasons=list(snapshot.get("exclusion_reasons", [])),
        intent_status=score.intent_status,
        latest_trigger_on=score.latest_trigger_on,
        opportunity_categories=score.opportunity_categories,
        components=[ComponentRead.model_validate(c) for c in score.components],
        explanation=score.explanation,
        next_step=score.next_step,
        next_step_text=score.next_step_text,
        evidence_ids=[uuid.UUID(e) for e in ids],
        reference_date=date.fromisoformat(snapshot.get("reference_date", score.created_at.date().isoformat())),
        research_run_id=score.research_run_id,
        enrichment_run_id=score.enrichment_run_id,
        created_at=score.created_at,
    )


def lead_read(row: LeadRow) -> LeadRead:
    return LeadRead(
        company_id=row.company.id,
        company_name=row.company.name,
        canonical_domain=row.company.canonical_domain,
        website_url=row.company.website_url,
        review_status=row.review_status,
        review_note=row.review_note,
        reviewed_at=row.reviewed_at,
        score=score_read(row.score),
    )
