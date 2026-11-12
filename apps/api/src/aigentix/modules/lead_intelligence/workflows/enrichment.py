"""Company enrichment workflow (growth triggers, buying intent, lead score), executed by the platform worker.

VALIDATE_INPUT → COLLECT_SOURCES → EXTRACT_SIGNALS → REVIEW_SIGNALS (optional AI) → VERIFY_EVIDENCE →
RESEARCH_INTENT → SCORE_LEAD

It reuses the research workflow's fetching, robots, SSRF and checkpoint machinery (same worker, no second
engine) and adds:
  * discovery of news / press / careers / tender / project-request pages;
  * segmentation into news items and job postings with their own dates (never the retrieval date);
  * deterministic classification and deduplication, optionally reviewed by an AI model that can only confirm,
    reject or re-type candidates (never add one, change a date or create intent);
  * evidence rows with verbatim excerpts for every signal and firmographic fact;
  * buying intent from the website, a configured tender source and licensed providers (none bundled);
  * a deterministic score with the organization's default profiles.
Idempotency: finished steps are recorded in run state; this run's evidence is replaced and signals / intents are
upserted by dedupe key, so retries and resumes never duplicate records.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urldefrag, urlsplit

from sqlalchemy import delete, select

from aigentix.core.db import utcnow
from aigentix.core.logging import get_logger
from aigentix.modules.lead_intelligence.agents.prompts import SIGNAL_REVIEW_PROMPT_VERSION
from aigentix.modules.lead_intelligence.agents.signal_reviewer import review_signals
from aigentix.modules.lead_intelligence.agents.text_safety import excerpt_in_source, strip_foreign_urls
from aigentix.modules.lead_intelligence.domain.domains import same_site
from aigentix.modules.lead_intelligence.domain.firmographics import extract_firmographics
from aigentix.modules.lead_intelligence.domain.intent import (
    IntentCandidate,
    merge_intents,
    tender_intents,
    website_intents,
)
from aigentix.modules.lead_intelligence.domain.profiles import IcpConfig
from aigentix.modules.lead_intelligence.domain.signals import DetectedSignal, detect
from aigentix.modules.lead_intelligence.integrations.fetcher import FetchedPage, SafeFetcher
from aigentix.modules.lead_intelligence.integrations.html import Link, is_excluded_path
from aigentix.modules.lead_intelligence.integrations.intent_providers import configured_intent_providers
from aigentix.modules.lead_intelligence.integrations.segments import Segment, extract_segments, signal_page_category
from aigentix.modules.lead_intelligence.integrations.tenders import TenderSource, build_tender_source
from aigentix.modules.lead_intelligence.models import (
    Basis,
    BusinessSignal,
    BusinessSignalEvidence,
    BuyingIntentEvidence,
    BuyingIntentSignal,
    DatePrecision,
    Evidence,
    EvidenceType,
    IcpProfile,
    IntentSourceType,
    ResearchRun,
    ResearchSource,
    ScoringProfile,
    SignalType,
)
from aigentix.modules.lead_intelligence.services import profiles
from aigentix.modules.lead_intelligence.services.scoring import score_company
from aigentix.modules.lead_intelligence.workflows.constants import ENRICHMENT_STEPS
from aigentix.modules.lead_intelligence.workflows.research import (
    ResearchDependencies,
    _Research,
    _task_available,
    default_dependencies,
)
from aigentix.platform.llm import LLMError
from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus

log = get_logger("aigentix.enrichment")

_PAGE_PRIORITY = ("requests", "news", "careers", "about")
MAX_FIRMOGRAPHIC_EVIDENCE = 3


@dataclass
class EnrichmentDependencies(ResearchDependencies):
    tender_source_factory: Callable[[], TenderSource | None] = lambda: None


def default_enrichment_dependencies() -> EnrichmentDependencies:
    base = default_dependencies()
    kind = base.settings.research_tender_source
    return EnrichmentDependencies(
        settings=base.settings,
        fetcher_factory=base.fetcher_factory,
        provider_factory=base.provider_factory,
        tender_source_factory=lambda: build_tender_source(kind),
    )


def make_enrichment_handler(
    deps_factory: Callable[[], EnrichmentDependencies] = default_enrichment_dependencies,
) -> Callable[[WorkflowContext], WorkflowResult]:
    def handler(ctx: WorkflowContext) -> WorkflowResult:
        return _Enrichment(ctx, deps_factory()).run_enrichment()

    return handler


def signal_candidate_pages(links: list[Link], *, domain: str, limit: int) -> list[tuple[str, str]]:
    """Same-site pages likely to carry announcements, job postings or requests (round-robin by category)."""
    by_category: dict[str, list[str]] = {}
    seen: set[str] = set()
    for link in links:
        parts = urlsplit(urldefrag(link.url)[0])
        if parts.scheme not in ("http", "https") or not same_site(parts.hostname or "", domain):
            continue
        if is_excluded_path(parts.path) or parts.query:
            continue
        key = (parts.path.rstrip("/") or "/").lower()
        if key == "/" or key in seen:
            continue
        category = signal_page_category(parts.path)
        if category is None:
            continue
        seen.add(key)
        by_category.setdefault(category, []).append(parts.geturl())
    chosen: list[tuple[str, str]] = []
    for rnd in range(4):
        for category in _PAGE_PRIORITY:
            urls = by_category.get(category, [])
            if rnd < len(urls) and len(chosen) < limit:
                chosen.append((urls[rnd], category))
    return chosen


class _Enrichment(_Research):
    _discovery_step = "collect_sources"

    def __init__(self, ctx: WorkflowContext, deps: EnrichmentDependencies) -> None:
        super().__init__(ctx, deps)
        self.enrichment_deps = deps
        self._last_body: tuple[str, bytes] | None = None
        self.reference: date = self.settings.reference_date()

    # --- hooks into the research fetching code ----------------------------------------------------

    def _fetch(self, fetcher: SafeFetcher, url: str) -> FetchedPage:
        page = fetcher.get(url)
        self._last_body = (page.url, page.body) if page.ok and page.is_html else None
        return page

    def _save_source(self, url: str, category: str, **kwargs: Any) -> ResearchSource:
        source = super()._save_source(url, category, **kwargs)
        if kwargs.get("page") is not None and self._last_body is not None:
            final_url, body = self._last_body
            segments = dict(self.ctx.get_state("segments", {}))
            items = extract_segments(body, final_url)
            for item in items:
                item.page_url = source.source_url  # cite the stored source, whatever the final URL was
            segments[str(source.id)] = [s.to_json() for s in items]
            self.ctx.set_state("segments", segments)
        self._last_body = None
        return source

    def _candidate_pages(self, links: list[Any], domain: str) -> list[tuple[str, str]]:
        return signal_candidate_pages(links, domain=domain, limit=self.settings.research_enrichment_max_pages - 1)

    # --- workflow --------------------------------------------------------------------------------

    def run_enrichment(self) -> WorkflowResult:
        steps: dict[str, Callable[[], None]] = {
            "validate_input": self.validate_input,
            "collect_sources": self.collect_sources,
            "extract_signals": self.extract_signals,
            "review_signals": self.review_signals_step,
            "verify_evidence": self.verify_evidence,
            "research_intent": self.research_intent,
            "score_lead": self.score_lead,
        }
        fetcher = None
        try:
            for name, progress in ENRICHMENT_STEPS:
                done: list[str] = list(self.ctx.get_state("done_steps", []))
                if name in done:
                    continue
                self.ctx.checkpoint(name, progress)
                if name == "collect_sources":
                    fetcher = fetcher or self.deps.fetcher_factory()
                    self._fetcher = fetcher
                started = time.perf_counter()
                steps[name]()
                durations = dict(self.ctx.get_state("step_ms", {}))
                durations[name] = round((time.perf_counter() - started) * 1000)
                self.ctx.set_state("step_ms", durations)
                self.ctx.set_state("done_steps", [*done, name])
                self.db.commit()
        finally:
            if fetcher is not None:
                fetcher.close()
        summary = {
            "pages_fetched": self.research.pages_fetched,
            "signals": self.ctx.get_state("signal_count", 0),
            "intents": self.ctx.get_state("intent_count", 0),
            "quarantined_items": self.ctx.get_state("quarantined", 0),
            "ai_review": self.ctx.get_state("ai_status", "skipped"),
            "score_id": self.ctx.get_state("score_id"),
        }
        return WorkflowResult(summary=summary, partial=False, message=self.ctx.get_state("ai_message"))

    def validate_input(self) -> None:
        super().validate_input()
        self.ctx.set_state("prompt_versions", {"signals": SIGNAL_REVIEW_PROMPT_VERSION})
        self.ctx.set_state("reference_date", self.reference.isoformat())

    def collect_sources(self) -> None:
        if not any(s.page_category == "home" for s in self._sources()):
            self.fetch_website()
            self.db.commit()
        self.discover_relevant_pages()

    def _segments(self) -> list[Segment]:
        stored: dict[str, list[dict[str, Any]]] = self.ctx.get_state("segments", {})
        return [Segment.from_json(item) for items in stored.values() for item in items]

    def _detected(self) -> list[DetectedSignal]:
        """Deterministic detection (recomputed from stored segments) with the AI review applied, if any."""
        signals = detect(self._segments(), reference=self.reference).signals
        decisions: dict[str, dict[str, str | bool]] = self.ctx.get_state("ai_decisions", {})
        kept: list[DetectedSignal] = []
        for index, signal in enumerate(signals):
            decision = decisions.get(str(index))
            if decision is not None:
                if not decision["keep"]:
                    continue
                signal.signal_type = SignalType(str(decision["signal_type"]))
                signal.details["ai_relevance"] = decision["relevance"]
                signal.details["ai_reason"] = decision["reason"]
            kept.append(signal)
        return kept

    def extract_signals(self) -> None:
        result = detect(self._segments(), reference=self.reference)
        self.ctx.set_state("candidate_count", len(result.signals))
        self.ctx.set_state("quarantined", len(result.quarantined))
        self.ctx.set_state("unclassified_items", result.unclassified)
        if result.quarantined:
            log.info("enrichment.quarantined_items", count=len(result.quarantined))

    def review_signals_step(self) -> None:
        signals = detect(self._segments(), reference=self.reference).signals
        provider = self.provider
        if not self.settings.research_signal_ai_review or not signals:
            self.ctx.set_state("ai_status", "skipped")
            return
        if provider is None or not _task_available(provider, "signals"):
            self.ctx.set_state("ai_status", "unavailable")
            self.ctx.set_state("ai_message", "AI review of triggers skipped: no AI provider is configured.")
            return
        max_tokens = self._token_budget(provider, "signals", 4_000)
        if max_tokens is None:
            return
        try:
            review = review_signals(
                provider,
                signals,
                max_repairs=self.settings.llm_max_repairs,
                record_usage=self._record_usage,
                max_tokens=max_tokens,
                can_spend=self._can_spend,
            )
        except LLMError as exc:
            self._ai_failed(exc, "trigger review")
            return
        self.ctx.set_state(
            "ai_decisions",
            {
                str(i): {"keep": d.keep, "signal_type": d.signal_type, "relevance": d.relevance, "reason": d.reason}
                for i, d in review.decisions.items()
            },
        )
        self.ctx.set_state("ai_ignored", review.ignored)
        self.ctx.set_state("ai_status", "completed")

    # --- evidence and signals ------------------------------------------------------------------

    def _evidence(self, source: ResearchSource, kind: EvidenceType, fact: str, excerpt: str) -> Evidence | None:
        """An evidence row whose excerpt is verbatim in the stored page text (else no evidence is created)."""
        if not excerpt_in_source(excerpt, source.extracted_text):
            return None
        row = Evidence(
            organization_id=self.company.organization_id,
            research_run_id=self.research.workflow_run_id,
            company_id=self.company.id,
            source_id=source.id,
            observed_fact=fact[:2000],
            supporting_excerpt=excerpt[:1000],
            evidence_type=kind.value,
            basis=Basis.OBSERVED.value,
            confidence="high",
            origin="deterministic",
        )
        self.db.add(row)
        return row

    def verify_evidence(self) -> None:
        run_id = self.research.workflow_run_id
        self.db.execute(delete(Evidence).where(Evidence.research_run_id == run_id))
        self.db.flush()
        sources = {s.source_url: s for s in self._sources() if s.extraction_status == "extracted"}
        domain = self.ctx.get_state("site_domain")
        stored: dict[str, list[str]] = {}  # dedupe key → evidence ids
        for signal in self._detected():
            evidence: list[Evidence] = []
            for candidate in signal.candidates:
                source = sources.get(candidate.segment.page_url)
                if source is None:
                    continue
                excerpt = candidate.excerpt if len(candidate.excerpt) >= 10 else candidate.segment.text[:300]
                when = candidate.date.value.value.isoformat() if candidate.date.value else "date not stated"
                fact = f"{signal.signal_type.value.replace('_', ' ').capitalize()}: {signal.title} ({when})"
                proof = self._evidence(source, EvidenceType.BUSINESS_SIGNAL, fact, excerpt)
                if proof is None and candidate.segment.headline:
                    proof = self._evidence(source, EvidenceType.BUSINESS_SIGNAL, fact, candidate.segment.headline)
                if proof is not None:
                    evidence.append(proof)
            if not evidence:
                continue  # no verifiable excerpt → no signal
            self.db.flush()
            row = self._upsert_signal(signal, domain)
            self.db.execute(delete(BusinessSignalEvidence).where(BusinessSignalEvidence.signal_id == row.id))
            self.db.add_all(
                BusinessSignalEvidence(signal_id=row.id, evidence_id=e.id, organization_id=row.organization_id)
                for e in evidence
            )
            stored[signal.dedupe_key] = [str(e.id) for e in evidence]
        self.ctx.set_state("signal_count", len(stored))
        self.ctx.set_state("signal_evidence", stored)
        self._firmographics(list(sources.values()))
        self.db.flush()

    def _upsert_signal(self, signal: DetectedSignal, domain: str | None) -> BusinessSignal:
        org = self.company.organization_id
        row = self.db.scalar(
            select(BusinessSignal).where(
                BusinessSignal.organization_id == org,
                BusinessSignal.company_id == self.company.id,
                BusinessSignal.dedupe_key == signal.dedupe_key,
            )
        )
        now = utcnow()
        if row is None:
            row = BusinessSignal(
                organization_id=org,
                company_id=self.company.id,
                dedupe_key=signal.dedupe_key,
                first_seen_at=now,
            )
            self.db.add(row)
        summary, _ = strip_foreign_urls(signal.summary, domain)
        row.enrichment_run_id = self.research.workflow_run_id
        row.signal_type = signal.signal_type.value
        row.title = signal.title[:300]
        row.summary = summary[:2000]
        row.occurred_on = signal.occurred.value if signal.occurred else None
        row.date_precision = (signal.occurred.precision if signal.occurred else DatePrecision.UNKNOWN).value
        row.date_conflict = signal.date_conflict
        row.date_candidates = [
            {**c.date.value.to_json(), "source_url": c.segment.page_url}
            for c in signal.candidates
            if c.date.value is not None
        ][:20]
        row.deadline_on = signal.deadline.value if signal.deadline else None
        row.confidence = signal.confidence
        row.relevance = str(signal.details.get("ai_relevance") or "medium")
        row.origin = "llm_reviewed" if "ai_relevance" in signal.details else "deterministic"
        row.mention_count = len(signal.candidates)
        row.source_urls = signal.source_urls[:20]
        row.details = {k: v for k, v in signal.details.items() if k != "ai_relevance"}
        row.last_seen_at = now
        self.db.flush()
        return row

    def _firmographics(self, sources: list[ResearchSource]) -> None:
        # Firmographics also use the latest research run's pages (about/services) when available.
        research_sources = self._latest_research_sources()
        pool = [*sources, *(s for s in research_sources if s.source_url not in {x.source_url for x in sources})]
        facts = extract_firmographics([s.extracted_text for s in pool])

        def cite(kind: EvidenceType, fact: str, excerpt: str, index: int) -> str | None:
            row = self._evidence(pool[index], kind, fact, excerpt)
            if row is None:
                return None
            self.db.flush()
            return str(row.id)

        country_ids = [
            e
            for f in facts.countries[:MAX_FIRMOGRAPHIC_EVIDENCE]
            if (e := cite(EvidenceType.LOCATION, f"Located in {f.value}", f.excerpt, f.source_index))
        ]
        industry_ids = [
            e
            for f in facts.industry_statements[:MAX_FIRMOGRAPHIC_EVIDENCE]
            if (e := cite(EvidenceType.INDUSTRY, f"Industry: {f.value}", f.excerpt, f.source_index))
        ]
        size_ids = [
            e
            for f in facts.sizes[: MAX_FIRMOGRAPHIC_EVIDENCE + 2]
            if (e := cite(EvidenceType.COMPANY_SIZE, f"About {f.employees} employees", f.excerpt, f.source_index))
        ]
        descriptions = [s.extracted_text[:600] for s in pool if s.page_category in ("about", "home")][:3]
        if self.company.short_description:
            descriptions.append(self.company.short_description[:600])
        if self.company.industry:
            descriptions.append(self.company.industry)
        about_ids = [
            e
            for s in pool
            if s.page_category == "about" and s.extracted_text
            for e in [cite(EvidenceType.COMPANY_DESCRIPTION, "About page", s.extracted_text[:300], pool.index(s))]
            if e
        ][:1]
        self.research.profile = {
            **(self.research.profile or {}),
            "firmographics": {
                "country": facts.country,
                "country_conflict": facts.country_conflict,
                "country_evidence_ids": country_ids,
                "industry_texts": [f.value for f in facts.industry_statements] + descriptions,
                "industry_evidence_ids": industry_ids + about_ids,
                "employees": facts.employees,
                "size_conflict": facts.size_conflict,
                "size_values": sorted({s.employees for s in facts.sizes}),
                "size_evidence_ids": size_ids,
            },
            "reference_date": self.reference.isoformat(),
            "quarantined_items": self.ctx.get_state("quarantined", 0),
            "generated_by": {
                "deterministic_parser": "signals-v1",
                "models": self.ctx.get_state("models_used", []),
                "prompt_versions": self.ctx.get_state("prompt_versions", {}),
            },
        }

    def _latest_research_sources(self) -> list[ResearchSource]:
        run_id = self.db.scalar(
            select(ResearchRun.workflow_run_id)
            .join(WorkflowRun, WorkflowRun.id == ResearchRun.workflow_run_id)
            .where(
                ResearchRun.organization_id == self.company.organization_id,
                ResearchRun.company_id == self.company.id,
                ResearchRun.kind == "research",
                WorkflowRun.status.in_([WorkflowStatus.COMPLETED.value, WorkflowStatus.PARTIAL.value]),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
        if run_id is None:
            return []
        return list(
            self.db.scalars(
                select(ResearchSource)
                .where(ResearchSource.research_run_id == run_id, ResearchSource.extraction_status == "extracted")
                .order_by(ResearchSource.retrieved_at, ResearchSource.source_url)
            )
        )

    # --- intent ----------------------------------------------------------------------------------

    def research_intent(self) -> None:
        org = self.company.organization_id
        icp = IcpConfig.model_validate(profiles.ensure_default(self.db, org, IcpProfile).config)
        signals = self._detected()
        stored: dict[str, list[str]] = self.ctx.get_state("signal_evidence", {})
        # Only signals with verified evidence can carry intent.
        evidence_by_index = {i: stored[s.dedupe_key] for i, s in enumerate(signals) if s.dedupe_key in stored}
        verified = [i for i in range(len(signals)) if i in evidence_by_index]
        site, ignored = website_intents(
            [signals[i] for i in verified], categories=icp.solution_categories, reference=self.reference
        )
        for candidate in site:  # indices refer to the filtered list
            if candidate.signal_index is not None:
                candidate.signal_index = verified[candidate.signal_index]
        external: list[IntentCandidate] = []
        tender_source = self.enrichment_deps.tender_source_factory()
        domain = self.company.canonical_domain or ""
        if tender_source is not None and domain:
            found, skipped = tender_intents(
                tender_source.tenders_for(domain), categories=icp.solution_categories, reference=self.reference
            )
            external.extend(found)
            ignored.extend(skipped)
        for provider in configured_intent_providers():  # pragma: no cover - none bundled
            log.info("enrichment.intent_provider", provider=provider.name)
        merged = merge_intents(site, external)

        keep_keys = {c.dedupe_key for c in merged}
        # Website / tender intents are re-derived on every enrichment; first-party records are never touched.
        self.db.execute(
            delete(BuyingIntentSignal).where(
                BuyingIntentSignal.organization_id == org,
                BuyingIntentSignal.company_id == self.company.id,
                BuyingIntentSignal.source_type.in_(
                    [IntentSourceType.WEBSITE.value, IntentSourceType.PUBLIC_TENDER.value]
                ),
                BuyingIntentSignal.dedupe_key.not_in(keep_keys) if keep_keys else BuyingIntentSignal.id.is_not(None),
            )
        )
        now = utcnow()
        for candidate in merged:
            row = self.db.scalar(
                select(BuyingIntentSignal).where(
                    BuyingIntentSignal.organization_id == org,
                    BuyingIntentSignal.company_id == self.company.id,
                    BuyingIntentSignal.dedupe_key == candidate.dedupe_key,
                )
            )
            if row is None:
                row = BuyingIntentSignal(
                    organization_id=org, company_id=self.company.id, dedupe_key=candidate.dedupe_key
                )
                self.db.add(row)
            summary, _ = strip_foreign_urls(candidate.summary, domain or None)
            row.enrichment_run_id = self.research.workflow_run_id
            row.strength = candidate.strength.value
            row.source_type = candidate.source_type.value
            row.title = candidate.title[:300]
            row.summary = summary[:2000]
            row.solution_category = candidate.solution_category
            row.observed_on = candidate.observed.value if candidate.observed else None
            row.deadline_on = candidate.deadline.value if candidate.deadline else None
            row.external_ref = candidate.external_ref
            row.source_url = candidate.source_url
            row.reliability = "high"
            row.last_seen_at = now
            self.db.flush()
            self.db.execute(delete(BuyingIntentEvidence).where(BuyingIntentEvidence.intent_id == row.id))
            if candidate.signal_index is not None:
                self.db.add_all(
                    BuyingIntentEvidence(intent_id=row.id, evidence_id=uuid.UUID(e), organization_id=org)
                    for e in evidence_by_index.get(candidate.signal_index, [])
                )
        self.db.flush()
        self.ctx.set_state("intent_count", len(merged))
        self.ctx.set_state("intent_ignored", ignored[:50])
        self.research.profile = {
            **(self.research.profile or {}),
            "intent": {
                "sources_checked": ["website"]
                + (["tender_source:" + tender_source.name] if tender_source is not None else [])
                + [f"provider:{p.name}" for p in configured_intent_providers()],
                "found": len(merged),
                "ignored": ignored[:50],
            },
        }

    def score_lead(self) -> None:
        org = self.company.organization_id
        # The run must count as finished for scoring: the score reflects this enrichment's results.
        self.db.flush()
        scoring = profiles.ensure_default(self.db, org, ScoringProfile)
        icp = profiles.ensure_default(self.db, org, IcpProfile)
        score, _ = score_company(
            self.db,
            org,
            self.company,
            scoring_profile=scoring,
            icp_profile=icp,
            reference=self.reference,
            user_id=None,
            current_enrichment=self.research,
        )
        self.ctx.set_state("score_id", str(score.id))
        self.research.ai_status = self.ctx.get_state("ai_status") or "skipped"
        self.research.audit_summary = self.ctx.get_state("ai_message")
