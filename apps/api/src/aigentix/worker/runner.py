import signal
import threading
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from aigentix.core.logging import get_logger
from aigentix.platform.workflows import service
from aigentix.platform.workflows.registry import WorkflowRegistry

log = get_logger("aigentix.worker")


def run_once(session_factory: sessionmaker[Session], registry: WorkflowRegistry) -> bool:
    """Claim and execute at most one queued run. Returns True if a run was processed."""
    with session_factory() as db:
        run = service.claim_next(db)
        if run is None:
            db.rollback()
            return False
        db.commit()  # persist the RUNNING state before executing
        bound = log.bind(
            run_id=str(run.id), workflow_type=run.workflow_type, organization_id=str(run.organization_id)
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
        except Exception as exc:
            db.rollback()
            db.refresh(run)
            service.mark_failed(db, run, error_type=type(exc).__name__, error_message=str(exc))
            db.commit()
            bound.exception("workflow.failed", error_type=type(exc).__name__)
            return True
        service.mark_succeeded(db, run, result)
        db.commit()
        bound.info("workflow.succeeded")
        return True


def run_forever(
    session_factory: sessionmaker[Session], registry: WorkflowRegistry, poll_interval: float
) -> None:
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker.stopping", signal=signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("worker.started", workflow_types=sorted(registry.handlers), poll_interval=poll_interval)
    while not stop.is_set():
        try:
            processed = run_once(session_factory, registry)
        except Exception:
            log.exception("worker.loop_error")
            processed = False
        if not processed:
            stop.wait(poll_interval)
    log.info("worker.stopped")
