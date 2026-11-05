import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, UrlConstraints

from aigentix.modules.lead_intelligence.models import ProjectStatus

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
WebsiteUrl = Annotated[AnyHttpUrl, UrlConstraints(max_length=2048, allowed_schemes=["http", "https"])]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""
    target_url: WebsiteUrl | None = Field(
        default=None, description="Company website to research (used from Sprint 2)."
    )


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str
    target_url: str | None
    status: ProjectStatus
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
