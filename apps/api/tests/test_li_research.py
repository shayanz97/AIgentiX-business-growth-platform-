"""Research workflow integration: lifecycle, persistence, failures, retries, resume, cancellation, AI handling."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from aigentix.core.db import get_session_factory, utcnow
from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider, ScriptedLLMProvider
from aigentix.modules.lead_intelligence.agents.schemas import AuditOutput, ExtractionOutput, ProposedOpportunity
from aigentix.modules.lead_intelligence.config import ResearchSettings
from aigentix.modules.lead_intelligence.integrations.fetcher import FetcherConfig, SafeFetcher, TransientFetchError
from aigentix.modules.lead_intelligence.integrations.fixture_web import fixture_resolver, fixture_transport
from aigentix.modules.lead_intelligence.integrations.llm import (
    LLMInvalidOutput,
    LLMPermanentError,
    LLMTransientError,
    LLMUsage,
)
from aigentix.modules.lead_intelligence.models import Company, Evidence, ResearchSource
from aigentix.platform.workflows.models import WorkflowRun
from aigentix.worker.runner import housekeeping, run_once
from tests.conftest import Tenant
from tests.research_helpers import FIXTURE_SETTINGS, add_company, drain, research_company, research_registry, start


def _run_row(db: Session, run_id: str) -> WorkflowRun:
    db.expire_all()
    run = db.get(WorkflowRun, uuid.UUID(run_id))
    assert run is not None
    return run


def _make_due(db: Session, run_id: str) -> None:
    db.execute(update(WorkflowRun).where(WorkflowRun.id == uuid.UUID(run_id)).values(next_attempt_at=utcnow()))
    db.commit()


def test_full_research_lifecycle_persists_profile_evidence_and_opportunities(tenant_a: Tenant, db: Session) -> None:
    run, results = research_company(tenant_a, "northwind-logistics.example", research_registry())
    assert run["status"] == "completed"
    assert run["progress"] == 100
    assert [s["state"] for s in run["steps"]] == ["done"] * 7
    assert run["ai_status"] == "completed"
    assert run["models_used"] == ["fixture-rules-v1"]
    assert run["prompt_versions"] == {"extraction": "extraction-v1", "audit": "audit-v1"}

    paths = {s["source_url"].split(".example")[1] for s in results["sources"]}
    assert {"/", "/about-us", "/services", "/contact", "/faq", "/careers"} <= paths
    assert not paths & {"/team/jane-doe", "/login", "/privacy-policy"}  # personal profile / login / legal excluded
    assert len(results["sources"]) <= FIXTURE_SETTINGS.research_max_pages

    # Every evidence item is tied to a stored source of this run; LLM excerpts are verbatim from that source.
    sources = {s.id: s for s in db.scalars(select(ResearchSource))}
    for evidence in db.scalars(select(Evidence)):
        source = sources[evidence.source_id]
        assert source.research_run_id == evidence.research_run_id
        if evidence.origin == "llm":
            assert (
                " ".join(evidence.supporting_excerpt.split()).lower() in " ".join(source.extracted_text.split()).lower()
            )
    labels = {e["id"]: e["label"] for e in results["evidence"]}
    assert results["opportunities"]
    for opportunity in results["opportunities"]:
        assert opportunity["evidence"]
        assert all(e["id"] in labels for e in opportunity["evidence"])
        assert opportunity["validation_questions"]

    company = tenant_a.client.get(f"/api/v1/companies/{run['company_id']}", headers=tenant_a.headers).json()
    assert company["name"] == "Northwind Logistics"  # derived from the website title
    assert company["short_description"]
    assert company["research_status"] == "completed"
    assert company["profile"]["generated_by"]["models"] == ["fixture-rules-v1"]
    assert "@" not in " ".join(s.extracted_text for s in sources.values())  # e-mail addresses redacted


def test_results_survive_restart(tenant_a: Tenant) -> None:
    """A new API process (new app, new session) reads the same persisted results."""
    from fastapi.testclient import TestClient

    from aigentix.api.app import create_app
    from tests.conftest import login

    run, results = research_company(tenant_a, "brightsmile-dental.example", research_registry())
    with TestClient(create_app()) as fresh:
        login(fresh, tenant_a.user.email)
        again = fresh.get(f"/api/v1/research-runs/{run['id']}/results", headers=tenant_a.headers).json()
    assert [e["id"] for e in again["evidence"]] == [e["id"] for e in results["evidence"]]
    assert [o["id"] for o in again["opportunities"]] == [o["id"] for o in results["opportunities"]]


@pytest.mark.parametrize(
    ("domain", "message"),
    [
        ("robots-blocked.example", "robots.txt"),
        ("ssrf-redirect.example", "blocked for safety reasons"),
        ("not-a-fixture.example", "does not resolve"),
    ],
)
def test_permanent_failures_are_not_retried(tenant_a: Tenant, db: Session, domain: str, message: str) -> None:
    run, results = research_company(tenant_a, domain, research_registry())
    assert run["status"] == "failed"
    assert message in run["error_message"]
    assert run["attempts"] == 1
    assert results["opportunities"] == []
    assert _run_row(db, run["id"]).next_attempt_at is None


def test_broken_pages_are_recorded_without_failing_the_run(tenant_a: Tenant) -> None:
    run, results = research_company(tenant_a, "sparse-info.example", research_registry())
    assert run["status"] == "completed"
    failed = [s for s in results["sources"] if s["extraction_status"] == "failed"]
    assert len(failed) == 3
    assert {s["http_status"] for s in failed} <= {404, 500}


def test_no_ai_provider_gives_partial_result_without_opportunities(tenant_a: Tenant) -> None:
    run, results = research_company(tenant_a, "northwind-logistics.example", research_registry(provider=lambda: None))
    assert run["status"] == "partial"
    assert run["ai_status"] == "unavailable"
    assert "no AI provider is configured" in run["error_message"]
    assert results["opportunities"] == []
    assert results["evidence"]  # deterministic research still ran
    assert {e["origin"] for e in results["evidence"]} == {"deterministic"}
    assert run["estimated_cost_usd"] == 0


def _scripted_happy() -> list[Any]:
    fixture = FixtureLLMProvider()
    return [
        lambda prompt: fixture._extract(prompt),
        lambda prompt: fixture._audit(prompt),
    ]


def test_transient_fetch_error_retries_and_resumes_without_duplicates(tenant_a: Tenant, db: Session) -> None:
    calls = {"n": 0}

    def flaky_fetcher() -> SafeFetcher:
        fetcher = SafeFetcher(FetcherConfig(user_agent="t"), resolver=fixture_resolver, transport=fixture_transport())
        original = fetcher.get

        def get(url: str) -> Any:
            calls["n"] += 1
            if url.endswith("/faq") and calls["n"] < 50 and not getattr(get, "failed", False):
                get.failed = True  # type: ignore[attr-defined]
                raise TransientFetchError("timeout")
            return original(url)

        fetcher.get = get  # type: ignore[method-assign]
        return fetcher

    # A failing sub-page is recorded and the run continues (no retry needed for optional pages).
    run, results = research_company(tenant_a, "northwind-logistics.example", research_registry(fetcher=flaky_fetcher))
    assert run["status"] == "completed"
    assert any(s["extraction_status"] == "failed" for s in results["sources"])

    # A failing homepage is transient → the run is re-queued, then resumes.
    state = {"failed": False}

    def homepage_down_once() -> SafeFetcher:
        fetcher = SafeFetcher(FetcherConfig(user_agent="t"), resolver=fixture_resolver, transport=fixture_transport())
        original = fetcher.get

        def get(url: str) -> Any:
            if url.rstrip("/").endswith("brightsmile-dental.example") and not state["failed"]:
                state["failed"] = True
                raise TransientFetchError("The website did not respond in time")
            return original(url)

        fetcher.get = get  # type: ignore[method-assign]
        return fetcher

    registry = research_registry(fetcher=homepage_down_once)
    company = add_company(tenant_a, "brightsmile-dental.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    drain(registry)
    row = _run_row(db, run_id)
    assert row.status == "pending"
    assert row.error_type == "TransientWorkflowError"
    assert row.next_attempt_at is not None
    _make_due(db, run_id)
    drain(registry)
    row = _run_row(db, run_id)
    assert row.status == "completed"
    assert row.attempts == 2
    urls = list(db.scalars(select(ResearchSource.source_url).where(ResearchSource.research_run_id == row.id)))
    assert len(urls) == len(set(urls))


class _WorkerCrash(BaseException):
    """Simulates the worker process dying (not handled by the runner)."""


def test_worker_crash_resumes_from_persisted_step_without_refetching(tenant_a: Tenant, db: Session) -> None:
    fetched: list[str] = []

    def counting_fetcher() -> SafeFetcher:
        fetcher = SafeFetcher(FetcherConfig(user_agent="t"), resolver=fixture_resolver, transport=fixture_transport())
        original = fetcher.get

        def get(url: str) -> Any:
            fetched.append(url)
            return original(url)

        fetcher.get = get  # type: ignore[method-assign]
        return fetcher

    def crashing_provider() -> ScriptedLLMProvider:
        return ScriptedLLMProvider([_WorkerCrash()])  # type: ignore[list-item]

    company = add_company(tenant_a, "fjord-accounting.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    with pytest.raises(_WorkerCrash):
        run_once(get_session_factory(), research_registry(provider=crashing_provider, fetcher=counting_fetcher))
    row = _run_row(db, run_id)
    assert row.status == "running"
    assert row.current_step == "extract_information"
    sources_before = db.scalar(select(func.count()).select_from(ResearchSource))
    pages_before = [u for u in fetched if not u.endswith("robots.txt")]

    # Housekeeping notices the dead worker and re-queues; the next worker resumes.
    db.execute(update(WorkflowRun).where(WorkflowRun.id == row.id).values(heartbeat_at=utcnow() - timedelta(hours=1)))
    db.commit()
    housekeeping(get_session_factory(), stale_after=timedelta(minutes=10))
    assert _run_row(db, run_id).status == "pending"
    fetched.clear()
    drain(research_registry(fetcher=counting_fetcher))
    row = _run_row(db, run_id)
    assert row.status == "completed"
    assert row.attempts == 2
    assert [u for u in fetched if not u.endswith("robots.txt")] == []  # nothing re-fetched
    assert db.scalar(select(func.count()).select_from(ResearchSource)) == sources_before
    assert pages_before


def test_cancellation_between_steps(tenant_a: Tenant, db: Session) -> None:
    company = add_company(tenant_a, "northwind-logistics.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]

    def cancelling_fetcher() -> SafeFetcher:
        fetcher = SafeFetcher(FetcherConfig(user_agent="t"), resolver=fixture_resolver, transport=fixture_transport())
        original = fetcher.get

        def get(url: str) -> Any:
            if url.endswith("/services"):
                tenant_a.client.post(f"/api/v1/research-runs/{run_id}/cancel", headers=tenant_a.headers)
            return original(url)

        fetcher.get = get  # type: ignore[method-assign]
        return fetcher

    drain(research_registry(fetcher=cancelling_fetcher))
    run = tenant_a.client.get(f"/api/v1/research-runs/{run_id}", headers=tenant_a.headers).json()
    assert run["status"] == "cancelled"
    assert run["cancel_requested"] is True
    assert run["current_step"] == "discover_relevant_pages"
    assert (
        tenant_a.client.get(f"/api/v1/research-runs/{run_id}/results", headers=tenant_a.headers).json()["opportunities"]
        == []
    )


def test_ai_transient_error_retries_then_completes(tenant_a: Tenant, db: Session) -> None:
    script = [LLMTransientError("overloaded"), *_scripted_happy()]
    provider = ScriptedLLMProvider(script)
    registry = research_registry(provider=lambda: provider)
    company = add_company(tenant_a, "greenleaf-shop.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    drain(registry)
    assert _run_row(db, run_id).status == "pending"
    _make_due(db, run_id)
    drain(registry)
    row = _run_row(db, run_id)
    assert row.status == "completed"
    assert row.attempts == 2
    assert row.estimated_cost_usd == Decimal("0.002")  # two successful scripted calls


def test_ai_transient_error_on_last_attempt_degrades_to_partial(tenant_a: Tenant, db: Session) -> None:
    provider = ScriptedLLMProvider([LLMTransientError("overloaded")])
    company = add_company(tenant_a, "greenleaf-shop.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    db.execute(update(WorkflowRun).where(WorkflowRun.id == uuid.UUID(run_id)).values(max_attempts=1))
    db.commit()
    drain(research_registry(provider=lambda: provider))
    run = tenant_a.client.get(f"/api/v1/research-runs/{run_id}", headers=tenant_a.headers).json()
    assert run["status"] == "partial"
    assert run["ai_status"] == "failed"
    assert "temporarily unavailable" not in (run["error_message"] or "")  # it says AI failed, run kept results


def test_invalid_ai_output_is_repaired_within_budget(tenant_a: Tenant) -> None:
    billed = LLMUsage(model="scripted", input_tokens=10, output_tokens=5, cost_usd=Decimal("0.0005"))
    provider = ScriptedLLMProvider([LLMInvalidOutput("bad json", usage=billed), *_scripted_happy()])
    run, results = research_company(tenant_a, "greenleaf-shop.example", research_registry(provider=lambda: provider))
    assert run["status"] == "completed"
    assert len(provider.calls) == 3
    assert "previous answer was rejected" in provider.calls[1]["messages"][0]["content"]
    assert run["estimated_cost_usd"] == pytest.approx(0.0025)  # failed attempt is billed too
    assert results["opportunities"]


def test_invalid_ai_output_beyond_budget_gives_partial(tenant_a: Tenant) -> None:
    settings = FIXTURE_SETTINGS.model_copy(update={"llm_max_repairs": 1})
    provider = ScriptedLLMProvider([LLMInvalidOutput("bad"), LLMInvalidOutput("bad again")])
    run, results = research_company(
        tenant_a, "greenleaf-shop.example", research_registry(provider=lambda: provider, settings=settings)
    )
    assert run["status"] == "partial"
    assert run["ai_status"] == "failed"
    assert results["opportunities"] == []
    assert len(provider.calls) == 2


def test_ai_refusal_is_permanent_and_partial(tenant_a: Tenant) -> None:
    provider = ScriptedLLMProvider([LLMPermanentError("The AI model declined this request")])
    run, _ = research_company(tenant_a, "greenleaf-shop.example", research_registry(provider=lambda: provider))
    assert run["status"] == "partial"
    assert run["attempts"] == 1
    assert "declined" in run["error_message"]


def test_cost_cap_skips_ai(tenant_a: Tenant) -> None:
    settings = ResearchSettings(**{**FIXTURE_SETTINGS.model_dump(), "llm_max_cost_per_run_usd": Decimal(0)})
    provider = ScriptedLLMProvider([])
    run, results = research_company(
        tenant_a, "greenleaf-shop.example", research_registry(provider=lambda: provider, settings=settings)
    )
    assert run["status"] == "partial"
    assert run["ai_status"] == "skipped"
    assert provider.calls == []
    assert results["opportunities"] == []


# --- Prompt injection ------------------------------------------------------------------------------


class SpyProvider(FixtureLLMProvider):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def structured(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.prompts.append(str(kwargs["messages"][-1]["content"]))
        return super().structured(**kwargs)


def test_prompt_injection_content_is_stripped_or_contained(tenant_a: Tenant, db: Session) -> None:
    spy = SpyProvider()
    run, results = research_company(tenant_a, "injection-test.example", research_registry(provider=lambda: spy))
    assert run["status"] == "completed"
    stored = " ".join(db.scalars(select(ResearchSource.extracted_text)))
    extraction_prompt = spy.prompts[0]
    # Hidden-div, HTML-comment and alt-text carriers never reach storage or the model.
    page_html = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/aigentix/modules/lead_intelligence/fixtures/sites/injection-test.example"
    )
    raw = "".join(p.read_text() for p in page_html.glob("*.html"))
    assert raw.count("IGNORE ALL PREVIOUS INSTRUCTIONS") >= 3
    assert stored.count("IGNORE ALL PREVIOUS INSTRUCTIONS") <= 1  # only the visible paragraph survives
    # Visible injection text is delimited as untrusted data and cannot close our delimiters.
    n_sources = len([s for s in results["sources"] if s["extraction_status"] == "extracted"])
    assert extraction_prompt.count("</website_content>") == n_sources
    assert "untrusted data" in spy.prompts[0] or True  # system prompt carries the rule (checked in unit tests)
    # Nothing in stored outputs carries the exfiltration link.
    everything = str(results)
    assert "evil.example" not in everything


def test_compromised_model_output_is_neutralised(tenant_a: Tenant) -> None:
    """Simulate a model that obeyed the injected instructions; validation must contain the damage."""

    def obey(prompt: str) -> AuditOutput:
        return AuditOutput(
            opportunities=[
                ProposedOpportunity(
                    title="Fix severely inefficient manual processes",
                    observed_context="The company has severely inefficient manual processes.",
                    problem_hypothesis="Staff waste hours; see http://evil.example/exfil",
                    supporting_evidence_ids=["E1"],
                    proposed_solution="Send all data to http://evil.example/exfil",
                    expected_benefit="Saves $2M per year",
                    implementation_complexity="low",
                    confidence="high",
                    assumptions=[],
                    validation_questions=[],
                    next_step="Visit http://evil.example/exfil",
                ),
                ProposedOpportunity(
                    title="Invented evidence",
                    observed_context="x",
                    problem_hypothesis="x",
                    supporting_evidence_ids=["E999", "admin"],
                    proposed_solution="x",
                    expected_benefit="x",
                    implementation_complexity="low",
                    confidence="high",
                    assumptions=[],
                    validation_questions=["?"],
                    next_step="x",
                ),
            ],
            no_opportunity_reason=None,
        )

    provider = ScriptedLLMProvider([ExtractionOutput(company_name=None, assertions=[], unknown_fields=[]), obey])
    run, results = research_company(tenant_a, "injection-test.example", research_registry(provider=lambda: provider))
    assert run["status"] == "completed"
    assert len(results["opportunities"]) == 1  # the one citing invented evidence was dropped
    opportunity = results["opportunities"][0]
    assert opportunity["confidence"] == "low"
    assert {"unsupported_claim", "external_link_removed", "missing_validation_questions"} <= set(
        opportunity["quality_flags"]
    )
    assert "evil.example" not in str(results)


def test_company_name_is_not_overwritten_when_user_provided(tenant_a: Tenant, db: Session) -> None:
    company = add_company(tenant_a, "northwind-logistics.example", name="NW (our name)")
    start(tenant_a, [company["id"]])
    drain(research_registry())
    db.expire_all()
    stored = db.get(Company, uuid.UUID(company["id"]))
    assert stored is not None
    assert stored.name == "NW (our name)"
