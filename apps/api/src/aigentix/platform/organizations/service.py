"""Organizations, memberships and tenant access checks. Framework-independent."""

import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.errors import Forbidden
from aigentix.platform.identity.models import User
from aigentix.platform.organizations.models import Organization, OrganizationMembership, Role


@dataclass(frozen=True)
class TenantContext:
    """The authenticated user acting inside one organization they are a verified member of."""

    user: User
    organization: Organization
    role: Role

    @property
    def organization_id(self) -> uuid.UUID:
        return self.organization.id

    @property
    def is_owner(self) -> bool:
        return self.role is Role.OWNER


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{slug}-{secrets.token_hex(3)}"


def create_organization(db: Session, *, name: str, owner: User) -> OrganizationMembership:
    org = Organization(name=name.strip(), slug=_slugify(name))
    db.add(org)
    db.flush()
    membership = OrganizationMembership(organization_id=org.id, user_id=owner.id, role=Role.OWNER.value)
    db.add(membership)
    db.flush()
    db.refresh(membership)
    return membership


def add_member(db: Session, *, organization: Organization, user: User, role: Role) -> OrganizationMembership:
    membership = OrganizationMembership(organization_id=organization.id, user_id=user.id, role=role.value)
    db.add(membership)
    db.flush()
    return membership


def list_memberships_for_user(db: Session, user: User) -> list[OrganizationMembership]:
    stmt = (
        select(OrganizationMembership)
        .join(Organization)
        .where(OrganizationMembership.user_id == user.id)
        .order_by(Organization.name)
    )
    return list(db.scalars(stmt).unique())


def resolve_tenant(db: Session, *, user: User, organization_id: uuid.UUID) -> TenantContext:
    """Verify that `user` is a member of `organization_id`. Never trust client-supplied org IDs."""
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
        )
    )
    if membership is None:
        # Same response whether the organization exists or not: no existence oracle.
        raise Forbidden("You are not a member of this organization")
    return TenantContext(user=user, organization=membership.organization, role=Role(membership.role))


def rename_organization(db: Session, tenant: TenantContext, *, name: str) -> Organization:
    if not tenant.is_owner:
        raise Forbidden("Only organization owners can change organization settings")
    tenant.organization.name = name.strip()
    db.flush()
    return tenant.organization


def list_members(db: Session, tenant: TenantContext) -> list[OrganizationMembership]:
    stmt = (
        select(OrganizationMembership)
        .join(User)
        .where(OrganizationMembership.organization_id == tenant.organization_id)
        .order_by(User.email)
    )
    return list(db.scalars(stmt).unique())
