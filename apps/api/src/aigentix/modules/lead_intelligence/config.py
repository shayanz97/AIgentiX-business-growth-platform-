"""Lead Intelligence settings (environment-based). See apps/api/.env.example."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # Import
    research_import_max_rows: int = Field(default=100, ge=1, le=10_000)
    research_import_max_bytes: int = Field(default=512 * 1024, ge=1024)

    # Fetching
    research_fetch_backend: Literal["internet", "fixtures"] = "internet"
    research_user_agent: str = "AIgentiXResearchBot/0.2 (+https://aigentix.example/bot)"
    research_robots_token: str = "AIgentiXResearchBot"  # noqa: S105 - robots.txt user-agent token, not a secret
    research_max_pages: int = Field(default=8, ge=1, le=20)
    research_http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    research_max_response_bytes: int = Field(default=2_000_000, ge=10_000)
    research_max_text_chars: int = Field(default=20_000, ge=1_000)
    research_domain_min_interval_seconds: float = Field(default=0.5, ge=0)  # ≈ ≤2 requests/second per domain
    research_max_concurrent_runs: int = Field(default=2, ge=1)
    research_max_attempts: int = Field(default=3, ge=1, le=10)
    # Stop reading further pages after this long (each request is separately capped by a 30 s deadline).
    research_max_discovery_seconds: float = Field(default=180.0, gt=0)

    # LLM — task routes "provider:model" (provider: anthropic | openai). Keys and client settings live in
    # aigentix.platform.llm.config (ANTHROPIC_API_KEY, OPENAI_API_KEY, LLM_TIMEOUT_SECONDS, LLM_PRICES_JSON).
    llm_route_extraction: str | None = None
    llm_route_audit: str | None = None
    # Used when no explicit route is set: provider for both tasks, plus a model per task.
    llm_provider: Literal["anthropic", "openai", "fixture", "none"] = "anthropic"
    llm_extraction_model: str = "claude-haiku-5-5"
    llm_audit_model: str = "claude-opus-5-5"
    llm_max_repairs: int = Field(default=2, ge=0, le=5)
    llm_max_cost_per_run_usd: Decimal = Field(default=Decimal("0.50"), ge=0)

    @model_validator(mode="after")
    def _no_test_doubles_in_production(self) -> "ResearchSettings":
        if self.environment == "production":
            if self.research_fetch_backend == "fixtures":
                raise ValueError("RESEARCH_FETCH_BACKEND=fixtures is not allowed in production")
            if self.llm_provider == "fixture":
                raise ValueError("LLM_PROVIDER=fixture is not allowed in production")
        self._validate_routes()
        return self

    def _validate_routes(self) -> None:
        from aigentix.platform.llm import Route

        for value in (self.llm_route_extraction, self.llm_route_audit):
            if value:
                Route.parse(value)
        if self.llm_provider == "openai":
            for task, route, model in (
                ("extraction", self.llm_route_extraction, self.llm_extraction_model),
                ("audit", self.llm_route_audit, self.llm_audit_model),
            ):
                if not route and model.startswith("claude-"):
                    raise ValueError(
                        f"LLM_PROVIDER=openai needs an OpenAI model for the {task} task: set "
                        f"LLM_ROUTE_{task.upper()}=openai:<model> or LLM_{task.upper()}_MODEL"
                    )


@lru_cache
def get_research_settings() -> ResearchSettings:
    return ResearchSettings()
