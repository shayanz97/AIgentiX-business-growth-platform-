"""AI Opportunity Audit agent: proposes ≤3 evidence-backed automation opportunities, then verifies them."""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aigentix.modules.lead_intelligence.agents.calls import UsageSink, call_with_repair
from aigentix.modules.lead_intelligence.agents.prompts import AUDIT_SYSTEM
from aigentix.modules.lead_intelligence.agents.schemas import AuditOutput, ProposedOpportunity
from aigentix.modules.lead_intelligence.agents.text_safety import (
    UNSUPPORTED_TERMS,
    neutralise_markup,
    strip_foreign_urls,
)
from aigentix.modules.lead_intelligence.integrations.llm import LLMProvider

MAX_OPPORTUNITIES = 3
_LABEL = re.compile(r"^E(\d+)$")


@dataclass(frozen=True)
class PromptEvidence:
    label: str  # E1, E2, ...
    evidence_id: uuid.UUID
    evidence_type: str
    observed_fact: str
    excerpt: str
    basis: str
    confidence: str
    source_url: str
    origin: str = "deterministic"  # deterministic | llm


@dataclass
class VerifiedOpportunity:
    title: str
    observed_context: str
    problem_hypothesis: str
    proposed_ai_solution: str
    estimated_business_impact: str
    implementation_complexity: str
    confidence: str
    assumptions: list[str]
    validation_questions: list[str]
    next_step: str
    evidence_ids: list[uuid.UUID]
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class AuditResult:
    opportunities: list[VerifiedOpportunity]
    summary: str | None
    dropped: list[str] = field(default_factory=list)


def build_audit_prompt(profile: dict[str, Any], evidence: list[PromptEvidence]) -> str:
    items = [
        {
            "id": e.label,
            "type": e.evidence_type,
            "fact": neutralise_markup(e.observed_fact),
            "excerpt": neutralise_markup(e.excerpt),
            "basis": e.basis,
            "confidence": e.confidence,
            "source_url": neutralise_markup(e.source_url),
        }
        for e in evidence
    ]
    profile_json = neutralise_markup(json.dumps(profile, ensure_ascii=False))
    return (
        f"<company_profile>\n{profile_json}\n</company_profile>\n\n"
        f"<evidence>\n{json.dumps(items, ensure_ascii=False)}\n</evidence>\n\n"
        "Propose up to three AI automation opportunities supported by this evidence."
    )


def _clean(text: str, domain: str | None, flags: set[str], limit: int = 2_000) -> str:
    cleaned, removed = strip_foreign_urls(text.strip()[:limit], domain)
    if removed:
        flags.add("external_link_removed")
    return cleaned


def _verify(
    proposal: ProposedOpportunity, by_label: dict[str, PromptEvidence], domain: str | None, dropped: list[str]
) -> VerifiedOpportunity | None:
    flags: set[str] = set()
    cited: list[PromptEvidence] = []
    for raw in proposal.supporting_evidence_ids:
        label = raw.strip().upper()
        if _LABEL.match(label) and label in by_label:
            if by_label[label] not in cited:
                cited.append(by_label[label])
        else:
            flags.add("cited_unknown_evidence")
    if not cited:
        dropped.append(f"{proposal.title[:80]!r}: no valid supporting evidence")
        return None

    confidence = proposal.confidence
    claims = f"{proposal.observed_context} {proposal.problem_hypothesis}".lower()
    # Support = verbatim excerpts plus parser-generated facts. LLM-written facts are not proof of themselves.
    support = " ".join(
        e.excerpt + (f" {e.observed_fact}" if e.origin == "deterministic" else "") for e in cited
    ).lower()
    if any(term in claims and term not in support for term in UNSUPPORTED_TERMS):
        flags.add("unsupported_claim")
        confidence = "low"
    if confidence == "high" and len(cited) < 2:
        flags.add("confidence_capped")
        confidence = "medium"
    if all(e.basis == "inferred" for e in cited) and confidence != "low":
        flags.add("inferred_evidence_only")
        confidence = "low" if confidence == "medium" else "medium"
    questions = [_clean(q, domain, flags, 300) for q in proposal.validation_questions if q.strip()][:6]
    if not questions:
        flags.add("missing_validation_questions")
        questions = ["Does this process exist at the company, and at what volume?"]
    return VerifiedOpportunity(
        title=_clean(proposal.title, domain, flags, 200),
        observed_context=_clean(proposal.observed_context, domain, flags),
        problem_hypothesis=_clean(proposal.problem_hypothesis, domain, flags),
        proposed_ai_solution=_clean(proposal.proposed_solution, domain, flags),
        estimated_business_impact=_clean(proposal.expected_benefit, domain, flags),
        implementation_complexity=proposal.implementation_complexity,
        confidence=confidence,
        assumptions=[_clean(a, domain, flags, 300) for a in proposal.assumptions if a.strip()][:6],
        validation_questions=questions,
        next_step=_clean(proposal.next_step, domain, flags, 500),
        evidence_ids=[e.evidence_id for e in cited],
        quality_flags=sorted(flags),
    )


def validate_audit(output: AuditOutput, evidence: list[PromptEvidence], *, company_domain: str | None) -> AuditResult:
    by_label = {e.label: e for e in evidence}
    dropped: list[str] = []
    verified: list[VerifiedOpportunity] = []
    for proposal in output.opportunities:
        if len(verified) >= MAX_OPPORTUNITIES:
            dropped.append(f"{proposal.title[:80]!r}: over the limit of {MAX_OPPORTUNITIES}")
            continue
        if (opportunity := _verify(proposal, by_label, company_domain, dropped)) is not None:
            verified.append(opportunity)
    summary = output.no_opportunity_reason
    if summary:
        summary, _ = strip_foreign_urls(summary.strip()[:1_000], company_domain)
    if not verified and not summary:
        summary = "No opportunity was supported by verifiable evidence."
    return AuditResult(opportunities=verified, summary=summary, dropped=dropped)


def run_audit(
    provider: LLMProvider,
    profile: dict[str, Any],
    evidence: list[PromptEvidence],
    *,
    company_domain: str | None,
    max_repairs: int,
    record_usage: UsageSink,
    max_tokens: int | None = None,
    can_spend: Callable[[], bool] | None = None,
) -> AuditResult:
    if not evidence:
        return AuditResult(opportunities=[], summary="No evidence was collected, so no opportunity can be proposed.")
    output = call_with_repair(
        provider,
        task="audit",
        system=AUDIT_SYSTEM,
        user=build_audit_prompt(profile, evidence),
        output_model=AuditOutput,
        max_tokens=max_tokens or 16_000,
        can_spend=can_spend,
        max_repairs=max_repairs,
        record_usage=record_usage,
    )
    return validate_audit(output, evidence, company_domain=company_domain)
