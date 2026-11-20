"""Sales module: deal pipeline, activities, contacts & compliance, follow-ups, briefs, proposals, CRM export.

Reads Lead Intelligence data only through aigentix.platform.leads (never imports that module). Sends nothing:
every external action is performed by a person outside AIgentiX and only recorded here.
"""

from fastapi import APIRouter

from aigentix.modules.base import ModuleDescriptor, ModuleStatus
from aigentix.modules.sales.routes import briefs, crm, pipeline, proposals, tasks
from aigentix.modules.sales.workflows import SALES_WORKFLOWS

router = APIRouter()
for _sub in (pipeline.router, briefs.router, proposals.router, tasks.router, crm.router):
    router.include_router(_sub)

descriptor = ModuleDescriptor(
    key="sales",
    name="Sales Automation",
    description="Deal pipeline, sales intelligence briefs, proposal drafts and follow-ups (no automatic outreach).",
    status=ModuleStatus.AVAILABLE,
    router=router,
    workflows=SALES_WORKFLOWS,
)
