from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from aigentix import __version__
from aigentix.api.middleware import origin_check, request_logging
from aigentix.api.routes import auth, health, me, modules, organizations, workflows
from aigentix.api.schemas import ErrorResponse
from aigentix.core.config import Settings, get_settings
from aigentix.core.errors import AppError
from aigentix.core.logging import configure_logging
from aigentix.modules.registry import MODULES

API_PREFIX = "/api/v1"


def _error(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": jsonable_encoder(details)}}
    return JSONResponse(status_code=status_code, content=body)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_req: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop raw input values from the error details so secrets (e.g. passwords) are never echoed.
        details = [{k: v for k, v in err.items() if k in ("loc", "msg", "type")} for err in exc.errors()]
        return _error(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(
        title="AIgentiX Growth Platform API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        responses={
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    _install_error_handlers(app)

    # Order: last added runs first. Logging wraps everything; origin check runs before routing.
    app.middleware("http")(origin_check(settings.cors_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Organization-Id", "X-Request-Id"],
    )
    app.middleware("http")(request_logging)

    app.include_router(health.router)
    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(me.router)
    v1.include_router(organizations.router)
    v1.include_router(modules.router)
    v1.include_router(workflows.router)
    for module in MODULES:
        if module.router is not None:
            v1.include_router(module.router)
    app.include_router(v1)
    return app
