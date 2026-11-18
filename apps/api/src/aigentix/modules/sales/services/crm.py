"""Explicit, owner-confirmed export of deals to an external CRM. One-way, on demand, no background sync.

Each exported deal upserts its company, optionally its eligible contacts (never suppressed or restricted ones),
then the deal. Every step is recorded in `sales_crm_mappings` (pending -> synced | failed). Re-exporting reuses the
stored external ids, so records are updated rather than duplicated. A provider error is a failed mapping, never a
success.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Forbidden, InvalidInput, NotFound
from aigentix.modules.sales.integrations.crm import (
    CompanyPayload,
    ContactPayload,
    CRMProvider,
    CRMProviderError,
    DealPayload,
    configured_names,
    get_crm_provider,
)
from aigentix.modules.sales.models import ContactRestriction, ExternalCRMMapping, SalesContact, SalesOpportunity
from aigentix.modules.sales.services.common import audit, get_deal
from aigentix.modules.sales.services.contacts import is_suppressed, permissions
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.organizations.service import TenantContext

MAX_EXPORT = 50
_SECRET = re.compile(r"(?i)(bearer\s+\S+|(?:token|key|secret|password|authorization)\s*[=:]\s*\S+)")


def sanitize_error(exc: Exception) -> str:
    """A short message safe to store and show: provider messages are scrubbed of credential-looking text; any
    unexpected exception is reduced to its class name."""
    if isinstance(exc, CRMProviderError):
        return _SECRET.sub("[redacted]", " ".join(str(exc).split()))[:500] or "Provider error"
    return f"Unexpected provider error ({type(exc).__name__})"


@dataclass(frozen=True)
class EntityResult:
    local_entity_type: str
    local_entity_id: uuid.UUID
    status: str
    external_entity_id: str | None
    error: str | None


@dataclass(frozen=True)
class ItemResult:
    opportunity_id: uuid.UUID
    status: str
    company: EntityResult
    deal: EntityResult | None
    contacts: list[EntityResult]
    skipped_contacts: int


def require_provider(name: str) -> CRMProvider:
    provider = get_crm_provider(name)
    if provider is None:
        raise NotFound("CRM provider is not configured")  # never pretend a provider exists
    return provider


def provider_overview() -> list[tuple[str, str, str, bool]]:
    """(name, status, detail, test_double) for every configured provider name."""
    rows = []
    for name in configured_names():
        provider = get_crm_provider(name)
        if provider is None:
            rows.append((name, "unavailable", "No adapter for this provider is bundled.", False))
            continue
        try:
            health = provider.health()
            rows.append((name, health.status, health.detail[:200], provider.test_double))
        except Exception as exc:
            rows.append((name, "unavailable", sanitize_error(exc), provider.test_double))
    return rows


def _mapping(db: Session, org: uuid.UUID, provider: str, entity_type: str, local_id: uuid.UUID) -> ExternalCRMMapping:
    mapping = db.scalar(
        select(ExternalCRMMapping).where(
            ExternalCRMMapping.organization_id == org,
            ExternalCRMMapping.provider == provider,
            ExternalCRMMapping.local_entity_type == entity_type,
            ExternalCRMMapping.local_entity_id == local_id,
        )
    )
    if mapping is None:
        mapping = ExternalCRMMapping(
            organization_id=org,
            provider=provider,
            local_entity_type=entity_type,
            local_entity_id=local_id,
            sync_status="pending",
        )
        db.add(mapping)
        db.flush()
    else:
        mapping.sync_status = "pending"
    return mapping


def _run(
    db: Session,
    org: uuid.UUID,
    provider: CRMProvider,
    entity_type: str,
    local_id: uuid.UUID,
    upsert: Callable[[str | None], str],
) -> EntityResult:
    mapping = _mapping(db, org, provider.name, entity_type, local_id)
    try:
        external_id = upsert(mapping.external_entity_id)
        if not external_id:
            raise CRMProviderError("Provider returned no external id")
    except Exception as exc:
        mapping.sync_status = "failed"
        mapping.last_error = sanitize_error(exc)
        db.commit()
        return EntityResult(entity_type, local_id, "failed", mapping.external_entity_id, mapping.last_error)
    try:
        with db.begin_nested():
            mapping.external_entity_id = external_id
            mapping.sync_status = "synced"
            mapping.last_error = None
            mapping.last_synced_at = utcnow()
            db.flush()
    except IntegrityError:
        # The provider returned an id that is already mapped to another local record: never overwrite it.
        mapping = _mapping(db, org, provider.name, entity_type, local_id)
        mapping.sync_status = "failed"
        mapping.last_error = "The external id is already mapped to another record"
        db.commit()
        return EntityResult(entity_type, local_id, "failed", mapping.external_entity_id, mapping.last_error)
    # Commit right after each external write: the external id must survive a later failure in this export,
    # otherwise the next export would create duplicates in the CRM.
    db.commit()
    return EntityResult(entity_type, local_id, "synced", external_id, None)


def _contact_call(provider: CRMProvider, payload: ContactPayload, ext: str | None) -> str:
    return provider.upsert_contact(payload, ext)


def _eligible_contacts(db: Session, tenant: TenantContext, company_id: uuid.UUID) -> tuple[list[SalesContact], int]:
    contacts = list(
        db.scalars(
            select(SalesContact)
            .where(SalesContact.organization_id == tenant.organization_id, SalesContact.company_id == company_id)
            .order_by(SalesContact.name, SalesContact.id)
            .limit(200)
        )
    )
    # Personal data leaves AIgentiX only for contacts a person reviewed as contactable on at least one channel
    # (which also excludes suppressed and restricted contacts): invariant 14.
    ok = [
        c
        for c in contacts
        if c.restriction_status == ContactRestriction.UNVERIFIED.value
        and not is_suppressed(db, tenant.organization_id, c)
        and any(p.permission.allowed for p in permissions(db, tenant, c))
    ]
    return ok, len(contacts) - len(ok)


def _export_deal(
    db: Session, tenant: TenantContext, provider: CRMProvider, deal: SalesOpportunity, include_contacts: bool
) -> ItemResult:
    org = tenant.organization_id
    names = get_lead_data_provider().company_names(db, org, {deal.company_id})
    ref = names.get(deal.company_id)
    if ref is None:
        raise NotFound("Company not found")
    company_payload = CompanyPayload(str(deal.company_id), ref.name, ref.canonical_domain, ref.website_url)
    company = _run(
        db, org, provider, "company", deal.company_id, lambda ext: provider.upsert_company(company_payload, ext)
    )
    contacts: list[EntityResult] = []
    skipped = 0
    deal_result: EntityResult | None = None
    if company.status == "synced" and company.external_entity_id:
        company_ext = company.external_entity_id
        if include_contacts:
            eligible, skipped = _eligible_contacts(db, tenant, deal.company_id)
            for c in eligible:
                payload = ContactPayload(str(c.id), c.name, c.role, c.business_email, c.business_phone, company_ext)
                contacts.append(_run(db, org, provider, "contact", c.id, partial(_contact_call, provider, payload)))
        deal_payload = DealPayload(
            str(deal.id),
            deal.title,
            deal.stage,
            deal.status,
            deal.priority,
            deal.estimated_value,
            deal.currency,
            deal.expected_close_date,
            deal.won_value,
            deal.lost_reason,
            company_ext,
        )
        deal_result = _run(db, org, provider, "deal", deal.id, lambda ext: provider.upsert_deal(deal_payload, ext))
    status = "synced" if company.status == "synced" and deal_result and deal_result.status == "synced" else "failed"
    audit(
        db,
        tenant,
        deal,
        f"Exported to CRM provider '{provider.name}' by a member ({status})",
        provider=provider.name,
        status=status,
        external_deal_id=deal_result.external_entity_id if deal_result else None,
        contacts_exported=sum(1 for c in contacts if c.status == "synced"),
    )
    return ItemResult(deal.id, status, company, deal_result, contacts, skipped)


def export_deals(
    db: Session,
    tenant: TenantContext,
    provider_name: str,
    *,
    opportunity_ids: list[uuid.UUID],
    confirm: bool,
    include_contacts: bool,
) -> list[ItemResult]:
    if not tenant.is_owner:
        raise Forbidden("Only organization owners can export to an external CRM")
    if not confirm:
        raise InvalidInput("Confirm the export (confirm=true): business data will be sent to the external system")
    if len(opportunity_ids) > MAX_EXPORT:
        raise InvalidInput(f"Export at most {MAX_EXPORT} opportunities at a time")
    provider = require_provider(provider_name)
    deals = [get_deal(db, tenant, i) for i in dict.fromkeys(opportunity_ids)]  # 404 for any foreign id, no dupes
    return [_export_deal(db, tenant, provider, deal, include_contacts) for deal in deals]


def list_mappings(
    db: Session,
    tenant: TenantContext,
    *,
    provider: str | None,
    local_entity_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[ExternalCRMMapping], int]:
    conditions = [ExternalCRMMapping.organization_id == tenant.organization_id]
    if provider:
        conditions.append(ExternalCRMMapping.provider == provider.strip().lower())
    if local_entity_type:
        conditions.append(ExternalCRMMapping.local_entity_type == local_entity_type)
    total = db.scalar(select(func.count()).select_from(ExternalCRMMapping).where(*conditions)) or 0
    rows = db.scalars(
        select(ExternalCRMMapping)
        .where(*conditions)
        .order_by(ExternalCRMMapping.updated_at.desc(), ExternalCRMMapping.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total)
