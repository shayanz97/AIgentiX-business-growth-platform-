"""The integration contract between the platform and a business module."""

import enum
from dataclasses import dataclass, field

from fastapi import APIRouter

from aigentix.platform.workflows.registry import WorkflowSpec


class ModuleStatus(enum.StrEnum):
    AVAILABLE = "available"
    PLANNED = "planned"


@dataclass(frozen=True)
class ModuleDescriptor:
    """What a module contributes to the platform. Registered explicitly in modules/registry.py.

    Rules: a module may import from `aigentix.core` and `aigentix.platform`, never from another module.
    Its tables must carry `organization_id` and its queries must be scoped by a TenantContext.
    """

    key: str
    name: str
    description: str
    status: ModuleStatus
    router: APIRouter | None = None
    workflows: dict[str, WorkflowSpec] = field(default_factory=dict)
