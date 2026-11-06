"""Optional company discovery interface (future: discovery by industry and region).

No implementation ships in Sprint 2 — the core MVP must not depend on paid search credentials.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CompanyCandidate:
    name: str
    website_url: str
    source: str  # provider name, for provenance


class CompanySearchProvider(Protocol):
    def search(self, *, industry: str, region: str, limit: int) -> list[CompanyCandidate]: ...
