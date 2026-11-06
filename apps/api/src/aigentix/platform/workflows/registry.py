"""Workflow type registry. Business modules contribute handlers through their ModuleDescriptor."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult

WorkflowHandler = Callable[[WorkflowContext], WorkflowResult]

NOOP_WORKFLOW = "platform.noop"


def _noop(ctx: WorkflowContext) -> WorkflowResult:
    """Platform self-test workflow: proves enqueue → worker → completion works end to end."""
    ctx.checkpoint("noop", 50)
    return WorkflowResult(summary={"echo": ctx.run.run_metadata.get("input")})


@dataclass(frozen=True)
class WorkflowSpec:
    handler: WorkflowHandler
    max_concurrent: int | None = None  # across all workers; None = unlimited


@dataclass
class WorkflowRegistry:
    specs: dict[str, WorkflowSpec] = field(default_factory=dict)

    def register(self, workflow_type: str, handler: WorkflowHandler, *, max_concurrent: int | None = None) -> None:
        if workflow_type in self.specs:
            raise ValueError(f"Workflow type already registered: {workflow_type}")
        self.specs[workflow_type] = WorkflowSpec(handler=handler, max_concurrent=max_concurrent)

    def get(self, workflow_type: str) -> WorkflowHandler | None:
        spec = self.specs.get(workflow_type)
        return spec.handler if spec else None

    @property
    def handlers(self) -> dict[str, WorkflowHandler]:
        return {name: spec.handler for name, spec in self.specs.items()}

    @property
    def concurrency_limits(self) -> dict[str, int]:
        return {name: s.max_concurrent for name, s in self.specs.items() if s.max_concurrent is not None}

    def __contains__(self, workflow_type: object) -> bool:
        return workflow_type in self.specs


def build_registry() -> WorkflowRegistry:
    """Assemble the registry from platform workflows plus every registered module."""
    from aigentix.modules.registry import MODULES  # local import: modules depend on platform, not vice versa

    registry = WorkflowRegistry()
    registry.register(NOOP_WORKFLOW, _noop)
    for module in MODULES:
        for workflow_type, spec in module.workflows.items():
            registry.register(workflow_type, spec.handler, max_concurrent=spec.max_concurrent)
    return registry


@lru_cache
def default_registry() -> WorkflowRegistry:
    """Process-wide registry (validated workflow types for enqueueing)."""
    return build_registry()
