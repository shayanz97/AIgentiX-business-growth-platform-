"""Worker entrypoint: `python -m aigentix.worker`."""

from aigentix.core.config import get_settings
from aigentix.core.db import get_session_factory
from aigentix.core.logging import configure_logging
from aigentix.platform.workflows.registry import build_registry
from aigentix.worker.runner import run_forever


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    run_forever(get_session_factory(), build_registry(), settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
