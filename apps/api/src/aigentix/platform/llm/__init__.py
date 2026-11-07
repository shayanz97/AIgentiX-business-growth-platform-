"""Shared LLM access for all business modules.

Modules depend only on `LLMProvider` (base.py). Which vendor and model serves a task is configuration:
`RoutedProvider` (router.py) maps task names to `provider:model` routes and dispatches to vendor clients
(providers/). Pricing (pricing.py) turns token usage into cost estimates for budgets and reporting.
"""

from aigentix.platform.llm.base import (
    LLMBudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMPermanentError,
    LLMProvider,
    LLMResponse,
    LLMTransientError,
    LLMUnavailable,
    LLMUsage,
    Task,
)
from aigentix.platform.llm.pricing import estimate_cost, max_output_tokens_within
from aigentix.platform.llm.router import PROVIDERS, Route, RoutedProvider, build_routed_provider

__all__ = [
    "PROVIDERS",
    "LLMBudgetExceeded",
    "LLMError",
    "LLMInvalidOutput",
    "LLMPermanentError",
    "LLMProvider",
    "LLMResponse",
    "LLMTransientError",
    "LLMUnavailable",
    "LLMUsage",
    "Route",
    "RoutedProvider",
    "Task",
    "build_routed_provider",
    "estimate_cost",
    "max_output_tokens_within",
]
