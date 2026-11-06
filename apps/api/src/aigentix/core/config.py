from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-based configuration. See apps/api/.env.example."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: PostgresDsn

    # Comma-separated list of browser origins allowed to call the API with credentials.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    session_cookie_name: str = "aigx_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = Field(default=24 * 7, ge=1, le=24 * 30)

    # Used by /ready to verify the database is migrated to the head revision.
    alembic_ini: str = "alembic.ini"

    worker_poll_interval_seconds: float = Field(default=2.0, gt=0)
    # RUNNING runs older than this are failed by worker housekeeping (crash recovery).
    worker_stale_run_minutes: int = Field(default=10, ge=1)
    worker_retry_base_seconds: float = Field(default=30.0, ge=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("Wildcard CORS origins are not allowed with credentialed requests")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment == "production" and not self.session_cookie_secure:
            raise ValueError("SESSION_COOKIE_SECURE must be true in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """Force the psycopg 3 driver regardless of the DSN scheme supplied."""
        url = str(self.database_url)
        for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
