"""Optional AI review of deterministic growth-trigger candidates.

The model may only confirm or reject candidates, re-type them among descriptive types and rate relevance. It can
never add a signal, change a date, or turn a candidate into a request/tender (which would create buying intent):
those types come from the deterministic parser only, so injected text cannot manufacture intent.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from aigentix.modules.lead_intelligence.agents.calls import UsageSink, call_with_repair
from aigentix.modules.lead_intelligence.agents.prompts import SIGNAL_REVIEW_SYSTEM
from aigentix.modules.lead_intelligence.agents.schemas import SignalReviewOutput
from aigentix.modules.lead_intelligence.agents.text_safety import neutralise_markup, strip_foreign_urls
from aigentix.modules.lead_intelligence.domain.signals import DetectedSignal
from aigentix.platform.llm import LLMProvider

# Types that can produce buying intent (directly or as INDIRECT intent): the model may never re-type into or
# out of them, so neither injected text nor a model mistake can create intent.
INTENT_TYPES = {"public_project_request", "procurement_tender", "inbound_inquiry", "digital_transformation"}
MAX_CANDIDATES = 30


@dataclass
class ReviewDecision:
    keep: bool
    signal_type: str
    relevance: str
    reason: str


@dataclass
class ReviewResult:
    decisions: dict[int, ReviewDecision] = field(default_factory=dict)  # index into the signals list
    ignored: list[str] = field(default_factory=list)


def _reason(text: str) -> str:
    """Model text is shown to users: no links to other sites, bounded length."""
    cleaned, _ = strip_foreign_urls(text, None)
    return " ".join(cleaned.split())[:300]


def _prompt(signals: list[DetectedSignal]) -> str:
    blocks = []
    for i, signal in enumerate(signals[:MAX_CANDIDATES], start=1):
        text = " ".join(c.segment.text for c in signal.candidates[:2])[:800]
        blocks.append(
            f'<website_content source_id="C{i}" page_type="{signal.signal_type.value}">\n'
            f"{neutralise_markup(text)}\n</website_content>"
        )
    return "Review these candidates (proposed type in page_type):\n\n" + "\n\n".join(blocks)


def review_signals(
    provider: LLMProvider,
    signals: list[DetectedSignal],
    *,
    max_repairs: int,
    record_usage: UsageSink,
    max_tokens: int,
    can_spend: Callable[[], bool] | None = None,
) -> ReviewResult:
    result = ReviewResult()
    if not signals:
        return result
    output = call_with_repair(
        provider,
        task="signals",
        system=SIGNAL_REVIEW_SYSTEM,
        user=_prompt(signals),
        output_model=SignalReviewOutput,
        max_tokens=max_tokens,
        max_repairs=max_repairs,
        record_usage=record_usage,
        can_spend=can_spend,
    )
    for decision in output.decisions:
        label = decision.candidate_id.strip().upper()
        if not label.startswith("C") or not label[1:].isdigit():
            result.ignored.append(f"unknown candidate id {decision.candidate_id[:20]!r}")
            continue
        index = int(label[1:]) - 1
        if not 0 <= index < min(len(signals), MAX_CANDIDATES) or index in result.decisions:
            result.ignored.append(f"unknown or repeated candidate id {label}")
            continue
        original = signals[index].signal_type.value
        new_type: str = decision.signal_type
        if new_type != original and (new_type in INTENT_TYPES or original in INTENT_TYPES):
            # Request/tender classification is deterministic only (no intent from model output).
            result.ignored.append(f"{label}: type change {original} → {new_type} not allowed")
            new_type = original
        if original in INTENT_TYPES - {"digital_transformation"} and not decision.keep:
            result.ignored.append(f"{label}: requests/tenders are kept for human review")
            result.decisions[index] = ReviewDecision(True, original, decision.relevance, _reason(decision.reason))
            continue
        result.decisions[index] = ReviewDecision(decision.keep, new_type, decision.relevance, _reason(decision.reason))
    return result
