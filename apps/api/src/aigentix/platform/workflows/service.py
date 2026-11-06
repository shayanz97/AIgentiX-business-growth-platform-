"""Workflow run lifecycle. Framework-independent; used by the API (reads/enqueue/cancel) and the worker."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import Conflict, InvalidInput, NotFound
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows.models import ACTIVE_STATUSES, WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import WorkflowRegistry

MAX_ERROR_LENGTH = 2000
# Serialises claims across workers so per-type concurrency limits hold (transaction-scoped lock).
_CLAIM_LOCK_KEY = 0x41494758  # "AIGX"


def enqueue(
    db: Session,
    tenant: TenantContext,
    *,
    workflow_type: str,
    registry: WorkflowRegistry,
    metadata: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> WorkflowRun:
    if workflow_type not in registry:
        raise InvalidInput(f"Unknown workflow type: {workflow_type}")
    run = WorkflowRun(
        organization_id=tenant.organization_id,
        workflow_type=workflow_type,
        status=WorkflowStatus.PENDING.value,
        run_metadata=metadata or {},
        max_attempts=max_attempts,
    )
    db.add(run)
    db.flush()
    return run


def get_run(db: Session, tenant: TenantContext, run_id: uuid.UUID) -> WorkflowRun:
    run = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.organization_id == tenant.organization_id)
    )
    if run is None:
        raise NotFound("Workflow run not found")
    return run


def list_runs(
    db: Session, tenant: TenantContext, *, limit: int, offset: int, workflow_type: str | None = None
) -> tuple[list[WorkflowRun], int]:
    conditions = [WorkflowRun.organization_id == tenant.organization_id]
    if workflow_type is not None:
        conditions.append(WorkflowRun.workflow_type == workflow_type)
    total = db.scalar(select(func.count()).select_from(WorkflowRun).where(*conditions)) or 0
    rows = db.scalars(
        select(WorkflowRun)
        .where(*conditions)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


def request_cancel(db: Session, run: WorkflowRun) -> WorkflowRun:
    """Pending runs are cancelled immediately; running runs stop at their next step boundary."""
    locked = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run.id).with_for_update())
    if locked is None:
        raise NotFound("Workflow run not found")
    status = WorkflowStatus(locked.status)
    if status not in ACTIVE_STATUSES:
        raise Conflict(f"Run is already {status.value}")
    locked.cancel_requested_at = utcnow()
    if status is WorkflowStatus.PENDING:
        _finish(locked, WorkflowStatus.CANCELLED)
    db.flush()
    return locked


# --- worker side ---------------------------------------------------------------------------------


def claim_next(db: Session, *, concurrency_limits: dict[str, int] | None = None) -> WorkflowRun | None:
    """Atomically claim the oldest due pending run, respecting per-type concurrency limits."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CLAIM_LOCK_KEY})
    excluded: list[str] = []
    for workflow_type, limit in (concurrency_limits or {}).items():
        running = db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_type == workflow_type, WorkflowRun.status == WorkflowStatus.RUNNING.value)
        )
        if (running or 0) >= limit:
            excluded.append(workflow_type)
    now = utcnow()
    query = (
        select(WorkflowRun)
        .where(
            WorkflowRun.status == WorkflowStatus.PENDING.value,
            WorkflowRun.cancel_requested_at.is_(None),
            (WorkflowRun.next_attempt_at.is_(None)) | (WorkflowRun.next_attempt_at <= now),
        )
        .order_by(WorkflowRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if excluded:
        query = query.where(WorkflowRun.workflow_type.not_in(excluded))
    run = db.scalar(query)
    if run is None:
        return None
    run.status = WorkflowStatus.RUNNING.value
    run.started_at = run.started_at or now
    run.heartbeat_at = now
    run.next_attempt_at = None
    run.attempts += 1
    db.flush()
    return run


def _finish(run: WorkflowRun, status: WorkflowStatus) -> None:
    run.status = status.value
    run.completed_at = utcnow()
    if status in (WorkflowStatus.COMPLETED, WorkflowStatus.PARTIAL):
        run.progress = 100


def mark_finished(
    db: Session, run: WorkflowRun, status: WorkflowStatus, *, summary: dict[str, Any], message: str | None
) -> None:
    _finish(run, status)
    run.current_step = "completed"
    run.error_type = None
    run.error_message = message[:MAX_ERROR_LENGTH] if message else None
    if summary:
        run.run_metadata = {**run.run_metadata, "result": summary}
    db.flush()


def mark_failed(db: Session, run: WorkflowRun, *, error_type: str, error_message: str) -> None:
    _finish(run, WorkflowStatus.FAILED)
    run.error_type = error_type[:200]
    run.error_message = error_message[:MAX_ERROR_LENGTH]
    db.flush()


def mark_cancelled(db: Session, run: WorkflowRun) -> None:
    _finish(run, WorkflowStatus.CANCELLED)
    run.cancel_requested_at = run.cancel_requested_at or utcnow()
    db.flush()


def schedule_retry(
    db: Session, run: WorkflowRun, *, error_type: str, error_message: str, base_delay: timedelta
) -> bool:
    """Re-queue a run after a transient error. Returns False (and fails the run) when attempts are exhausted."""
    if run.cancel_requested_at is not None:  # a cancel requested during the failed attempt wins
        mark_cancelled(db, run)
        return False
    if run.attempts >= run.max_attempts:
        mark_failed(
            db,
            run,
            error_type=error_type,
            error_message=f"{error_message} (gave up after {run.attempts} attempts)",
        )
        return False
    run.status = WorkflowStatus.PENDING.value
    run.next_attempt_at = utcnow() + base_delay * (2 ** (run.attempts - 1))
    run.error_type = error_type[:200]
    run.error_message = error_message[:MAX_ERROR_LENGTH]
    db.flush()
    return True


def recover_stale_runs(db: Session, *, older_than: timedelta) -> tuple[int, int]:
    """Runs whose worker stopped heart-beating are resumed (re-queued) or failed. Returns (requeued, failed)."""
    cutoff = utcnow() - older_than
    stale = list(
        db.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.status == WorkflowStatus.RUNNING.value,
                func.coalesce(WorkflowRun.heartbeat_at, WorkflowRun.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    )
    requeued = failed = 0
    for run in stale:
        if run.cancel_requested_at is not None:
            mark_cancelled(db, run)
        elif run.attempts < run.max_attempts:
            run.status = WorkflowStatus.PENDING.value
            run.next_attempt_at = utcnow()
            run.error_type = "WorkerInterrupted"
            run.error_message = "The worker stopped during this run; it will resume from the last completed step."
            requeued += 1
        else:
            mark_failed(
                db,
                run,
                error_type="StaleRun",
                error_message="The run did not finish in time and was stopped.",
            )
            failed += 1
    db.flush()
    return requeued, failed
