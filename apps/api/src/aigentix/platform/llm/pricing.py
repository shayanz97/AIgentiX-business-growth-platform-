"""Token prices (USD per million tokens) for cost estimates and per-run budgets.

Built-in prices cover the Anthropic models used by default. Any other model — including OpenAI models — is
priced pessimistically unless LLM_PRICES_JSON provides its price, so budgets fail safe (stop early) rather
than overspend. Estimates are shown to users as estimates.
"""

from decimal import Decimal

from aigentix.platform.llm.config import get_llm_settings, parse_prices

BUILT_IN_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-fable-5-1": (Decimal("10.00"), Decimal("50.00")),
}
UNKNOWN_MODEL_PRICE = (Decimal("10.00"), Decimal("50.00"))
_MILLION = Decimal(1_000_000)


def price_for(model: str) -> tuple[Decimal, Decimal]:
    raw = get_llm_settings().llm_prices_json
    overrides = parse_prices(raw) if raw.strip() else {}
    return overrides.get(model) or BUILT_IN_PRICES.get(model) or UNKNOWN_MODEL_PRICE


def is_priced(model: str) -> bool:
    return price_for(model) is not UNKNOWN_MODEL_PRICE


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = price_for(model)
    return (price_in * input_tokens + price_out * output_tokens) / _MILLION


def max_output_tokens_within(budget_usd: Decimal, model: str, ceiling: int) -> int:
    """Largest max_tokens whose worst-case output cost stays within 80% of the remaining budget."""
    _, price_out = price_for(model)
    if budget_usd <= 0:
        return 0
    return max(0, min(ceiling, int(budget_usd * Decimal("0.8") / price_out * _MILLION)))
