"""Worker entrypoint: `python -m aigentix.worker`."""

from datetime import timedelta
from pathlib import Path

from aigentix.core.config import get_settings
from aigentix.core.db import get_session_factory
from aigentix.core.logging import configure_logging
from aigentix.platform.workflows.registry import build_registry
from aigentix.worker.runner import WorkerSettings, run_forever


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    run_forever(
        get_session_factory(),
        build_registry(),
        settings.worker_poll_interval_seconds,
        settings=WorkerSettings(
            retry_base_delay=timedelta(seconds=settings.worker_retry_base_seconds),
            stale_after=timedelta(minutes=settings.worker_stale_run_minutes),
            heartbeat_file=Path(settings.worker_heartbeat_file) if settings.worker_heartbeat_file else None,
        ),
    )


if __name__ == "__main__":
    main()
