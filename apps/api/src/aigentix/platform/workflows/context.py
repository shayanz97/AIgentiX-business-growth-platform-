"""What a workflow handler gets: the run, a session, checkpoints, persisted state and usage accounting."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from aigentix.core.db import utcnow
from aigentix.platform.workflows.errors import WorkflowCancelled, WorkflowClaimLost
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus


@dataclass(frozen=True)
class WorkflowResult:
    """Returned by a handler. `partial` = finished, but an optional part did not run (explained in message)."""

    summary: dict[str, Any] = field(default_factory=dict)
    partial: bool = False
    message: str | None = None

    @property
    def status(self) -> WorkflowStatus:
        return WorkflowStatus.PARTIAL if self.partial else WorkflowStatus.COMPLETED


class WorkflowContext:
    def __init__(self, db: Session, run: WorkflowRun, session_factory: sessionmaker[Session]) -> None:
        self.db = db
        self.run = run
        self._session_factory = session_factory
        # The attempt number this worker claimed; any other value means another worker owns the run now.
        self.claimed_attempt = run.attempts

    @property
    def run_id(self) -> Any:
        return self.run.id

    @property
    def organization_id(self) -> Any:
        return self.run.organization_id

    # --- progress -------------------------------------------------------------------------------

    def checkpoint(self, step: str, progress: int) -> None:
        """Commit work done so far, record the step about to start, and honour cancellation and ownership."""
        row = self.db.execute(
            select(WorkflowRun.status, WorkflowRun.attempts, WorkflowRun.cancel_requested_at)
            .where(WorkflowRun.id == self.run.id)
            .with_for_update()
        ).one()
        if row.status != WorkflowStatus.RUNNING.value or row.attempts != self.claimed_attempt:
            raise WorkflowClaimLost
        if row.cancel_requested_at is not None:
            raise WorkflowCancelled
        self.run.current_step = step
        self.run.progress = max(0, min(100, progress))
        self.run.heartbeat_at = utcnow()
        self.db.commit()

    # --- persisted state (survives retries / worker restarts) ------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        return self.run.run_metadata.get("state", {}).get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        state = dict(self.run.run_metadata.get("state", {}))
        state[key] = value
        # Reassign so SQLAlchemy detects the JSONB change.
        self.run.run_metadata = {**self.run.run_metadata, "state": state}

    # --- usage / cost --------------------------------------------------------------------------

    def record_usage(self, *, input_tokens: int, output_tokens: int, cost_usd: Decimal) -> None:
        """Add model usage immediately in its own transaction, so spend is never lost on failure."""
        with self._session_factory() as other:
            other.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == self.run.id)
                .values(
                    input_tokens=WorkflowRun.input_tokens + input_tokens,
                    output_tokens=WorkflowRun.output_tokens + output_tokens,
                    estimated_cost_usd=WorkflowRun.estimated_cost_usd + cost_usd,
                )
            )
            other.commit()

    def spent_usd(self) -> Decimal:
        with self._session_factory() as other:
            value = other.scalar(select(WorkflowRun.estimated_cost_usd).where(WorkflowRun.id == self.run.id))
        return Decimal(value or 0)
