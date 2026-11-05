import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aigentix.core.db import Base, utcnow


class WorkflowStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED})


class WorkflowRun(Base):
    """One execution of a workflow for a tenant. Executed by the worker process."""

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    workflow_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=WorkflowStatus.QUEUED.value)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_type: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        # Composite FK guarantees a run can only reference a project of the *same* organization.
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["research_projects.id", "research_projects.organization_id"],
            ondelete="CASCADE",
            name="fk_workflow_runs_project_same_org",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="status_valid"
        ),
        Index("ix_workflow_runs_org_created", "organization_id", "created_at"),
        Index("ix_workflow_runs_project", "project_id"),
        # Partial index used by the worker to find work quickly.
        Index("ix_workflow_runs_queued", "created_at", postgresql_where=text("status = 'queued'")),
    )
