import signal
import threading
import time
import uuid
from datetime import timedelta
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from aigentix.core.logging import get_logger
from aigentix.platform.identity.service import purge_expired_sessions
from aigentix.platform.workflows import service
from aigentix.platform.workflows.models import WorkflowRun
from aigentix.platform.workflows.registry import WorkflowRegistry
from aigentix.platform.workflows.service import WorkflowError

log = get_logger("aigentix.worker")

GENERIC_FAILURE = "The workflow failed due to an internal error."


def _record_failure(
    session_factory: sessionmaker[Session], run_id: uuid.UUID, *, error_type: str, message: str
) -> None:
    """Persist a failure in a fresh session, so it is recorded even if the run's session is broken."""
    with session_factory() as db:
        run = db.get(WorkflowRun, run_id)
        if run is not None:
            service.mark_failed(db, run, error_type=error_type, error_message=message)
            db.commit()


def run_once(session_factory: sessionmaker[Session], registry: WorkflowRegistry) -> bool:
    """Claim and execute at most one queued run. Returns True if a run was processed."""
    with session_factory() as db:
        run = service.claim_next(db)
        if run is None:
            db.rollback()
            return False
        db.commit()  # persist the RUNNING state before executing
        run_id = run.id
        bound = log.bind(
            run_id=str(run_id), workflow_type=run.workflow_type, organization_id=str(run.organization_id)
        )
        bound.info("workflow.started")

        handler = registry.get(run.workflow_type)
        if handler is None:
            service.mark_failed(
                db, run, error_type="UnknownWorkflowType", error_message=f"No handler for {run.workflow_type}"
            )
            db.commit()
            bound.error("workflow.failed", error_type="UnknownWorkflowType")
            return True

        try:
            result = handler(db, run)
            service.mark_succeeded(db, run, result)
            db.commit()
        except Exception as exc:
            db.rollback()
            # Only messages of WorkflowError are tenant-visible; everything else may contain internals.
            message = str(exc) if isinstance(exc, WorkflowError) else GENERIC_FAILURE
            bound.exception("workflow.failed", error_type=type(exc).__name__)
            _record_failure(session_factory, run_id, error_type=type(exc).__name__, message=message)
            return True
        bound.info("workflow.succeeded")
        return True


def housekeeping(session_factory: sessionmaker[Session], *, stale_after: timedelta) -> None:
    with session_factory() as db:
        stale = service.fail_stale_runs(db, older_than=stale_after)
        purged = purge_expired_sessions(db)
        db.commit()
    if stale or purged:
        log.info("worker.housekeeping", stale_runs_failed=stale, expired_sessions_purged=purged)


def run_forever(
    session_factory: sessionmaker[Session],
    registry: WorkflowRegistry,
    poll_interval: float,
    *,
    stale_after: timedelta = timedelta(minutes=30),
    housekeeping_interval: float = 60.0,
) -> None:
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker.stopping", signal=signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("worker.started", workflow_types=sorted(registry.handlers), poll_interval=poll_interval)
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_housekeeping:
                housekeeping(session_factory, stale_after=stale_after)
                next_housekeeping = time.monotonic() + housekeeping_interval
            processed = run_once(session_factory, registry)
        except Exception:
            log.exception("worker.loop_error")
            processed = False
        if not processed:
            stop.wait(poll_interval)
    log.info("worker.stopped")
