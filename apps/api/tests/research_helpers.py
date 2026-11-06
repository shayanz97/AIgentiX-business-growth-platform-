"""Shared helpers for Lead Intelligence tests: offline research dependencies and a worker driver."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from aigentix.core.db import get_session_factory
from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider
from aigentix.modules.lead_intelligence.config import ResearchSettings
from aigentix.modules.lead_intelligence.integrations.fetcher import FetcherConfig, SafeFetcher
from aigentix.modules.lead_intelligence.integrations.fixture_web import fixture_resolver, fixture_transport
from aigentix.modules.lead_intelligence.workflows.constants import RESEARCH_WORKFLOW
from aigentix.modules.lead_intelligence.workflows.research import ResearchDependencies, make_research_handler
from aigentix.platform.llm import LLMProvider
from aigentix.platform.workflows.registry import WorkflowRegistry
from aigentix.worker.runner import WorkerSettings, run_once
from tests.conftest import Tenant

FIXTURE_SETTINGS = ResearchSettings(
    environment="test",
    research_fetch_backend="fixtures",
    llm_provider="fixture",
    research_domain_min_interval_seconds=0,
    llm_max_cost_per_run_usd=Decimal("1.00"),
)


def research_registry(
    provider: Callable[[], LLMProvider | None] = FixtureLLMProvider,
    settings: ResearchSettings = FIXTURE_SETTINGS,
    fetcher: Callable[[], SafeFetcher] | None = None,
) -> WorkflowRegistry:
    def default_fetcher() -> SafeFetcher:
        return SafeFetcher(
            FetcherConfig(user_agent="test-bot", max_bytes=settings.research_max_response_bytes),
            resolver=fixture_resolver,
            transport=fixture_transport(),
        )

    deps = ResearchDependencies(
        settings=settings, fetcher_factory=fetcher or default_fetcher, provider_factory=provider
    )
    registry = WorkflowRegistry()
    registry.register(RESEARCH_WORKFLOW, make_research_handler(lambda: deps), max_concurrent=2)
    return registry


def drain(registry: WorkflowRegistry, *, max_runs: int = 50) -> int:
    processed = 0
    while processed < max_runs and run_once(get_session_factory(), registry, WorkerSettings()):
        processed += 1
    return processed


def add_company(t: Tenant, website: str, **extra: Any) -> dict[str, Any]:
    response = t.client.post("/api/v1/companies", json={"website_url": website, **extra}, headers=t.headers)
    assert response.status_code in (200, 201), response.text
    return response.json()["company"]  # type: ignore[no-any-return]


def start(t: Tenant, company_ids: list[str]) -> dict[str, Any]:
    response = t.client.post("/api/v1/research-runs", json={"company_ids": company_ids}, headers=t.headers)
    assert response.status_code == 202, response.text
    return response.json()  # type: ignore[no-any-return]


def research_company(t: Tenant, domain: str, registry: WorkflowRegistry) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add a fixture company, research it to completion and return (run, results)."""
    company = add_company(t, f"https://{domain}/")
    run_id = start(t, [company["id"]])["started"][0]["id"]
    drain(registry)
    run = t.client.get(f"/api/v1/research-runs/{run_id}", headers=t.headers).json()
    results = t.client.get(f"/api/v1/research-runs/{run_id}/results", headers=t.headers).json()
    return run, results


def client_get(client: TestClient, url: str, headers: dict[str, str]) -> Any:
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()
