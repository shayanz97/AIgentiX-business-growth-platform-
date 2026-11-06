"""Bounded repair loop around a structured LLM call, with usage reported for every attempt."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from aigentix.platform.llm import (
    LLMBudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    LLMUsage,
    Task,
)

UsageSink = Callable[[LLMUsage], None]


def call_with_repair[T: BaseModel](
    provider: LLMProvider,
    *,
    task: Task,
    system: str,
    user: str,
    output_model: type[T],
    max_tokens: int,
    max_repairs: int,
    record_usage: UsageSink,
    can_spend: Callable[[], bool] | None = None,
) -> T:
    content = user
    for attempt in range(max_repairs + 1):
        if attempt > 0 and can_spend is not None and not can_spend():
            raise LLMBudgetExceeded("The per-run AI cost limit was reached before the response could be repaired")
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        try:
            response = provider.structured(
                task=task, system=system, messages=messages, output_model=output_model, max_tokens=max_tokens
            )
        except LLMInvalidOutput as exc:
            if exc.usage:
                record_usage(exc.usage)
            if attempt >= max_repairs:
                raise
            content = (
                f"{user}\n\nYour previous answer was rejected: {exc}. "
                "Answer again with output that exactly matches the required schema."
            )
            continue
        except LLMError as exc:
            if exc.usage:
                record_usage(exc.usage)
            raise
        record_usage(response.usage)
        return response.output
    raise AssertionError("unreachable")
