import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Page[T](BaseModel):
    """Standard paginated list envelope."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class MembershipRead(BaseModel):
    organization: OrganizationRead
    role: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
