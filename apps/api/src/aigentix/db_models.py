"""Imports every ORM model so Base.metadata is complete (used by Alembic and tests)."""

from aigentix.core.db import Base
from aigentix.modules.lead_intelligence.models import ResearchProject
from aigentix.platform.identity.models import User, UserSession
from aigentix.platform.organizations.models import Organization, OrganizationMembership
from aigentix.platform.workflows.models import WorkflowRun

__all__ = [
    "Base",
    "Organization",
    "OrganizationMembership",
    "ResearchProject",
    "User",
    "UserSession",
    "WorkflowRun",
]
