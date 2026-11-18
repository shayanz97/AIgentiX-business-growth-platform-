"""API schemas for Sprint 3: profiles, enrichment, signals, intent, scores and ranked leads."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from aigentix.modules.lead_intelligence.models import ReviewStatus
from aigentix.modules.lead_intelligence.schemas import EvidenceRef, ResearchRunRead

ProfileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
IntentStatus = Literal["explicit", "strong", "indirect", "none_verified", "unknown"]
PriorityBand = Literal["high", "medium", "low", "excluded"]
CriterionState = Literal["assessed", "unknown", "insufficient_evidence", "not_applicable"]


# --- profiles ----------------------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProfileName
    description: Description = ""
    config: dict[str, Any] | None = Field(default=None, description="Profile configuration; omitted = defaults.")
    is_default: bool = False


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProfileName | None = None
    description: Description | None = None
    config: dict[str, Any] | None = Field(default=None, description="Complete new configuration (validated).")
    is_default: bool | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    version: int
    is_default: bool
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# --- enrichment ----------------------------------------------------------------------------------------


class EnrichmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = Field(default=False, description="Re-crawl even if a recent enrichment exists.")


class EnrichmentRunCreate(EnrichmentRequest):
    company_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    project_id: uuid.UUID | None = Field(default=None, description="Enrich every company in this project.")


class EnrichmentSkipped(BaseModel):
    company_id: uuid.UUID
    reason: Literal["not_found", "no_website", "already_running"]


class RescoredCompany(BaseModel):
    company_id: uuid.UUID
    score_id: uuid.UUID
    reason: Literal["recently_enriched"] = "recently_enriched"


class EnrichmentStartResult(BaseModel):
    started: list[ResearchRunRead]
    rescored: list[RescoredCompany]
    skipped: list[EnrichmentSkipped]


# --- signals and intent --------------------------------------------------------------------------------


class SignalRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    signal_type: str
    title: str
    summary: str
    occurred_on: date | None = Field(description="Event date stated by the source; null when unknown.")
    date_precision: Literal["day", "month", "year", "unknown"]
    date_conflict: bool
    date_candidates: list[dict[str, Any]]
    deadline_on: date | None
    freshness: Literal["recent", "moderate", "older", "historical", "unknown"]
    confidence: Literal["low", "medium", "high"]
    relevance: Literal["low", "medium", "high"]
    origin: Literal["deterministic", "llm_reviewed"]
    mention_count: int
    source_urls: list[str]
    details: dict[str, Any]
    evidence: list[EvidenceRef]
    first_seen_at: datetime
    last_seen_at: datetime


class IntentRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    strength: Literal["explicit", "strong", "indirect"]
    source_type: Literal["website", "public_tender", "first_party", "licensed_provider"]
    title: str
    summary: str
    solution_category: str | None
    observed_on: date | None
    deadline_on: date | None
    active: bool = Field(description="False once the deadline has passed.")
    external_ref: str | None
    source_url: str | None
    reliability: Literal["low", "medium", "high"]
    evidence: list[EvidenceRef]
    created_at: datetime


class CompanySignals(BaseModel):
    company_id: uuid.UUID
    intent_status: IntentStatus
    signals: list[SignalRead]
    intents: list[IntentRead]
    enrichment_run: ResearchRunRead | None
    sources_checked: list[str]
    ignored: list[str] = Field(description="Records found but not counted (expired, irrelevant, ...).")


class FirstPartyIntentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["contact_form", "email", "phone", "event", "referral", "other"]
    received_on: date
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    solution_category: str | None = None


# --- scores ----------------------------------------------------------------------------------------------


class CriterionRead(BaseModel):
    key: str
    label: str
    state: CriterionState
    points: float | None
    max_points: float
    explanation: str
    evidence_ids: list[uuid.UUID]
    references: list[dict[str, str]]


class ComponentRead(BaseModel):
    key: Literal["opportunity", "fit", "triggers", "intent"]
    label: str
    weight: int
    state: CriterionState
    score_low: float
    score_high: float
    coverage: float
    contribution_low: float
    contribution_high: float
    summary: str
    criteria: list[CriterionRead]


class LeadScoreRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    scoring_profile_id: uuid.UUID
    scoring_profile_version: int
    icp_profile_id: uuid.UUID
    icp_profile_version: int
    scoring_version: str
    score_low: float = Field(description="Conservative score: unassessed criteria count as 0.")
    score_high: float = Field(description="Upper bound: unassessed criteria count as full points.")
    coverage: float = Field(description="Share of the total weight that could be assessed (0-1).")
    provisional: bool
    confidence_level: Literal["low", "medium", "high"]
    priority_band: PriorityBand
    fit_excluded: bool
    exclusion_reasons: list[str]
    intent_status: IntentStatus
    latest_trigger_on: date | None
    opportunity_categories: list[str]
    components: list[ComponentRead]
    explanation: str
    next_step: str
    next_step_text: str
    evidence_ids: list[uuid.UUID]
    reference_date: date
    research_run_id: uuid.UUID | None
    enrichment_run_id: uuid.UUID | None
    created_at: datetime


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scoring_profile_id: uuid.UUID | None = Field(default=None, description="Defaults to the default profile.")
    icp_profile_id: uuid.UUID | None = Field(default=None, description="Defaults to the default profile.")


class ScoreRunResult(BaseModel):
    scored: int
    new_snapshots: int
    scores: list[LeadScoreRead]


# --- leads -------------------------------------------------------------------------------------------------


class LeadRead(BaseModel):
    company_id: uuid.UUID
    company_name: str
    canonical_domain: str | None
    website_url: str | None
    review_status: ReviewStatus
    review_note: str | None
    reviewed_at: datetime | None
    score: LeadScoreRead


class LeadReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class LeadReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    status: ReviewStatus
    note: str | None
    lead_score_id: uuid.UUID | None
    reviewed_by_user_id: uuid.UUID | None
    created_at: datetime


class LeadDetail(BaseModel):
    lead: LeadRead | None = Field(description="Null until the company has been scored.")
    reviews: list[LeadReviewRead]
