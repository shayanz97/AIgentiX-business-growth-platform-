import signal
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from types import FrameType

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aigentix.core.logging import get_logger
from aigentix.platform.identity.service import purge_expired_sessions
from aigentix.platform.workflows import service
from aigentix.platform.workflows.context import WorkflowContext
from aigentix.platform.workflows.errors import TransientWorkflowError, WorkflowCancelled, WorkflowError
from aigentix.platform.workflows.models import WorkflowRun
from aigentix.platform.workflows.registry import WorkflowRegistry

log = get_logger("aigentix.worker")

GENERIC_FAILURE = "The workflow failed due to an internal error."


@dataclass(frozen=True)
class WorkerSettings:
    retry_base_delay: timedelta = timedelta(seconds=30)
    stale_after: timedelta = timedelta(minutes=30)


def _with_run(
    session_factory: sessionmaker[Session],
    run_id: uuid.UUID,
    action: Callable[[Session, WorkflowRun], object],
) -> None:
    """Apply a final state change in a fresh session (the run's own session may be unusable)."""
    with session_factory() as db:
        run = db.get(WorkflowRun, run_id, with_for_update=True)
        if run is not None:
            action(db, run)
            db.commit()


def run_once(
    session_factory: sessionmaker[Session],
    registry: WorkflowRegistry,
    settings: WorkerSettings | None = None,
) -> bool:
    """Claim and execute at most one due run. Returns True if a run was processed."""
    settings = settings or WorkerSettings()
    with session_factory() as db:
        run = service.claim_next(db, concurrency_limits=registry.concurrency_limits)
        if run is None:
            db.rollback()
            return False
        db.commit()  # persist the RUNNING state before executing
        run_id = run.id
        bound = log.bind(
            run_id=str(run_id),
            workflow_type=run.workflow_type,
            organization_id=str(run.organization_id),
            attempt=run.attempts,
        )
        bound.info("workflow.started", resume_step=run.current_step)
        started = time.perf_counter()

        handler = registry.get(run.workflow_type)
        if handler is None:
            service.mark_failed(
                db, run, error_type="UnknownWorkflowType", error_message=f"No handler for {run.workflow_type}"
            )
            db.commit()
            bound.error("workflow.failed", error_type="UnknownWorkflowType")
            return True

        try:
            result = handler(WorkflowContext(db, run, session_factory))
            service.mark_finished(db, run, result.status, summary=result.summary, message=result.message)
            db.commit()
        except WorkflowCancelled:
            db.rollback()
            _with_run(session_factory, run_id, service.mark_cancelled)
            bound.info("workflow.cancelled")
            return True
        except (TransientWorkflowError, OperationalError) as exc:
            db.rollback()
            message = str(exc) if isinstance(exc, WorkflowError) else "A temporary database error occurred."
            error_type = type(exc).__name__
            retried: list[bool] = []
            _with_run(
                session_factory,
                run_id,
                lambda s, r: retried.append(
                    service.schedule_retry(
                        s,
                        r,
                        error_type=error_type,
                        error_message=message,
                        base_delay=settings.retry_base_delay,
                    )
                ),
            )
            bound.warning("workflow.transient_error", error_type=error_type, will_retry=bool(retried and retried[0]))
            return True
        except Exception as exc:
            db.rollback()
            # Only WorkflowError messages are tenant-visible; everything else may contain internals.
            message = str(exc) if isinstance(exc, WorkflowError) else GENERIC_FAILURE
            error_type = type(exc).__name__
            if isinstance(exc, WorkflowError):
                bound.warning("workflow.failed", error_type=error_type)
            else:
                bound.exception("workflow.failed", error_type=error_type)
            _with_run(
                session_factory,
                run_id,
                lambda s, r: service.mark_failed(s, r, error_type=error_type, error_message=message),
            )
            return True
        bound.info(
            "workflow.finished",
            status=result.status.value,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return True


def housekeeping(session_factory: sessionmaker[Session], *, stale_after: timedelta) -> None:
    with session_factory() as db:
        requeued, failed = service.recover_stale_runs(db, older_than=stale_after)
        purged = purge_expired_sessions(db)
        db.commit()
    if requeued or failed or purged:
        log.info(
            "worker.housekeeping",
            stale_runs_requeued=requeued,
            stale_runs_failed=failed,
            expired_sessions_purged=purged,
        )


def run_forever(
    session_factory: sessionmaker[Session],
    registry: WorkflowRegistry,
    poll_interval: float,
    *,
    settings: WorkerSettings | None = None,
    housekeeping_interval: float = 60.0,
) -> None:
    settings = settings or WorkerSettings()
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker.stopping", signal=signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("worker.started", workflow_types=sorted(registry.specs), poll_interval=poll_interval)
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_housekeeping:
                housekeeping(session_factory, stale_after=settings.stale_after)
                next_housekeeping = time.monotonic() + housekeeping_interval
            processed = run_once(session_factory, registry, settings)
        except Exception:
            log.exception("worker.loop_error")
            processed = False
        if not processed:
            stop.wait(poll_interval)
    log.info("worker.stopped")
