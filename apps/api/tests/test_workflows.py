"""Platform workflow engine: lifecycle, retries, cancellation, stale-run recovery, concurrency, usage."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.db import get_session_factory, utcnow
from aigentix.core.errors import Conflict, InvalidInput
from aigentix.platform.organizations.service import TenantContext, resolve_tenant
from aigentix.platform.workflows import service
from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult
from aigentix.platform.workflows.errors import TransientWorkflowError, WorkflowError
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import NOOP_WORKFLOW, WorkflowRegistry, build_registry
from aigentix.worker.runner import GENERIC_FAILURE, WorkerSettings, housekeeping, run_once
from tests.conftest import Tenant

NO_DELAY = WorkerSettings(retry_base_delay=timedelta(0))


def _boom(_ctx: WorkflowContext) -> WorkflowResult:
    raise RuntimeError("upstream exploded with secret details")


def _flaky(ctx: WorkflowContext) -> WorkflowResult:
    ctx.checkpoint("step_one", 10)
    if ctx.run.attempts < 2:
        raise TransientWorkflowError("Service temporarily unavailable")
    return WorkflowResult(summary={"ok": True})


def _always_transient(_ctx: WorkflowContext) -> WorkflowResult:
    raise TransientWorkflowError("Still down")


def _partial(ctx: WorkflowContext) -> WorkflowResult:
    ctx.record_usage(input_tokens=1000, output_tokens=200, cost_usd=Decimal("0.0123"))
    return WorkflowResult(summary={"pages": 3}, partial=True, message="AI analysis unavailable")


def _expected_failure(_ctx: WorkflowContext) -> WorkflowResult:
    raise WorkflowError("Website could not be reached")


@pytest.fixture
def registry() -> WorkflowRegistry:
    reg = build_registry()
    reg.register("test.failing", _boom)
    reg.register("test.flaky", _flaky)
    reg.register("test.down", _always_transient)
    reg.register("test.partial", _partial)
    reg.register("test.expected", _expected_failure)
    reg.register("test.limited", _partial, max_concurrent=1)
    return reg


def _tenant(db: Session, t: Tenant) -> TenantContext:
    return resolve_tenant(db, user=t.user, organization_id=t.org.id)


def _enqueue(db: Session, t: Tenant, registry: WorkflowRegistry, workflow_type: str, **kw: object) -> WorkflowRun:
    run = service.enqueue(db, _tenant(db, t), workflow_type=workflow_type, registry=registry, **kw)  # type: ignore[arg-type]
    db.commit()
    return run


def test_registry_contains_platform_and_module_workflows() -> None:
    registry = build_registry()
    assert NOOP_WORKFLOW in registry
    assert "lead_intelligence.company_research" in registry
    assert registry.concurrency_limits["lead_intelligence.company_research"] >= 1


def test_registry_rejects_duplicates(registry: WorkflowRegistry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(NOOP_WORKFLOW, _boom)


def test_enqueue_rejects_unknown_type(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    with pytest.raises(InvalidInput):
        service.enqueue(db, _tenant(db, tenant_a), workflow_type="nope", registry=registry)


def test_worker_executes_pending_run(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, NOOP_WORKFLOW, metadata={"input": 42})
    assert run.status == WorkflowStatus.PENDING
    assert run_once(get_session_factory(), registry) is True
    db.refresh(run)
    assert run.status == WorkflowStatus.COMPLETED
    assert run.progress == 100
    assert run.started_at is not None
    assert run.completed_at is not None
    assert run.completed_at >= run.started_at
    assert run.attempts == 1
    assert run.run_metadata["result"] == {"echo": 42}
    assert run_once(get_session_factory(), registry) is False  # queue drained


def test_partial_result_and_usage_are_recorded(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, "test.partial")
    run_once(get_session_factory(), registry)
    db.refresh(run)
    assert run.status == WorkflowStatus.PARTIAL
    assert run.error_message == "AI analysis unavailable"
    assert (run.input_tokens, run.output_tokens) == (1000, 200)
    assert run.estimated_cost_usd == Decimal("0.0123")


def test_unexpected_errors_are_recorded_generically(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, "test.failing")
    run_once(get_session_factory(), registry)
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_type == "RuntimeError"
    assert run.error_message == GENERIC_FAILURE  # internal text is not exposed to tenant users
    assert run.attempts == 1  # unexpected errors are not retried


def test_permanent_workflow_errors_are_not_retried(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, "test.expected")
    run_once(get_session_factory(), registry, NO_DELAY)
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_message == "Website could not be reached"
    assert run_once(get_session_factory(), registry, NO_DELAY) is False


def test_transient_errors_retry_with_backoff_then_succeed(
    db: Session, tenant_a: Tenant, registry: WorkflowRegistry
) -> None:
    run = _enqueue(db, tenant_a, registry, "test.flaky")
    run_once(get_session_factory(), registry, WorkerSettings(retry_base_delay=timedelta(minutes=5)))
    db.refresh(run)
    assert run.status == WorkflowStatus.PENDING
    assert run.error_type == "TransientWorkflowError"
    assert run.next_attempt_at is not None
    assert run.next_attempt_at > utcnow() + timedelta(minutes=4)
    # Not due yet: the worker leaves it alone.
    assert run_once(get_session_factory(), registry) is False
    db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id).values(next_attempt_at=utcnow()))
    db.commit()
    assert run_once(get_session_factory(), registry) is True
    db.refresh(run)
    assert run.status == WorkflowStatus.COMPLETED
    assert run.attempts == 2
    assert run.error_type is None


def test_transient_errors_fail_after_max_attempts(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, "test.down", max_attempts=2)
    for _ in range(2):
        run_once(get_session_factory(), registry, NO_DELAY)
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.attempts == 2
    assert run.error_message is not None
    assert "gave up after 2 attempts" in run.error_message


def test_worker_fails_runs_without_handler(db: Session, tenant_a: Tenant) -> None:
    run = WorkflowRun(organization_id=tenant_a.org.id, workflow_type="removed.workflow")
    db.add(run)
    db.commit()
    run_once(get_session_factory(), WorkflowRegistry())
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_type == "UnknownWorkflowType"


def test_cancel_pending_run_is_immediate(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = _enqueue(db, tenant_a, registry, NOOP_WORKFLOW)
    service.request_cancel(db, run)
    db.commit()
    db.refresh(run)
    assert run.status == WorkflowStatus.CANCELLED
    assert run_once(get_session_factory(), registry) is False
    with pytest.raises(Conflict):
        service.request_cancel(db, run)


def test_cancel_running_run_stops_at_next_checkpoint(db: Session, tenant_a: Tenant) -> None:
    registry = WorkflowRegistry()

    def handler(ctx: WorkflowContext) -> WorkflowResult:
        ctx.checkpoint("first", 10)
        with get_session_factory()() as other:  # cancellation requested by the API mid-run
            other.execute(update(WorkflowRun).where(WorkflowRun.id == ctx.run_id).values(cancel_requested_at=utcnow()))
            other.commit()
        ctx.checkpoint("second", 50)
        raise AssertionError("must not get here")

    registry.register("test.cancel", handler)
    run = _enqueue(db, tenant_a, registry, "test.cancel")
    run_once(get_session_factory(), registry)
    db.refresh(run)
    assert run.status == WorkflowStatus.CANCELLED
    assert run.current_step == "first"


def test_stale_running_runs_resume_then_fail(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    resumable = WorkflowRun(
        organization_id=tenant_a.org.id,
        workflow_type=NOOP_WORKFLOW,
        status=WorkflowStatus.RUNNING.value,
        attempts=1,
        max_attempts=3,
        current_step="discover_relevant_pages",
        started_at=utcnow() - timedelta(hours=2),
        heartbeat_at=utcnow() - timedelta(hours=1),
    )
    exhausted = WorkflowRun(
        organization_id=tenant_a.org.id,
        workflow_type=NOOP_WORKFLOW,
        status=WorkflowStatus.RUNNING.value,
        attempts=3,
        max_attempts=3,
        started_at=utcnow() - timedelta(hours=2),
        heartbeat_at=utcnow() - timedelta(hours=1),
    )
    fresh = WorkflowRun(
        organization_id=tenant_a.org.id,
        workflow_type=NOOP_WORKFLOW,
        status=WorkflowStatus.RUNNING.value,
        attempts=1,
        started_at=utcnow(),
        heartbeat_at=utcnow(),
    )
    db.add_all([resumable, exhausted, fresh])
    db.commit()
    housekeeping(get_session_factory(), stale_after=timedelta(minutes=10))
    for run in (resumable, exhausted, fresh):
        db.refresh(run)
    assert resumable.status == WorkflowStatus.PENDING
    assert resumable.current_step == "discover_relevant_pages"  # resumes from the persisted step
    assert resumable.error_type == "WorkerInterrupted"
    assert exhausted.status == WorkflowStatus.FAILED
    assert exhausted.error_type == "StaleRun"
    assert fresh.status == WorkflowStatus.RUNNING


def test_concurrency_limit_per_workflow_type(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    busy = WorkflowRun(
        organization_id=tenant_a.org.id, workflow_type="test.limited", status="running", heartbeat_at=utcnow()
    )
    db.add(busy)
    db.commit()
    waiting = _enqueue(db, tenant_a, registry, "test.limited")
    other = _enqueue(db, tenant_a, registry, NOOP_WORKFLOW)
    assert run_once(get_session_factory(), registry) is True  # runs the unrelated workflow
    db.refresh(waiting)
    db.refresh(other)
    assert other.status == WorkflowStatus.COMPLETED
    assert waiting.status == WorkflowStatus.PENDING  # limit of 1 is taken
    assert run_once(get_session_factory(), registry) is False


def test_workflow_listing_is_tenant_scoped(
    db: Session, tenant_a: Tenant, tenant_b: Tenant, registry: WorkflowRegistry
) -> None:
    _enqueue(db, tenant_a, registry, NOOP_WORKFLOW)
    mine = tenant_a.client.get("/api/v1/workflows", headers=tenant_a.headers).json()
    assert mine["total"] == 1
    assert mine["items"][0]["status"] == "pending"
    assert mine["items"][0]["progress"] == 0
    theirs = tenant_b.client.get("/api/v1/workflows", headers=tenant_b.headers).json()
    assert theirs["total"] == 0


def test_invalid_status_rejected_by_database(db: Session, tenant_a: Tenant) -> None:
    db.add(WorkflowRun(id=uuid.uuid4(), organization_id=tenant_a.org.id, workflow_type="x", status="queued"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_progress_range_enforced_by_database(db: Session, tenant_a: Tenant) -> None:
    db.add(WorkflowRun(organization_id=tenant_a.org.id, workflow_type="x", progress=101))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
