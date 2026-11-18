"""API schemas for sales briefs, proposals (+ revisions) and the service catalogue."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from aigentix.modules.sales.schemas import Currency, Money, Title

SectionKey = Literal[
    "executive_summary",
    "business_context",
    "identified_opportunity",
    "proposed_solution",
    "scope_and_deliverables",
    "implementation_approach",
    "customer_dependencies",
    "assumptions",
    "expected_benefits",
    "success_criteria",
    "timeline_estimate",
    "commercial_terms",
    "next_steps",
]
SectionStatus = Literal["draft", "needs_input"]
EditText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
EditItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowInfo(BaseModel):
    id: uuid.UUID
    status: str
    progress: int
    current_step: str | None
    error_message: str | None
    attempts: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    created_at: datetime
    completed_at: datetime | None


# --- briefs -----------------------------------------------------------------------------------------------------


class BriefEdit(_Strict):
    """Human edits, stored separately from the AI content (which is never overwritten). Omitted = unchanged."""

    company_summary: EditText | None = None
    observed_situation: list[EditItem] | None = Field(default=None, max_length=20)
    main_opportunity_title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    main_opportunity: EditText | None = None
    supporting_evidence: list[EditItem] | None = Field(default=None, max_length=20)
    assumptions_and_uncertainty: list[EditItem] | None = Field(default=None, max_length=20)
    potential_impact: list[EditItem] | None = Field(default=None, max_length=20)
    suggested_solution: EditText | None = None
    implementation_requirements: list[EditItem] | None = Field(default=None, max_length=20)
    discovery_questions: list[EditItem] | None = Field(default=None, max_length=20)
    recommended_next_action: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    notes: EditText | None = None


class BriefUpdate(_Strict):
    expected_version: int = Field(ge=1, description="Version the change is based on (optimistic locking).")
    edited_content: BriefEdit | None = None
    status: Literal["approved", "draft"] | None = None


class BriefRead(BaseModel):
    id: uuid.UUID
    sales_opportunity_id: uuid.UUID
    status: Literal["generating", "draft", "approved", "superseded", "failed"]
    content: dict[str, Any] = Field(description="Validated AI output. Plain text: render as text, never as HTML.")
    edited_content: dict[str, Any] | None
    source_evidence_ids: list[uuid.UUID]
    quality_flags: list[str]
    generation_version: str
    model: str | None
    message: str | None
    created_by_user_id: uuid.UUID | None
    edited_by_user_id: uuid.UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    workflow: WorkflowInfo | None


# --- proposals -------------------------------------------------------------------------------------------------


class ProposalCreate(_Strict):
    brief_id: uuid.UUID | None = Field(default=None, description="Default: the latest approved, else draft brief.")
    title: Title | None = None


class ProposalSection(BaseModel):
    key: SectionKey
    title: str
    body: str
    status: SectionStatus


class SectionEdit(_Strict):
    key: SectionKey
    body: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    status: SectionStatus | None = None


ProposalStatusName = Literal["generating", "draft", "ready", "sent", "accepted", "declined", "failed"]


class ProposalUpdate(_Strict):
    expected_version: int = Field(ge=1)
    title: Title | None = None
    sections: list[SectionEdit] | None = Field(default=None, max_length=13)
    assumptions: list[EditItem] | None = Field(default=None, max_length=30)
    note: Note | None = Field(default=None, description="Why this revision was made.")
    status: Literal["draft", "ready", "sent", "accepted", "declined"] | None = None
    sent_at: datetime | None = Field(
        default=None, description="When a person sent it outside AIgentiX (required for status 'sent'; not future)."
    )


class ProposalRead(BaseModel):
    id: uuid.UUID
    sales_opportunity_id: uuid.UUID
    brief_id: uuid.UUID | None
    title: str
    status: ProposalStatusName
    current_revision: int
    sent_at: datetime | None
    message: str | None
    created_by_user_id: uuid.UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    workflow: WorkflowInfo | None


class ProposalDetail(ProposalRead):
    sections: list[ProposalSection]
    assumptions: list[str]
    quality_flags: list[str]
    revision_origin: Literal["ai", "human"] | None
    model: str | None
    generation_version: str | None


class RevisionRead(BaseModel):
    id: uuid.UUID
    revision: int
    origin: Literal["ai", "human"]
    sections: list[ProposalSection]
    assumptions: list[str]
    quality_flags: list[str]
    source_evidence_ids: list[uuid.UUID]
    model: str | None
    generation_version: str | None
    note: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime


# --- service catalogue ------------------------------------------------------------------------------------------

OfferingName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
PriceUnit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class OfferingCreate(_Strict):
    name: OfferingName
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""
    solution_category: Category | None = None
    price_amount: Money | None = None
    price_unit: PriceUnit | None = None
    currency: Currency = "EUR"
    price_approved: bool = Field(default=False, description="Only approved prices are used in proposals.")
    active: bool = True


class OfferingUpdate(_Strict):
    name: OfferingName | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    solution_category: Category | None = None
    price_amount: Money | None = None
    price_unit: PriceUnit | None = None
    currency: Currency | None = None
    price_approved: bool | None = None
    active: bool | None = None


class OfferingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    solution_category: str | None
    price_amount: Decimal | None
    price_unit: str | None
    currency: str
    price_approved: bool
    active: bool
    created_at: datetime
    updated_at: datetime
