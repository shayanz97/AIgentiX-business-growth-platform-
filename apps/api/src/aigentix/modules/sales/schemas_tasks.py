"""API schemas for follow-up tasks, CSV export and CRM export."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
SuggestionKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,60}$")]
TaskStatusLiteral = Literal["open", "completed", "cancelled"]
TaskView = Literal["overdue", "today", "upcoming", "completed", "open", "all"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCreate(_Strict):
    sales_opportunity_id: uuid.UUID
    title: Title
    description: LongText = ""
    due_at: AwareDatetime
    assigned_user_id: uuid.UUID | None = Field(default=None, description="Defaults to the current user.")
    suggestion_key: SuggestionKey | None = None


class TaskUpdate(_Strict):
    title: Title | None = None
    description: LongText | None = None
    due_at: AwareDatetime | None = Field(default=None, description="Reschedule.")
    assigned_user_id: uuid.UUID | None = Field(default=None, description="null unassigns.")
    status: TaskStatusLiteral | None = None


class TaskRead(BaseModel):
    id: uuid.UUID
    sales_opportunity_id: uuid.UUID
    deal_title: str
    company_name: str | None
    assigned_user_id: uuid.UUID | None
    title: str
    description: str
    due_at: datetime
    status: TaskStatusLiteral
    overdue: bool
    suggestion_key: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskSuggestionRead(BaseModel):
    key: str
    title: str
    reason: str
    suggested_due_at: datetime


class TaskSummaryRead(BaseModel):
    overdue: int
    today: int
    upcoming: int
    open: int
    completed_last_7_days: int
    mine_open: int


# --- CRM -------------------------------------------------------------------------------------------------


class CRMProviderRead(BaseModel):
    name: str
    status: Literal["ok", "degraded", "unavailable"]
    detail: str
    test_double: bool


class CRMProvidersRead(BaseModel):
    providers: list[CRMProviderRead]
    note: str


class CRMExportRequest(_Strict):
    opportunity_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    confirm: bool = Field(description="Must be true: exporting sends business data to the external system.")
    include_contacts: bool = False


class CRMEntityResult(BaseModel):
    local_entity_type: Literal["company", "contact", "deal"]
    local_entity_id: uuid.UUID
    status: Literal["synced", "failed"]
    external_entity_id: str | None
    error: str | None


class CRMExportItem(BaseModel):
    opportunity_id: uuid.UUID
    status: Literal["synced", "failed"]
    company: CRMEntityResult
    deal: CRMEntityResult | None
    contacts: list[CRMEntityResult]
    skipped_contacts: int = Field(description="Contacts left out because they are suppressed or restricted.")


class CRMExportResult(BaseModel):
    provider: str
    items: list[CRMExportItem]


class CRMMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    local_entity_type: Literal["company", "contact", "deal"]
    local_entity_id: uuid.UUID
    external_entity_id: str | None
    sync_status: Literal["pending", "synced", "failed"]
    last_error: str | None
    last_synced_at: datetime | None
    updated_at: datetime


