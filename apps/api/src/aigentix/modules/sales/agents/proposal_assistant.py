"""Proposal Assistant: an editable 13-section proposal draft from a sales brief.

The model drafts text; the system owns everything that must be exact: the section list and order, commercial
terms (built only from approved service-offering prices, otherwise explicit placeholders), the removal of
unapproved amounts, guarantees and certification promises, hypotheses moved into assumptions, and markers for
unknown requirements and unjustified timelines. A draft is always a draft: it is never sent by AIgentiX.
"""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from aigentix.modules.sales.agents.calls import UsageSink, call_with_repair
from aigentix.modules.sales.agents.llm import PROPOSAL_TASK
from aigentix.modules.sales.agents.prompts import PROPOSAL_SYSTEM
from aigentix.modules.sales.agents.sales_intelligence import PromptEvidence
from aigentix.modules.sales.agents.schemas import ProposalOutput, ProposalSectionOutput
from aigentix.modules.sales.agents.validation import TextGuard, is_hedged, restates
from aigentix.platform.llm import LLMProvider
from aigentix.platform.llm.safety import neutralise_markup

SECTIONS: tuple[tuple[str, str], ...] = (
    ("executive_summary", "Executive summary"),
    ("business_context", "Business context"),
    ("identified_opportunity", "Identified opportunity"),
    ("proposed_solution", "Proposed solution"),
    ("scope_and_deliverables", "Scope and deliverables"),
    ("implementation_approach", "Implementation approach"),
    ("customer_dependencies", "Customer dependencies"),
    ("assumptions", "Assumptions"),
    ("expected_benefits", "Expected benefits"),
    ("success_criteria", "Success criteria"),
    ("timeline_estimate", "Timeline estimate"),
    ("commercial_terms", "Commercial terms"),
    ("next_steps", "Next steps"),
)
SECTION_KEYS = tuple(k for k, _ in SECTIONS)
SECTION_TITLES = dict(SECTIONS)
TO_CONFIRM = "[TO BE CONFIRMED WITH CUSTOMER]"
PRICE_PLACEHOLDER = "[PRICE TO BE CONFIRMED — no approved price configured]"
TIMELINE_PLACEHOLDER = (
    "[TIMELINE TO BE CONFIRMED WITH CUSTOMER] A timeline can be estimated once scope and requirements are confirmed."
)
_LABEL = re.compile(r"^E\d+$")
_TIMING = re.compile(r"(?i)\b(week|weeks|month|months|day|days|woche|wochen|monat|monate|tage|quartal|quarter)\b")
_REQUIREMENT_SECTIONS = ("scope_and_deliverables", "success_criteria")
_FACT_SECTIONS = ("executive_summary", "business_context", "identified_opportunity", "expected_benefits")


@dataclass(frozen=True)
class OfferingTerms:
    name: str
    description: str
    solution_category: str | None
    price_amount: Decimal | None
    price_unit: str | None
    currency: str
    price_approved: bool


@dataclass
class ProposalInputs:
    company: dict[str, Any]
    company_domain: str | None
    brief: dict[str, Any]
    hypotheses: list[str]
    evidence: list[PromptEvidence]
    requirements: list[str]
    offerings: list[OfferingTerms]

    @property
    def support(self) -> str:
        """Text the draft may take facts and numbers from (never prices: those come from approved offerings)."""
        brief_text = json.dumps(self.brief, ensure_ascii=False)
        offerings = " ".join(f"{o.name} {o.description}" for o in self.offerings)
        return " ".join([brief_text, *(e.support for e in self.evidence), *self.requirements, offerings])


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or "")
    return str(item or "")


def brief_view(
    content: dict[str, Any], edited: dict[str, Any] | None, label_of: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """What the proposal is based on: human edits win over the AI content, section by section.
    Returns (view, hypotheses). AI hypotheses are only carried over for sections the human did not edit."""
    edited = edited or {}

    def labels(item: Any) -> list[str]:
        ids = item.get("evidence_ids", []) if isinstance(item, dict) else []
        return [label_of[i] for i in ids if i in label_of]

    def statements(key: str) -> list[dict[str, Any]]:
        if key in edited:
            return [{"text": str(t), "evidence": [], "basis": "confirmed_by_user"} for t in edited[key]]
        return [
            {"text": _text_of(s), "evidence": labels(s), "basis": s.get("basis", "hypothesis")}
            for s in content.get(key) or []
        ]

    def single(key: str) -> dict[str, Any] | None:
        if key in edited:
            return {"text": str(edited[key]), "evidence": [], "basis": "confirmed_by_user"}
        item = content.get(key)
        return {"text": _text_of(item), "evidence": labels(item), "basis": item.get("basis")} if item else None

    opportunity = single("main_opportunity")
    view = {
        "company_summary": single("company_summary"),
        "observed_situation": statements("observed_situation"),
        "main_opportunity_title": edited.get("main_opportunity_title")
        or ((content.get("main_opportunity") or {}).get("title")),
        "main_opportunity": opportunity,
        "supporting_evidence": statements("supporting_evidence"),
        "potential_impact": statements("potential_impact"),
        "suggested_solution": single("suggested_solution"),
        "implementation_requirements": edited.get("implementation_requirements")
        or content.get("implementation_requirements", []),
        "discovery_questions": edited.get("discovery_questions") or content.get("discovery_questions", []),
        "assumptions_and_uncertainty": edited.get("assumptions_and_uncertainty")
        or content.get("assumptions_and_uncertainty", []),
        "unknowns": content.get("unknowns", []),
        "notes": edited.get("notes"),
    }
    hypotheses: list[str] = []
    for item in [opportunity, view["suggested_solution"], *view["potential_impact"]]:
        if item and item.get("basis") == "hypothesis" and item["text"]:
            hypotheses.append(item["text"])
    return view, hypotheses


def _block(tag: str, data: Any) -> str:
    return f"<{tag}>\n{neutralise_markup(json.dumps(data, ensure_ascii=False))}\n</{tag}>"


def build_proposal_prompt(inputs: ProposalInputs) -> str:
    evidence = [{"id": e.label, "type": e.evidence_type, "fact": e.fact, "excerpt": e.excerpt} for e in inputs.evidence]
    offerings = [
        {
            "name": o.name,
            "description": o.description,
            "category": o.solution_category,
            "approved_price_configured": o.price_approved,
        }
        for o in inputs.offerings
    ]
    sections = [{"key": k, "title": t} for k, t in SECTIONS]
    return "\n\n".join(
        [
            _block("company_profile", inputs.company),
            _block("sales_brief", inputs.brief),
            _block("hypotheses", inputs.hypotheses),
            _block("evidence", evidence),
            _block("confirmed_requirements", inputs.requirements),
            _block("service_offerings", offerings),
            _block("required_sections", sections),
            "Draft the proposal sections. Leave amounts out: commercial terms are filled in by the system.",
        ]
    )


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def commercial_terms(offerings: list[OfferingTerms], proposed_text: str) -> tuple[str, str, bool]:
    """Deterministic commercial terms: (body, status, any placeholder?). Offerings named in the proposed solution
    or scope are used; otherwise every active offering is listed."""
    named = [o for o in offerings if o.name.lower() in proposed_text.lower()]
    chosen = named or offerings
    if not chosen:
        body = (
            f"{PRICE_PLACEHOLDER}\n"
            "No service offering is configured. Add the services and approve their prices before quoting."
        )
        return body, "needs_input", True
    lines = ["Prices are taken only from the approved service catalogue:"]
    placeholder = False
    for o in chosen:
        if o.price_approved and o.price_amount is not None:
            unit = f" ({o.price_unit})" if o.price_unit else ""
            lines.append(f"- {neutralise_markup(o.name)}: {_money(o.price_amount)} {o.currency}{unit}")
        else:
            lines.append(f"- {neutralise_markup(o.name)}: {PRICE_PLACEHOLDER}")
            placeholder = True
    lines.append("Final scope and terms are agreed with the customer before the proposal is sent.")
    return "\n".join(lines), "needs_input" if placeholder else "draft", placeholder


@dataclass
class ValidatedProposal:
    sections: list[dict[str, Any]]
    assumptions: list[str]
    quality_flags: list[str]
    evidence_ids: list[uuid.UUID] = field(default_factory=list)


def _placeholder(section: str) -> str:
    return f"{TO_CONFIRM} Nothing could be drafted for this section from the confirmed inputs."


def validate_proposal(output: ProposalOutput, inputs: ProposalInputs) -> ValidatedProposal:
    guard = TextGuard(inputs.company_domain, strict_money=True)
    flags = guard.flags
    by_label = {e.label: e for e in inputs.evidence}
    support = inputs.support
    drafts: dict[str, ProposalSectionOutput] = {}
    for section in output.sections:
        key = section.key.strip().lower()
        if key not in SECTION_TITLES:
            flags.add("unknown_section_dropped")
        elif key not in drafts:
            drafts[key] = section
    cited: dict[str, PromptEvidence] = {}
    sections: list[dict[str, Any]] = []
    timing_justified = any(
        _TIMING.search(t) for t in [*inputs.requirements, *(o.description for o in inputs.offerings)]
    )
    for key, title in SECTIONS:
        if key == "commercial_terms":
            sections.append({"key": key, "title": title, "body": "", "status": "draft"})  # filled in below
            continue
        draft = drafts.get(key)
        if draft is None:
            flags.add("missing_section")
            sections.append({"key": key, "title": title, "body": _placeholder(key), "status": "needs_input"})
            continue
        for raw in draft.evidence:
            label = raw.strip().upper()
            if _LABEL.match(label) and label in by_label:
                cited[label] = by_label[label]
            else:
                flags.add("cited_unknown_evidence")
        body = guard.text(draft.body, support=support, limit=4_000)
        if key in _FACT_SECTIONS:
            body = _hedge_hypotheses(body, inputs.hypotheses, flags)
        status = draft.status
        if key == "timeline_estimate" and (not timing_justified or not body):
            if draft.body.strip() and status == "draft":
                flags.add("timeline_unjustified")
            body, status = TIMELINE_PLACEHOLDER, "needs_input"
        if key in _REQUIREMENT_SECTIONS and not inputs.requirements:
            flags.add("requirements_unconfirmed")
            status = "needs_input"
            if TO_CONFIRM not in body:
                body = f"{body}\n\n{TO_CONFIRM} No customer requirements have been confirmed yet.".strip()
        if not body:
            body, status = _placeholder(key), "needs_input"
        if "[TO BE CONFIRMED" in body:
            status = "needs_input"
        sections.append({"key": key, "title": title, "body": body, "status": status})

    proposed = " ".join(s["body"] for s in sections if s["key"] in ("proposed_solution", "scope_and_deliverables"))
    terms, terms_status, placeholder = commercial_terms(inputs.offerings, proposed)
    if placeholder:
        flags.add("price_placeholder")
    for s in sections:
        if s["key"] == "commercial_terms":
            s["body"], s["status"] = terms, terms_status

    assumptions: list[str] = []
    for raw in output.assumptions:
        text = guard.text(raw, support=support, limit=400)
        if text and text not in assumptions:
            assumptions.append(text)
    for hypothesis in inputs.hypotheses:
        text = guard.text(f"Hypothesis to validate: {hypothesis}", support=support, limit=500)
        if text and text not in assumptions:
            assumptions.append(text)
            flags.add("hypotheses_listed_as_assumptions")
    assumptions.append("Prices are quoted only from approved service offerings; nothing is sent automatically.")
    ordered = [e for e in inputs.evidence if e.label in cited]
    return ValidatedProposal(
        sections=sections,
        assumptions=assumptions[:20],
        quality_flags=sorted(flags),
        evidence_ids=[e.evidence_id for e in ordered],
    )


def _hedge_hypotheses(body: str, hypotheses: list[str], flags: set[str]) -> str:
    """A sentence that restates a brief hypothesis without hedging is marked as a hypothesis."""
    if not hypotheses or not body:
        return body
    out: list[str] = []
    for line in body.splitlines():
        if any(restates(line, h) for h in hypotheses) and not is_hedged(line):
            flags.add("hypothesis_stated_as_fact")
            line = f"Hypothesis to validate: {line.strip()}"
        out.append(line)
    return "\n".join(out)


def run_proposal(
    provider: LLMProvider,
    inputs: ProposalInputs,
    *,
    max_repairs: int,
    record_usage: UsageSink,
    max_tokens: int,
    can_spend: Callable[[], bool] | None = None,
) -> ValidatedProposal:
    output = call_with_repair(
        provider,
        task=PROPOSAL_TASK,
        system=PROPOSAL_SYSTEM,
        user=build_proposal_prompt(inputs),
        output_model=ProposalOutput,
        max_tokens=max_tokens,
        max_repairs=max_repairs,
        record_usage=record_usage,
        can_spend=can_spend,
    )
    return validate_proposal(output, inputs)
