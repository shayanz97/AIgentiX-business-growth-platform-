from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from aigentix.api.deps import DbSession

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str


@router.get("/health", response_model=HealthStatus, operation_id="health")
def health() -> HealthStatus:
    """Liveness: the process is up. Does not touch dependencies."""
    return HealthStatus(status="ok")


@router.get(
    "/ready",
    response_model=HealthStatus,
    operation_id="ready",
    responses={503: {"model": HealthStatus}},
)
def ready(db: DbSession) -> HealthStatus | JSONResponse:
    """Readiness: database reachable and migrations applied."""
    try:
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "database_unavailable"})
    if version is None:
        return JSONResponse(status_code=503, content={"status": "migrations_pending"})
    return HealthStatus(status="ready")
