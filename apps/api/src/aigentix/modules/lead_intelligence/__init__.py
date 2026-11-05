"""Lead Intelligence module.

Sprint 1: research projects (CRUD foundation).
Sprint 2+: company research, opportunity audit and scoring workflows (LangGraph), registered via
`workflow_handlers` below.
"""

from aigentix.modules.base import ModuleDescriptor, ModuleStatus
from aigentix.modules.lead_intelligence.router import router

# Declared now so the type name is stable; no handler until the workflow is implemented in Sprint 2.
COMPANY_RESEARCH_WORKFLOW = "lead_intelligence.company_research"

descriptor = ModuleDescriptor(
    key="lead_intelligence",
    name="Lead Intelligence",
    description="Company research, AI opportunity audits and lead scoring.",
    status=ModuleStatus.AVAILABLE,
    router=router,
    workflow_handlers={},
)
