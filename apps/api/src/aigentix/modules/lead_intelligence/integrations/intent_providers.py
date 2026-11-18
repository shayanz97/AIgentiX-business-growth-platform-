"""Interface for licensed third-party intent-data providers.

No provider is bundled or enabled: AIgentiX does not buy or scrape intent data. A contracted provider would
implement `IntentProvider`, be registered explicitly, and its results would be stored as
`buying_intent_signals` with source_type `licensed_provider` and the provider's own reference. Until then the
platform reports intent from the company's website, configured tender sources and first-party inquiries only.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class ProviderIntent:
    reference: str  # provider's record id
    topic: str  # e.g. "customer service automation"
    strength: str  # explicit | strong | indirect (provider's assessment mapped by the integration)
    observed_on: date | None
    url: str | None


class IntentProvider(Protocol):
    name: str

    def intents_for(self, domain: str) -> list[ProviderIntent]: ...


def configured_intent_providers() -> list[IntentProvider]:
    """Licensed providers configured for this deployment (none)."""
    return []
