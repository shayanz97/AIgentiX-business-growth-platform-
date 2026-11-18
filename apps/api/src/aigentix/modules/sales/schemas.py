"""API schemas for deals, conversion, stage changes, activities, contacts / compliance and metrics."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from aigentix.modules.sales.models import (
    ActivityType,
    Channel,
    ContactRestriction,
    ContactSource,
    DealStatus,
    LawfulBasis,
    Priority,
    Stage,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Requirement = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _no_nulls(model: BaseModel, fields: tuple[str, ...]) -> None:
    """Optional in a PATCH means "leave unchanged"; an explicit null for a required column is rejected."""
    nulled = [f for f in fields if f in model.model_fields_set and getattr(model, f) is None]
    if nulled:
        raise ValueError(f"{', '.join(nulled)} cannot be null")


# --- deals -----------------------------------------------------------------------------------------------


class DealCreate(_Strict):
    company_id: uuid.UUID
    title: Title
    description: LongText = ""
    owner_user_id: uuid.UUID | None = None
    priority: Priority = Priority.MEDIUM
    estimated_value: Money | None = None
    currency: Currency = "EUR"
    expected_close_date: date | None = None


class DealUpdate(_Strict):
    expected_version: int = Field(ge=1, description="Version the change is based on (optimistic locking).")
    title: Title | None = None
    description: LongText | None = None
    owner_user_id: uuid.UUID | None = None
    priority: Priority | None = None
    estimated_value: Money | None = None
    currency: Currency | None = None
    expected_close_date: date | None = None
    confirmed_requirements: list[Requirement] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _required_not_null(self) -> "DealUpdate":
        _no_nulls(self, ("title", "description", "priority", "currency", "confirmed_requirements"))
        return self


class StageChange(_Strict):
    expected_version: int = Field(ge=1)
    stage: Stage
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class DealClose(_Strict):
    expected_version: int = Field(ge=1)
    outcome: Literal["won", "lost"]
    won_value: Money | None = Field(default=None, description="Value actually won, as entered by a person.")
    lost_reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class DealReopen(_Strict):
    expected_version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class CompanyRef(BaseModel):
    id: uuid.UUID
    name: str
    canonical_domain: str | None
    website_url: str | None


class DealRead(BaseModel):
    id: uuid.UUID
    company: CompanyRef
    source_opportunity_id: uuid.UUID | None
    source_lead_score_id: uuid.UUID | None
    title: str
    description: str
    owner_user_id: uuid.UUID | None
    stage: Stage
    status: DealStatus
    priority: Priority
    estimated_value: Decimal | None
    currency: str
    expected_close_date: date | None
    confirmed_requirements: list[str]
    won_value: Decimal | None
    lost_reason: str | None
    closed_at: datetime | None
    version: int
    open_tasks: int
    overdue_tasks: int
    created_at: datetime
    updated_at: datetime


class StageHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    previous_stage: Stage | None
    new_stage: Stage
    changed_by_user_id: uuid.UUID | None
    changed_at: datetime
    reason: str | None


class ConversionRequest(_Strict):
    idempotency_key: uuid.UUID = Field(description="Client-generated; retries with the same key never duplicate.")
    source_opportunity_id: uuid.UUID | None = Field(default=None, description="Research opportunity to pursue.")
    title: Title | None = None
    allow_additional: bool = Field(
        default=False, description="Create another opportunity although an open one exists for the same lead."
    )


class ConversionResult(BaseModel):
    created: bool
    opportunity: DealRead


# --- activities --------------------------------------------------------------------------------------------

ManualActivity = Literal["note", "call", "meeting", "email_sent", "email_received", "letter_sent", "other"]


class ActivityCreate(_Strict):
    activity_type: ManualActivity
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    occurred_at: datetime | None = Field(default=None, description="When it happened (default: now; never future).")
    contact_id: uuid.UUID | None = None


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sales_opportunity_id: uuid.UUID
    activity_type: ActivityType
    description: str
    contact_id: uuid.UUID | None
    details: dict[str, object]
    created_by_user_id: uuid.UUID | None
    occurred_at: datetime
    created_at: datetime


# --- contacts & compliance ------------------------------------------------------------------------------------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=5, max_length=50, pattern=r"^[0-9+()/ .-]+$")
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ContactCreate(_Strict):
    company_id: uuid.UUID
    name: Name
    role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    business_email: EmailStr | None = None
    business_phone: Phone | None = None
    source: ContactSource
    source_note: Note | None = None
    lawful_basis: LawfulBasis = LawfulBasis.NONE
    lawful_basis_reference: Note | None = None


class ContactUpdate(_Strict):
    expected_version: int = Field(ge=1)
    name: Name | None = None
    role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    business_email: EmailStr | None = None
    business_phone: Phone | None = None
    source_note: Note | None = None
    lawful_basis: LawfulBasis | None = None
    lawful_basis_reference: Note | None = None
    restriction_status: ContactRestriction | None = None

    @model_validator(mode="after")
    def _required_not_null(self) -> "ContactUpdate":
        _no_nulls(self, ("name", "restriction_status", "lawful_basis"))
        return self


class ChannelPermissionRead(BaseModel):
    channel: Channel
    allowed: bool
    reason: str


class ContactRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    role: str | None
    business_email: str | None
    business_phone: str | None
    source: ContactSource
    source_note: str | None
    lawful_basis: LawfulBasis
    lawful_basis_reference: str | None
    restriction_status: ContactRestriction
    permissions: list[ChannelPermissionRead]
    version: int
    created_at: datetime
    updated_at: datetime


class ContactReviewCreate(_Strict):
    channel: Channel
    decision: Literal["allowed", "not_allowed"]
    lawful_basis: LawfulBasis
    note: Note | None = None


class ContactReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID
    channel: Channel
    decision: Literal["allowed", "not_allowed"]
    lawful_basis: LawfulBasis
    note: str | None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime


class SuppressionCreate(_Strict):
    channel: Literal["email", "phone"]
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]
    reason: Note | None = None


class SuppressionResult(BaseModel):
    created: bool
    detail: str = "Only a hash of the address is stored; matching contacts are now suppressed."


# --- metrics ---------------------------------------------------------------------------------------------------


class SalesMetricsRead(BaseModel):
    qualified_leads: int
    converted_leads: int
    lead_to_opportunity_rate: float | None
    opportunities_total: int
    open_opportunities: int
    opportunities_by_stage: dict[str, int]
    pipeline_value: dict[str, Decimal]
    open_without_value: int
    won_count: int
    lost_count: int
    won_value: dict[str, Decimal]
    won_without_value: int
    opportunity_to_won_rate: float | None
    win_rate: float | None
    overdue_tasks: int
    open_tasks: int
    proposals_drafted: int
    proposals_sent: int
    definitions: dict[str, str]
