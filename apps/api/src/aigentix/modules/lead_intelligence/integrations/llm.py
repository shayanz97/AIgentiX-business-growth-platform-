"""LLM provider abstraction: structured (Pydantic) outputs, error classification, usage and cost.

Callers depend on `LLMProvider`; `AnthropicProvider` is the production implementation. Test doubles live in
agents/fixture_llm.py. Prices are USD per million tokens (first-party API list prices) and are only used for
estimates shown to users.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

Task = Literal["extraction", "audit"]

# (input, output) USD per 1M tokens.
MODEL_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-fable-5-1": (Decimal("10.00"), Decimal("50.00")),
}
_MILLION = Decimal(1_000_000)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = MODEL_PRICES.get(model, (Decimal("10.00"), Decimal("50.00")))  # unknown: pessimistic
    return (price_in * input_tokens + price_out * output_tokens) / _MILLION


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)


@dataclass(frozen=True)
class LLMResponse[T: BaseModel]:
    output: T
    usage: LLMUsage


class LLMError(Exception):
    """Base class. `usage` is set when the provider was billed before the error."""

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class LLMTransientError(LLMError):
    """Rate limits, overload, timeouts, 5xx — worth retrying later."""


class LLMPermanentError(LLMError):
    """Authentication, invalid request, refusal — retrying will not help."""


class LLMInvalidOutput(LLMError):
    """The response did not match the requested schema (repairable)."""


class LLMProvider(Protocol):
    name: str

    def model_for(self, task: Task) -> str: ...

    def structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        messages: list[dict[str, Any]],
        output_model: type[T],
        max_tokens: int,
    ) -> LLMResponse[T]: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        extraction_model: str,
        audit_model: str,
        timeout_seconds: float,
        server_side_fallback: bool = True,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._models: dict[Task, str] = {"extraction": extraction_model, "audit": audit_model}
        self._fallback = server_side_fallback
        # SDK retries connection errors, 408/409/429 and 5xx with backoff (2 retries); the workflow adds
        # step-level retries on top for longer outages.
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def model_for(self, task: Task) -> str:
        return self._models[task]

    def structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        messages: list[dict[str, Any]],
        output_model: type[T],
        max_tokens: int,
    ) -> LLMResponse[T]:
        model = self._models[task]
        try:
            if self._fallback and model.startswith(("claude-opus-5", "claude-fable", "claude-sonnet-5-5")):
                # Server-side refusal fallback (routes a declined request to a suitable model).
                response: Any = self._client.beta.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,  # type: ignore[arg-type]
                    output_format=output_model,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                response = self._client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,  # type: ignore[arg-type]
                    output_format=output_model,
                )
        except ValidationError as exc:
            raise LLMInvalidOutput(f"Response did not match the schema: {exc.error_count()} error(s)") from exc
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise LLMTransientError(f"AI provider temporarily unavailable ({type(exc).__name__})") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise LLMTransientError(f"AI provider temporarily unavailable ({exc.status_code})") from exc
            raise LLMPermanentError(f"AI provider rejected the request ({exc.status_code})") from exc

        served_model = str(getattr(response, "model", model))
        usage = LLMUsage(
            model=served_model,
            input_tokens=int(response.usage.input_tokens or 0),
            output_tokens=int(response.usage.output_tokens or 0),
            cost_usd=estimate_cost(served_model, response.usage.input_tokens or 0, response.usage.output_tokens or 0),
        )
        if response.stop_reason == "refusal":
            raise LLMPermanentError("The AI model declined this request", usage=usage)
        if response.stop_reason == "max_tokens":
            raise LLMInvalidOutput("The AI response was cut off", usage=usage)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMInvalidOutput("The AI response contained no structured output", usage=usage)
        return LLMResponse(output=parsed, usage=usage)


def build_provider(settings: Any) -> LLMProvider | None:
    """Return the configured provider, or None when AI analysis is unavailable (no key / disabled)."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "fixture":
        from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider

        return FixtureLLMProvider()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not key:
        return None
    return AnthropicProvider(
        api_key=key,
        extraction_model=settings.llm_extraction_model,
        audit_model=settings.llm_audit_model,
        timeout_seconds=settings.llm_timeout_seconds,
        server_side_fallback=settings.llm_server_side_fallback,
    )
