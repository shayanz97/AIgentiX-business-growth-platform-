"""Business contacts, per-channel eligibility reviews and suppressions (opt-outs).

Contacts are entered by people with their source; nothing is scraped. `permission()` is the only way to ask
whether a contact may be approached through a channel (see domain/compliance.py).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.sales.domain.compliance import (
    Permission,
    Review,
    basis_valid_for,
    contact_permission,
    suppression_hash,
)
from aigentix.modules.sales.models import (
    Channel,
    ContactRestriction,
    ContactSource,
    LawfulBasis,
    SalesContact,
    SalesContactReview,
    SalesSuppression,
)
from aigentix.modules.sales.services.common import check_version
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext


def get_contact(db: Session, tenant: TenantContext, contact_id: uuid.UUID) -> SalesContact:
    contact = db.scalar(
        select(SalesContact).where(
            SalesContact.id == contact_id, SalesContact.organization_id == tenant.organization_id
        )
    )
    if contact is None:
        raise NotFound("Contact not found")
    return contact


def create_contact(
    db: Session,
    tenant: TenantContext,
    *,
    company_id: uuid.UUID,
    name: str,
    role: str | None,
    business_email: str | None,
    business_phone: str | None,
    source: ContactSource,
    source_note: str | None,
    lawful_basis: LawfulBasis,
    lawful_basis_reference: str | None,
) -> SalesContact:
    if not get_lead_data_provider().company_exists(db, tenant.organization_id, company_id):
        raise NotFound("Company not found")
    if lawful_basis != LawfulBasis.NONE and not (lawful_basis_reference or "").strip():
        raise InvalidInput("Document where the legal basis is recorded (lawful_basis_reference)")
    contact = SalesContact(
        organization_id=tenant.organization_id,
        company_id=company_id,
        name=name.strip(),
        role=(role or "").strip() or None,
        business_email=(business_email or "").strip().lower() or None,
        business_phone=(business_phone or "").strip() or None,
        source=source.value,
        source_note=(source_note or "").strip() or None,
        lawful_basis=lawful_basis.value,
        lawful_basis_reference=(lawful_basis_reference or "").strip() or None,
        created_by_user_id=tenant.user.id,
    )
    if is_suppressed(db, tenant.organization_id, contact):
        contact.restriction_status = ContactRestriction.SUPPRESSED.value
    db.add(contact)
    db.flush()
    return contact


def list_contacts(db: Session, tenant: TenantContext, *, company_id: uuid.UUID | None) -> list[SalesContact]:
    query = select(SalesContact).where(SalesContact.organization_id == tenant.organization_id)
    if company_id is not None:
        query = query.where(SalesContact.company_id == company_id)
    return list(db.scalars(query.order_by(SalesContact.name, SalesContact.id).limit(500)))


_EDITABLE = {
    "name",
    "role",
    "business_email",
    "business_phone",
    "source_note",
    "lawful_basis",
    "lawful_basis_reference",
    "restriction_status",
}


def update_contact(
    db: Session, tenant: TenantContext, contact_id: uuid.UUID, changes: dict[str, Any], *, expected_version: int
) -> SalesContact:
    contact = get_contact(db, tenant, contact_id)
    check_version(contact.version, expected_version)
    if set(changes) - _EDITABLE:
        raise InvalidInput("Unknown contact field")
    for key, value in changes.items():
        value = value.value if hasattr(value, "value") else value
        if key == "business_email" and value:
            value = str(value).strip().lower()
        setattr(contact, key, value)
    if contact.lawful_basis != LawfulBasis.NONE.value and not contact.lawful_basis_reference:
        raise InvalidInput("Document where the legal basis is recorded (lawful_basis_reference)")
    if is_suppressed(db, tenant.organization_id, contact):
        contact.restriction_status = ContactRestriction.SUPPRESSED.value  # an opt-out cannot be edited away
    contact.version += 1
    db.flush()
    return contact


def _addresses(contact: SalesContact) -> dict[Channel, str | None]:
    return {
        Channel.EMAIL: contact.business_email,
        Channel.PHONE: contact.business_phone,
        Channel.LINKEDIN: contact.name,  # LinkedIn has no stored address; the review itself is the record
        Channel.LETTER: contact.name,
    }


def is_suppressed(db: Session, org: uuid.UUID, contact: SalesContact, channel: Channel | None = None) -> bool:
    hashes = [
        suppression_hash(ch, value)
        for ch, value in _addresses(contact).items()
        if value and ch in (Channel.EMAIL, Channel.PHONE) and (channel is None or ch == channel)
    ]
    if not hashes:
        return False
    return (
        db.scalar(
            select(SalesSuppression.id).where(
                SalesSuppression.organization_id == org, SalesSuppression.value_hash.in_(hashes)
            )
        )
        is not None
    )


def add_suppression(db: Session, tenant: TenantContext, *, channel: Channel, value: str, reason: str | None) -> bool:
    """Record an opt-out. Only a hash is stored; matching contacts become suppressed. Returns True if new."""
    if channel not in (Channel.EMAIL, Channel.PHONE):
        raise InvalidInput("Suppressions are recorded for e-mail addresses and phone numbers")
    if not value.strip():
        raise InvalidInput("Provide the address or number to suppress")
    value_hash = suppression_hash(channel, value)
    new_id = db.scalar(
        insert(SalesSuppression)
        .values(
            id=uuid.uuid4(),
            organization_id=tenant.organization_id,
            channel=channel.value,
            value_hash=value_hash,
            reason=(reason or "").strip() or None,
            created_by_user_id=tenant.user.id,
        )
        .on_conflict_do_nothing(constraint="uq_sales_suppressions_value")
        .returning(SalesSuppression.id)
    )
    for contact in db.scalars(select(SalesContact).where(SalesContact.organization_id == tenant.organization_id)):
        if is_suppressed(db, tenant.organization_id, contact):
            contact.restriction_status = ContactRestriction.SUPPRESSED.value
    db.flush()
    return new_id is not None


def review_contact(
    db: Session,
    tenant: TenantContext,
    contact_id: uuid.UUID,
    *,
    channel: Channel,
    decision: str,
    lawful_basis: LawfulBasis,
    note: str | None,
) -> SalesContactReview:
    contact = get_contact(db, tenant, contact_id)
    if decision == "allowed":
        if contact.restriction_status == ContactRestriction.SUPPRESSED.value or is_suppressed(
            db, tenant.organization_id, contact
        ):
            raise InvalidInput("The contact is suppressed (opt-out); it cannot be allowed for any channel")
        if not basis_valid_for(channel, lawful_basis):
            raise InvalidInput(f"{lawful_basis.value} is not a sufficient legal basis for {channel.value}")
        if not contact.lawful_basis_reference and lawful_basis != LawfulBasis.LEGITIMATE_INTEREST:
            raise InvalidInput("Record where the consent or relationship is documented on the contact first")
    review = SalesContactReview(
        organization_id=tenant.organization_id,
        contact_id=contact.id,
        channel=channel.value,
        decision=decision,
        lawful_basis=lawful_basis.value,
        note=(note or "").strip() or None,
        reviewed_by_user_id=tenant.user.id,
    )
    db.add(review)
    db.flush()
    return review


def reviews_for(db: Session, tenant: TenantContext, contact_id: uuid.UUID) -> list[SalesContactReview]:
    get_contact(db, tenant, contact_id)
    return list(
        db.scalars(
            select(SalesContactReview)
            .where(
                SalesContactReview.contact_id == contact_id,
                SalesContactReview.organization_id == tenant.organization_id,
            )
            .order_by(SalesContactReview.reviewed_at.desc(), SalesContactReview.id.desc())
        )
    )


@dataclass(frozen=True)
class ChannelPermission:
    channel: Channel
    permission: Permission


def permission(db: Session, tenant: TenantContext, contact: SalesContact, channel: Channel) -> Permission:
    """THE gate: any feature that prepares outreach must call this (suppression always wins)."""
    latest = db.scalar(
        select(SalesContactReview)
        .where(
            SalesContactReview.organization_id == tenant.organization_id,
            SalesContactReview.contact_id == contact.id,
            SalesContactReview.channel == channel.value,
        )
        .order_by(SalesContactReview.reviewed_at.desc(), SalesContactReview.id.desc())
        .limit(1)
    )
    return contact_permission(
        channel,
        restriction=ContactRestriction(contact.restriction_status),
        suppressed=is_suppressed(db, tenant.organization_id, contact, channel),
        has_address=bool(_addresses(contact)[channel]),
        latest_review=Review(Channel(latest.channel), latest.decision, LawfulBasis(latest.lawful_basis))
        if latest
        else None,
    )


def permissions(db: Session, tenant: TenantContext, contact: SalesContact) -> list[ChannelPermission]:
    return [ChannelPermission(ch, permission(db, tenant, contact, ch)) for ch in Channel]
