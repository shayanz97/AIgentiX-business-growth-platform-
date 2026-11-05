import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from aigentix.core.logging import get_logger

log = get_logger("aigentix.request")

_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
Handler = Callable[[Request], Awaitable[Response]]


def origin_check(allowed_origins: list[str]) -> Callable[[Request, Handler], Awaitable[Response]]:
    """CSRF defence-in-depth (on top of SameSite=Lax): reject unsafe browser requests from foreign origins.

    Requests without an Origin header (server-to-server, CLI, tests) are allowed; browsers always send
    Origin on cross-origin unsafe requests.
    """
    allowed = frozenset(allowed_origins)

    async def middleware(request: Request, call_next: Handler) -> Response:
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin is not None and origin.rstrip("/") not in allowed:
            log.warning("request.origin_rejected", origin=origin, path=request.url.path)
            return JSONResponse(
                status_code=403,
                content={
                    "error": {"code": "origin_not_allowed", "message": "Origin not allowed", "details": None}
                },
            )
        return await call_next(request)

    return middleware


async def request_logging(request: Request, call_next: Handler) -> Response:
    """One structured log line per request. Logs path only (no query string, headers, cookies or body)."""
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if _REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request.unhandled_error", method=request.method, path=request.url.path)
        raise
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    response.headers["X-Request-Id"] = request_id
    log.info(
        "request.completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response
