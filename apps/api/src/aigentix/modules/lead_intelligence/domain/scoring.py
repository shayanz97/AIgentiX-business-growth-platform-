"""Deterministic, explainable lead scoring ("scoring-v1").

Total = sum of weight_c * score_c / 100 over four components: AI opportunity, ICP fit, growth triggers, buying intent.

Missing data is never hidden and weights are never silently renormalised:
  * every criterion is `assessed`, `unknown` (its data source was not collected), `insufficient_evidence`
    (collected, but nothing to judge on, or contradictory) or `not_applicable` (the profile does not use it);
  * the conservative score (`score_low`) counts unassessed criteria as 0, the upper bound (`score_high`) as full;
  * `coverage` is the assessed share of the total weight; below the profile's `min_coverage` the score is
    `provisional`.
Every criterion lists the evidence IDs (and signal / intent references) it is based on.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from aigentix.modules.lead_intelligence.domain.dates import freshness
from aigentix.modules.lead_intelligence.domain.firmographics import mentions_any
from aigentix.modules.lead_intelligence.domain.intent import solution_categories_for
from aigentix.modules.lead_intelligence.domain.profiles import IcpConfig, ScoringConfig

SCORING_VERSION = "scoring-v1"

TRIGGER_TYPE_VALUE: dict[str, float] = {
    "public_project_request": 1.0,
    "procurement_tender": 1.0,
    "inbound_inquiry": 1.0,
    "digital_transformation": 1.0,
    "hiring": 0.9,
    "expansion": 0.9,
    "funding": 0.8,
    "technology_adoption": 0.8,
    "operational_change": 0.8,
    "leadership_change": 0.6,
    "product_launch": 0.5,
    "other": 0.3,
}
DIMINISHING = (1.0, 0.25, 0.1)  # the strongest trigger counts fully, the 2nd a quarter, the 3rd a tenth
INTENT_VALUE = {"explicit": 100.0, "strong": 80.0, "indirect": 40.0}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.85, "low": 0.6}
OPPORTUNITY_CONFIDENCE = {"high": 1.0, "medium": 0.7, "low": 0.4}


# --- inputs ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpportunityInput:
    id: str
    title: str
    text: str
    confidence: str
    flagged: bool
    evidence_ids: list[str]


@dataclass(frozen=True)
class SignalInput:
    id: str
    signal_type: str
    title: str
    occurred_on: date | None
    date_conflict: bool
    confidence: str
    mention_count: int
    evidence_ids: list[str]
    text: str = ""


@dataclass(frozen=True)
class IntentInput:
    id: str
    strength: str
    source_type: str
    title: str
    observed_on: date | None
    deadline_on: date | None
    reliability: str
    solution_category: str | None
    evidence_ids: list[str]


@dataclass(frozen=True)
class FitInput:
    country: str | None = None
    country_conflict: bool = False
    country_evidence_ids: list[str] = field(default_factory=list)
    industry_texts: list[str] = field(default_factory=list)  # industry statements + company descriptions
    industry_evidence_ids: list[str] = field(default_factory=list)
    employees: int | None = None
    size_conflict: bool = False
    size_evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoringInputs:
    research_state: str  # none | completed | ai_unavailable | failed (latest research run)
    enrichment_state: str  # none | completed | failed (latest enrichment run)
    opportunities: list[OpportunityInput]
    signals: list[SignalInput]
    intents: list[IntentInput]
    fit: FitInput
    reference: date

    def fingerprint(self) -> dict[str, Any]:
        data = asdict(self)
        return json.loads(json.dumps(data, default=str, sort_keys=True))  # type: ignore[no-any-return]


# --- result ------------------------------------------------------------------------------------------------


@dataclass
class Criterion:
    key: str
    label: str
    state: str  # assessed | unknown | insufficient_evidence | not_applicable
    max_points: float
    points: float | None = None
    explanation: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Component:
    key: str
    label: str
    weight: int
    criteria: list[Criterion]
    summary: str = ""
    state: str = "unknown"
    score_low: float = 0.0
    score_high: float = 0.0
    coverage: float = 0.0
    contribution_low: float = 0.0
    contribution_high: float = 0.0

    def finalise(self) -> None:
        applicable = [c for c in self.criteria if c.state != "not_applicable"]
        total = sum(c.max_points for c in applicable)
        if total <= 0:
            self.state, self.coverage = "not_applicable", 1.0
            return
        assessed = [c for c in applicable if c.state == "assessed"]
        points = sum(c.points or 0.0 for c in assessed)
        open_max = sum(c.max_points for c in applicable if c.state != "assessed")
        self.score_low = round(100 * points / total, 1)
        self.score_high = round(100 * (points + open_max) / total, 1)
        self.coverage = round(sum(c.max_points for c in assessed) / total, 3)
        if self.coverage >= 1:
            self.state = "assessed"
        elif self.coverage > 0:
            self.state = "assessed"  # partially; `coverage` shows how much
        elif any(c.state == "unknown" for c in applicable):
            self.state = "unknown"
        else:
            self.state = "insufficient_evidence"
        self.contribution_low = round(self.weight * self.score_low / 100, 2)
        self.contribution_high = round(self.weight * self.score_high / 100, 2)


@dataclass
class ScoreResult:
    components: list[Component]
    score_low: float
    score_high: float
    coverage: float
    provisional: bool
    confidence_level: str
    priority_band: str
    fit_excluded: bool
    exclusion_reasons: list[str]
    intent_status: str
    latest_trigger_on: date | None
    opportunity_categories: list[str]
    evidence_ids: list[str]
    explanation: str
    next_step: str
    next_step_text: str
    inputs_hash: str

    def components_json(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self.components]


# --- components --------------------------------------------------------------------------------------------


def _opportunity(inputs: ScoringInputs, icp: IcpConfig, weight: int) -> tuple[Component, list[str]]:
    best = Criterion("best_opportunity", "Strongest supported AI opportunity", "unknown", 70)
    breadth = Criterion("opportunity_breadth", "Number of supported opportunities", "unknown", 30)
    component = Component("opportunity", "AI opportunity", weight, [best, breadth])
    categories: list[str] = []
    if inputs.research_state != "completed":
        reason = {
            "none": "No website research has been completed yet.",
            "failed": "The latest website research failed.",
            "ai_unavailable": "The AI opportunity audit did not run (no AI provider or budget).",
        }.get(inputs.research_state, "No research results.")
        best.explanation = breadth.explanation = reason
        component.summary = reason
        return component, categories
    values: list[tuple[float, OpportunityInput, list[str]]] = []
    for opp in inputs.opportunities:
        cats = solution_categories_for(opp.text, icp.solution_categories)
        value = OPPORTUNITY_CONFIDENCE.get(opp.confidence, 0.4)
        value *= 0.5 if opp.flagged else 1.0
        value *= 1.0 if cats else 0.6
        values.append((value, opp, cats))
        categories.extend(cats)
    values.sort(key=lambda v: (-v[0], v[1].id))
    best.state = breadth.state = "assessed"
    if not values:
        best.points = breadth.points = 0.0
        best.explanation = "The opportunity audit found no supported AI opportunity."
        breadth.explanation = "No supported opportunities."
        component.summary = "Research completed; no supported opportunity."
        return component, []
    top_value, top, top_cats = values[0]
    best.points = round(70 * top_value, 1)
    best.explanation = (
        f"'{top.title}' ({top.confidence} confidence"
        + (", flagged by validation" if top.flagged else "")
        + (f", category {', '.join(top_cats)}" if top_cats else ", outside the target solution categories")
        + ")."
    )
    best.evidence_ids = list(top.evidence_ids)
    best.references = [{"type": "opportunity", "id": top.id}]
    supported = [v for v in values if v[0] >= 0.35]
    share = {0: 0.0, 1: 0.5, 2: 0.8}.get(len(supported), 1.0)
    breadth.points = round(30 * share, 1)
    breadth.explanation = f"{len(supported)} supported opportunit{'y' if len(supported) == 1 else 'ies'}."
    breadth.evidence_ids = sorted({e for v in supported for e in v[1].evidence_ids})
    breadth.references = [{"type": "opportunity", "id": v[1].id} for v in supported]
    component.summary = f"{len(values)} opportunit{'y' if len(values) == 1 else 'ies'}; strongest: {top.title}."
    return component, list(dict.fromkeys(categories))


def _fit(inputs: ScoringInputs, icp: IcpConfig, weight: int, categories: list[str]) -> tuple[Component, list[str]]:
    collected = inputs.enrichment_state == "completed"  # firmographics come from the enrichment run
    missing = "insufficient_evidence" if collected else "unknown"
    fit = inputs.fit
    exclusions: list[str] = []

    country = Criterion("country", "Target country", missing, 30, evidence_ids=list(fit.country_evidence_ids))
    if fit.country_conflict:
        country.state = "insufficient_evidence"
        country.explanation = "The website names different countries for the company's location."
    elif fit.country:
        country.state = "assessed"
        if fit.country in icp.countries:
            country.points = 30.0
            country.explanation = f"Located in {fit.country} (target: {', '.join(icp.countries)})."
        else:
            country.points = 0.0
            country.explanation = f"Located in {fit.country}, outside the target countries {', '.join(icp.countries)}."
            exclusions.append(f"country {fit.country} is outside the ICP")
    else:
        country.explanation = "No location statement found." if collected else "Not researched yet."

    industry = Criterion("industry", "Industry", missing, 30, evidence_ids=list(fit.industry_evidence_ids))
    text = " ".join(fit.industry_texts)
    if text:
        excluded = mentions_any(text, icp.excluded_industries)
        industry.state = "assessed"
        if excluded:
            industry.points = 0.0
            industry.explanation = f"The company describes itself with the excluded industry term '{excluded}'."
            exclusions.append(f"excluded industry '{excluded}'")
        elif icp.target_industries:
            target = mentions_any(text, icp.target_industries)
            industry.points = 30.0 if target else 0.0
            industry.explanation = (
                f"Matches target industry '{target}'." if target else "Not one of the target industries."
            )
        else:
            industry.points = 30.0
            industry.explanation = "Industry stated and not excluded (the profile targets all industries)."
    else:
        industry.explanation = "No industry statement or description found." if collected else "Not researched yet."

    size = Criterion("company_size", "Company size", missing, 20, evidence_ids=list(fit.size_evidence_ids))
    if icp.min_employees is None and icp.max_employees is None:
        size.state, size.explanation = "not_applicable", "The profile has no size range."
    elif fit.size_conflict:
        size.state = "insufficient_evidence"
        size.explanation = "The website gives contradicting employee numbers."
    elif fit.employees is not None:
        low, high = icp.min_employees or 1, icp.max_employees or 10**9
        size.state = "assessed"
        inside = low <= fit.employees <= high
        size.points = 20.0 if inside else 0.0
        size.explanation = f"About {fit.employees} employees ({'inside' if inside else 'outside'} {low}-{high})."
    else:
        size.explanation = "No employee count published." if collected else "Not researched yet."

    solution = Criterion("solution_category", "Relevant solution category", missing, 20)
    intent_cats = [i.solution_category for i in inputs.intents if i.solution_category]
    all_cats = list(dict.fromkeys([*categories, *intent_cats]))
    if all_cats:
        solution.state, solution.points = "assessed", 20.0
        solution.explanation = f"Evidence relates to: {', '.join(all_cats)}."
        solution.references = [{"type": "intent", "id": i.id} for i in inputs.intents if i.solution_category]
        solution.evidence_ids = sorted({e for i in inputs.intents if i.solution_category for e in i.evidence_ids})
    elif inputs.research_state == "completed":
        solution.state, solution.points = "assessed", 0.0
        solution.explanation = "No evidence relates to a target solution category."
    else:
        solution.explanation = "Needs a completed opportunity audit." if collected else "Not researched yet."

    component = Component("fit", "ICP fit", weight, [country, industry, size, solution])
    component.summary = "Outside the ICP: " + "; ".join(exclusions) + "." if exclusions else ""
    return component, exclusions


def _signal_value(signal: SignalInput, config: ScoringConfig, reference: date) -> tuple[float, str]:
    band = (
        "unknown"
        if signal.date_conflict
        else freshness(signal.occurred_on, reference, config.freshness_bands.model_dump())
    )
    factor = getattr(config.freshness_factors, band)
    value = TRIGGER_TYPE_VALUE.get(signal.signal_type, 0.3) * factor * CONFIDENCE_FACTOR.get(signal.confidence, 0.6)
    return value, band


def _triggers(inputs: ScoringInputs, config: ScoringConfig, weight: int) -> Component:
    criterion = Criterion("growth_triggers", "Growth triggers (diminishing returns)", "unknown", 100)
    component = Component("triggers", "Growth triggers", weight, [criterion])
    if inputs.enrichment_state != "completed":
        criterion.explanation = component.summary = (
            "Enrichment has not run yet." if inputs.enrichment_state == "none" else "The latest enrichment failed."
        )
        return component
    criterion.state = "assessed"
    scored = sorted(
        ((*_signal_value(s, config, inputs.reference), s) for s in inputs.signals),
        key=lambda t: (-t[0], t[2].id),
    )
    total = 0.0
    parts: list[str] = []
    for factor, (value, band, signal) in zip(DIMINISHING, scored, strict=False):
        total += 100 * value * factor
        when = signal.occurred_on.isoformat() if signal.occurred_on else "date unknown"
        if signal.date_conflict:
            when = "conflicting dates"
        parts.append(f"{signal.signal_type} ({when}, {band}) → {100 * value * factor:.0f}")
        criterion.evidence_ids.extend(signal.evidence_ids)
        criterion.references.append({"type": "signal", "id": signal.id})
    criterion.points = round(min(100.0, total), 1)
    criterion.evidence_ids = sorted(set(criterion.evidence_ids))
    if scored:
        criterion.explanation = "; ".join(parts) + (
            f" (+{len(scored) - 3} further trigger(s) not counted)" if len(scored) > 3 else ""
        )
    else:
        criterion.explanation = "No growth trigger was found on the company's public pages."
    component.summary = f"{len(scored)} trigger(s)." if scored else "No verified trigger."
    return component


def _active(intent: IntentInput, reference: date) -> bool:
    return intent.deadline_on is None or intent.deadline_on >= reference


def _intent(inputs: ScoringInputs, config: ScoringConfig, weight: int) -> tuple[Component, str]:
    criterion = Criterion("buying_intent", "Strongest verified buying intent", "unknown", 100)
    component = Component("intent", "Buying intent", weight, [criterion])
    active = [i for i in inputs.intents if _active(i, inputs.reference)]
    if not active and inputs.enrichment_state != "completed":
        criterion.explanation = component.summary = "Intent sources have not been checked yet."
        return component, "unknown"
    criterion.state = "assessed"
    if not active:
        criterion.points = 0.0
        criterion.explanation = (
            "No verified buying intent: no request, tender or inquiry was found in the checked sources. "
            "This is not evidence that there is no need."
        )
        component.summary = "None verified."
        return component, "none_verified"
    bands = config.freshness_bands.model_dump()

    def value(i: IntentInput) -> float:
        factor = float(getattr(config.freshness_factors, freshness(i.observed_on, inputs.reference, bands)))
        return INTENT_VALUE[i.strength] * factor * CONFIDENCE_FACTOR.get(i.reliability, 0.6)

    best = max(active, key=lambda i: (value(i), INTENT_VALUE[i.strength], i.id))
    strongest = max(active, key=lambda i: INTENT_VALUE[i.strength]).strength
    band = freshness(best.observed_on, inputs.reference, bands)
    criterion.points = round(value(best), 1)
    criterion.explanation = (
        f"{best.strength} intent from {best.source_type.replace('_', ' ')}: '{best.title[:120]}' "
        f"({best.observed_on.isoformat() if best.observed_on else 'date unknown'}, {band}"
        + (f", deadline {best.deadline_on.isoformat()}" if best.deadline_on else "")
        + ")."
    )
    criterion.evidence_ids = list(best.evidence_ids)
    criterion.references = [{"type": "intent", "id": best.id}]
    component.summary = f"{strongest} ({len(active)} verified source(s))."
    return component, strongest


# --- total ---------------------------------------------------------------------------------------------------


def _next_step(result_band: str, intent_status: str, provisional: bool, components: list[Component]) -> tuple[str, str]:
    if result_band == "excluded":
        return "reject_outside_icp", "Outside the ideal customer profile: reject or archive unless the ICP changes."
    if intent_status in ("explicit", "strong"):
        return (
            "review_active_request",
            "A verified, active request or tender exists: review it now and decide manually whether to respond.",
        )
    missing = [c.label for c in components if c.state in ("unknown", "insufficient_evidence")]
    if provisional and missing:
        return "complete_research", f"Complete the research before deciding (missing: {', '.join(missing)})."
    if result_band == "high":
        return "qualify_for_review", "Strong evidence-backed fit: qualify the lead for human review."
    if result_band == "medium":
        return "monitor", "Promising but not urgent: monitor for new triggers and re-score later."
    return "deprioritize", "Weak evidence of need or fit: deprioritise."


def score_lead(inputs: ScoringInputs, icp: IcpConfig, config: ScoringConfig) -> ScoreResult:
    weights = config.weights
    opportunity, categories = _opportunity(inputs, icp, weights.opportunity)
    fit, exclusions = _fit(inputs, icp, weights.fit, categories)
    triggers = _triggers(inputs, config, weights.triggers)
    intent, intent_status = _intent(inputs, config, weights.intent)
    components = [opportunity, fit, triggers, intent]
    for component in components:
        component.finalise()

    score_low = round(sum(c.contribution_low for c in components), 1)
    score_high = round(sum(c.contribution_high for c in components), 1)
    coverage = round(sum(c.weight * c.coverage for c in components) / 100, 3)
    provisional = coverage < config.min_coverage
    conflicts = inputs.fit.size_conflict or inputs.fit.country_conflict or any(s.date_conflict for s in inputs.signals)
    if coverage >= 0.9 and not conflicts:
        confidence_level = "high"
    elif coverage >= 0.6:
        confidence_level = "medium"
    else:
        confidence_level = "low"
    if exclusions:
        band = "excluded"
    elif score_low >= config.thresholds.high:
        band = "high"
    elif score_low >= config.thresholds.medium:
        band = "medium"
    else:
        band = "low"
    next_step, next_text = _next_step(band, intent_status, provisional, components)

    dated = [s.occurred_on for s in inputs.signals if s.occurred_on and not s.date_conflict]
    evidence = sorted({e for c in components for cr in c.criteria for e in cr.evidence_ids})
    explanation = (
        f"Score {score_low:.1f}"
        + (f"-{score_high:.1f}" if score_high > score_low else "")
        + f" of 100 ({coverage:.0%} of the weight assessed"
        + (", provisional" if provisional else "")
        + "). "
        + " ".join(
            f"{c.label} ({c.weight}%): {c.score_low:.0f}"
            + (f"-{c.score_high:.0f}" if c.score_high > c.score_low else "")
            + f"/100 — {c.summary or c.state}"
            for c in components
        )
    )
    payload = {
        "inputs": inputs.fingerprint(),
        "icp": icp.model_dump(),
        "config": config.model_dump(),
        "version": SCORING_VERSION,
    }
    inputs_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return ScoreResult(
        components=components,
        score_low=score_low,
        score_high=score_high,
        coverage=coverage,
        provisional=provisional,
        confidence_level=confidence_level,
        priority_band=band,
        fit_excluded=bool(exclusions),
        exclusion_reasons=exclusions,
        intent_status=intent_status,
        latest_trigger_on=max(dated) if dated else None,
        opportunity_categories=categories,
        evidence_ids=evidence,
        explanation=explanation,
        next_step=next_step,
        next_step_text=next_text,
        inputs_hash=inputs_hash,
    )
