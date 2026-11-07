"""OpenAI Responses API client (structured output via `responses.parse` with a Pydantic `text_format`)."""

from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from aigentix.platform.llm.base import (
    LLMInvalidOutput,
    LLMPermanentError,
    LLMResponse,
    LLMTransientError,
    LLMUsage,
)
from aigentix.platform.llm.pricing import estimate_cost


class OpenAIClient:
    name = "openai"

    def __init__(self, *, api_key: str, timeout_seconds: float, client: openai.OpenAI | None = None) -> None:
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff (2 retries).
        self._client = client or openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def structured[T: BaseModel](
        self, *, model: str, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]:
        try:
            response: Any = self._client.responses.parse(
                model=model,
                instructions=system,
                input=messages,  # type: ignore[arg-type]
                text_format=output_model,
                max_output_tokens=max_tokens,
                store=False,  # do not retain research content on the provider side
            )
        except ValidationError as exc:
            estimate = LLMUsage(
                model=model, output_tokens=max_tokens, cost_usd=estimate_cost(model, 0, max_tokens), provider=self.name
            )
            raise LLMInvalidOutput(
                f"Response did not match the schema: {exc.error_count()} error(s)", usage=estimate
            ) from exc
        except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as exc:
            # APITimeoutError is a subclass of APIConnectionError.
            raise LLMTransientError(f"AI provider temporarily unavailable ({type(exc).__name__})") from exc
        except openai.APIStatusError as exc:
            if exc.status_code in (408, 409, 429) or exc.status_code >= 500:
                raise LLMTransientError(f"AI provider temporarily unavailable ({exc.status_code})") from exc
            raise LLMPermanentError(f"AI provider rejected the request ({exc.status_code})") from exc

        served_model = str(getattr(response, "model", None) or model)
        raw_usage = getattr(response, "usage", None)
        input_tokens = int(getattr(raw_usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(raw_usage, "output_tokens", 0) or 0)
        usage = LLMUsage(
            model=served_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(served_model, input_tokens, output_tokens),
            provider=self.name,
        )

        status = getattr(response, "status", None)
        if status == "failed":
            error = getattr(response, "error", None)
            code = str(getattr(error, "code", "") or "")
            if code in ("server_error", "rate_limit_exceeded"):
                raise LLMTransientError(f"AI provider temporarily unavailable ({code})", usage=usage)
            raise LLMPermanentError(f"AI provider could not complete the request ({code or 'failed'})", usage=usage)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            if reason == "content_filter":
                raise LLMPermanentError("The AI model declined this request (content filter)", usage=usage)
            raise LLMInvalidOutput(f"The AI response was cut off ({reason or 'incomplete'})", usage=usage)
        if _refused(response):
            raise LLMPermanentError("The AI model declined this request", usage=usage)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise LLMInvalidOutput("The AI response contained no structured output", usage=usage)
        return LLMResponse(output=parsed, usage=usage)


def _refused(response: Any) -> bool:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        if any(getattr(part, "type", None) == "refusal" for part in getattr(item, "content", None) or []):
            return True
    return False
