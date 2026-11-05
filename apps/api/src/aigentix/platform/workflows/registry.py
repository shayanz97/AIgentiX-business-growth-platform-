"""Workflow type registry. Business modules contribute handlers through their ModuleDescriptor."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aigentix.platform.workflows.models import WorkflowRun

# A handler receives the DB session and the run, and returns result metadata merged into the run.
WorkflowHandler = Callable[[Session, WorkflowRun], dict[str, Any] | None]

NOOP_WORKFLOW = "platform.noop"


def _noop(_db: Session, run: WorkflowRun) -> dict[str, Any]:
    """Platform self-test workflow: proves enqueue → worker → completion works end to end."""
    return {"echo": run.run_metadata.get("input")}


@dataclass
class WorkflowRegistry:
    handlers: dict[str, WorkflowHandler] = field(default_factory=dict)

    def register(self, workflow_type: str, handler: WorkflowHandler) -> None:
        if workflow_type in self.handlers:
            raise ValueError(f"Workflow type already registered: {workflow_type}")
        self.handlers[workflow_type] = handler

    def get(self, workflow_type: str) -> WorkflowHandler | None:
        return self.handlers.get(workflow_type)

    def __contains__(self, workflow_type: object) -> bool:
        return workflow_type in self.handlers


def build_registry() -> WorkflowRegistry:
    """Assemble the registry from platform workflows plus every registered module."""
    from aigentix.modules.registry import MODULES  # local import: modules depend on platform, not vice versa

    registry = WorkflowRegistry()
    registry.register(NOOP_WORKFLOW, _noop)
    for module in MODULES:
        for workflow_type, handler in module.workflow_handlers.items():
            registry.register(workflow_type, handler)
    return registry
