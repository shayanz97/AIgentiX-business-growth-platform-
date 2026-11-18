"""The organization's service catalogue. Prices reach proposals only when explicitly approved (owner only)."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Conflict, Forbidden, InvalidInput, NotFound
from aigentix.modules.sales.models import SalesServiceOffering
from aigentix.platform.organizations.service import TenantContext

_FIELDS = {
    "name",
    "description",
    "solution_category",
    "price_amount",
    "price_unit",
    "currency",
    "price_approved",
    "active",
}


def _require_owner(tenant: TenantContext) -> None:
    if not tenant.is_owner:
        raise Forbidden("Only organization owners can change the service catalogue and its prices")


def _name_taken(db: Session, tenant: TenantContext, name: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(SalesServiceOffering.id).where(
        SalesServiceOffering.organization_id == tenant.organization_id,
        func.lower(SalesServiceOffering.name) == name.lower(),
    )
    if exclude is not None:
        query = query.where(SalesServiceOffering.id != exclude)
    return db.scalar(query) is not None


def _check(offering: SalesServiceOffering) -> None:
    if offering.price_approved and offering.price_amount is None:
        raise InvalidInput("An approved price needs a price amount")


def list_offerings(db: Session, tenant: TenantContext, *, active: bool | None = None) -> list[SalesServiceOffering]:
    query = select(SalesServiceOffering).where(SalesServiceOffering.organization_id == tenant.organization_id)
    if active is not None:
        query = query.where(SalesServiceOffering.active.is_(active))
    return list(db.scalars(query.order_by(func.lower(SalesServiceOffering.name), SalesServiceOffering.id)))


def create_offering(db: Session, tenant: TenantContext, **fields: Any) -> SalesServiceOffering:
    _require_owner(tenant)
    if _name_taken(db, tenant, fields["name"]):
        raise Conflict("A service with this name already exists")
    offering = SalesServiceOffering(organization_id=tenant.organization_id, **_normalise(fields))
    _check(offering)
    db.add(offering)
    db.flush()
    return offering


def update_offering(
    db: Session, tenant: TenantContext, offering_id: uuid.UUID, changes: dict[str, Any]
) -> SalesServiceOffering:
    _require_owner(tenant)
    offering = db.scalar(
        select(SalesServiceOffering)
        .where(SalesServiceOffering.id == offering_id, SalesServiceOffering.organization_id == tenant.organization_id)
        .with_for_update()
    )
    if offering is None:
        raise NotFound("Service not found")
    if set(changes) - _FIELDS:
        raise InvalidInput("Unknown field")
    if changes.get("name") and _name_taken(db, tenant, changes["name"], exclude=offering.id):
        raise Conflict("A service with this name already exists")
    previous_price = offering.price_amount
    for key, value in _normalise(changes).items():
        if key in ("name", "currency", "price_approved", "active", "description") and value is None:
            raise InvalidInput(f"{key} cannot be empty")
        setattr(offering, key, value)
    # A changed price is no longer the approved one unless approval is given in the same change.
    if offering.price_amount != previous_price and "price_approved" not in changes:
        offering.price_approved = False
    _check(offering)
    offering.updated_at = utcnow()
    db.flush()
    return offering


def _normalise(fields: dict[str, Any]) -> dict[str, Any]:
    out = dict(fields)
    if out.get("currency"):
        out["currency"] = str(out["currency"]).upper()
    return out
