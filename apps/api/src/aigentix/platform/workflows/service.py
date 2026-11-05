"""Workflow run lifecycle. Framework-independent; used by the API (reads/enqueue) and the worker."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import WorkflowRegistry

MAX_ERROR_LENGTH = 2000


class WorkflowError(Exception):
    """Raise from a handler for an expected failure whose message is safe to show to tenant users.

    Any other exception is recorded with a generic message; details go to the worker log only.
    """


def enqueue(
    db: Session,
    tenant: TenantContext,
    *,
    workflow_type: str,
    registry: WorkflowRegistry,
    project_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkflowRun:
    if workflow_type not in registry:
        raise InvalidInput(f"Unknown workflow type: {workflow_type}")
    run = WorkflowRun(
        organization_id=tenant.organization_id,
        project_id=project_id,
        workflow_type=workflow_type,
        status=WorkflowStatus.QUEUED.value,
        run_metadata=metadata or {},
    )
    db.add(run)
    db.flush()
    return run


def list_runs(
    db: Session,
    tenant: TenantContext,
    *,
    limit: int,
    offset: int,
    project_id: uuid.UUID | None = None,
) -> tuple[list[WorkflowRun], int]:
    conditions = [WorkflowRun.organization_id == tenant.organization_id]
    if project_id is not None:
        conditions.append(WorkflowRun.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(WorkflowRun).where(*conditions)) or 0
    rows = db.scalars(
        select(WorkflowRun)
        .where(*conditions)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


def claim_next(db: Session) -> WorkflowRun | None:
    """Atomically claim the oldest queued run. Safe with several workers (SKIP LOCKED)."""
    run = db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.status == WorkflowStatus.QUEUED.value)
        .order_by(WorkflowRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    run.status = WorkflowStatus.RUNNING.value
    run.started_at = utcnow()
    run.attempts += 1
    db.flush()
    return run


def mark_succeeded(db: Session, run: WorkflowRun, result: dict[str, Any] | None) -> None:
    run.status = WorkflowStatus.SUCCEEDED.value
    run.completed_at = utcnow()
    if result:
        run.run_metadata = {**run.run_metadata, "result": result}
    db.flush()


def fail_stale_runs(db: Session, *, older_than: timedelta) -> int:
    """Fail runs stuck in RUNNING (e.g. the worker was killed mid-run). Returns the number affected."""
    result = db.execute(
        update(WorkflowRun)
        .where(
            WorkflowRun.status == WorkflowStatus.RUNNING.value,
            WorkflowRun.started_at < utcnow() - older_than,
        )
        .values(
            status=WorkflowStatus.FAILED.value,
            completed_at=utcnow(),
            error_type="StaleRun",
            error_message="The run did not finish in time and was stopped.",
        )
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


def mark_failed(db: Session, run: WorkflowRun, *, error_type: str, error_message: str) -> None:
    run.status = WorkflowStatus.FAILED.value
    run.completed_at = utcnow()
    run.error_type = error_type[:200]
    run.error_message = error_message[:MAX_ERROR_LENGTH]
    db.flush()
