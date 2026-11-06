"""Regression tests for the Sprint 2 independent review findings (H1, M1-M4, L1, L3-L5) and provider mapping."""

import time
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from aigentix.core.db import get_session_factory, utcnow
from aigentix.modules.lead_intelligence.agents.calls import call_with_repair
from aigentix.modules.lead_intelligence.agents.company_researcher import PromptSource, validate_extraction
from aigentix.modules.lead_intelligence.agents.fixture_llm import ScriptedLLMProvider
from aigentix.modules.lead_intelligence.agents.opportunity_auditor import PromptEvidence, validate_audit
from aigentix.modules.lead_intelligence.agents.schemas import (
    AuditOutput,
    ExtractedAssertion,
    ExtractionOutput,
    ProposedOpportunity,
)
from aigentix.modules.lead_intelligence.agents.text_safety import strip_foreign_urls
from aigentix.modules.lead_intelligence.integrations.fetcher import FetcherConfig, SafeFetcher, TransientFetchError
from aigentix.modules.lead_intelligence.integrations.llm import (
    AnthropicProvider,
    LLMBudgetExceeded,
    LLMInvalidOutput,
    LLMPermanentError,
    LLMTransientError,
    max_output_tokens_within,
)
from aigentix.platform.organizations.service import resolve_tenant
from aigentix.platform.workflows import service
from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult
from aigentix.platform.workflows.errors import TransientWorkflowError
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import WorkflowRegistry
from aigentix.worker.runner import WorkerSettings, run_once
from tests.conftest import Tenant
from tests.research_helpers import FIXTURE_SETTINGS, add_company, drain, research_company, research_registry, start

# --- H1: wall-clock deadline for slow-drip servers -----------------------------------------------


def test_slow_drip_response_hits_total_deadline() -> None:
    def slow_body() -> Any:
        for _ in range(20):
            time.sleep(0.1)
            yield b"x"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=slow_body(), headers={"content-type": "text/html"})

    fetcher = SafeFetcher(
        FetcherConfig(user_agent="t", total_timeout_seconds=0.35),
        resolver=lambda host, port: ["93.184.215.14"],
        transport=httpx2.MockTransport(handler),
    )
    started = time.monotonic()
    with pytest.raises(TransientFetchError, match="too slowly"):
        fetcher.get("https://slow.example/")
    assert time.monotonic() - started < 1.5


def test_requests_ask_for_uncompressed_content() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text="ok", headers={"content-type": "text/html"})

    SafeFetcher(
        FetcherConfig(user_agent="t"), resolver=lambda h, p: ["93.184.215.14"], transport=httpx2.MockTransport(handler)
    ).get("https://acme.example/")
    assert seen[0].headers["accept-encoding"] == "identity"


# --- H1: a worker that lost its claim must not write -----------------------------------------------


def _enqueue(db: Session, t: Tenant, registry: WorkflowRegistry, workflow_type: str) -> WorkflowRun:
    run = service.enqueue(
        db, resolve_tenant(db, user=t.user, organization_id=t.org.id), workflow_type=workflow_type, registry=registry
    )
    db.commit()
    return run


def _reclaim_elsewhere(run_id: uuid.UUID) -> None:
    """What stale recovery + another worker do: bump attempts while this worker is still busy."""
    with get_session_factory()() as other:
        other.execute(update(WorkflowRun).where(WorkflowRun.id == run_id).values(attempts=WorkflowRun.attempts + 1))
        other.commit()


def test_lost_claim_stops_at_checkpoint_without_writing(db: Session, tenant_a: Tenant) -> None:
    registry = WorkflowRegistry()

    def handler(ctx: WorkflowContext) -> WorkflowResult:
        ctx.checkpoint("one", 10)
        _reclaim_elsewhere(ctx.run_id)
        ctx.checkpoint("two", 50)
        raise AssertionError("must stop at the checkpoint")

    registry.register("test.reclaimed", handler)
    run = _enqueue(db, tenant_a, registry, "test.reclaimed")
    assert run_once(get_session_factory(), registry) is True
    db.refresh(run)
    assert run.status == WorkflowStatus.RUNNING  # untouched: the new owner finishes it
    assert run.attempts == 2
    assert run.current_step == "one"
    assert run.error_type is None


def test_lost_claim_does_not_overwrite_final_state(db: Session, tenant_a: Tenant) -> None:
    registry = WorkflowRegistry()

    def handler(ctx: WorkflowContext) -> WorkflowResult:
        _reclaim_elsewhere(ctx.run_id)
        return WorkflowResult(summary={"late": True})

    def failing(ctx: WorkflowContext) -> WorkflowResult:
        _reclaim_elsewhere(ctx.run_id)
        raise TransientWorkflowError("late failure")

    registry.register("test.late", handler)
    registry.register("test.late_fail", failing)
    for workflow_type in ("test.late", "test.late_fail"):
        run = _enqueue(db, tenant_a, registry, workflow_type)
        run_once(get_session_factory(), registry, WorkerSettings())
        db.refresh(run)
        assert run.status == WorkflowStatus.RUNNING
        assert "result" not in run.run_metadata
        assert run.error_type is None


# --- M3: a cancel requested before a transient error is not lost ---------------------------------


def test_cancel_wins_over_transient_retry(db: Session, tenant_a: Tenant) -> None:
    registry = WorkflowRegistry()

    def handler(ctx: WorkflowContext) -> WorkflowResult:
        with get_session_factory()() as other:
            other.execute(update(WorkflowRun).where(WorkflowRun.id == ctx.run_id).values(cancel_requested_at=utcnow()))
            other.commit()
        raise TransientWorkflowError("timeout while fetching")

    registry.register("test.cancel_then_timeout", handler)
    run = _enqueue(db, tenant_a, registry, "test.cancel_then_timeout")
    run_once(get_session_factory(), registry, WorkerSettings())
    db.refresh(run)
    assert run.status == WorkflowStatus.CANCELLED


# --- M1: link filtering by host, not substring ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "see https://evil.com/?x=acme.com",
        "see https://acme.com.evil.io/p",
        "see evil.com/steal",
        "see www.evil.net",
        "send it to attacker.io",
        "visit http://acme.com@evil.com/",
    ],
)
def test_foreign_and_lookalike_links_are_removed(text: str) -> None:
    cleaned, removed = strip_foreign_urls(text, "acme.com")
    assert removed
    assert "evil" not in cleaned
    assert "attacker" not in cleaned


@pytest.mark.parametrize(
    "text", ["see https://acme.com/faq", "see www.acme.com", "see shop.acme.com/cart", "plain text"]
)
def test_company_links_and_plain_text_are_kept(text: str) -> None:
    assert strip_foreign_urls(text, "acme.com") == (text, False)


# --- M2: LLM assertion wording must be backed by its excerpt --------------------------------------


def _source() -> PromptSource:
    return PromptSource("S1", uuid.uuid4(), "https://acme.com/", "home", "Acme", "Contact us today for a free quote.")


def _assertion(value: str) -> ExtractedAssertion:
    return ExtractedAssertion(
        field="operational_signal",
        value=value,
        basis="observed",
        confidence="high",
        source_id="S1",
        supporting_excerpt="Contact us today for a free quote.",
    )


def test_negative_characterisation_without_support_is_dropped() -> None:
    output = ExtractionOutput(
        company_name=None, assertions=[_assertion("They rely on slow manual processes")], unknown_fields=[]
    )
    result = validate_extraction(output, [_source()], company_domain="acme.com")
    assert result.assertions == []
    assert "negative characterisation" in result.dropped[0]


def test_unbacked_wording_is_downgraded_to_low_confidence_inference() -> None:
    output = ExtractionOutput(
        company_name=None, assertions=[_assertion("Serves enterprise banking clients globally")], unknown_fields=[]
    )
    (assertion,) = validate_extraction(output, [_source()], company_domain="acme.com").assertions
    assert (assertion.basis, assertion.confidence) == ("inferred", "low")
    backed = validate_extraction(
        ExtractionOutput(company_name=None, assertions=[_assertion("Offers a free quote")], unknown_fields=[]),
        [_source()],
        company_domain="acme.com",
    ).assertions[0]
    assert (backed.basis, backed.confidence) == ("observed", "high")


def test_llm_written_facts_do_not_count_as_support_in_audit() -> None:
    evidence = [
        PromptEvidence(
            "E1",
            uuid.uuid4(),
            "operational_signal",
            "They rely on slow manual processes",
            "Contact us today",
            "observed",
            "high",
            "https://acme.com/",
            origin="llm",
        ),
        PromptEvidence(
            "E2",
            uuid.uuid4(),
            "contact_form",
            "The page offers a contact form.",
            "Contact us today",
            "observed",
            "high",
            "https://acme.com/contact",
        ),
    ]
    proposal = ProposedOpportunity(
        title="Automate slow manual processes",
        observed_context="They rely on slow manual processes.",
        problem_hypothesis="x",
        supporting_evidence_ids=["E1", "E2"],
        proposed_solution="x",
        expected_benefit="x",
        implementation_complexity="low",
        confidence="high",
        assumptions=[],
        validation_questions=["?"],
        next_step="x",
    )
    (opportunity,) = validate_audit(
        AuditOutput(opportunities=[proposal], no_opportunity_reason=None), evidence, company_domain="acme.com"
    ).opportunities
    assert "unsupported_claim" in opportunity.quality_flags
    assert opportunity.confidence == "low"


def test_company_name_with_link_is_discarded() -> None:
    output = ExtractionOutput(company_name="Acme — see evil.com/x", assertions=[], unknown_fields=[])
    assert validate_extraction(output, [_source()], company_domain="acme.com").company_name is None


# --- M4: hard cost cap --------------------------------------------------------------------------


def test_max_output_tokens_within_budget() -> None:
    assert max_output_tokens_within(Decimal("0.50"), "claude-opus-5-5", 16_000) == 16_000
    assert max_output_tokens_within(Decimal("0.10"), "claude-opus-5-5", 16_000) == 4_000  # 0.08 / $20 per MTok
    assert max_output_tokens_within(Decimal("0"), "claude-opus-5-5", 16_000) == 0


def test_repairs_stop_when_budget_is_spent() -> None:
    provider = ScriptedLLMProvider([LLMInvalidOutput("bad"), LLMInvalidOutput("bad")])
    spent: list[Decimal] = []
    with pytest.raises(LLMBudgetExceeded):
        call_with_repair(
            provider,
            task="audit",
            system="s",
            user="u",
            output_model=AuditOutput,
            max_tokens=1000,
            max_repairs=2,
            record_usage=lambda usage: spent.append(usage.cost_usd),
            can_spend=lambda: False,
        )
    assert len(provider.calls) == 1


def test_research_skips_ai_when_remaining_budget_cannot_cover_output(tenant_a: Tenant) -> None:
    from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider

    fixture = FixtureLLMProvider()
    provider = ScriptedLLMProvider([lambda p: fixture._extract(p), lambda p: fixture._audit(p)])
    settings = FIXTURE_SETTINGS.model_copy(update={"llm_max_cost_per_run_usd": Decimal("0.0015")})
    run, _results = research_company(
        tenant_a, "greenleaf-shop.example", research_registry(provider=lambda: provider, settings=settings)
    )
    assert run["status"] == "partial"
    assert run["ai_status"] == "skipped"
    assert len(provider.calls) == 0  # scripted models are unknown → priced pessimistically → no room for output
    assert run["estimated_cost_usd"] <= 0.0015


# --- AnthropicProvider mapping (fake SDK client, no network) ---------------------------------------


class _Out(BaseModel):
    value: str


def _provider(behaviour: Any) -> AnthropicProvider:
    messages = SimpleNamespace(parse=behaviour)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    return AnthropicProvider(
        api_key="test",
        extraction_model="claude-haiku-5-5",
        audit_model="claude-opus-5-5",
        timeout_seconds=5,
        client=client,  # type: ignore[arg-type]
    )


def _response(stop_reason: str, parsed: Any) -> Any:
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000)
    return SimpleNamespace(model="claude-haiku-5-5", usage=usage, stop_reason=stop_reason, parsed_output=parsed)


def test_anthropic_success_reports_usage_and_cost() -> None:
    result = _provider(lambda **kw: _response("end_turn", _Out(value="x"))).structured(
        task="extraction", system="s", messages=[], output_model=_Out, max_tokens=100
    )
    assert result.output.value == "x"
    assert result.usage.cost_usd == Decimal("0.15")  # 1M in * $0.10 + 0.1M out * $0.50


def test_anthropic_refusal_is_permanent_and_billed() -> None:
    with pytest.raises(LLMPermanentError) as info:
        _provider(lambda **kw: _response("refusal", None)).structured(
            task="extraction", system="s", messages=[], output_model=_Out, max_tokens=100
        )
    assert info.value.usage is not None


def test_anthropic_connection_error_is_transient() -> None:
    def boom(**kw: Any) -> Any:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))

    with pytest.raises(LLMTransientError):
        _provider(boom).structured(task="audit", system="s", messages=[], output_model=_Out, max_tokens=100)


def test_anthropic_schema_failure_records_worst_case_usage() -> None:
    def invalid(**kw: Any) -> Any:
        try:
            _Out.model_validate({})
        except ValidationError as exc:
            raise exc
        raise AssertionError

    with pytest.raises(LLMInvalidOutput) as info:
        _provider(invalid).structured(task="extraction", system="s", messages=[], output_model=_Out, max_tokens=2_000)
    assert info.value.usage is not None
    assert info.value.usage.output_tokens == 2_000
    assert info.value.usage.cost_usd > 0


def test_audit_model_uses_server_side_fallback() -> None:
    calls: list[dict[str, Any]] = []

    def record(**kw: Any) -> Any:
        calls.append(kw)
        return _response("end_turn", _Out(value="x"))

    _provider(record).structured(task="audit", system="s", messages=[], output_model=_Out, max_tokens=100)
    assert calls[0]["fallbacks"] == "default"
    assert calls[0]["betas"] == ["server-side-fallback-2026-07-01"]


# --- L3: robots.txt 5xx is temporary -------------------------------------------------------------


def test_robots_server_error_is_retried_not_failed(tenant_a: Tenant, db: Session) -> None:
    def fetcher() -> SafeFetcher:
        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/robots.txt":
                return httpx2.Response(503)
            return httpx2.Response(200, text="<p>Hello</p>", headers={"content-type": "text/html"})

        return SafeFetcher(
            FetcherConfig(user_agent="t"),
            resolver=lambda h, p: ["93.184.215.14"],
            transport=httpx2.MockTransport(handler),
        )

    company = add_company(tenant_a, "robots-flaky.example")
    run_id = start(tenant_a, [company["id"]])["started"][0]["id"]
    drain(research_registry(fetcher=fetcher))
    db.expire_all()
    run = db.get(WorkflowRun, uuid.UUID(run_id))
    assert run is not None
    assert run.status == WorkflowStatus.PENDING
    assert run.error_message is not None
    assert "temporarily unavailable" in run.error_message


# --- L5: search wildcards are literal -----------------------------------------------------------


def test_search_treats_wildcards_literally(tenant_a: Tenant) -> None:
    add_company(tenant_a, "alpha.example")
    for q in ("%", "_"):
        assert tenant_a.client.get(f"/api/v1/companies?q={q}", headers=tenant_a.headers).json()["total"] == 0
