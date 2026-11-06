"""Platform LLM settings: vendor credentials, client behaviour, price overrides (environment-based)."""

import json
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Anthropic server-side refusal fallback on models that support it.
    llm_server_side_fallback: bool = True
    # JSON object {"model-id": [input_usd_per_mtok, output_usd_per_mtok]} added to / overriding built-in prices.
    llm_prices_json: str = ""

    @field_validator("llm_prices_json")
    @classmethod
    def _valid_prices(cls, value: str) -> str:
        if value.strip():
            parse_prices(value)
        return value

    def key_for(self, provider: str) -> str | None:
        secret = {"anthropic": self.anthropic_api_key, "openai": self.openai_api_key}.get(provider)
        value = secret.get_secret_value().strip() if secret else ""
        return value or None


def parse_prices(raw: str) -> dict[str, tuple[Decimal, Decimal]]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM_PRICES_JSON must be an object of model -> [input, output] USD per million tokens")
    prices: dict[str, tuple[Decimal, Decimal]] = {}
    for model, pair in data.items():
        if not (isinstance(pair, list) and len(pair) == 2):
            raise ValueError(f"LLM_PRICES_JSON[{model!r}] must be [input, output]")
        prices[str(model)] = (Decimal(str(pair[0])), Decimal(str(pair[1])))
    return prices


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
