"""Sales workflow types (registered in the module descriptor)."""

from aigentix.modules.sales.workflows.constants import BRIEF_WORKFLOW, PROPOSAL_WORKFLOW
from aigentix.modules.sales.workflows.generation import make_brief_handler, make_proposal_handler
from aigentix.platform.workflows.registry import WorkflowSpec

SALES_WORKFLOWS: dict[str, WorkflowSpec] = {
    BRIEF_WORKFLOW: WorkflowSpec(handler=make_brief_handler(), max_concurrent=4),
    PROPOSAL_WORKFLOW: WorkflowSpec(handler=make_proposal_handler(), max_concurrent=4),
}
