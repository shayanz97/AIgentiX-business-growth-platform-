"""Company Researcher agent: LLM-based semantic extraction, verified against stored source text."""

import uuid
from dataclasses import dataclass, field

from aigentix.modules.lead_intelligence.agents.calls import UsageSink, call_with_repair
from aigentix.modules.lead_intelligence.agents.prompts import EXTRACTION_SYSTEM
from aigentix.modules.lead_intelligence.agents.schemas import ExtractionOutput
from aigentix.modules.lead_intelligence.agents.text_safety import (
    excerpt_in_source,
    neutralise_markup,
    strip_foreign_urls,
)
from aigentix.modules.lead_intelligence.integrations.llm import LLMProvider
from aigentix.modules.lead_intelligence.models import EvidenceType

FIELD_TO_EVIDENCE: dict[str, EvidenceType] = {
    "description": EvidenceType.COMPANY_DESCRIPTION,
    "industry": EvidenceType.INDUSTRY,
    "service": EvidenceType.SERVICE_OFFERING,
    "target_customer": EvidenceType.TARGET_CUSTOMER,
    "business_model": EvidenceType.BUSINESS_MODEL,
    "customer_interaction": EvidenceType.CUSTOMER_SUPPORT,
    "document_workflow": EvidenceType.DOCUMENT_WORKFLOW,
    "operational_signal": EvidenceType.OPERATIONAL_SIGNAL,
    "location": EvidenceType.LOCATION,
}
MAX_ASSERTIONS = 25
MAX_CHARS_PER_SOURCE = 6_000


@dataclass(frozen=True)
class PromptSource:
    label: str  # S1, S2, ...
    source_id: uuid.UUID
    url: str
    category: str
    title: str | None
    text: str


@dataclass(frozen=True)
class VerifiedAssertion:
    field: str
    value: str
    basis: str
    confidence: str
    source_id: uuid.UUID
    excerpt: str

    @property
    def evidence_type(self) -> EvidenceType:
        return FIELD_TO_EVIDENCE[self.field]


@dataclass
class ExtractionResult:
    company_name: str | None
    assertions: list[VerifiedAssertion] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # reasons for discarded assertions


def build_extraction_prompt(sources: list[PromptSource]) -> str:
    blocks = []
    for s in sources:
        text = neutralise_markup(s.text[:MAX_CHARS_PER_SOURCE])
        title = neutralise_markup(s.title or "")
        blocks.append(
            f'<website_content source_id="{s.label}" page_type="{s.category}" url="{neutralise_markup(s.url)}" '
            f'title="{title}">\n{text}\n</website_content>'
        )
    return "Sources:\n\n" + "\n\n".join(blocks) + "\n\nExtract the company profile."


def validate_extraction(
    output: ExtractionOutput, sources: list[PromptSource], *, company_domain: str | None
) -> ExtractionResult:
    by_label = {s.label: s for s in sources}
    result = ExtractionResult(
        company_name=(output.company_name or "").strip()[:200] or None,
        unknown_fields=list(output.unknown_fields),
    )
    for assertion in output.assertions:
        if len(result.assertions) >= MAX_ASSERTIONS:
            result.dropped.append("over assertion limit")
            continue
        source = by_label.get(assertion.source_id.strip())
        if source is None:
            result.dropped.append(f"{assertion.field}: unknown source {assertion.source_id!r}")
            continue
        if not excerpt_in_source(assertion.supporting_excerpt, source.text):
            result.dropped.append(f"{assertion.field}: excerpt not found in {source.label}")
            continue
        value, _ = strip_foreign_urls(assertion.value.strip()[:400], company_domain)
        if not value:
            continue
        result.assertions.append(
            VerifiedAssertion(
                field=assertion.field,
                value=value,
                basis=assertion.basis,
                confidence=assertion.confidence,
                source_id=source.source_id,
                excerpt=assertion.supporting_excerpt.strip()[:400],
            )
        )
    return result


def run_extraction(
    provider: LLMProvider,
    sources: list[PromptSource],
    *,
    company_domain: str | None,
    max_repairs: int,
    record_usage: UsageSink,
) -> ExtractionResult:
    output = call_with_repair(
        provider,
        task="extraction",
        system=EXTRACTION_SYSTEM,
        user=build_extraction_prompt(sources),
        output_model=ExtractionOutput,
        max_tokens=8_000,
        max_repairs=max_repairs,
        record_usage=record_usage,
    )
    return validate_extraction(output, sources, company_domain=company_domain)
