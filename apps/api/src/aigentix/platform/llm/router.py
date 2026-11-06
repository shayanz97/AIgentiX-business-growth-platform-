"""Task → `provider:model` routing.

Configuration example (per module task):
    LLM_ROUTE_EXTRACTION=anthropic:claude-haiku-5-5
    LLM_ROUTE_AUDIT=openai:<model-id>
A task whose provider has no API key raises LLMUnavailable, which modules report as "AI analysis unavailable".
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from aigentix.platform.llm.base import LLMResponse, LLMUnavailable, ModelClient, Task
from aigentix.platform.llm.config import LLMSettings


def _anthropic(settings: LLMSettings, key: str) -> ModelClient:
    from aigentix.platform.llm.providers.anthropic import AnthropicClient

    return AnthropicClient(
        api_key=key,
        timeout_seconds=settings.llm_timeout_seconds,
        server_side_fallback=settings.llm_server_side_fallback,
    )


def _openai(settings: LLMSettings, key: str) -> ModelClient:
    from aigentix.platform.llm.providers.openai import OpenAIClient

    return OpenAIClient(api_key=key, timeout_seconds=settings.llm_timeout_seconds)


# Supported vendors: name → factory(settings, api_key). Add new vendors here.
PROVIDERS: dict[str, Callable[[LLMSettings, str], ModelClient]] = {"anthropic": _anthropic, "openai": _openai}


@dataclass(frozen=True)
class Route:
    provider: str
    model: str

    @classmethod
    def parse(cls, value: str) -> "Route":
        provider, sep, model = value.strip().partition(":")
        provider, model = provider.strip().lower(), model.strip()
        if not sep or not provider or not model:
            raise ValueError(
                f"Invalid LLM route {value!r}: expected 'provider:model', e.g. 'anthropic:claude-haiku-5-5'"
            )
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown LLM provider {provider!r} in route {value!r}; supported: {sorted(PROVIDERS)}")
        return cls(provider=provider, model=model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


class RoutedProvider:
    """`LLMProvider` that sends each task to its configured vendor client and model."""

    name = "routed"

    def __init__(self, routes: Mapping[Task, Route], clients: Mapping[str, ModelClient]) -> None:
        self.routes = dict(routes)
        self._clients = dict(clients)

    def model_for(self, task: Task) -> str:
        route = self.routes.get(task)
        if route is None:
            raise LLMUnavailable(f"no AI model is configured for task {task!r}")
        return route.model

    def available(self, task: Task) -> bool:
        route = self.routes.get(task)
        return route is not None and route.provider in self._clients

    def structured[T: BaseModel](
        self, *, task: Task, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]:
        route = self.routes.get(task)
        if route is None:
            raise LLMUnavailable(f"no AI model is configured for task {task!r}")
        client = self._clients.get(route.provider)
        if client is None:
            raise LLMUnavailable(f"no API key is configured for provider {route.provider!r} (task {task!r})")
        return client.structured(
            model=route.model, system=system, messages=messages, output_model=output_model, max_tokens=max_tokens
        )


def build_routed_provider(
    routes: Mapping[Task, str | Route],
    settings: LLMSettings,
    *,
    factories: Mapping[str, Callable[[LLMSettings, str], ModelClient]] | None = None,
) -> RoutedProvider | None:
    """Create clients for the providers the routes use and that have a key. None when no task is usable."""
    parsed = {task: r if isinstance(r, Route) else Route.parse(r) for task, r in routes.items()}
    factories = factories or PROVIDERS
    clients: dict[str, ModelClient] = {}
    for provider in {r.provider for r in parsed.values()}:
        key = settings.key_for(provider)
        if key:
            clients[provider] = factories[provider](settings, key)
    if not clients:
        return None
    return RoutedProvider(parsed, clients)
