"""Company research workflow, executed by the platform worker.

VALIDATE_INPUT → FETCH_WEBSITE → DISCOVER_RELEVANT_PAGES → EXTRACT_INFORMATION → SAVE_EVIDENCE →
AI_OPPORTUNITY_AUDIT → PERSIST_RESULTS

Idempotency rules (a retried or resumed run never duplicates records):
  * finished steps are recorded in the run state ("done_steps") in the same transaction as their output and
    are skipped on resume;
  * sources are unique per (run, url) and checked before fetching, and each fetched page is committed;
  * evidence and opportunities are replaced for the run inside the transaction that marks the step done.
Errors: invalid input / blocked or forbidden website → WorkflowError (no retry); network/LLM outages →
TransientWorkflowError (retried with backoff). On the last attempt an AI outage degrades the run to `partial`
instead of discarding the deterministic research.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select

from aigentix.core.logging import get_logger
from aigentix.modules.lead_intelligence.agents.company_researcher import (
    PromptSource,
    VerifiedAssertion,
    run_extraction,
)
from aigentix.modules.lead_intelligence.agents.opportunity_auditor import PromptEvidence, run_audit
from aigentix.modules.lead_intelligence.agents.prompts import AUDIT_PROMPT_VERSION, EXTRACTION_PROMPT_VERSION
from aigentix.modules.lead_intelligence.config import ResearchSettings, get_research_settings
from aigentix.modules.lead_intelligence.domain.domains import InvalidWebsite, canonical_domain, parse_website
from aigentix.modules.lead_intelligence.integrations.fetcher import (
    BlockedDestination,
    DomainRateLimiter,
    FetchedPage,
    FetcherConfig,
    FetchError,
    SafeFetcher,
)
from aigentix.modules.lead_intelligence.integrations.html import (
    discover_relevant_links,
    extract_page,
    name_from_title,
)
from aigentix.modules.lead_intelligence.integrations.llm import (
    LLMError,
    LLMProvider,
    LLMTransientError,
    LLMUsage,
    build_provider,
)
from aigentix.modules.lead_intelligence.integrations.robots import RobotsPolicy, load_robots
from aigentix.modules.lead_intelligence.models import (
    Basis,
    Company,
    Confidence,
    Evidence,
    EvidenceType,
    Opportunity,
    OpportunityEvidence,
    ResearchRun,
    ResearchSource,
)
from aigentix.modules.lead_intelligence.workflows.constants import STEPS
from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult
from aigentix.platform.workflows.errors import TransientWorkflowError, WorkflowError

log = get_logger("aigentix.research")

MAX_EVIDENCE_FOR_AUDIT = 40
MAX_LINKS_KEPT = 300
_CRAWL_DELAY_CAP_SECONDS = 5.0
_STRUCTURAL_TYPES = {
    EvidenceType.CONTACT_FORM,
    EvidenceType.QUOTE_REQUEST_FORM,
    EvidenceType.ONLINE_BOOKING,
    EvidenceType.LIVE_CHAT,
    EvidenceType.DOCUMENT_DOWNLOAD,
    EvidenceType.FAQ,
    EvidenceType.CAREERS_HIRING,
}


@dataclass
class ResearchDependencies:
    settings: ResearchSettings
    fetcher_factory: Callable[[], SafeFetcher]
    provider_factory: Callable[[], LLMProvider | None]


_rate_limiter: DomainRateLimiter | None = None


def default_dependencies() -> ResearchDependencies:
    global _rate_limiter
    settings = get_research_settings()
    if _rate_limiter is None:
        _rate_limiter = DomainRateLimiter(settings.research_domain_min_interval_seconds)
    limiter = _rate_limiter
    config = FetcherConfig(
        user_agent=settings.research_user_agent,
        timeout_seconds=settings.research_http_timeout_seconds,
        max_bytes=settings.research_max_response_bytes,
    )

    def fetcher() -> SafeFetcher:
        if settings.research_fetch_backend == "fixtures":
            from aigentix.modules.lead_intelligence.integrations.fixture_web import (
                fixture_resolver,
                fixture_transport,
            )

            return SafeFetcher(config, resolver=fixture_resolver, transport=fixture_transport(), rate_limiter=limiter)
        return SafeFetcher(config, rate_limiter=limiter)

    return ResearchDependencies(
        settings=settings, fetcher_factory=fetcher, provider_factory=lambda: build_provider(settings)
    )


def make_research_handler(
    deps_factory: Callable[[], ResearchDependencies] = default_dependencies,
) -> Callable[[WorkflowContext], WorkflowResult]:
    def handler(ctx: WorkflowContext) -> WorkflowResult:
        return _Research(ctx, deps_factory()).run()

    return handler


class _Research:
    def __init__(self, ctx: WorkflowContext, deps: ResearchDependencies) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.deps = deps
        self.settings = deps.settings
        research = self.db.get(ResearchRun, ctx.run_id)
        if research is None or research.organization_id != ctx.organization_id:
            raise WorkflowError("Research run record is missing")
        company = self.db.get(Company, research.company_id)
        if company is None or company.organization_id != ctx.organization_id:
            raise WorkflowError("The company no longer exists")
        self.research = research
        self.company = company
        self._provider: LLMProvider | None = None
        self._provider_loaded = False

    # --- helpers -------------------------------------------------------------------------------

    @property
    def provider(self) -> LLMProvider | None:
        if not self._provider_loaded:
            self._provider, self._provider_loaded = self.deps.provider_factory(), True
        return self._provider

    def _record_usage(self, usage: LLMUsage) -> None:
        self.ctx.record_usage(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=usage.cost_usd
        )
        models = set(self.ctx.get_state("models_used", []))
        models.add(usage.model)
        self.ctx.set_state("models_used", sorted(models))

    def _last_attempt(self) -> bool:
        return self.ctx.run.attempts >= self.ctx.run.max_attempts

    def _ai_failed(self, exc: LLMError, stage: str) -> None:
        """Transient AI errors are retried unless this is the last attempt; otherwise AI is marked failed."""
        if isinstance(exc, LLMTransientError) and not self._last_attempt():
            raise TransientWorkflowError("The AI provider is temporarily unavailable; the run will retry.") from exc
        log.warning("research.ai_failed", stage=stage, error_type=type(exc).__name__)
        self.ctx.set_state("ai_status", "failed")
        self.ctx.set_state("ai_message", f"AI {stage} failed: {exc}")

    def _budget_left(self) -> bool:
        if self.ctx.spent_usd() >= self.settings.llm_max_cost_per_run_usd:
            self.ctx.set_state("ai_status", "skipped")
            self.ctx.set_state("ai_message", "AI analysis skipped: the per-run cost limit was reached.")
            return False
        return True

    def _sources(self) -> list[ResearchSource]:
        return list(
            self.db.scalars(
                select(ResearchSource)
                .where(ResearchSource.research_run_id == self.research.workflow_run_id)
                .order_by(ResearchSource.retrieved_at, ResearchSource.source_url)
            )
        )

    def _save_source(
        self,
        url: str,
        category: str,
        *,
        status: str,
        http_status: int | None = None,
        error: str | None = None,
        page: Any = None,
    ) -> ResearchSource:
        source = ResearchSource(
            organization_id=self.company.organization_id,
            research_run_id=self.research.workflow_run_id,
            company_id=self.company.id,
            source_url=url[:2048],
            page_category=category,
            http_status=http_status,
            extraction_status=status,
            extraction_error=error[:500] if error else None,
            page_title=page.title if page else None,
            content_hash=page.content_hash if page else None,
            extracted_text=page.text if page else "",
        )
        self.db.add(source)
        self.db.flush()
        if page is not None:
            signals = dict(self.ctx.get_state("signals", {}))
            signals[str(source.id)] = [[s.evidence_type.value, s.observed_fact, s.excerpt] for s in page.signals]
            self.ctx.set_state("signals", signals)
        return source

    def _fetch(self, fetcher: SafeFetcher, url: str) -> FetchedPage:
        return fetcher.get(url)

    # --- workflow ------------------------------------------------------------------------------

    def run(self) -> WorkflowResult:
        steps: dict[str, Callable[[], None]] = {
            "validate_input": self.validate_input,
            "fetch_website": self.fetch_website,
            "discover_relevant_pages": self.discover_relevant_pages,
            "extract_information": self.extract_information,
            "save_evidence": self.save_evidence,
            "ai_opportunity_audit": self.ai_opportunity_audit,
            "persist_results": self.persist_results,
        }
        fetcher = None
        try:
            for name, progress in STEPS:
                done: list[str] = list(self.ctx.get_state("done_steps", []))
                if name in done:
                    continue
                self.ctx.checkpoint(name, progress)
                if name in ("fetch_website", "discover_relevant_pages"):
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

        ai_status = self.research.ai_status
        summary = {
            "pages_fetched": self.research.pages_fetched,
            "evidence": len(self.ctx.get_state("evidence_ids", [])),
            "opportunities": self.ctx.get_state("opportunity_count", 0),
            "ai_status": ai_status,
            "dropped_unsupported": len(self.ctx.get_state("extraction_dropped", []))
            + len(self.ctx.get_state("audit_dropped", [])),
        }
        partial = ai_status != "completed"
        message = self.ctx.get_state("ai_message") if partial else None
        return WorkflowResult(summary=summary, partial=partial, message=message)

    def validate_input(self) -> None:
        if not self.company.website_url:
            raise WorkflowError("The company has no website to research.")
        try:
            website = parse_website(self.company.website_url)
        except InvalidWebsite as exc:
            raise WorkflowError(f"Invalid website: {exc}") from exc
        self.ctx.set_state("homepage", website.url)
        self.ctx.set_state("site_domain", website.canonical_domain)
        self.ctx.set_state("prompt_versions", {"extraction": EXTRACTION_PROMPT_VERSION, "audit": AUDIT_PROMPT_VERSION})

    def _robots(self, origin: str) -> RobotsPolicy:
        return load_robots(self._fetcher, origin, self.settings.research_robots_token)

    def fetch_website(self) -> None:
        homepage: str = self.ctx.get_state("homepage")
        if any(s.page_category == "home" for s in self._sources()):
            return
        try:
            robots = self._robots(homepage)
            if not robots.allows(self.settings.research_robots_token, homepage):
                raise WorkflowError("The website's robots.txt does not allow automated research.")
            page = self._fetch(self._fetcher, homepage)
        except BlockedDestination as exc:
            raise WorkflowError(f"The website was blocked for safety reasons: {exc}") from exc
        except FetchError as exc:
            if exc.transient:
                raise TransientWorkflowError(f"Could not load the website: {exc}") from exc
            raise WorkflowError(f"Could not load the website: {exc}") from exc
        if page.status == 429 or page.status >= 500:
            raise TransientWorkflowError(f"The website returned HTTP {page.status}.")
        if not page.ok:
            raise WorkflowError(f"The website returned HTTP {page.status}.")
        if not page.is_html:
            raise WorkflowError("The website did not return an HTML page.")
        content = extract_page(page.body, page.url, max_chars=self.settings.research_max_text_chars)
        final_domain = canonical_domain(urlsplit(page.url).hostname or "")
        self.ctx.set_state("site_domain", final_domain)
        self.ctx.set_state("home_links", [[link.url, link.text] for link in content.links[:MAX_LINKS_KEPT]])
        self.ctx.set_state(
            "home_meta",
            {"title": content.title, "site_name": content.site_name, "description": content.description},
        )
        self._save_source(
            page.url,
            "home",
            status="extracted" if content.text else "empty",
            http_status=page.status,
            page=content,
        )

    def discover_relevant_pages(self) -> None:
        from aigentix.modules.lead_intelligence.integrations.html import Link

        domain: str = self.ctx.get_state("site_domain")
        links = [Link(url=u, text=t) for u, t in self.ctx.get_state("home_links", [])]
        candidates = discover_relevant_links(links, domain=domain, limit=self.settings.research_max_pages - 1)
        existing = {s.source_url for s in self._sources()}
        homepage: str = self.ctx.get_state("homepage")
        try:
            robots = self._robots(homepage)
        except FetchError as exc:
            if exc.transient:
                raise TransientWorkflowError(f"Could not load robots.txt: {exc}") from exc
            raise WorkflowError(f"Could not load robots.txt: {exc}") from exc
        delay = min(robots.crawl_delay or 0.0, _CRAWL_DELAY_CAP_SECONDS)
        for index, (url, category) in enumerate(candidates):
            if url in existing:
                continue
            # Heartbeat, cancellation point and commit of the previous page.
            self.ctx.checkpoint("discover_relevant_pages", 20 + int(30 * index / max(len(candidates), 1)))
            if not robots.allows(self.settings.research_robots_token, url):
                self._save_source(url, category, status="skipped", error="Disallowed by robots.txt")
                continue
            if delay:
                time.sleep(delay)
            try:
                page = self._fetch(self._fetcher, url)
            except FetchError as exc:  # one bad page does not fail the run
                self._save_source(url, category, status="failed", error=str(exc))
                continue
            if not page.ok or not page.is_html:
                self._save_source(
                    url,
                    category,
                    status="failed",
                    http_status=page.status,
                    error=f"HTTP {page.status}" if not page.ok else "Not an HTML page",
                )
                continue
            final = urlsplit(page.url)
            if canonical_domain(final.hostname or "") != domain:
                self._save_source(
                    url,
                    category,
                    status="skipped",
                    http_status=page.status,
                    error="Redirected to another website",
                )
                continue
            content = extract_page(page.body, page.url, max_chars=self.settings.research_max_text_chars)
            self._save_source(
                url,
                category,
                status="extracted" if content.text else "empty",
                http_status=page.status,
                page=content,
            )
        self.research.pages_fetched = sum(1 for s in self._sources() if s.extraction_status in ("extracted", "empty"))

    def extract_information(self) -> None:
        sources = [s for s in self._sources() if s.extraction_status == "extracted"]
        provider = self.provider
        if provider is None:
            self.ctx.set_state("ai_status", "unavailable")
            self.ctx.set_state("ai_message", "AI analysis unavailable: no AI provider is configured.")
            return
        if not sources or not self._budget_left():
            return
        prompt_sources = [
            PromptSource(
                label=f"S{i}",
                source_id=s.id,
                url=s.source_url,
                category=s.page_category,
                title=s.page_title,
                text=s.extracted_text,
            )
            for i, s in enumerate(sources, start=1)
        ]
        try:
            result = run_extraction(
                provider,
                prompt_sources,
                company_domain=self.ctx.get_state("site_domain"),
                max_repairs=self.settings.llm_max_repairs,
                record_usage=self._record_usage,
            )
        except LLMError as exc:
            self._ai_failed(exc, "extraction")
            return
        self.ctx.set_state("llm_company_name", result.company_name)
        self.ctx.set_state("unknown_fields", result.unknown_fields)
        self.ctx.set_state("extraction_dropped", result.dropped)
        self.ctx.set_state(
            "llm_assertions",
            [
                {
                    "field": a.field,
                    "value": a.value,
                    "basis": a.basis,
                    "confidence": a.confidence,
                    "source_id": str(a.source_id),
                    "excerpt": a.excerpt,
                }
                for a in result.assertions
            ],
        )

    def save_evidence(self) -> None:
        run_id = self.research.workflow_run_id
        # Replace this run's evidence (and dependent opportunities) atomically: retries never duplicate.
        self.db.execute(delete(Opportunity).where(Opportunity.research_run_id == run_id))
        self.db.execute(delete(Evidence).where(Evidence.research_run_id == run_id))
        org = self.company.organization_id
        rows: list[Evidence] = []
        seen: set[tuple[str, str]] = set()
        for source_id, signals in self.ctx.get_state("signals", {}).items():
            for evidence_type, fact, excerpt in signals:
                key = (evidence_type, fact)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    Evidence(
                        organization_id=org,
                        research_run_id=run_id,
                        company_id=self.company.id,
                        source_id=uuid.UUID(source_id),
                        observed_fact=fact[:2000],
                        supporting_excerpt=excerpt[:1000],
                        evidence_type=evidence_type,
                        basis=Basis.OBSERVED.value,
                        confidence=Confidence.HIGH.value,
                        origin="deterministic",
                    )
                )
        assertions = [
            VerifiedAssertion(**{**a, "source_id": uuid.UUID(a["source_id"])})
            for a in self.ctx.get_state("llm_assertions", [])
        ]
        for a in assertions:
            rows.append(
                Evidence(
                    organization_id=org,
                    research_run_id=run_id,
                    company_id=self.company.id,
                    source_id=a.source_id,
                    observed_fact=a.value[:2000],
                    supporting_excerpt=a.excerpt[:1000],
                    evidence_type=a.evidence_type.value,
                    basis=a.basis,
                    confidence=a.confidence,
                    origin="llm",
                )
            )
        self.db.add_all(rows)
        self.db.flush()
        self.ctx.set_state("evidence_ids", [str(e.id) for e in rows])
        self.research.profile = self._build_profile(rows, assertions)
        self._update_company(assertions)

    def _build_profile(self, evidence: list[Evidence], assertions: list[VerifiedAssertion]) -> dict[str, Any]:
        meta = self.ctx.get_state("home_meta", {}) or {}
        by_excerpt = {(e.source_id, e.supporting_excerpt, e.observed_fact): e.id for e in evidence}
        fields: dict[str, list[dict[str, Any]]] = {}
        for a in assertions:
            fields.setdefault(a.field, []).append(
                {
                    "value": a.value,
                    "basis": a.basis,
                    "confidence": a.confidence,
                    "evidence_id": str(by_excerpt.get((a.source_id, a.excerpt[:1000], a.value[:2000]), "")) or None,
                }
            )
        signals = sorted({e.evidence_type for e in evidence if e.origin == "deterministic"})
        all_fields = (
            "description",
            "industry",
            "service",
            "target_customer",
            "business_model",
            "customer_interaction",
            "document_workflow",
            "operational_signal",
            "location",
        )
        return {
            "name": self.ctx.get_state("llm_company_name")
            or meta.get("site_name")
            or name_from_title(meta.get("title"))
            or self.company.name,
            "website_title": meta.get("title"),
            "website_description": meta.get("description"),
            "fields": fields,
            "unknown_fields": sorted(
                (set(self.ctx.get_state("unknown_fields", [])) | {f for f in all_fields if f not in fields})
                - ({"description"} if meta.get("description") else set())
            ),
            "observed_signals": signals,
            "generated_by": {
                "deterministic_parser": "html-v1",
                "models": self.ctx.get_state("models_used", []),
                "prompt_versions": self.ctx.get_state("prompt_versions", {}),
            },
        }

    def _update_company(self, assertions: list[VerifiedAssertion]) -> None:
        rank = {"high": 3, "medium": 2, "low": 1}

        def best(field: str) -> str | None:
            candidates = [a for a in assertions if a.field == field and a.basis == "observed"] or [
                a for a in assertions if a.field == field and a.confidence != "low"
            ]
            return max(candidates, key=lambda a: rank[a.confidence]).value if candidates else None

        meta = self.ctx.get_state("home_meta", {}) or {}
        description = best("description") or meta.get("description")
        if description:
            self.company.short_description = description[:1000]
        if industry := best("industry"):
            self.company.industry = industry[:200]
        if location := best("location"):
            self.company.location = location[:200]
        name = self.ctx.get_state("llm_company_name") or meta.get("site_name") or name_from_title(meta.get("title"))
        if name and self.company.name == self.company.canonical_domain:
            self.company.name = str(name)[:200]

    def ai_opportunity_audit(self) -> None:
        provider = self.provider
        if self.ctx.get_state("ai_status") in ("unavailable", "failed", "skipped") or provider is None:
            if provider is None:
                self.ctx.set_state("ai_status", "unavailable")
                self.ctx.set_state("ai_message", "AI analysis unavailable: no AI provider is configured.")
            return
        if not self._budget_left():
            return
        ids = [uuid.UUID(i) for i in self.ctx.get_state("evidence_ids", [])]
        evidence = list(self.db.scalars(select(Evidence).where(Evidence.id.in_(ids)))) if ids else []
        evidence.sort(
            key=lambda e: (
                EvidenceType(e.evidence_type) not in _STRUCTURAL_TYPES,
                e.basis != "observed",
                str(e.id),
            )
        )
        evidence = evidence[:MAX_EVIDENCE_FOR_AUDIT]
        urls = {s.id: s.source_url for s in self._sources()}
        prompt_evidence = [
            PromptEvidence(
                label=f"E{i}",
                evidence_id=e.id,
                evidence_type=e.evidence_type,
                observed_fact=e.observed_fact,
                excerpt=e.supporting_excerpt,
                basis=e.basis,
                confidence=e.confidence,
                source_url=urls.get(e.source_id, ""),
            )
            for i, e in enumerate(evidence, start=1)
        ]
        profile = {
            k: v
            for k, v in self.research.profile.items()
            if k in ("name", "fields", "unknown_fields", "observed_signals")
        }
        try:
            result = run_audit(
                provider,
                profile,
                prompt_evidence,
                company_domain=self.ctx.get_state("site_domain"),
                max_repairs=self.settings.llm_max_repairs,
                record_usage=self._record_usage,
            )
        except LLMError as exc:
            self._ai_failed(exc, "opportunity audit")
            return
        self.ctx.set_state("ai_status", "completed")
        self.ctx.set_state("audit_summary", result.summary)
        self.ctx.set_state("audit_dropped", result.dropped)
        self.ctx.set_state(
            "audit_opportunities",
            [
                {
                    "title": o.title,
                    "observed_context": o.observed_context,
                    "problem_hypothesis": o.problem_hypothesis,
                    "proposed_ai_solution": o.proposed_ai_solution,
                    "estimated_business_impact": o.estimated_business_impact,
                    "implementation_complexity": o.implementation_complexity,
                    "confidence": o.confidence,
                    "assumptions": o.assumptions,
                    "validation_questions": o.validation_questions,
                    "next_step": o.next_step,
                    "evidence_ids": [str(i) for i in o.evidence_ids],
                    "quality_flags": o.quality_flags,
                }
                for o in result.opportunities
            ],
        )

    def persist_results(self) -> None:
        run_id = self.research.workflow_run_id
        org = self.company.organization_id
        self.db.execute(delete(Opportunity).where(Opportunity.research_run_id == run_id))
        proposals: list[dict[str, Any]] = self.ctx.get_state("audit_opportunities", [])
        for p in proposals:
            opportunity = Opportunity(
                organization_id=org,
                research_run_id=run_id,
                company_id=self.company.id,
                **{k: v for k, v in p.items() if k != "evidence_ids"},
            )
            self.db.add(opportunity)
            self.db.flush()
            self.db.add_all(
                OpportunityEvidence(opportunity_id=opportunity.id, evidence_id=uuid.UUID(eid), organization_id=org)
                for eid in p["evidence_ids"]
            )
        self.ctx.set_state("opportunity_count", len(proposals))
        self.research.ai_status = self.ctx.get_state("ai_status") or "unavailable"
        self.research.audit_summary = self.ctx.get_state("audit_summary") or self.ctx.get_state("ai_message")
        self.db.flush()
