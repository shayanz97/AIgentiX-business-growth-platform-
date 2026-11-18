"""Read-only contract for lead data shared between business modules.

Lead Intelligence implements `LeadDataProvider` and registers it in its ModuleDescriptor
(`provides={"lead_data": ...}`); other modules (Sales) depend only on this file, never on the Lead Intelligence
package. Every call is scoped to one organization; implementations must filter by it.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, cast

from sqlalchemy.orm import Session

LEAD_DATA = "lead_data"


@dataclass(frozen=True)
class EvidenceItem:
    id: uuid.UUID
    evidence_type: str
    observed_fact: str
    excerpt: str
    source_url: str | None
    retrieved_at: datetime | None
    basis: str  # observed | inferred
    origin: str  # deterministic | llm


@dataclass(frozen=True)
class ResearchOpportunity:
    id: uuid.UUID
    title: str
    status: str  # proposed | under_review | approved | rejected
    confidence: str
    observed_context: str
    problem_hypothesis: str
    proposed_ai_solution: str
    estimated_business_impact: str
    validation_questions: list[str]
    quality_flags: list[str]
    evidence_ids: list[uuid.UUID]


@dataclass(frozen=True)
class SignalItem:
    id: uuid.UUID
    signal_type: str
    title: str
    occurred_on: date | None
    date_conflict: bool
    evidence_ids: list[uuid.UUID]


@dataclass(frozen=True)
class IntentItem:
    id: uuid.UUID
    strength: str  # explicit | strong | indirect
    source_type: str
    title: str
    observed_on: date | None
    deadline_on: date | None
    evidence_ids: list[uuid.UUID]


@dataclass(frozen=True)
class ScoreSnapshot:
    id: uuid.UUID
    score_low: float
    score_high: float
    coverage: float
    provisional: bool
    priority_band: str
    intent_status: str
    next_step: str
    scoring_version: str
    created_at: datetime


@dataclass(frozen=True)
class LeadSnapshot:
    company_id: uuid.UUID
    name: str
    canonical_domain: str | None
    website_url: str | None
    industry: str | None
    location: str | None
    description: str | None
    review_status: str  # new | needs_research | qualified_for_review | reviewed | rejected
    research_completed_at: datetime | None
    latest_score: ScoreSnapshot | None
    opportunities: list[ResearchOpportunity] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    signals: list[SignalItem] = field(default_factory=list)
    intents: list[IntentItem] = field(default_factory=list)


@dataclass(frozen=True)
class CompanyName:
    name: str
    canonical_domain: str | None
    website_url: str | None


class LeadDataProvider(Protocol):
    def company_exists(self, db: Session, organization_id: uuid.UUID, company_id: uuid.UUID) -> bool: ...

    def company_names(
        self, db: Session, organization_id: uuid.UUID, company_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, CompanyName]: ...

    def snapshot(self, db: Session, organization_id: uuid.UUID, company_id: uuid.UUID) -> LeadSnapshot | None:
        """Current lead view (latest finished research + latest score), or None for unknown/foreign companies."""
        ...

    def score(self, db: Session, organization_id: uuid.UUID, score_id: uuid.UUID) -> ScoreSnapshot | None: ...

    def qualified_company_ids(self, db: Session, organization_id: uuid.UUID) -> set[uuid.UUID]:
        """Companies whose latest lead review is qualified_for_review or reviewed."""
        ...


def get_lead_data_provider() -> LeadDataProvider:
    from aigentix.modules.registry import MODULES  # local import: modules depend on platform, not vice versa

    for module in MODULES:
        provider = module.provides.get(LEAD_DATA)
        if provider is not None:
            return cast(LeadDataProvider, provider)
    raise RuntimeError("No module provides lead data")
