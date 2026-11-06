"""Anthropic Messages API client (structured output via `messages.parse`)."""

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from aigentix.platform.llm.base import (
    LLMInvalidOutput,
    LLMPermanentError,
    LLMResponse,
    LLMTransientError,
    LLMUsage,
)
from aigentix.platform.llm.pricing import estimate_cost

_FALLBACK_MODELS = ("claude-opus-5", "claude-fable", "claude-sonnet-5-5")


class AnthropicClient:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        server_side_fallback: bool = True,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._fallback = server_side_fallback
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff (2 retries); workflows add
        # step-level retries on top for longer outages.
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def structured[T: BaseModel](
        self, *, model: str, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]:
        try:
            if self._fallback and model.startswith(_FALLBACK_MODELS):
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
            # The SDK does not expose usage when parsing fails: record a worst-case estimate so budgets hold.
            estimate = LLMUsage(
                model=model, output_tokens=max_tokens, cost_usd=estimate_cost(model, 0, max_tokens), provider=self.name
            )
            raise LLMInvalidOutput(
                f"Response did not match the schema: {exc.error_count()} error(s)", usage=estimate
            ) from exc
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            raise LLMTransientError(f"AI provider temporarily unavailable ({type(exc).__name__})") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise LLMTransientError(f"AI provider temporarily unavailable ({exc.status_code})") from exc
            raise LLMPermanentError(f"AI provider rejected the request ({exc.status_code})") from exc

        served_model = str(getattr(response, "model", model))
        input_tokens = int(response.usage.input_tokens or 0)
        output_tokens = int(response.usage.output_tokens or 0)
        usage = LLMUsage(
            model=served_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(served_model, input_tokens, output_tokens),
            provider=self.name,
        )
        if response.stop_reason == "refusal":
            raise LLMPermanentError("The AI model declined this request", usage=usage)
        if response.stop_reason == "max_tokens":
            raise LLMInvalidOutput("The AI response was cut off", usage=usage)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMInvalidOutput("The AI response contained no structured output", usage=usage)
        return LLMResponse(output=parsed, usage=usage)
