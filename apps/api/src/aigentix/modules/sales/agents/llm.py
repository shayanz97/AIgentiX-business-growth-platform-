"""How the Sales module chooses its AI provider and models.

Tasks and their `provider:model` routes (see aigentix.platform.llm.router):
    SALES_LLM_ROUTE_BRIEF      sales intelligence brief
    SALES_LLM_ROUTE_PROPOSAL   proposal draft
Without explicit routes both use LLM_PROVIDER + LLM_AUDIT_MODEL (reasoning over evidence).
LLM_PROVIDER=fixture selects the rule-based FixtureSalesLLM (refused in production); `none` disables AI.
"""

from aigentix.modules.sales.config import SalesSettings
from aigentix.platform.llm import LLMProvider, Route, build_routed_provider
from aigentix.platform.llm.config import LLMSettings, get_llm_settings

BRIEF_TASK = "sales_brief"
PROPOSAL_TASK = "sales_proposal"


def sales_routes(settings: SalesSettings) -> dict[str, Route]:
    default = f"{settings.llm_provider}:{settings.llm_audit_model}"
    return {
        BRIEF_TASK: Route.parse(settings.sales_llm_route_brief or default),
        PROPOSAL_TASK: Route.parse(settings.sales_llm_route_proposal or default),
    }


def build_sales_provider(settings: SalesSettings, llm_settings: LLMSettings | None = None) -> LLMProvider | None:
    """The configured provider, or None when AI is unavailable (disabled / no key for any route)."""
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "fixture":
        from aigentix.modules.sales.agents.fixture_llm import FixtureSalesLLM

        return FixtureSalesLLM()
    return build_routed_provider(sales_routes(settings), llm_settings or get_llm_settings())
