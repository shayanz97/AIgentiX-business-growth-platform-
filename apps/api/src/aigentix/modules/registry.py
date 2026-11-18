"""Explicit module registration. Add a module by appending its descriptor here."""

from aigentix.modules import lead_intelligence, sales
from aigentix.modules.base import ModuleDescriptor, ModuleStatus

MODULES: tuple[ModuleDescriptor, ...] = (
    lead_intelligence.descriptor,
    sales.descriptor,
    ModuleDescriptor(
        key="marketing",
        name="Marketing Studio",
        description="Content generation, campaign planning and SEO research.",
        status=ModuleStatus.PLANNED,
    ),
    ModuleDescriptor(
        key="analytics",
        name="Growth Analytics",
        description="Performance tracking, KPIs and improvement recommendations.",
        status=ModuleStatus.PLANNED,
    ),
)
