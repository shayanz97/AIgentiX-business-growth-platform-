"""Lead Intelligence module: companies, website research, evidence and AI opportunity audits."""

from fastapi import APIRouter

from aigentix.modules.base import ModuleDescriptor, ModuleStatus
from aigentix.modules.lead_intelligence.config import get_research_settings
from aigentix.modules.lead_intelligence.routes import companies, opportunities, projects, research_runs, scoring
from aigentix.modules.lead_intelligence.workflows.constants import ENRICHMENT_WORKFLOW, RESEARCH_WORKFLOW
from aigentix.modules.lead_intelligence.workflows.enrichment import make_enrichment_handler
from aigentix.modules.lead_intelligence.workflows.research import make_research_handler
from aigentix.platform.workflows.registry import WorkflowSpec

router = APIRouter()
for _sub in (projects.router, companies.router, research_runs.router, opportunities.router, scoring.router):
    router.include_router(_sub)

descriptor = ModuleDescriptor(
    key="lead_intelligence",
    name="Lead Intelligence",
    description="Company research, AI opportunity audits and lead scoring.",
    status=ModuleStatus.AVAILABLE,
    router=router,
    workflows={
        RESEARCH_WORKFLOW: WorkflowSpec(
            handler=make_research_handler(),
            max_concurrent=get_research_settings().research_max_concurrent_runs,
        ),
        ENRICHMENT_WORKFLOW: WorkflowSpec(
            handler=make_enrichment_handler(),
            max_concurrent=get_research_settings().research_max_concurrent_runs,
        ),
    },
)
