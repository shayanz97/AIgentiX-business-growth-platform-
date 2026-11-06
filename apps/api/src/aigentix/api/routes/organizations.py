import uuid
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from aigentix.api.deps import CurrentUser, DbSession
from aigentix.api.schemas import MembershipRead, OrganizationRead, UserRead
from aigentix.platform.organizations import service as orgs

router = APIRouter(prefix="/organizations", tags=["organizations"])

OrgName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: OrgName


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: OrgName


class MemberRead(BaseModel):
    user: UserRead
    role: str


@router.get("", response_model=list[MembershipRead], operation_id="listOrganizations")
def list_organizations(user: CurrentUser, db: DbSession) -> list[MembershipRead]:
    """Organizations the caller belongs to, with the caller's role in each."""
    return [
        MembershipRead(organization=OrganizationRead.model_validate(m.organization), role=m.role)
        for m in orgs.list_memberships_for_user(db, user)
    ]


@router.post("", response_model=MembershipRead, status_code=status.HTTP_201_CREATED, operation_id="createOrganization")
def create_organization(body: OrganizationCreate, user: CurrentUser, db: DbSession) -> MembershipRead:
    membership = orgs.create_organization(db, name=body.name, owner=user)
    db.commit()
    return MembershipRead(organization=OrganizationRead.model_validate(membership.organization), role=membership.role)


@router.patch("/{organization_id}", response_model=OrganizationRead, operation_id="updateOrganization")
def update_organization(
    organization_id: uuid.UUID, body: OrganizationUpdate, user: CurrentUser, db: DbSession
) -> OrganizationRead:
    tenant = orgs.resolve_tenant(db, user=user, organization_id=organization_id)
    org = orgs.rename_organization(db, tenant, name=body.name)
    db.commit()
    return OrganizationRead.model_validate(org)


@router.get("/{organization_id}/members", response_model=list[MemberRead], operation_id="listMembers")
def list_members(organization_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[MemberRead]:
    tenant = orgs.resolve_tenant(db, user=user, organization_id=organization_id)
    return [MemberRead(user=UserRead.model_validate(m.user), role=m.role) for m in orgs.list_members(db, tenant)]
