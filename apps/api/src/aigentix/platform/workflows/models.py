import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aigentix.core.db import Base, utcnow


class WorkflowStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # finished, but some optional part (e.g. AI analysis) did not run
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = frozenset({WorkflowStatus.PENDING, WorkflowStatus.RUNNING})
TERMINAL_STATUSES = frozenset(
    {WorkflowStatus.COMPLETED, WorkflowStatus.PARTIAL, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
)


class WorkflowRun(Base):
    """One execution of a workflow for a tenant. Generic: module-specific links live in module tables."""

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=WorkflowStatus.PENDING.value)
    current_step: Mapped[str | None] = mapped_column(String(60))
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_type: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column()
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    cancel_requested_at: Mapped[datetime | None] = mapped_column()
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        # Target for module tables' composite FKs (same-organization guarantee).
        UniqueConstraint("id", "organization_id", name="uq_workflow_runs_id_org"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempts_valid"),
        Index("ix_workflow_runs_org_created", "organization_id", "created_at"),
        # Partial indexes used by the worker to find work and stale runs quickly.
        Index("ix_workflow_runs_pending", "created_at", postgresql_where=text("status = 'pending'")),
        Index("ix_workflow_runs_running", "heartbeat_at", postgresql_where=text("status = 'running'")),
    )
