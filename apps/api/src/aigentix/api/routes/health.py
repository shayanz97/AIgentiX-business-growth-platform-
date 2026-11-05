from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from aigentix.api.deps import DbSession
from aigentix.core.config import get_settings


@lru_cache
def _expected_head() -> str | None:
    """Head revision of the migration scripts shipped with this build (None if they are not available)."""
    ini = Path(get_settings().alembic_ini)
    if not ini.is_file():
        return None
    return ScriptDirectory.from_config(Config(str(ini))).get_current_head()


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
    head = _expected_head()
    if version is None or (head is not None and version != head):
        return JSONResponse(status_code=503, content={"status": "migrations_pending"})
    return HealthStatus(status="ready")
