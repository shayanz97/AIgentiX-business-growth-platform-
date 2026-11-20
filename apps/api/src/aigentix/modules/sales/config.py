"""Sales settings (environment-based). See apps/api/.env.example."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SalesSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # LLM routes "provider:model" for the sales tasks; without a route LLM_PROVIDER + LLM_AUDIT_MODEL are used
    # (both tasks need reasoning over evidence). Keys come from aigentix.platform.llm.config.
    llm_provider: Literal["anthropic", "openai", "fixture", "none"] = "anthropic"
    llm_audit_model: str = "claude-opus-5-5"
    sales_llm_route_brief: str | None = None
    sales_llm_route_proposal: str | None = None
    sales_llm_max_cost_per_run_usd: Decimal = Field(default=Decimal("0.50"), ge=0)
    sales_llm_max_repairs: int = Field(default=2, ge=0, le=5)
    sales_max_attempts: int = Field(default=3, ge=1, le=10)

    # External CRM providers enabled for explicit, owner-confirmed export (comma-separated). None are bundled;
    # "mock" is a test double and refused in production.
    sales_crm_providers: str = ""

    @model_validator(mode="after")
    def _no_test_doubles_in_production(self) -> "SalesSettings":
        if self.environment == "production":
            if self.llm_provider == "fixture":
                raise ValueError("LLM_PROVIDER=fixture is not allowed in production")
            if "mock" in self.crm_providers():
                raise ValueError("SALES_CRM_PROVIDERS=mock is not allowed in production")
        from aigentix.platform.llm import Route

        for value in (self.sales_llm_route_brief, self.sales_llm_route_proposal):
            if value:
                Route.parse(value)
        return self

    def crm_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.sales_crm_providers.split(",") if p.strip()]


@lru_cache
def get_sales_settings() -> SalesSettings:
    return SalesSettings()
