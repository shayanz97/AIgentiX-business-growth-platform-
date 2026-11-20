"""Sales Intelligence agent: an evidence-grounded internal brief for one deal.

inputs (lead snapshot via the platform contract) → labelled evidence E1..En in neutralised blocks → structured
model output → post-validation (citations exist, observed facts cite evidence, numbers / money / guarantees /
certifications only when the cited evidence supports them, no links or contact data, lead score never shown as a
probability, next action is a human action). Deterministic parts (unknowns, lead score, evidence index) are never
written by the model.
"""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from aigentix.modules.sales.agents.calls import UsageSink, call_with_repair
from aigentix.modules.sales.agents.llm import BRIEF_TASK
from aigentix.modules.sales.agents.prompts import BRIEF_SYSTEM, SCORE_NOTE
from aigentix.modules.sales.agents.schemas import BriefOutput, Statement
from aigentix.modules.sales.agents.validation import HUMAN_NEXT_ACTION, TextGuard, is_outreach_action, word_overlap
from aigentix.platform.leads import LeadSnapshot
from aigentix.platform.llm import LLMProvider
from aigentix.platform.llm.safety import neutralise_markup, strip_foreign_urls

MAX_EVIDENCE = 40
STALE_AFTER = timedelta(days=180)
PROFILE_LABEL = "PROFILE"
MIN_OBSERVED_OVERLAP = 0.3
_LABEL = re.compile(r"^E\d+$")
_STAFF = re.compile(r"(?i)(\d[\d.,]*)\s*(?:mitarbeit|beschäftigt|angestellt|employees|staff|people)")
_LIMITS = {"observed_situation": 6, "supporting_evidence": 8, "potential_impact": 4}
_LIST_LIMITS = {"assumptions_and_uncertainty": 10, "implementation_requirements": 8, "discovery_questions": 8}


@dataclass(frozen=True)
class PromptEvidence:
    label: str  # E1, E2, ...
    evidence_id: uuid.UUID
    evidence_type: str
    fact: str
    excerpt: str
    source_url: str | None
    retrieved_at: datetime | None
    basis: str
    origin: str  # deterministic | llm
    stale: bool

    @property
    def support(self) -> str:
        """Verbatim excerpt plus parser-generated facts; LLM-written facts are not proof of themselves."""
        return self.excerpt + (f" {self.fact}" if self.origin == "deterministic" else "")


@dataclass(frozen=True)
class OfferingInfo:
    name: str
    description: str
    solution_category: str | None


@dataclass
class BriefInputs:
    company: dict[str, Any]
    company_domain: str | None
    evidence: list[PromptEvidence]
    opportunities: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    intents: list[dict[str, Any]]
    score: dict[str, Any] | None
    requirements: list[str]
    offerings: list[OfferingInfo]
    gaps: list[str] = field(default_factory=list)
    gap_flags: set[str] = field(default_factory=set)

    @property
    def by_label(self) -> dict[str, PromptEvidence]:
        return {e.label: e for e in self.evidence}

    @property
    def profile_text(self) -> str:
        return " ".join(str(v) for v in self.company.values() if v)

    @property
    def all_support(self) -> str:
        """Everything list items (assumptions, questions, requirements) may take numbers from: evidence, the
        profile, confirmed requirements, the deterministic gaps and the lead score."""
        score = json.dumps(self.score) if self.score else ""
        return " ".join([self.profile_text, *(e.support for e in self.evidence), *self.requirements, *self.gaps, score])


def _labels(ids: list[uuid.UUID], label_of: dict[uuid.UUID, str]) -> list[str]:
    return [label_of[i] for i in ids if i in label_of]


def build_brief_inputs(
    snapshot: LeadSnapshot,
    *,
    source_opportunity_id: uuid.UUID | None,
    requirements: list[str],
    offerings: list[OfferingInfo],
    today: date,
) -> BriefInputs:
    """Deterministic selection and labelling of everything the model may see (and the known gaps)."""
    gaps: list[str] = []
    flags: set[str] = set()
    opportunities = [o for o in snapshot.opportunities if o.status != "rejected"]
    opportunities.sort(key=lambda o: o.id != source_opportunity_id)  # the deal's own opportunity first
    if source_opportunity_id and not any(o.id == source_opportunity_id for o in opportunities):
        gaps.append("The research opportunity this deal was created from is no longer current (rejected or replaced).")
        flags.add("source_opportunity_unavailable")

    ordered: list[uuid.UUID] = [e for o in opportunities for e in o.evidence_ids]
    ordered += [e for i in snapshot.intents for e in i.evidence_ids]
    ordered += [e for s in snapshot.signals for e in s.evidence_ids]
    ordered += [e.id for e in snapshot.evidence]
    by_id = {e.id: e for e in snapshot.evidence}
    evidence: list[PromptEvidence] = []
    for evidence_id in dict.fromkeys(ordered):
        item = by_id.get(evidence_id)
        if item is None or len(evidence) >= MAX_EVIDENCE:
            continue
        retrieved = item.retrieved_at
        evidence.append(
            PromptEvidence(
                label=f"E{len(evidence) + 1}",
                evidence_id=item.id,
                evidence_type=item.evidence_type,
                fact=item.observed_fact,
                excerpt=item.excerpt,
                source_url=item.source_url,
                retrieved_at=retrieved,
                basis=item.basis,
                origin=item.origin,
                stale=retrieved is not None and retrieved.date() < today - STALE_AFTER,
            )
        )
    label_of = {e.evidence_id: e.label for e in evidence}

    if not evidence:
        gaps.append("No research evidence is available for this company.")
        flags.add("no_evidence")
    stale = [e for e in evidence if e.stale]
    if stale:
        gaps.append(f"{len(stale)} evidence item(s) were retrieved more than 180 days ago and may be outdated.")
        flags.add("stale_evidence")
    if snapshot.research_completed_at is None:
        gaps.append("Company research has not completed; the profile may be incomplete.")
        flags.add("research_incomplete")
    missing = [name for name, value in (("industry", snapshot.industry), ("location", snapshot.location)) if not value]
    if missing:
        gaps.append(f"Not recorded in the company profile: {', '.join(missing)} (check the evidence).")
    if not opportunities:
        gaps.append(
            "Lead research recorded no AI opportunity for this company; opportunities in this brief are hypotheses."
        )
        flags.add("no_research_opportunity")

    signals: list[dict[str, Any]] = []
    for s in snapshot.signals:
        old = s.occurred_on is not None and s.occurred_on < today - STALE_AFTER
        if old:
            gaps.append(f"The trigger {s.title!r} dates from {s.occurred_on}; it may no longer be current.")
            flags.add("stale_evidence")
        if s.date_conflict:
            gaps.append(f"Sources give conflicting dates for {s.title!r}; no single date is assumed.")
            flags.add("conflicting_sources")
        signals.append(
            {
                "type": s.signal_type,
                "title": s.title,
                "occurred_on": s.occurred_on.isoformat() if s.occurred_on else None,
                "date_conflict": s.date_conflict,
                "older_than_180_days": old,
                "evidence": _labels(s.evidence_ids, label_of),
            }
        )
    intents: list[dict[str, Any]] = []
    for i in snapshot.intents:
        expired = i.deadline_on is not None and i.deadline_on < today
        if expired:
            gaps.append(f"The deadline of {i.title!r} ({i.deadline_on}) has passed.")
            flags.add("expired_intent")
        intents.append(
            {
                "strength": i.strength,
                "source": i.source_type,
                "title": i.title,
                "observed_on": i.observed_on.isoformat() if i.observed_on else None,
                "deadline_on": i.deadline_on.isoformat() if i.deadline_on else None,
                "deadline_passed": expired,
                "evidence": _labels(i.evidence_ids, label_of),
            }
        )

    score = snapshot.latest_score
    score_view: dict[str, Any] | None = None
    if score is None:
        gaps.append("No lead score exists for this company.")
    else:
        score_view = {
            "score_low": round(score.score_low, 1),
            "score_high": round(score.score_high, 1),
            "coverage": round(score.coverage, 2),
            "provisional": score.provisional,
            "priority_band": score.priority_band,
            "intent_status": score.intent_status,
            "scoring_version": score.scoring_version,
            "note": SCORE_NOTE,
        }
        if score.provisional:
            gaps.append("The lead score is provisional (important data is missing).")
    verified_intent = [i for i in snapshot.intents if not (i.deadline_on and i.deadline_on < today)]
    if not verified_intent and (score is None or score.intent_status in ("none_verified", "unknown")):
        gaps.append("No verified buying intent: no request, tender or first-party inquiry is recorded.")
        flags.add("no_verified_intent")
    if not requirements:
        gaps.append("No customer requirements have been confirmed yet.")
        flags.add("requirements_unconfirmed")
    staff = sorted({m.group(1).rstrip(".,") for e in evidence for m in _STAFF.finditer(e.excerpt)})
    if len(staff) > 1:
        gaps.append(f"Sources state different employee counts ({', '.join(staff)}); the company size is uncertain.")
        flags.add("conflicting_sources")

    return BriefInputs(
        company={
            "name": snapshot.name,
            "domain": snapshot.canonical_domain,
            "industry": snapshot.industry,
            "location": snapshot.location,
            "description": snapshot.description,
            "lead_review_status": snapshot.review_status,
        },
        company_domain=snapshot.canonical_domain,
        evidence=evidence,
        opportunities=[
            {
                "primary": o.id == source_opportunity_id,
                "title": o.title,
                "status": o.status,
                "confidence": o.confidence,
                "observed_context": o.observed_context,
                "problem_hypothesis": o.problem_hypothesis,
                "proposed_ai_solution": o.proposed_ai_solution,
                "estimated_business_impact": o.estimated_business_impact,
                "validation_questions": o.validation_questions[:6],
                "evidence": _labels(o.evidence_ids, label_of),
            }
            for o in opportunities[:5]
        ],
        signals=signals,
        intents=intents,
        score=score_view,
        requirements=requirements,
        offerings=offerings,
        gaps=gaps,
        gap_flags=flags,
    )


def _block(tag: str, data: Any) -> str:
    return f"<{tag}>\n{neutralise_markup(json.dumps(data, ensure_ascii=False))}\n</{tag}>"


def build_brief_prompt(inputs: BriefInputs) -> str:
    evidence = [
        {
            "id": e.label,
            "type": e.evidence_type,
            "fact": e.fact,
            "excerpt": e.excerpt,
            "basis": e.basis,
            "origin": e.origin,
            "retrieved_on": e.retrieved_at.date().isoformat() if e.retrieved_at else None,
            "older_than_180_days": e.stale,
        }
        for e in inputs.evidence
    ]
    offerings = [
        {"name": o.name, "description": o.description, "category": o.solution_category} for o in inputs.offerings
    ]
    return "\n\n".join(
        [
            _block("company_profile", inputs.company),
            _block("lead_score", inputs.score),
            _block("research_opportunities", inputs.opportunities),
            _block("signals", inputs.signals),
            _block("buying_intent", inputs.intents),
            _block("evidence", evidence),
            _block("confirmed_requirements", inputs.requirements),
            _block("service_offerings", offerings),
            _block("known_gaps", inputs.gaps),
            "Write the internal sales brief for this company. Cite evidence labels for every factual statement.",
        ]
    )


@dataclass
class ValidatedBrief:
    content: dict[str, Any]
    quality_flags: list[str]
    evidence_ids: list[uuid.UUID]


class _BriefValidator:
    def __init__(self, inputs: BriefInputs) -> None:
        self.inputs = inputs
        self.by_label = inputs.by_label
        self.guard = TextGuard(inputs.company_domain)
        self.cited: dict[str, PromptEvidence] = {}
        self.dropped: list[str] = []

    @property
    def flags(self) -> set[str]:
        return self.guard.flags

    def statement(self, st: Statement, section: str, *, observed_only: bool = False) -> dict[str, Any] | None:
        labels: list[str] = []
        for raw in st.evidence:
            label = raw.strip().upper()
            if label == PROFILE_LABEL or (_LABEL.match(label) and label in self.by_label):
                if label not in labels:
                    labels.append(label)
            else:
                self.flags.add("cited_unknown_evidence")
                self.dropped.append(f"{section}: cites unknown evidence {raw[:20]!r}")
                return None
        basis = st.basis
        evidence_labels = [lbl for lbl in labels if lbl != PROFILE_LABEL]
        if basis == "observed" and not labels:
            if observed_only:
                self.flags.add("uncited_observation_removed")
                self.dropped.append(f"{section}: observed statement without evidence")
                return None
            self.flags.add("uncited_observation_downgraded")
            basis = "hypothesis"
        support = " ".join(
            [self.by_label[lbl].support for lbl in evidence_labels]
            + ([self.inputs.profile_text] if PROFILE_LABEL in labels else [])
        )
        text = self.guard.text(st.text, support=support, limit=800)
        if not text:
            self.dropped.append(f"{section}: nothing left after validation")
            return None
        if basis == "observed" and word_overlap(text, support) < MIN_OBSERVED_OVERLAP:
            # The cited evidence does not visibly say this: keep it only as a hypothesis (or drop it where only
            # observations belong).
            self.flags.add("observation_not_in_evidence")
            if observed_only:
                self.dropped.append(f"{section}: statement not found in the cited evidence")
                return None
            basis = "hypothesis"
        for lbl in evidence_labels:
            self.cited[lbl] = self.by_label[lbl]
        return {
            "text": text,
            "basis": basis,
            "evidence": evidence_labels,
            "evidence_ids": [str(self.by_label[lbl].evidence_id) for lbl in evidence_labels],
            "from_profile": PROFILE_LABEL in labels,
        }

    def statements(self, items: list[Statement], section: str, *, observed_only: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for st in items:
            if len(result) >= _LIMITS[section]:
                self.flags.add("output_truncated")
                break
            if (item := self.statement(st, section, observed_only=observed_only)) is not None:
                result.append(item)
        return result

    def strings(self, items: list[str], section: str) -> list[str]:
        result: list[str] = []
        for raw in items:
            text = self.guard.text(raw, support=self.inputs.all_support, limit=300)
            if text and text not in result:
                result.append(text)
        if len(result) > _LIST_LIMITS[section]:
            self.flags.add("output_truncated")
        return result[: _LIST_LIMITS[section]]


def validate_brief(output: BriefOutput, inputs: BriefInputs) -> ValidatedBrief:
    v = _BriefValidator(inputs)
    summary = v.statement(output.company_summary, "company_summary")
    main = v.statement(output.main_opportunity, "main_opportunity")
    title = v.guard.text(output.main_opportunity_title, support=inputs.all_support, limit=200) if main else ""
    solution = v.statement(output.suggested_solution, "suggested_solution")
    next_action = v.guard.text(output.recommended_next_action, support=inputs.all_support, limit=300)
    if is_outreach_action(output.recommended_next_action):
        v.flags.add("outreach_action_replaced")  # AIgentiX never suggests automatic outreach
        next_action = HUMAN_NEXT_ACTION
    next_action = next_action or HUMAN_NEXT_ACTION
    observed = v.statements(output.observed_situation, "observed_situation", observed_only=True)
    supporting = v.statements(output.supporting_evidence, "supporting_evidence", observed_only=True)
    impact = v.statements(output.potential_impact, "potential_impact")
    if not observed and not supporting:
        v.flags.add("insufficient_evidence")
    if v.dropped:
        v.flags.add("items_dropped")
    content = {
        "company_summary": summary or _profile_summary(inputs),
        "observed_situation": observed,
        "main_opportunity": {"title": title or "Opportunity to be identified", **main} if main else None,
        "supporting_evidence": supporting,
        "assumptions_and_uncertainty": v.strings(output.assumptions_and_uncertainty, "assumptions_and_uncertainty"),
        "potential_impact": impact,
        "suggested_solution": solution,
        "implementation_requirements": v.strings(output.implementation_requirements, "implementation_requirements"),
        "discovery_questions": v.strings(output.discovery_questions, "discovery_questions"),
        "recommended_next_action": next_action,
    }
    return _finish(content, inputs, v.cited, v.flags, v.dropped)


def _profile_summary(inputs: BriefInputs) -> dict[str, Any]:
    parts = [str(inputs.company["name"])]
    if inputs.company.get("industry"):
        parts.append(f"industry: {inputs.company['industry']}")
    if inputs.company.get("location"):
        parts.append(f"location: {inputs.company['location']}")
    return {
        "text": neutralise_markup(", ".join(parts)),
        "basis": "observed",
        "evidence": [],
        "evidence_ids": [],
        "from_profile": True,
    }


def _finish(
    content: dict[str, Any],
    inputs: BriefInputs,
    cited: dict[str, PromptEvidence],
    flags: set[str],
    dropped: list[str],
) -> ValidatedBrief:
    ordered = [e for e in inputs.evidence if e.label in cited]
    content.update(
        {
            "unknowns": [strip_foreign_urls(g, inputs.company_domain)[0] for g in inputs.gaps],
            "lead_score": inputs.score,
            "score_note": SCORE_NOTE,
            "evidence": [
                {
                    "label": e.label,
                    "evidence_id": str(e.evidence_id),
                    "evidence_type": e.evidence_type,
                    "excerpt": neutralise_markup(e.excerpt[:500]),
                    "source_url": e.source_url,
                    "retrieved_at": e.retrieved_at.isoformat() if e.retrieved_at else None,
                    "older_than_180_days": e.stale,
                }
                for e in ordered
            ],
            "dropped": dropped[:30],
        }
    )
    return ValidatedBrief(
        content=content,
        quality_flags=sorted(flags | inputs.gap_flags),
        evidence_ids=[e.evidence_id for e in ordered],
    )


def unknowns_only_brief(inputs: BriefInputs) -> ValidatedBrief:
    """Without any evidence nothing can be grounded: a brief that lists only what is known to be missing."""
    content: dict[str, Any] = {
        "company_summary": _profile_summary(inputs),
        "observed_situation": [],
        "main_opportunity": None,
        "supporting_evidence": [],
        "assumptions_and_uncertainty": [],
        "potential_impact": [],
        "suggested_solution": None,
        "implementation_requirements": [],
        "discovery_questions": [
            "What does the company do, and which processes matter most to it?",
            "Is there a current initiative or need related to automation?",
        ],
        "recommended_next_action": "Complete the company research before preparing any outreach.",
    }
    return _finish(content, inputs, {}, {"insufficient_evidence"}, [])


def run_brief(
    provider: LLMProvider,
    inputs: BriefInputs,
    *,
    max_repairs: int,
    record_usage: UsageSink,
    max_tokens: int,
    can_spend: Callable[[], bool] | None = None,
) -> ValidatedBrief:
    output = call_with_repair(
        provider,
        task=BRIEF_TASK,
        system=BRIEF_SYSTEM,
        user=build_brief_prompt(inputs),
        output_model=BriefOutput,
        max_tokens=max_tokens,
        max_repairs=max_repairs,
        record_usage=record_usage,
        can_spend=can_spend,
    )
    return validate_brief(output, inputs)
