"""ICP and scoring profiles: list, create, update (owner only; every change bumps the version)."""

import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.errors import Conflict, Forbidden, InvalidInput, NotFound
from aigentix.modules.lead_intelligence.domain.profiles import IcpConfig, ScoringConfig
from aigentix.modules.lead_intelligence.models import IcpProfile, ScoringProfile
from aigentix.platform.organizations.service import TenantContext

_CONFIG: dict[type, type[BaseModel]] = {IcpProfile: IcpConfig, ScoringProfile: ScoringConfig}
DEFAULT_NAME = "Default"
_DEFAULT_DESCRIPTION = {
    IcpProfile: "German SMEs (B2B and B2C, 1-249 employees) with a need in the target AI solution categories.",
    ScoringProfile: "Opportunity 35 · Fit 25 · Triggers 20 · Intent 20; freshness bands 30/90/180 days.",
}


def ensure_default[P: (IcpProfile, ScoringProfile)](db: Session, organization_id: uuid.UUID, model: type[P]) -> P:
    """The organization's default profile, created on first use (concurrency-safe)."""
    existing = db.scalar(select(model).where(model.organization_id == organization_id, model.is_default.is_(True)))
    if existing is not None:
        return existing
    config = _CONFIG[model]().model_dump(mode="json")
    db.execute(
        insert(model)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=DEFAULT_NAME,
            description=_DEFAULT_DESCRIPTION[model],
            version=1,
            is_default=True,
            config=config,
        )
        .on_conflict_do_nothing()
    )
    found = db.scalar(select(model).where(model.organization_id == organization_id, model.is_default.is_(True)))
    if found is None:  # a non-default profile already uses the name "Default"
        found = db.scalar(
            select(model).where(model.organization_id == organization_id).order_by(model.created_at).limit(1)
        )
        if found is None:  # pragma: no cover - insert conflicted on something else
            raise Conflict("Could not create the default profile")
        found.is_default = True
        db.flush()
    return found


def list_profiles[P: (IcpProfile, ScoringProfile)](db: Session, tenant: TenantContext, model: type[P]) -> list[P]:
    ensure_default(db, tenant.organization_id, model)
    return list(
        db.scalars(
            select(model)
            .where(model.organization_id == tenant.organization_id)
            .order_by(model.is_default.desc(), func.lower(model.name), model.id)
        )
    )


def get_profile[P: (IcpProfile, ScoringProfile)](
    db: Session, tenant: TenantContext, model: type[P], profile_id: uuid.UUID
) -> P:
    profile = db.scalar(select(model).where(model.id == profile_id, model.organization_id == tenant.organization_id))
    if profile is None:
        raise NotFound("Profile not found")
    return profile


def resolve[P: (IcpProfile, ScoringProfile)](
    db: Session, tenant: TenantContext, model: type[P], profile_id: uuid.UUID | None
) -> P:
    if profile_id is None:
        return ensure_default(db, tenant.organization_id, model)
    return get_profile(db, tenant, model, profile_id)


def _validated[P: (IcpProfile, ScoringProfile)](model: type[P], config: dict[str, Any]) -> dict[str, Any]:
    try:
        return _CONFIG[model].model_validate(config).model_dump(mode="json")
    except ValidationError as exc:
        # Report locations and messages only, never the submitted values.
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors())
        raise InvalidInput(f"Invalid profile configuration: {problems}") from None


def _require_owner(tenant: TenantContext) -> None:
    if not tenant.is_owner:
        raise Forbidden("Only organization owners can change scoring and ICP profiles")


def _set_default[P: (IcpProfile, ScoringProfile)](db: Session, model: type[P], profile: P) -> None:
    db.execute(
        update(model)
        .where(model.organization_id == profile.organization_id, model.id != profile.id, model.is_default.is_(True))
        .values(is_default=False)
    )
    db.flush()
    profile.is_default = True


def create_profile[P: (IcpProfile, ScoringProfile)](
    db: Session,
    tenant: TenantContext,
    model: type[P],
    *,
    name: str,
    description: str,
    config: dict[str, Any] | None,
    make_default: bool,
) -> P:
    _require_owner(tenant)
    ensure_default(db, tenant.organization_id, model)
    profile = model(
        organization_id=tenant.organization_id,
        name=name.strip(),
        description=description.strip(),
        version=1,
        is_default=False,
        config=_validated(model, config or {}),
        updated_by_user_id=tenant.user.id,
    )
    db.add(profile)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A profile with this name already exists") from None
    if make_default:
        _set_default(db, model, profile)
        db.flush()
    return profile


def update_profile[P: (IcpProfile, ScoringProfile)](
    db: Session,
    tenant: TenantContext,
    model: type[P],
    profile_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
    config: dict[str, Any] | None,
    make_default: bool | None,
) -> P:
    _require_owner(tenant)
    profile = db.scalar(
        select(model).where(model.id == profile_id, model.organization_id == tenant.organization_id).with_for_update()
    )
    if profile is None:
        raise NotFound("Profile not found")
    changed = False
    if name is not None and name.strip() != profile.name:
        profile.name, changed = name.strip(), True
    if description is not None and description.strip() != profile.description:
        profile.description, changed = description.strip(), True
    if config is not None:
        validated = _validated(model, config)
        if validated != profile.config:
            profile.config, changed = validated, True
    if make_default is True and not profile.is_default:
        _set_default(db, model, profile)
    elif make_default is False and profile.is_default:
        raise InvalidInput("Make another profile the default instead of unsetting the default")
    if changed:
        profile.version += 1  # scores keep the version (and a snapshot) they were computed with
        profile.updated_by_user_id = tenant.user.id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A profile with this name already exists") from None
    return profile
