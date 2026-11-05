"""Authentication and tenant-resolution dependencies shared by all routers."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from aigentix.core.config import Settings, get_settings
from aigentix.core.db import get_db
from aigentix.core.errors import InvalidInput, NotAuthenticated
from aigentix.platform.identity import service as identity
from aigentix.platform.identity.models import User
from aigentix.platform.organizations.service import TenantContext, resolve_tenant

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

ORG_HEADER = "X-Organization-Id"


def get_current_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    user = identity.resolve_session(db, token) if token else None
    if user is None:
        raise NotAuthenticated("Authentication required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_tenant(
    db: DbSession,
    user: CurrentUser,
    organization_id: Annotated[
        str | None,
        Header(alias=ORG_HEADER, description="Active organization. Membership is verified server-side."),
    ] = None,
) -> TenantContext:
    if not organization_id:
        raise InvalidInput(f"The {ORG_HEADER} header is required", details={"header": ORG_HEADER})
    try:
        org_uuid = uuid.UUID(organization_id)
    except ValueError as exc:
        raise InvalidInput(f"The {ORG_HEADER} header must be a UUID") from exc
    return resolve_tenant(db, user=user, organization_id=org_uuid)


Tenant = Annotated[TenantContext, Depends(get_tenant)]


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def get_page_params(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(get_page_params)]
