"""Helpers for the Sales AI tests: offline workflow registry, a scripted LLM double, and API shortcuts."""

import json
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from aigentix.core.db import get_session_factory
from aigentix.modules.sales.agents.fixture_llm import FixtureSalesLLM
from aigentix.modules.sales.agents.schemas import BriefOutput, ProposalOutput
from aigentix.modules.sales.config import SalesSettings
from aigentix.modules.sales.workflows.constants import BRIEF_WORKFLOW, PROPOSAL_WORKFLOW
from aigentix.modules.sales.workflows.generation import (
    SalesAIDependencies,
    make_brief_handler,
    make_proposal_handler,
)
from aigentix.platform.llm import LLMProvider, LLMResponse, LLMUsage, Task
from aigentix.platform.workflows.registry import WorkflowRegistry
from aigentix.worker.runner import WorkerSettings, run_once
from tests.conftest import Tenant
from tests.research_helpers import REFERENCE_DATE, client_get

SCRIPTED_DIR = Path(__file__).resolve().parents[1] / "src/aigentix/modules/sales/fixtures/scripted"
SALES_SETTINGS = SalesSettings(environment="test", llm_provider="fixture", sales_llm_max_cost_per_run_usd=Decimal("1"))

Step = BaseModel | Exception | Callable[[str], BaseModel]


class ScriptedSalesLLM:
    """Returns queued outputs in order: a model instance, an exception to raise, or fn(prompt) -> model."""

    name = "scripted"

    def __init__(self, steps: list[Step], *, cost_per_call: Decimal = Decimal("0.001")) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        self.cost_per_call = cost_per_call

    def model_for(self, task: Task) -> str:
        return "claude-haiku-5-5"  # priced, so the cost cap is computed like for a real model

    def structured[T: BaseModel](
        self, *, task: Task, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]:
        self.calls.append({"task": task, "system": system, "prompt": messages[-1]["content"], "max_tokens": max_tokens})
        if not self.steps:
            raise AssertionError("ScriptedSalesLLM ran out of scripted responses")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        output = step(str(messages[-1]["content"])) if callable(step) and not isinstance(step, BaseModel) else step
        assert isinstance(output, output_model), f"scripted {type(output).__name__} for {output_model.__name__}"
        usage = LLMUsage(model=f"scripted-{task}", input_tokens=100, output_tokens=50, cost_usd=self.cost_per_call)
        return LLMResponse(output=output, usage=usage)  # type: ignore[arg-type]


def evidence_in_prompt(prompt: str) -> list[dict[str, Any]]:
    match = re.search(r"<evidence>\n(.*?)\n</evidence>", prompt, re.S)
    return json.loads(match.group(1)) if match else []  # type: ignore[no-any-return]


def scripted(name: str) -> Callable[[str], BaseModel]:
    """A scripted answer from sales/fixtures/scripted/<name>.json; {{E1}} becomes the prompt's E1 fact."""
    raw = (SCRIPTED_DIR / f"{name}.json").read_text(encoding="utf-8")
    model: type[BaseModel] = ProposalOutput if "proposal" in name else BriefOutput

    def answer(prompt: str) -> BaseModel:
        evidence = evidence_in_prompt(prompt)
        e1 = next((e for e in evidence if e["id"] == "E1"), None)
        fact = e1["fact"] if e1 and e1.get("origin", "deterministic") == "deterministic" else (e1 or {}).get("excerpt")
        return model.model_validate_json(raw.replace("{{E1}}", json.dumps(fact or "")[1:-1]))

    return answer


def sales_registry(
    provider: Callable[[], LLMProvider | None] = FixtureSalesLLM,
    settings: SalesSettings = SALES_SETTINGS,
    today: date = REFERENCE_DATE,
) -> WorkflowRegistry:
    deps = SalesAIDependencies(settings=settings, provider_factory=provider, today=lambda: today)
    registry = WorkflowRegistry()
    registry.register(BRIEF_WORKFLOW, make_brief_handler(lambda: deps))
    registry.register(PROPOSAL_WORKFLOW, make_proposal_handler(lambda: deps))
    return registry


def drain(registry: WorkflowRegistry, *, max_runs: int = 20) -> int:
    processed = 0
    settings = WorkerSettings(retry_base_delay=timedelta(0))
    while processed < max_runs and run_once(get_session_factory(), registry, settings):
        processed += 1
    return processed


def generate_brief(t: Tenant, deal_id: str, registry: WorkflowRegistry | None = None) -> dict[str, Any]:
    response = t.client.post(f"/api/v1/sales/opportunities/{deal_id}/briefs", headers=t.headers)
    assert response.status_code == 202, response.text
    brief_id = response.json()["id"]
    drain(registry or sales_registry())
    return client_get(t.client, f"/api/v1/sales/briefs/{brief_id}", t.headers)  # type: ignore[no-any-return]


def generate_proposal(t: Tenant, deal_id: str, registry: WorkflowRegistry | None = None, **body: Any) -> dict[str, Any]:
    response = t.client.post(f"/api/v1/sales/opportunities/{deal_id}/proposals", json=body, headers=t.headers)
    assert response.status_code == 202, response.text
    proposal_id = response.json()["id"]
    drain(registry or sales_registry())
    return client_get(t.client, f"/api/v1/sales/proposals/{proposal_id}", t.headers)  # type: ignore[no-any-return]


def add_service(t: Tenant, **fields: Any) -> dict[str, Any]:
    response = t.client.post("/api/v1/sales/services", json=fields, headers=t.headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def brief_text(brief: dict[str, Any]) -> str:
    return json.dumps(brief["content"], ensure_ascii=False)


def sections_by_key(proposal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["key"]: s for s in proposal["sections"]}
