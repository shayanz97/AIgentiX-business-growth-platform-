"""Lead Intelligence tables. Every table carries organization_id; cross-table links use composite foreign keys
including organization_id, so the database itself rejects links between different tenants' rows."""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aigentix.core.db import Base, TimestampMixin, utcnow


class ProjectStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Confidence(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Basis(enum.StrEnum):
    OBSERVED = "observed"  # stated on the website
    INFERRED = "inferred"  # interpretation of what is stated


class EvidenceType(enum.StrEnum):
    COMPANY_DESCRIPTION = "company_description"
    SERVICE_OFFERING = "service_offering"
    TARGET_CUSTOMER = "target_customer"
    BUSINESS_MODEL = "business_model"
    CONTACT_FORM = "contact_form"
    QUOTE_REQUEST_FORM = "quote_request_form"
    ONLINE_BOOKING = "online_booking"
    LIVE_CHAT = "live_chat"
    CUSTOMER_SUPPORT = "customer_support"
    FAQ = "faq"
    CAREERS_HIRING = "careers_hiring"
    DOCUMENT_DOWNLOAD = "document_download"
    DOCUMENT_WORKFLOW = "document_workflow"
    ECOMMERCE = "ecommerce"
    TECHNOLOGY_SIGNAL = "technology_signal"
    OPERATIONAL_SIGNAL = "operational_signal"
    INDUSTRY = "industry"
    LOCATION = "location"
    # Sprint 3 (enrichment)
    COMPANY_SIZE = "company_size"
    BUSINESS_SIGNAL = "business_signal"
    BUYING_INTENT = "buying_intent"


class OpportunityStatus(enum.StrEnum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"  # approved for further investigation
    REJECTED = "rejected"


def _enum_check(column: str, values: type[enum.StrEnum], name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{v.value}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class ResearchProject(TimestampMixin, Base):
    """A tenant-owned research project (campaign) grouping companies."""

    __tablename__ = "research_projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ProjectStatus.DRAFT.value)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_research_projects_id_org"),
        _enum_check("status", ProjectStatus, "status_valid"),
        Index("ix_research_projects_org_created", "organization_id", "created_at"),
    )


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_domain: Mapped[str | None] = mapped_column(String(253))
    website_url: Mapped[str | None] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    short_description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_companies_id_org"),
        # Deduplication is per organization: by domain, or by name for companies without a website.
        Index(
            "uq_companies_org_domain",
            "organization_id",
            "canonical_domain",
            unique=True,
            postgresql_where=text("canonical_domain IS NOT NULL"),
        ),
        Index(
            "uq_companies_org_name_without_domain",
            "organization_id",
            func.lower(name),
            unique=True,
            postgresql_where=text("canonical_domain IS NULL"),
        ),
        CheckConstraint("(canonical_domain IS NULL) = (website_url IS NULL)", name="domain_and_url_together"),
        Index("ix_companies_org_created", "organization_id", "created_at"),
    )


class ResearchProjectCompany(Base):
    __tablename__ = "research_project_companies"

    research_project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    added_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("research_project_id", "company_id"),
        ForeignKeyConstraint(
            ["research_project_id", "organization_id"],
            ["research_projects.id", "research_projects.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        Index("ix_research_project_companies_company", "company_id"),
    )


class ResearchRun(Base):
    """Lead-Intelligence view of a platform workflow run: which company/project it researched and its outputs."""

    __tablename__ = "research_runs"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column()
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # "research" = Sprint 2 website research + audit; "enrichment" = growth triggers, buying intent and scoring.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="research", server_default="research")
    ai_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    audit_summary: Mapped[str | None] = mapped_column(Text)
    pages_fetched: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("workflow_run_id", "organization_id", name="uq_research_runs_id_org"),
        ForeignKeyConstraint(
            ["workflow_run_id", "organization_id"],
            ["workflow_runs.id", "workflow_runs.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["research_projects.id", "research_projects.organization_id"],
            ondelete="SET NULL (project_id)",
        ),
        CheckConstraint(
            "ai_status IN ('pending', 'completed', 'unavailable', 'failed', 'skipped')",
            name="ai_status_valid",
        ),
        CheckConstraint("kind IN ('research', 'enrichment')", name="kind_valid"),
        Index("ix_research_runs_company_created", "company_id", "created_at"),
        Index("ix_research_runs_project", "project_id"),
        Index("ix_research_runs_org_created", "organization_id", "created_at"),
    )


class ResearchSource(Base):
    """A fetched public web page. Text is truncated and redacted; kept only for evidence provenance."""

    __tablename__ = "research_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    research_run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_title: Mapped[str | None] = mapped_column(String(500))
    page_category: Mapped[str] = mapped_column(String(40), nullable=False, default="home")
    http_status: Mapped[int | None] = mapped_column()
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(String(20), nullable=False)
    extraction_error: Mapped[str | None] = mapped_column(String(500))
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_research_sources_id_org"),
        UniqueConstraint("research_run_id", "source_url", name="uq_research_sources_run_url"),
        ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "extraction_status IN ('extracted', 'empty', 'failed', 'skipped')", name="extraction_status_valid"
        ),
        Index("ix_research_sources_company", "company_id"),
    )


class Evidence(Base):
    """A single observation with a verbatim excerpt from a stored source."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    research_run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    observed_fact: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)  # deterministic | llm
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_evidence_id_org"),
        ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["research_sources.id", "research_sources.organization_id"],
            ondelete="CASCADE",
        ),
        _enum_check("evidence_type", EvidenceType, "evidence_type_valid"),
        _enum_check("basis", Basis, "basis_valid"),
        _enum_check("confidence", Confidence, "confidence_valid"),
        CheckConstraint("origin IN ('deterministic', 'llm')", name="origin_valid"),
        Index("ix_evidence_run", "research_run_id"),
        Index("ix_evidence_company", "company_id"),
    )


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    research_run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_context: Mapped[str] = mapped_column(Text, nullable=False)
    problem_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_ai_solution: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_business_impact: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_complexity: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    validation_questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    next_step: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OpportunityStatus.PROPOSED.value)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_opportunities_id_org"),
        ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        _enum_check("implementation_complexity", Confidence, "complexity_valid"),
        _enum_check("confidence", Confidence, "confidence_valid"),
        _enum_check("status", OpportunityStatus, "status_valid"),
        Index("ix_opportunities_company", "company_id"),
        Index("ix_opportunities_org_status", "organization_id", "status"),
        Index("ix_opportunities_run", "research_run_id"),
    )


class OpportunityEvidence(Base):
    __tablename__ = "opportunity_evidence"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("opportunity_id", "evidence_id"),
        ForeignKeyConstraint(
            ["opportunity_id", "organization_id"],
            ["opportunities.id", "opportunities.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "organization_id"],
            ["evidence.id", "evidence.organization_id"],
            ondelete="CASCADE",
        ),
        Index("ix_opportunity_evidence_evidence", "evidence_id"),
    )


# --- Sprint 3: growth triggers, buying intent, ICP / scoring profiles, lead scores, reviews ------------------


class SignalType(enum.StrEnum):
    HIRING = "hiring"
    EXPANSION = "expansion"
    FUNDING = "funding"
    PRODUCT_LAUNCH = "product_launch"
    LEADERSHIP_CHANGE = "leadership_change"
    TECHNOLOGY_ADOPTION = "technology_adoption"
    DIGITAL_TRANSFORMATION = "digital_transformation"
    OPERATIONAL_CHANGE = "operational_change"
    PUBLIC_PROJECT_REQUEST = "public_project_request"
    PROCUREMENT_TENDER = "procurement_tender"
    INBOUND_INQUIRY = "inbound_inquiry"
    OTHER = "other"


class DatePrecision(enum.StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class IntentStrength(enum.StrEnum):
    """Stored strengths. NONE_VERIFIED and UNKNOWN are computed states (no row is ever stored for them)."""

    EXPLICIT = "explicit"
    STRONG = "strong"
    INDIRECT = "indirect"


class IntentSourceType(enum.StrEnum):
    WEBSITE = "website"  # the company's own public website
    PUBLIC_TENDER = "public_tender"  # a configured tender source
    FIRST_PARTY = "first_party"  # an inquiry received by the organization itself (recorded by a user)
    LICENSED_PROVIDER = "licensed_provider"  # a contracted intent-data provider (interface only, none bundled)


class ReviewStatus(enum.StrEnum):
    NEW = "new"
    NEEDS_RESEARCH = "needs_research"
    QUALIFIED_FOR_REVIEW = "qualified_for_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class BusinessSignal(Base):
    """A deduplicated growth trigger observed for a company. Repeated mentions raise mention_count only."""

    __tablename__ = "business_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    enrichment_run_id: Mapped[uuid.UUID | None] = mapped_column()  # run that last observed it
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_on: Mapped[date | None] = mapped_column(Date)  # event date; never the retrieval date
    date_precision: Mapped[str] = mapped_column(String(10), nullable=False, default=DatePrecision.UNKNOWN.value)
    date_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    date_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    deadline_on: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    relevance: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    mention_count: Mapped[int] = mapped_column(nullable=False, default=1)
    source_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_business_signals_id_org"),
        UniqueConstraint("organization_id", "company_id", "dedupe_key", name="uq_business_signals_dedupe"),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["enrichment_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="SET NULL (enrichment_run_id)",
        ),
        _enum_check("signal_type", SignalType, "signal_type_valid"),
        _enum_check("date_precision", DatePrecision, "date_precision_valid"),
        _enum_check("confidence", Confidence, "confidence_valid"),
        _enum_check("relevance", Confidence, "relevance_valid"),
        CheckConstraint("origin IN ('deterministic', 'llm_reviewed')", name="origin_valid"),
        CheckConstraint("mention_count >= 1", name="mention_count_positive"),
        Index("ix_business_signals_company", "company_id"),
        Index("ix_business_signals_org_type", "organization_id", "signal_type"),
    )


class BusinessSignalEvidence(Base):
    __tablename__ = "business_signal_evidence"

    signal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("signal_id", "evidence_id"),
        ForeignKeyConstraint(
            ["signal_id", "organization_id"],
            ["business_signals.id", "business_signals.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "organization_id"], ["evidence.id", "evidence.organization_id"], ondelete="CASCADE"
        ),
        Index("ix_business_signal_evidence_evidence", "evidence_id"),
    )


class BuyingIntentSignal(Base):
    """Verified buying intent from a real source. Never created without a source; never inferred from absence."""

    __tablename__ = "buying_intent_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    enrichment_run_id: Mapped[uuid.UUID | None] = mapped_column()
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    solution_category: Mapped[str | None] = mapped_column(String(60))
    observed_on: Mapped[date | None] = mapped_column(Date)  # publication / inquiry date, if known
    deadline_on: Mapped[date | None] = mapped_column(Date)
    external_ref: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    reliability: Mapped[str] = mapped_column(String(10), nullable=False, default="high")
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_buying_intent_signals_id_org"),
        UniqueConstraint("organization_id", "company_id", "dedupe_key", name="uq_buying_intent_signals_dedupe"),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["enrichment_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="SET NULL (enrichment_run_id)",
        ),
        _enum_check("strength", IntentStrength, "strength_valid"),
        _enum_check("source_type", IntentSourceType, "source_type_valid"),
        _enum_check("reliability", Confidence, "reliability_valid"),
        Index("ix_buying_intent_signals_company", "company_id"),
    )


class BuyingIntentEvidence(Base):
    __tablename__ = "buying_intent_evidence"

    intent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("intent_id", "evidence_id"),
        ForeignKeyConstraint(
            ["intent_id", "organization_id"],
            ["buying_intent_signals.id", "buying_intent_signals.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "organization_id"], ["evidence.id", "evidence.organization_id"], ondelete="CASCADE"
        ),
        Index("ix_buying_intent_evidence_evidence", "evidence_id"),
    )


class _VersionedProfile(TimestampMixin):
    """A named, versioned JSON configuration. Every change bumps `version`; scores snapshot the config used."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class IcpProfile(_VersionedProfile, Base):
    __tablename__ = "icp_profiles"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_icp_profiles_id_org"),
        Index("uq_icp_profiles_org_name", "organization_id", text("lower(name)"), unique=True),
        Index("uq_icp_profiles_org_default", "organization_id", unique=True, postgresql_where=text("is_default")),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class ScoringProfile(_VersionedProfile, Base):
    __tablename__ = "scoring_profiles"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_scoring_profiles_id_org"),
        Index("uq_scoring_profiles_org_name", "organization_id", text("lower(name)"), unique=True),
        Index("uq_scoring_profiles_org_default", "organization_id", unique=True, postgresql_where=text("is_default")),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class LeadScore(Base):
    """Append-only score snapshot: inputs, profile versions, per-criterion breakdown and evidence links."""

    __tablename__ = "lead_scores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scoring_profile_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scoring_profile_version: Mapped[int] = mapped_column(nullable=False)
    icp_profile_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    icp_profile_version: Mapped[int] = mapped_column(nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False)
    score_low: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), nullable=False)
    score_high: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), nullable=False)
    coverage: Mapped[float] = mapped_column(Numeric(4, 3, asdecimal=False), nullable=False)
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(10), nullable=False)
    priority_band: Mapped[str] = mapped_column(String(20), nullable=False)
    fit_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intent_status: Mapped[str] = mapped_column(String(20), nullable=False)
    latest_trigger_on: Mapped[date | None] = mapped_column(Date)
    opportunity_categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    next_step: Mapped[str] = mapped_column(String(40), nullable=False)
    next_step_text: Mapped[str] = mapped_column(Text, nullable=False)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column()
    enrichment_run_id: Mapped[uuid.UUID | None] = mapped_column()
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_lead_scores_id_org"),
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["scoring_profile_id", "organization_id"],
            ["scoring_profiles.id", "scoring_profiles.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["icp_profile_id", "organization_id"],
            ["icp_profiles.id", "icp_profiles.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="SET NULL (research_run_id)",
        ),
        ForeignKeyConstraint(
            ["enrichment_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            ondelete="SET NULL (enrichment_run_id)",
        ),
        CheckConstraint("score_low >= 0 AND score_low <= score_high AND score_high <= 100", name="score_bounds"),
        CheckConstraint("coverage >= 0 AND coverage <= 1", name="coverage_range"),
        _enum_check("confidence_level", Confidence, "confidence_level_valid"),
        CheckConstraint("priority_band IN ('high', 'medium', 'low', 'excluded')", name="priority_band_valid"),
        CheckConstraint(
            "intent_status IN ('explicit', 'strong', 'indirect', 'none_verified', 'unknown')",
            name="intent_status_valid",
        ),
        Index("ix_lead_scores_company_created", "company_id", "created_at"),
        # Serves the ranked list: latest snapshot per company for one (scoring, ICP) profile pair.
        Index(
            "ix_lead_scores_ranked",
            "organization_id",
            "scoring_profile_id",
            "icp_profile_id",
            "company_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )


class LeadScoreEvidence(Base):
    __tablename__ = "lead_score_evidence"

    lead_score_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("lead_score_id", "evidence_id"),
        ForeignKeyConstraint(
            ["lead_score_id", "organization_id"],
            ["lead_scores.id", "lead_scores.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "organization_id"], ["evidence.id", "evidence.organization_id"], ondelete="CASCADE"
        ),
        Index("ix_lead_score_evidence_evidence", "evidence_id"),
    )


class LeadReview(Base):
    """Append-only review history for a lead (company). The newest row is the current review status."""

    __tablename__ = "lead_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    lead_score_id: Mapped[uuid.UUID | None] = mapped_column()
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["lead_score_id", "organization_id"],
            ["lead_scores.id", "lead_scores.organization_id"],
            ondelete="SET NULL (lead_score_id)",
        ),
        _enum_check("status", ReviewStatus, "status_valid"),
        Index("ix_lead_reviews_company_created", "company_id", "created_at"),
    )
