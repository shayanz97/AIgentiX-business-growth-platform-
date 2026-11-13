"""Buying-intent rules. Intent is only recorded from a real source; absence of a source is never intent.

EXPLICIT  the company itself asks for a relevant solution (a project request on its website, or an inquiry it
          sent to the organization — first-party data).
STRONG    a published, still-open procurement / tender for a relevant solution.
INDIRECT  stated interest in a relevant area (e.g. a digitalisation programme) without a purchase request.
NONE_VERIFIED / UNKNOWN are computed by scoring: sources were checked and nothing was found / could not check.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from aigentix.modules.lead_intelligence.domain.dates import ParsedDate, parse_machine_date
from aigentix.modules.lead_intelligence.domain.firmographics import mentions_any
from aigentix.modules.lead_intelligence.domain.profiles import SOLUTION_CATEGORIES
from aigentix.modules.lead_intelligence.domain.signals import DetectedSignal
from aigentix.modules.lead_intelligence.models import IntentSourceType, IntentStrength, SignalType

_REFERENCE = re.compile(r"\b[A-Z]{1,6}-20\d{2}-\d{2,6}\b|\b(?:Aktenzeichen|Vergabe-Nr\.?|Ref\.?)\s*:?\s*([\w/-]{4,40})")


def solution_categories_for(text: str, allowed: list[str]) -> list[str]:
    return [c for c in allowed if mentions_any(text, SOLUTION_CATEGORIES.get(c, ()))]


@dataclass(frozen=True)
class TenderRecord:
    """A tender from a configured tender source (see integrations/tenders.py)."""

    id: str
    title: str
    buyer_name: str
    buyer_domain: str
    published_at: str | None
    deadline: str | None
    url: str | None
    description: str
    category: str


@dataclass
class IntentCandidate:
    strength: IntentStrength
    source_type: IntentSourceType
    title: str
    summary: str
    solution_category: str | None
    observed: ParsedDate | None
    deadline: ParsedDate | None
    external_ref: str | None
    source_url: str | None
    dedupe_key: str
    signal_index: int | None = None  # website intent: index into the detected signals (for evidence links)


@dataclass
class IntentResult:
    intents: list[IntentCandidate]
    ignored: list[str]  # human-readable reasons for records that were not counted (expired, irrelevant, ...)


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).lower().encode()).hexdigest()[:32]


def _reference_in(text: str) -> str | None:
    match = _REFERENCE.search(text)
    if not match:
        return None
    return (match.group(1) or match.group(0)).strip()


def website_intents(
    signals: list[DetectedSignal], *, categories: list[str], reference: date
) -> tuple[list[IntentCandidate], list[str]]:
    intents: list[IntentCandidate] = []
    ignored: list[str] = []
    for index, signal in enumerate(signals):
        text = " ".join(c.segment.text for c in signal.candidates)
        relevant = solution_categories_for(text, categories)
        url = signal.source_urls[0] if signal.source_urls else None
        if signal.signal_type in (SignalType.PUBLIC_PROJECT_REQUEST, SignalType.PROCUREMENT_TENDER):
            if not relevant:
                ignored.append(f"'{signal.title[:80]}' is a request for something outside the target solutions")
                continue
            if signal.deadline is not None and signal.deadline.value < reference:
                ignored.append(f"'{signal.title[:80]}' has an expired deadline")
                continue
            tender = signal.signal_type == SignalType.PROCUREMENT_TENDER
            ref = _reference_in(text)
            intents.append(
                IntentCandidate(
                    strength=IntentStrength.STRONG if tender else IntentStrength.EXPLICIT,
                    source_type=IntentSourceType.WEBSITE,
                    title=signal.title,
                    summary=signal.summary,
                    solution_category=relevant[0],
                    observed=signal.occurred,
                    deadline=signal.deadline,
                    external_ref=ref,
                    source_url=url,
                    dedupe_key=_key("ref", ref) if ref else _key("site", signal.dedupe_key),
                    signal_index=index,
                )
            )
        elif signal.signal_type == SignalType.DIGITAL_TRANSFORMATION and relevant:
            intents.append(
                IntentCandidate(
                    strength=IntentStrength.INDIRECT,
                    source_type=IntentSourceType.WEBSITE,
                    title=signal.title,
                    summary=signal.summary,
                    solution_category=relevant[0],
                    observed=signal.occurred,
                    deadline=None,
                    external_ref=None,
                    source_url=url,
                    dedupe_key=_key("site", signal.dedupe_key),
                    signal_index=index,
                )
            )
    return intents, ignored


def tender_intents(
    tenders: list[TenderRecord], *, categories: list[str], reference: date
) -> tuple[list[IntentCandidate], list[str]]:
    intents: list[IntentCandidate] = []
    ignored: list[str] = []
    for tender in tenders:
        category = tender.category if tender.category in categories else None
        if category is None:
            matched = solution_categories_for(f"{tender.title} {tender.description}", categories)
            category = matched[0] if matched and tender.category != "other" else None
        if category is None:
            ignored.append(f"Tender {tender.id} is outside the target solution categories")
            continue
        deadline = parse_machine_date(tender.deadline) if tender.deadline else None
        if deadline is not None and deadline.value < reference:
            ignored.append(f"Tender {tender.id} closed on {deadline.value.isoformat()}")
            continue
        published = parse_machine_date(tender.published_at) if tender.published_at else None
        intents.append(
            IntentCandidate(
                strength=IntentStrength.STRONG,
                source_type=IntentSourceType.PUBLIC_TENDER,
                title=tender.title[:300],
                summary=tender.description[:1000],
                solution_category=category,
                observed=published if published and published.value <= reference else None,
                deadline=deadline,
                external_ref=tender.id[:200],
                source_url=tender.url,
                dedupe_key=_key("ref", tender.id),
            )
        )
    return intents, ignored


def merge_intents(website: list[IntentCandidate], external: list[IntentCandidate]) -> list[IntentCandidate]:
    """The same tender found on the website and in a tender source is one intent (tender record preferred)."""
    by_key: dict[str, IntentCandidate] = {}
    for candidate in [*external, *website]:
        existing = by_key.get(candidate.dedupe_key)
        if existing is None:
            by_key[candidate.dedupe_key] = candidate
        elif existing.signal_index is None and candidate.signal_index is not None:
            existing.signal_index = candidate.signal_index  # keep the website evidence link
    return list(by_key.values())


def first_party_key(channel: str, received_on: date, summary: str) -> str:
    return _key("first_party", channel, received_on.isoformat(), summary.strip())
