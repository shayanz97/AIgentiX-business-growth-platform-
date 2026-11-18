"""How Lead Intelligence chooses its AI provider and models.

Each research task has a `provider:model` route (see aigentix.platform.llm.router):
    LLM_ROUTE_EXTRACTION   semantic extraction from website text (a lower-cost model is enough)
    LLM_ROUTE_AUDIT        AI Opportunity Audit (a stronger reasoning model)
    LLM_ROUTE_SIGNALS      review of growth-trigger candidates (defaults to the extraction route)
Without explicit routes, LLM_PROVIDER + LLM_EXTRACTION_MODEL / LLM_AUDIT_MODEL are used (Sprint 2 settings).
"""

from typing import TYPE_CHECKING

from aigentix.platform.llm import LLMProvider, Route, build_routed_provider
from aigentix.platform.llm.config import LLMSettings, get_llm_settings

if TYPE_CHECKING:
    from aigentix.modules.lead_intelligence.config import ResearchSettings

EXTRACTION = "extraction"
AUDIT = "audit"
SIGNALS = "signals"  # optional AI review of growth-trigger candidates (defaults to the extraction route)


def research_routes(settings: "ResearchSettings") -> dict[str, Route]:
    provider = settings.llm_provider
    return {
        EXTRACTION: Route.parse(settings.llm_route_extraction or f"{provider}:{settings.llm_extraction_model}"),
        AUDIT: Route.parse(settings.llm_route_audit or f"{provider}:{settings.llm_audit_model}"),
        SIGNALS: Route.parse(
            settings.llm_route_signals or settings.llm_route_extraction or f"{provider}:{settings.llm_extraction_model}"
        ),
    }


def build_provider(settings: "ResearchSettings", llm_settings: LLMSettings | None = None) -> LLMProvider | None:
    """The configured provider, or None when AI analysis is unavailable (disabled / no key for any route)."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "fixture":
        from aigentix.modules.lead_intelligence.agents.fixture_llm import FixtureLLMProvider

        return FixtureLLMProvider()
    return build_routed_provider(research_routes(settings), llm_settings or get_llm_settings())
