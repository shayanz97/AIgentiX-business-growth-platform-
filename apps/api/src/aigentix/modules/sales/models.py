"""Sales tables. Every table carries organization_id; links use composite foreign keys (id, organization_id),
including the references to Lead Intelligence tables (companies, opportunities, lead_scores), so the database
itself rejects cross-tenant links. Sales never writes Lead Intelligence tables."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aigentix.core.db import Base, TimestampMixin, utcnow


class Stage(enum.StrEnum):
    QUALIFIED = "qualified"
    RESEARCHING = "researching"
    CONTACT_PLANNED = "contact_planned"
    IN_CONVERSATION = "in_conversation"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"


class DealStatus(enum.StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Priority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActivityType(enum.StrEnum):
    NOTE = "note"
    CALL = "call"
    MEETING = "meeting"
    EMAIL_SENT = "email_sent"  # sent by a person outside AIgentiX and recorded here
    EMAIL_RECEIVED = "email_received"
    LETTER_SENT = "letter_sent"
    PROPOSAL_SENT = "proposal_sent"
    OTHER = "other"
    SYSTEM = "system"  # audit events written by AIgentiX itself (conversion, close, export, ...)


class TaskStatus(enum.StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BriefStatus(enum.StrEnum):
    GENERATING = "generating"
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ProposalStatus(enum.StrEnum):
    GENERATING = "generating"
    DRAFT = "draft"
    READY = "ready"  # reviewed internally, not yet sent
    SENT = "sent"  # the user confirmed they sent it outside AIgentiX
    ACCEPTED = "accepted"
    DECLINED = "declined"
    FAILED = "failed"


class Channel(enum.StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    LETTER = "letter"
    LINKEDIN = "linkedin"


class LawfulBasis(enum.StrEnum):
    NONE = "none"
    EXPLICIT_CONSENT = "explicit_consent"  # documented prior consent
    EXISTING_CUSTOMER = "existing_customer"  # e.g. § 7 (3) UWG for e-mail to own customers
    PRESUMED_CONSENT_B2B = "presumed_consent_b2b"  # § 7 (2) Nr. 1 UWG, phone to businesses, documented reason
    INBOUND_REQUEST = "inbound_request"  # the contact asked to be contacted about this matter
    LEGITIMATE_INTEREST = "legitimate_interest"  # art. 6 (1) f GDPR assessment (e.g. postal letters)


class ContactSource(enum.StrEnum):
    INBOUND_INQUIRY = "inbound_inquiry"
    BUSINESS_CARD = "business_card"
    EVENT = "event"
    REFERRAL = "referral"
    WEBSITE_IMPRINT = "website_imprint"
    WEBSITE_CONTACT_PAGE = "website_contact_page"
    EXISTING_CUSTOMER = "existing_customer"
    OTHER = "other"


class ContactRestriction(enum.StrEnum):
    UNVERIFIED = "unverified"
    RESTRICTED = "restricted"  # do not contact until reviewed again
    SUPPRESSED = "suppressed"  # opted out / objected: never contact


def _enum_check(column: str, values: type[enum.StrEnum], name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{v.value}'" for v in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def _company_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["company_id", "organization_id"], ["companies.id", "companies.organization_id"], ondelete="CASCADE"
    )


def _deal_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["sales_opportunity_id", "organization_id"],
        ["sales_opportunities.id", "sales_opportunities.organization_id"],
        ondelete="CASCADE",
    )


class SalesOpportunity(TimestampMixin, Base):
    __tablename__ = "sales_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_opportunity_id: Mapped[uuid.UUID | None] = mapped_column()  # Lead Intelligence research opportunity
    source_lead_score_id: Mapped[uuid.UUID | None] = mapped_column()  # score snapshot at conversion
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default=Stage.QUALIFIED.value)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=DealStatus.OPEN.value)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default=Priority.MEDIUM.value)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # entered by a person only
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    confirmed_requirements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    won_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lost_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column()
    conversion_key: Mapped[uuid.UUID | None] = mapped_column()  # idempotency key of the conversion request
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(nullable=False, default=1)  # optimistic locking

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_sales_opportunities_id_org"),
        UniqueConstraint("organization_id", "conversion_key", name="uq_sales_opportunities_conversion_key"),
        _company_fk(),
        ForeignKeyConstraint(
            ["source_opportunity_id", "organization_id"],
            ["opportunities.id", "opportunities.organization_id"],
            ondelete="SET NULL (source_opportunity_id)",
        ),
        ForeignKeyConstraint(
            ["source_lead_score_id", "organization_id"],
            ["lead_scores.id", "lead_scores.organization_id"],
            ondelete="SET NULL (source_lead_score_id)",
        ),
        _enum_check("stage", Stage, "stage_valid"),
        _enum_check("status", DealStatus, "status_valid"),
        _enum_check("priority", Priority, "priority_valid"),
        CheckConstraint("estimated_value IS NULL OR estimated_value >= 0", name="estimated_value_positive"),
        CheckConstraint("won_value IS NULL OR won_value >= 0", name="won_value_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "(status = 'open') = (closed_at IS NULL) AND "
            "(status = 'open' AND stage NOT IN ('won', 'lost') OR status = stage)",
            name="status_stage_consistent",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_sales_opportunities_org_stage", "organization_id", "stage"),
        Index("ix_sales_opportunities_company", "company_id"),
        Index("ix_sales_opportunities_org_updated", "organization_id", "updated_at"),
    )


class SalesStageHistory(Base):
    __tablename__ = "sales_stage_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sales_opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    previous_stage: Mapped[str | None] = mapped_column(String(30))
    new_stage: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        _deal_fk(),
        _enum_check("new_stage", Stage, "new_stage_valid"),
        Index("ix_sales_stage_history_deal", "sales_opportunity_id", "changed_at"),
    )


class SalesContact(TimestampMixin, Base):
    """A business contact person, entered manually with its source. Minimal personal data by design."""

    __tablename__ = "sales_contacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    business_email: Mapped[str | None] = mapped_column(String(320))
    business_phone: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    lawful_basis: Mapped[str] = mapped_column(String(40), nullable=False, default=LawfulBasis.NONE.value)
    lawful_basis_reference: Mapped[str | None] = mapped_column(Text)  # where the consent / assessment is documented
    restriction_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContactRestriction.UNVERIFIED.value
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_sales_contacts_id_org"),
        _company_fk(),
        _enum_check("source", ContactSource, "source_valid"),
        _enum_check("lawful_basis", LawfulBasis, "lawful_basis_valid"),
        _enum_check("restriction_status", ContactRestriction, "restriction_status_valid"),
        Index("ix_sales_contacts_company", "company_id"),
    )


class SalesContactReview(Base):
    """Append-only per-channel contact eligibility decision by a person."""

    __tablename__ = "sales_contact_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # allowed | not_allowed
    lawful_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["contact_id", "organization_id"],
            ["sales_contacts.id", "sales_contacts.organization_id"],
            ondelete="CASCADE",
        ),
        _enum_check("channel", Channel, "channel_valid"),
        _enum_check("lawful_basis", LawfulBasis, "lawful_basis_valid"),
        CheckConstraint("decision IN ('allowed', 'not_allowed')", name="decision_valid"),
        Index("ix_sales_contact_reviews_contact", "contact_id", "reviewed_at"),
    )


class SalesSuppression(Base):
    """Opt-out / objection for one address or number. Stored as a hash of the normalised value."""

    __tablename__ = "sales_suppressions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "channel", "value_hash", name="uq_sales_suppressions_value"),
        _enum_check("channel", Channel, "channel_valid"),
    )


class SalesActivity(Base):
    __tablename__ = "sales_activities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sales_opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column()
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        _deal_fk(),
        ForeignKeyConstraint(
            ["contact_id", "organization_id"],
            ["sales_contacts.id", "sales_contacts.organization_id"],
            ondelete="SET NULL (contact_id)",
        ),
        _enum_check("activity_type", ActivityType, "activity_type_valid"),
        Index("ix_sales_activities_deal", "sales_opportunity_id", "occurred_at"),
    )


class SalesTask(Base):
    __tablename__ = "sales_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sales_opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.OPEN.value)
    suggestion_key: Mapped[str | None] = mapped_column(String(60))  # set when created from a suggestion
    completed_at: Mapped[datetime | None] = mapped_column()
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_sales_tasks_id_org"),
        _deal_fk(),
        _enum_check("status", TaskStatus, "status_valid"),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="completed_consistent"),
        Index("ix_sales_tasks_org_status_due", "organization_id", "status", "due_at"),
        Index("ix_sales_tasks_deal", "sales_opportunity_id"),
        Index("ix_sales_tasks_assignee", "assigned_user_id"),
    )


class SalesBrief(TimestampMixin, Base):
    """AI sales intelligence brief. `content` is the validated AI output; human edits live in `edited_content`
    and are never overwritten by regeneration (which creates a new brief)."""

    __tablename__ = "sales_briefs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sales_opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BriefStatus.GENERATING.value)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    edited_content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    generation_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_sales_briefs_id_org"),
        _deal_fk(),
        ForeignKeyConstraint(
            ["workflow_run_id", "organization_id"],
            ["workflow_runs.id", "workflow_runs.organization_id"],
            ondelete="SET NULL (workflow_run_id)",
        ),
        _enum_check("status", BriefStatus, "status_valid"),
        Index("ix_sales_briefs_deal", "sales_opportunity_id", "created_at"),
    )


class SalesProposal(TimestampMixin, Base):
    __tablename__ = "sales_proposals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sales_opportunity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    brief_id: Mapped[uuid.UUID | None] = mapped_column()
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ProposalStatus.GENERATING.value)
    current_revision: Mapped[int] = mapped_column(nullable=False, default=0)  # 0 = nothing saved yet
    sent_at: Mapped[datetime | None] = mapped_column()  # recorded by a person; AIgentiX never sends
    message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_sales_proposals_id_org"),
        _deal_fk(),
        ForeignKeyConstraint(
            ["brief_id", "organization_id"],
            ["sales_briefs.id", "sales_briefs.organization_id"],
            ondelete="SET NULL (brief_id)",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "organization_id"],
            ["workflow_runs.id", "workflow_runs.organization_id"],
            ondelete="SET NULL (workflow_run_id)",
        ),
        _enum_check("status", ProposalStatus, "status_valid"),
        CheckConstraint("(status IN ('sent', 'accepted', 'declined')) = (sent_at IS NOT NULL)", name="sent_consistent"),
        Index("ix_sales_proposals_deal", "sales_opportunity_id", "created_at"),
    )


class SalesProposalRevision(Base):
    """Immutable saved version of a proposal (AI draft or human edit)."""

    __tablename__ = "sales_proposal_revisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposal_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)  # ai | human
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str | None] = mapped_column(String(120))
    generation_version: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("proposal_id", "revision", name="uq_sales_proposal_revisions_number"),
        ForeignKeyConstraint(
            ["proposal_id", "organization_id"],
            ["sales_proposals.id", "sales_proposals.organization_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("origin IN ('ai', 'human')", name="origin_valid"),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )


class SalesServiceOffering(TimestampMixin, Base):
    """The organization's own services. A price is used in proposals only when `price_approved` is true."""

    __tablename__ = "sales_service_offerings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    solution_category: Mapped[str | None] = mapped_column(String(60))
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_unit: Mapped[str | None] = mapped_column(String(60))  # e.g. "one-time", "per month"
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    price_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("uq_sales_service_offerings_org_name", "organization_id", text("lower(name)"), unique=True),
        CheckConstraint("price_amount IS NULL OR price_amount >= 0", name="price_positive"),
        CheckConstraint("NOT price_approved OR price_amount IS NOT NULL", name="approved_price_present"),
    )


class ExternalCRMMapping(Base):
    __tablename__ = "sales_crm_mappings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    local_entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # company | contact | deal
    local_entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    external_entity_id: Mapped[str | None] = mapped_column(String(200))
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending | synced | failed
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider", "local_entity_type", "local_entity_id", name="uq_sales_crm_mappings_local"
        ),
        Index(
            "uq_sales_crm_mappings_external",
            "organization_id",
            "provider",
            "local_entity_type",
            "external_entity_id",
            unique=True,
            postgresql_where=text("external_entity_id IS NOT NULL"),
        ),
        CheckConstraint("local_entity_type IN ('company', 'contact', 'deal')", name="entity_type_valid"),
        CheckConstraint("sync_status IN ('pending', 'synced', 'failed')", name="sync_status_valid"),
        CheckConstraint("sync_status <> 'synced' OR external_entity_id IS NOT NULL", name="synced_has_external_id"),
    )
