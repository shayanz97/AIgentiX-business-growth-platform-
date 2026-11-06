"""Lead Intelligence tables. Every table carries organization_id; cross-table links use composite foreign keys
including organization_id, so the database itself rejects links between different tenants' rows."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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
