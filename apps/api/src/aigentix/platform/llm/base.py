"""Vendor-neutral LLM contract: structured (Pydantic) output, usage, and a small error taxonomy."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

# A task is a module-defined purpose such as "extraction" or "audit"; routes are configured per task.
Task = str


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    provider: str = ""

    @property
    def label(self) -> str:
        """`provider:model` for reporting (just the model when the provider is unknown)."""
        return f"{self.provider}:{self.model}" if self.provider else self.model


@dataclass(frozen=True)
class LLMResponse[T: BaseModel]:
    output: T
    usage: LLMUsage


class LLMError(Exception):
    """Base class. `usage` is set when the provider was (or may have been) billed before the error."""

    def __init__(self, message: str, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class LLMTransientError(LLMError):
    """Rate limits, overload, timeouts, 5xx — worth retrying later."""


class LLMPermanentError(LLMError):
    """Authentication, invalid request, refusal — retrying will not help."""


class LLMUnavailable(LLMPermanentError):
    """No usable provider/key is configured for this task."""


class LLMInvalidOutput(LLMError):
    """The response did not match the requested schema (repairable)."""


class LLMBudgetExceeded(LLMError):
    """Another call would exceed the per-run cost limit."""


class LLMProvider(Protocol):
    """What modules call. Implementations: RoutedProvider (production) and module test doubles."""

    name: str

    def model_for(self, task: Task) -> str: ...

    def structured[T: BaseModel](
        self, *, task: Task, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]: ...


class ModelClient(Protocol):
    """One vendor's API. The router passes the model explicitly on every call."""

    name: str

    def structured[T: BaseModel](
        self, *, model: str, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]: ...
