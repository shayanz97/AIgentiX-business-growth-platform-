"""Public-tender sources. Only real, configured sources count as intent; none is bundled for production.

`RESEARCH_TENDER_SOURCE=none` (default): no tender source — tender intent comes only from the company's own
website. `fixtures`: the offline sample file used by tests, the evaluation and demos (refused in production).
A licensed tender-data feed would be another `TenderSource` implementation.
"""

import json
from pathlib import Path
from typing import Protocol

from aigentix.modules.lead_intelligence.domain.intent import TenderRecord

FIXTURE_TENDERS = Path(__file__).resolve().parent.parent / "fixtures" / "enrichment" / "tenders.json"


class TenderSource(Protocol):
    name: str

    def tenders_for(self, domain: str) -> list[TenderRecord]: ...


class FixtureTenderSource:
    """Reads bundled sample tenders (fictional buyers on `.example` domains)."""

    name = "fixture-tenders"

    def __init__(self, path: Path = FIXTURE_TENDERS) -> None:
        rows = json.loads(path.read_text(encoding="utf-8"))
        self._tenders = [TenderRecord(**row) for row in rows]

    def tenders_for(self, domain: str) -> list[TenderRecord]:
        return [t for t in self._tenders if t.buyer_domain.lower() == domain.lower()]


def build_tender_source(kind: str) -> TenderSource | None:
    if kind == "fixtures":
        return FixtureTenderSource()
    return None
