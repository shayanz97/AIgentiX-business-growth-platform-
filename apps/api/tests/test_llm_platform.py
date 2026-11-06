"""Shared LLM layer: vendor clients (fake SDK clients, no network), routing, configuration, pricing."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from pydantic import BaseModel, ValidationError

from aigentix.modules.lead_intelligence.config import ResearchSettings
from aigentix.modules.lead_intelligence.integrations.llm import build_provider, research_routes
from aigentix.platform.llm import (
    LLMInvalidOutput,
    LLMPermanentError,
    LLMResponse,
    LLMTransientError,
    LLMUnavailable,
    LLMUsage,
    Route,
    RoutedProvider,
    build_routed_provider,
    estimate_cost,
    max_output_tokens_within,
    pricing,
)
from aigentix.platform.llm.config import LLMSettings
from aigentix.platform.llm.providers.anthropic import AnthropicClient
from aigentix.platform.llm.providers.openai import OpenAIClient


class _Out(BaseModel):
    value: str


def _schema_error(**_: Any) -> Any:
    _Out.model_validate({})
    raise AssertionError


# --- Anthropic client ----------------------------------------------------------------------------


def _anthropic(behaviour: Any) -> AnthropicClient:
    messages = SimpleNamespace(parse=behaviour)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    return AnthropicClient(api_key="test", timeout_seconds=5, client=client)  # type: ignore[arg-type]


def _anthropic_response(stop_reason: str, parsed: Any, model: str = "claude-haiku-5-5") -> Any:
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000)
    return SimpleNamespace(model=model, usage=usage, stop_reason=stop_reason, parsed_output=parsed)


def test_anthropic_success_reports_usage_and_cost() -> None:
    result = _anthropic(lambda **kw: _anthropic_response("end_turn", _Out(value="x"))).structured(
        model="claude-haiku-5-5", system="s", messages=[], output_model=_Out, max_tokens=100
    )
    assert result.output.value == "x"
    assert result.usage.cost_usd == Decimal("0.15")  # 1M in * $0.10 + 0.1M out * $0.50
    assert result.usage.label == "anthropic:claude-haiku-5-5"


def test_anthropic_refusal_is_permanent_and_billed() -> None:
    with pytest.raises(LLMPermanentError) as info:
        _anthropic(lambda **kw: _anthropic_response("refusal", None)).structured(
            model="claude-haiku-5-5", system="s", messages=[], output_model=_Out, max_tokens=100
        )
    assert info.value.usage is not None


def test_anthropic_connection_error_is_transient() -> None:
    def boom(**kw: Any) -> Any:
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))

    with pytest.raises(LLMTransientError):
        _anthropic(boom).structured(model="claude-opus-5-5", system="s", messages=[], output_model=_Out, max_tokens=1)


def test_anthropic_schema_failure_records_worst_case_usage() -> None:
    with pytest.raises(LLMInvalidOutput) as info:
        _anthropic(_schema_error).structured(
            model="claude-haiku-5-5", system="s", messages=[], output_model=_Out, max_tokens=2_000
        )
    assert info.value.usage is not None
    assert info.value.usage.output_tokens == 2_000
    assert info.value.usage.cost_usd > 0


def test_anthropic_uses_server_side_fallback_on_supported_models() -> None:
    calls: list[dict[str, Any]] = []

    def record(**kw: Any) -> Any:
        calls.append(kw)
        return _anthropic_response("end_turn", _Out(value="x"))

    client = _anthropic(record)
    client.structured(model="claude-opus-5-5", system="s", messages=[], output_model=_Out, max_tokens=100)
    client.structured(model="claude-haiku-5-5", system="s", messages=[], output_model=_Out, max_tokens=100)
    assert calls[0]["fallbacks"] == "default"
    assert calls[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert "fallbacks" not in calls[1]


# --- OpenAI client -------------------------------------------------------------------------------


def _openai(behaviour: Any) -> OpenAIClient:
    client = SimpleNamespace(responses=SimpleNamespace(parse=behaviour))
    return OpenAIClient(api_key="test", timeout_seconds=5, client=client)  # type: ignore[arg-type]


def _openai_response(
    *,
    status: str = "completed",
    parsed: Any = None,
    output: list[Any] | None = None,
    incomplete_reason: str | None = None,
    error_code: str | None = None,
) -> Any:
    return SimpleNamespace(
        model="test-model",
        status=status,
        usage=SimpleNamespace(input_tokens=2_000, output_tokens=500),
        output=output or [],
        output_parsed=parsed,
        incomplete_details=SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None,
        error=SimpleNamespace(code=error_code) if error_code else None,
    )


def test_openai_success_passes_schema_and_reports_usage() -> None:
    calls: list[dict[str, Any]] = []

    def parse(**kw: Any) -> Any:
        calls.append(kw)
        return _openai_response(parsed=_Out(value="y"))

    result = _openai(parse).structured(
        model="test-model",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        output_model=_Out,
        max_tokens=321,
    )
    assert result.output.value == "y"
    assert calls[0]["text_format"] is _Out
    assert calls[0]["instructions"] == "sys"
    assert calls[0]["max_output_tokens"] == 321
    assert calls[0]["store"] is False
    assert (result.usage.input_tokens, result.usage.output_tokens) == (2_000, 500)
    assert result.usage.provider == "openai"
    # Unknown model → pessimistic built-in price (fails safe for budgets).
    assert result.usage.cost_usd == estimate_cost("test-model", 2_000, 500) == Decimal("0.045")


def test_openai_refusal_is_permanent() -> None:
    refusal = SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="no")])
    with pytest.raises(LLMPermanentError, match="declined"):
        _openai(lambda **kw: _openai_response(output=[refusal])).structured(
            model="m", system="s", messages=[], output_model=_Out, max_tokens=10
        )


@pytest.mark.parametrize(
    ("reason", "error"),
    [("max_output_tokens", LLMInvalidOutput), ("content_filter", LLMPermanentError)],
)
def test_openai_incomplete_responses(reason: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        _openai(lambda **kw: _openai_response(status="incomplete", incomplete_reason=reason)).structured(
            model="m", system="s", messages=[], output_model=_Out, max_tokens=10
        )


@pytest.mark.parametrize(
    ("code", "error"), [("server_error", LLMTransientError), ("invalid_prompt", LLMPermanentError)]
)
def test_openai_failed_status(code: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        _openai(lambda **kw: _openai_response(status="failed", error_code=code)).structured(
            model="m", system="s", messages=[], output_model=_Out, max_tokens=10
        )


def test_openai_missing_parsed_output_is_repairable() -> None:
    with pytest.raises(LLMInvalidOutput):
        _openai(lambda **kw: _openai_response(parsed=None)).structured(
            model="m", system="s", messages=[], output_model=_Out, max_tokens=10
        )


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return cls("error", response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (
            lambda: openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com")),
            LLMTransientError,
        ),
        (lambda: openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com")), LLMTransientError),
        (lambda: _status_error(openai.RateLimitError, 429), LLMTransientError),
        (lambda: _status_error(openai.InternalServerError, 503), LLMTransientError),
        (lambda: _status_error(openai.AuthenticationError, 401), LLMPermanentError),
        (lambda: _status_error(openai.BadRequestError, 400), LLMPermanentError),
    ],
)
def test_openai_error_mapping(exc: Any, error: type[Exception]) -> None:
    def boom(**kw: Any) -> Any:
        raise exc()

    with pytest.raises(error):
        _openai(boom).structured(model="m", system="s", messages=[], output_model=_Out, max_tokens=10)


def test_openai_schema_failure_records_worst_case_usage() -> None:
    with pytest.raises(LLMInvalidOutput) as info:
        _openai(_schema_error).structured(model="m", system="s", messages=[], output_model=_Out, max_tokens=1_000)
    assert info.value.usage is not None
    assert info.value.usage.cost_usd == estimate_cost("m", 0, 1_000)


def test_research_schemas_are_openai_strict_compatible() -> None:
    """OpenAI strict structured outputs need every property required and no additional properties."""
    from openai.lib._pydantic import to_strict_json_schema

    from aigentix.modules.lead_intelligence.agents.schemas import AuditOutput, ExtractionOutput

    def check(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("properties", {})) == set(node.get("required", []))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    for model in (ExtractionOutput, AuditOutput):
        check(to_strict_json_schema(model))


# --- Routing ---------------------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def structured(self, *, model: str, output_model: type[BaseModel], **_: Any) -> LLMResponse[Any]:
        self.calls.append(model)
        return LLMResponse(
            output=output_model.model_validate({"value": model}), usage=LLMUsage(model=model, provider=self.name)
        )


def test_route_parsing() -> None:
    assert Route.parse(" OpenAI : my-model ") == Route("openai", "my-model")
    assert str(Route.parse("anthropic:claude-haiku-5-5")) == "anthropic:claude-haiku-5-5"
    assert Route.parse("openai:ft:base:org:id").model == "ft:base:org:id"  # colons allowed in model ids
    for bad in ("claude-haiku-5-5", "openai:", ":model", "mistral:large"):
        with pytest.raises(ValueError, match=r"route|provider"):
            Route.parse(bad)


def test_router_dispatches_each_task_to_its_provider_and_model() -> None:
    anthropic_client, openai_client = _FakeClient("anthropic"), _FakeClient("openai")
    provider = RoutedProvider(
        {"extraction": Route("anthropic", "claude-haiku-5-5"), "audit": Route("openai", "o-model")},
        {"anthropic": anthropic_client, "openai": openai_client},
    )
    assert provider.model_for("audit") == "o-model"
    out = provider.structured(task="extraction", system="s", messages=[], output_model=_Out, max_tokens=5)
    assert out.output.value == "claude-haiku-5-5"
    provider.structured(task="audit", system="s", messages=[], output_model=_Out, max_tokens=5)
    assert (anthropic_client.calls, openai_client.calls) == (["claude-haiku-5-5"], ["o-model"])


def test_router_reports_missing_keys_per_task() -> None:
    settings = LLMSettings(anthropic_api_key="a-key", openai_api_key=None)  # type: ignore[arg-type]
    factories = {"anthropic": lambda s, k: _FakeClient("anthropic"), "openai": lambda s, k: _FakeClient("openai")}
    provider = build_routed_provider(
        {"extraction": "anthropic:claude-haiku-5-5", "audit": "openai:o-model"}, settings, factories=factories
    )
    assert provider is not None
    assert provider.available("extraction") is True
    assert provider.available("audit") is False
    with pytest.raises(LLMUnavailable, match="openai"):
        provider.structured(task="audit", system="s", messages=[], output_model=_Out, max_tokens=5)
    with pytest.raises(LLMUnavailable):
        provider.model_for("unknown-task")
    assert build_routed_provider({"audit": "openai:o"}, settings, factories=factories) is None  # no usable key


def test_router_only_creates_clients_for_routed_providers() -> None:
    created: list[str] = []
    settings = LLMSettings(anthropic_api_key="a", openai_api_key="o")  # type: ignore[arg-type]
    factories = {
        "anthropic": lambda s, k: created.append("anthropic") or _FakeClient("anthropic"),
        "openai": lambda s, k: created.append("openai") or _FakeClient("openai"),
    }
    build_routed_provider({"extraction": "openai:a", "audit": "openai:b"}, settings, factories=factories)
    assert created == ["openai"]


def test_blank_keys_count_as_missing() -> None:
    assert LLMSettings(openai_api_key="   ").key_for("openai") is None  # type: ignore[arg-type]
    assert LLMSettings(openai_api_key="sk-x").key_for("openai") == "sk-x"  # type: ignore[arg-type]
    assert LLMSettings().key_for("unknown") is None


# --- Lead Intelligence route resolution -------------------------------------------------------------


def _research(**kw: Any) -> ResearchSettings:
    base: dict[str, Any] = {"environment": "test", "llm_route_extraction": None, "llm_route_audit": None}
    return ResearchSettings(**{**base, **kw})


def test_default_routes_keep_sprint2_behaviour() -> None:
    routes = research_routes(_research(llm_provider="anthropic"))
    assert routes == {
        "extraction": Route("anthropic", "claude-haiku-5-5"),
        "audit": Route("anthropic", "claude-opus-5-5"),
    }


def test_explicit_routes_win_and_can_mix_providers() -> None:
    settings = _research(llm_route_extraction="anthropic:claude-haiku-5-5", llm_route_audit="openai:o-model")
    assert research_routes(settings)["audit"] == Route("openai", "o-model")
    provider = build_provider(settings, LLMSettings(anthropic_api_key="a", openai_api_key="o"))  # type: ignore[arg-type]
    assert isinstance(provider, RoutedProvider)
    assert provider.available("extraction")
    assert provider.available("audit")


def test_openai_provider_requires_openai_models() -> None:
    with pytest.raises(ValidationError, match="LLM_ROUTE_EXTRACTION"):
        _research(llm_provider="openai")
    settings = _research(llm_provider="openai", llm_extraction_model="small-model", llm_audit_model="big-model")
    assert research_routes(settings)["audit"] == Route("openai", "big-model")


def test_invalid_route_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError, match="Unknown LLM provider"):
        _research(llm_route_audit="mistral:large")


def test_no_keys_means_ai_unavailable() -> None:
    assert build_provider(_research(llm_provider="anthropic"), LLMSettings()) is None
    assert build_provider(_research(llm_provider="none"), LLMSettings(anthropic_api_key="a")) is None  # type: ignore[arg-type]


# --- Pricing -----------------------------------------------------------------------------------------


def test_price_overrides_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pricing, "get_llm_settings", lambda: LLMSettings(llm_prices_json='{"o-model": [1.25, 10]}'))
    assert pricing.price_for("o-model") == (Decimal("1.25"), Decimal("10"))
    assert pricing.is_priced("o-model")
    assert not pricing.is_priced("other")
    assert max_output_tokens_within(Decimal("0.10"), "o-model", 50_000) == 8_000  # 0.08 / $10 per MTok


def test_invalid_price_overrides_are_rejected() -> None:
    for raw in ('["x"]', '{"m": 3}', '{"m": [1]}', "not json"):
        with pytest.raises((ValidationError, ValueError)):
            LLMSettings(llm_prices_json=raw)


# --- Mixed routes in the research workflow -----------------------------------------------------------


class _FixtureBackedClient:
    """A ModelClient that answers like the offline test double, recording which models were asked."""

    def __init__(self, name: str) -> None:
        from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider

        self.name = name
        self.models: list[str] = []
        self._fixture = FixtureLLMProvider()

    def structured(self, *, model: str, **kwargs: Any) -> LLMResponse[Any]:
        self.models.append(model)
        response = self._fixture.structured(task="routed", **kwargs)
        return LLMResponse(output=response.output, usage=LLMUsage(model=model, provider=self.name))


def test_missing_key_for_extraction_still_runs_the_audit(tenant_a: Any) -> None:
    from tests.research_helpers import research_company, research_registry

    openai_client = _FixtureBackedClient("openai")
    provider = RoutedProvider(
        {"extraction": Route("anthropic", "claude-haiku-5-5"), "audit": Route("openai", "o-model")},
        {"openai": openai_client},  # no Anthropic key configured
    )
    run, results = research_company(
        tenant_a, "northwind-logistics.example", research_registry(provider=lambda: provider)
    )
    assert run["status"] == "completed"
    assert run["ai_status"] == "completed"
    assert run["models_used"] == ["openai:o-model"]
    assert openai_client.models == ["o-model"]
    assert {e["origin"] for e in results["evidence"]} == {"deterministic"}  # no AI extraction
    assert results["opportunities"]


def test_missing_key_for_audit_gives_partial_result(tenant_a: Any) -> None:
    from tests.research_helpers import research_company, research_registry

    anthropic_client = _FixtureBackedClient("anthropic")
    provider = RoutedProvider(
        {"extraction": Route("anthropic", "claude-haiku-5-5"), "audit": Route("openai", "o-model")},
        {"anthropic": anthropic_client},
    )
    run, results = research_company(
        tenant_a, "northwind-logistics.example", research_registry(provider=lambda: provider)
    )
    assert run["status"] == "partial"
    assert run["ai_status"] == "unavailable"
    assert "opportunity audit" in run["error_message"]
    assert run["models_used"] == ["anthropic:claude-haiku-5-5"]
    assert results["opportunities"] == []
