"""ASGI entrypoint: `uvicorn aigentix.main:app`."""

from aigentix.api.app import create_app

app = create_app()
