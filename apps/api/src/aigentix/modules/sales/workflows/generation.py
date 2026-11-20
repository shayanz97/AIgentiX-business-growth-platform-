"""Sales AI workflows, executed by the platform worker.

sales.brief_generation:    LOAD_INPUTS → GENERATE_BRIEF → SAVE_BRIEF
sales.proposal_generation: LOAD_INPUTS → GENERATE_PROPOSAL → SAVE_REVISION

Both are single-output and idempotent: a resumed run whose record is no longer `generating` returns at once, and
the AI revision is inserted only if it does not exist. AI problems never fabricate output: no provider, no key,
the per-run cost cap or an invalid answer mark the brief / proposal `failed` with a user-safe message and end the
run `partial`; transient outages are retried (on the last attempt they fail the record the same way). Model spend
is recorded on every call. Lead data is read only through aigentix.platform.leads.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from aigentix.core.db import utcnow
from aigentix.core.logging import get_logger
from aigentix.modules.sales.agents.llm import BRIEF_TASK, PROPOSAL_TASK, build_sales_provider
from aigentix.modules.sales.agents.prompts import BRIEF_PROMPT_VERSION, PROPOSAL_PROMPT_VERSION
from aigentix.modules.sales.agents.proposal_assistant import (
    OfferingTerms,
    ProposalInputs,
    ValidatedProposal,
    brief_view,
    run_proposal,
)
from aigentix.modules.sales.agents.sales_intelligence import (
    STALE_AFTER,
    OfferingInfo,
    PromptEvidence,
    ValidatedBrief,
    build_brief_inputs,
    run_brief,
    unknowns_only_brief,
)
from aigentix.modules.sales.config import SalesSettings, get_sales_settings
from aigentix.modules.sales.models import (
    BriefStatus,
    ProposalStatus,
    SalesBrief,
    SalesOpportunity,
    SalesProposal,
    SalesProposalRevision,
    SalesServiceOffering,
)
from aigentix.platform.leads import LeadDataProvider, LeadSnapshot, get_lead_data_provider
from aigentix.platform.llm import (
    LLMBudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    LLMTransientError,
    LLMUnavailable,
    LLMUsage,
    Task,
    max_output_tokens_within,
)
from aigentix.platform.workflows.context import WorkflowContext, WorkflowResult
from aigentix.platform.workflows.errors import TransientWorkflowError, WorkflowError

log = get_logger("aigentix.sales")

NO_PROVIDER = "AI unavailable: no provider configured"
_MIN_OUTPUT_TOKENS = 1_024


def _today() -> date:
    return utcnow().date()


@dataclass
class SalesAIDependencies:
    settings: SalesSettings
    provider_factory: Callable[[], LLMProvider | None]
    lead_data: Callable[[], LeadDataProvider] = get_lead_data_provider
    today: Callable[[], date] = field(default=_today)


def default_dependencies() -> SalesAIDependencies:
    settings = get_sales_settings()
    return SalesAIDependencies(settings=settings, provider_factory=lambda: build_sales_provider(settings))


def _task_available(provider: LLMProvider, task: Task) -> bool:
    """Routed providers know per task whether a key exists; test doubles are always available."""
    check = getattr(provider, "available", None)
    return bool(check(task)) if callable(check) else True


class _AIFailure(Exception):
    """The AI step cannot produce output; the record is marked failed with this (user-safe) message."""


class _Generation:
    def __init__(self, ctx: WorkflowContext, deps: SalesAIDependencies) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.deps = deps
        self.settings = deps.settings
        self.models: set[str] = set()

    def _record_usage(self, usage: LLMUsage) -> None:
        self.ctx.record_usage(
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=usage.cost_usd
        )
        self.models.add(usage.label)

    def _remaining_budget(self) -> Decimal:
        return self.settings.sales_llm_max_cost_per_run_usd - self.ctx.spent_usd()

    def _can_spend(self) -> bool:
        return self._remaining_budget() > 0

    def _last_attempt(self) -> bool:
        return self.ctx.run.attempts >= self.ctx.run.max_attempts

    def _prepare(self, provider: LLMProvider | None, task: Task, ceiling: int) -> tuple[LLMProvider, int]:
        if provider is None:
            raise _AIFailure(NO_PROVIDER)
        if not _task_available(provider, task):
            raise _AIFailure("AI unavailable: no API key is configured for this task's provider")
        tokens = max_output_tokens_within(self._remaining_budget(), provider.model_for(task), ceiling)
        if tokens < _MIN_OUTPUT_TOKENS:
            raise _AIFailure("AI stopped: the per-run cost limit was reached")
        return provider, tokens

    def _ai_error(self, exc: LLMError) -> _AIFailure:
        if isinstance(exc, LLMTransientError):
            if not self._last_attempt():
                raise TransientWorkflowError("The AI provider is temporarily unavailable; the run will retry.") from exc
            return _AIFailure("AI unavailable: the provider was temporarily unavailable; try again later")
        if isinstance(exc, LLMUnavailable):
            return _AIFailure(f"AI unavailable: {exc}")
        if isinstance(exc, LLMBudgetExceeded):
            return _AIFailure(f"AI stopped: {exc}")
        log.warning("sales.ai_failed", error_type=type(exc).__name__, run_id=str(self.ctx.run_id))
        if isinstance(exc, LLMInvalidOutput):
            return _AIFailure("AI output did not match the required format; nothing was saved")
        return _AIFailure("AI request failed; nothing was saved")

    @property
    def model_label(self) -> str | None:
        return ", ".join(sorted(self.models))[:120] or None

    def _deal(self, deal_id: Any) -> SalesOpportunity:
        deal = self.db.get(SalesOpportunity, deal_id)
        if deal is None or deal.organization_id != self.ctx.organization_id:
            raise WorkflowError("The sales opportunity no longer exists")
        return deal

    def _offerings(self) -> list[SalesServiceOffering]:
        return list(
            self.db.scalars(
                select(SalesServiceOffering)
                .where(
                    SalesServiceOffering.organization_id == self.ctx.organization_id,
                    SalesServiceOffering.active.is_(True),
                )
                .order_by(SalesServiceOffering.name)
            )
        )

    def _snapshot(self, deal: SalesOpportunity) -> LeadSnapshot | None:
        return self.deps.lead_data().snapshot(self.db, self.ctx.organization_id, deal.company_id)


def make_brief_handler(
    deps_factory: Callable[[], SalesAIDependencies] = default_dependencies,
) -> Callable[[WorkflowContext], WorkflowResult]:
    def handler(ctx: WorkflowContext) -> WorkflowResult:
        return _BriefGeneration(ctx, deps_factory()).run()

    return handler


def make_proposal_handler(
    deps_factory: Callable[[], SalesAIDependencies] = default_dependencies,
) -> Callable[[WorkflowContext], WorkflowResult]:
    def handler(ctx: WorkflowContext) -> WorkflowResult:
        return _ProposalGeneration(ctx, deps_factory()).run()

    return handler


class _BriefGeneration(_Generation):
    def run(self) -> WorkflowResult:
        brief_id = self.ctx.run.run_metadata.get("brief_id")
        brief = self.db.get(SalesBrief, brief_id) if brief_id else None
        if brief is None or brief.organization_id != self.ctx.organization_id:
            raise WorkflowError("The sales brief no longer exists")
        if brief.status != BriefStatus.GENERATING.value:  # resumed after the brief was saved
            return WorkflowResult(summary={"brief_id": str(brief.id), "status": brief.status})
        self.ctx.checkpoint("load_inputs", 10)
        deal = self._deal(brief.sales_opportunity_id)
        snapshot = self._snapshot(deal)
        if snapshot is None:
            self._fail(brief, "The company no longer exists; no brief can be generated.")
            self.db.commit()
            raise WorkflowError("The company no longer exists; no brief can be generated.")
        inputs = build_brief_inputs(
            snapshot,
            source_opportunity_id=deal.source_opportunity_id,
            requirements=list(deal.confirmed_requirements),
            offerings=[OfferingInfo(o.name, o.description, o.solution_category) for o in self._offerings()],
            today=self.deps.today(),
        )
        message: str | None = None
        try:
            provider, max_tokens = self._prepare(self.deps.provider_factory(), BRIEF_TASK, 8_000)
            if not inputs.evidence:
                result: ValidatedBrief = unknowns_only_brief(inputs)
                message = "No research evidence is available; the brief lists only what is unknown."
            else:
                self.ctx.checkpoint("generate_brief", 30)
                try:
                    result = run_brief(
                        provider,
                        inputs,
                        max_repairs=self.settings.sales_llm_max_repairs,
                        record_usage=self._record_usage,
                        max_tokens=max_tokens,
                        can_spend=self._can_spend,
                    )
                except LLMError as exc:
                    raise self._ai_error(exc) from exc
        except _AIFailure as failure:
            self._fail(brief, str(failure))
            return WorkflowResult(
                summary={"brief_id": str(brief.id), "status": "failed"}, partial=True, message=str(failure)
            )

        self.ctx.checkpoint("save_brief", 90)
        brief.content = result.content
        brief.quality_flags = result.quality_flags
        brief.source_evidence_ids = [str(i) for i in result.evidence_ids]
        brief.model = self.model_label
        brief.generation_version = BRIEF_PROMPT_VERSION
        brief.status = BriefStatus.DRAFT.value
        brief.message = message
        brief.updated_at = utcnow()
        # Older drafts of this deal are superseded now that the new one exists; approved briefs stay approved.
        self.db.execute(
            update(SalesBrief)
            .where(
                SalesBrief.organization_id == brief.organization_id,
                SalesBrief.sales_opportunity_id == brief.sales_opportunity_id,
                SalesBrief.status == BriefStatus.DRAFT.value,
                SalesBrief.id != brief.id,
                SalesBrief.created_at < brief.created_at,
            )
            .values(status=BriefStatus.SUPERSEDED.value, updated_at=utcnow(), version=SalesBrief.version + 1)
        )
        self.db.flush()
        summary = {
            "brief_id": str(brief.id),
            "status": brief.status,
            "evidence_cited": len(result.evidence_ids),
            "quality_flags": result.quality_flags,
        }
        return WorkflowResult(summary=summary, partial=message is not None, message=message)

    def _fail(self, brief: SalesBrief, message: str) -> None:
        brief.status = BriefStatus.FAILED.value
        brief.message = message
        brief.model = self.model_label
        brief.updated_at = utcnow()
        self.db.flush()


class _ProposalGeneration(_Generation):
    def run(self) -> WorkflowResult:
        proposal_id = self.ctx.run.run_metadata.get("proposal_id")
        proposal = self.db.get(SalesProposal, proposal_id) if proposal_id else None
        if proposal is None or proposal.organization_id != self.ctx.organization_id:
            raise WorkflowError("The proposal no longer exists")
        if proposal.status != ProposalStatus.GENERATING.value:
            return WorkflowResult(summary={"proposal_id": str(proposal.id), "status": proposal.status})
        self.ctx.checkpoint("load_inputs", 10)
        deal = self._deal(proposal.sales_opportunity_id)
        brief = self.db.get(SalesBrief, proposal.brief_id) if proposal.brief_id else None
        if brief is None or brief.organization_id != self.ctx.organization_id:
            self._fail(proposal, "The sales brief this proposal is based on no longer exists.")
            return WorkflowResult(summary={"proposal_id": str(proposal.id)}, partial=True, message=proposal.message)
        inputs = self._inputs(deal, brief)
        try:
            provider, max_tokens = self._prepare(self.deps.provider_factory(), PROPOSAL_TASK, 12_000)
            self.ctx.checkpoint("generate_proposal", 30)
            try:
                result: ValidatedProposal = run_proposal(
                    provider,
                    inputs,
                    max_repairs=self.settings.sales_llm_max_repairs,
                    record_usage=self._record_usage,
                    max_tokens=max_tokens,
                    can_spend=self._can_spend,
                )
            except LLMError as exc:
                raise self._ai_error(exc) from exc
        except _AIFailure as failure:
            self._fail(proposal, str(failure))
            return WorkflowResult(
                summary={"proposal_id": str(proposal.id), "status": "failed"}, partial=True, message=str(failure)
            )

        self.ctx.checkpoint("save_revision", 90)
        exists = self.db.scalar(
            select(SalesProposalRevision.id).where(
                SalesProposalRevision.proposal_id == proposal.id, SalesProposalRevision.revision == 1
            )
        )
        if exists is None:
            self.db.add(
                SalesProposalRevision(
                    organization_id=proposal.organization_id,
                    proposal_id=proposal.id,
                    revision=1,
                    origin="ai",
                    sections=result.sections,
                    assumptions=result.assumptions,
                    quality_flags=result.quality_flags,
                    source_evidence_ids=[str(i) for i in result.evidence_ids],
                    model=self.model_label,
                    generation_version=PROPOSAL_PROMPT_VERSION,
                    created_by_user_id=proposal.created_by_user_id,
                )
            )
        proposal.current_revision = 1
        proposal.status = ProposalStatus.DRAFT.value  # always a draft: only a person marks it ready or sent
        proposal.message = None
        proposal.version += 1
        proposal.updated_at = utcnow()
        self.db.flush()
        needs_input = [s["key"] for s in result.sections if s["status"] == "needs_input"]
        return WorkflowResult(
            summary={
                "proposal_id": str(proposal.id),
                "status": proposal.status,
                "sections_needing_input": needs_input,
                "quality_flags": result.quality_flags,
            }
        )

    def _inputs(self, deal: SalesOpportunity, brief: SalesBrief) -> ProposalInputs:
        snapshot = self._snapshot(deal)
        today = self.deps.today()
        wanted = set(brief.source_evidence_ids)
        evidence: list[PromptEvidence] = []
        for item in snapshot.evidence if snapshot else []:
            if str(item.id) not in wanted:
                continue
            evidence.append(
                PromptEvidence(
                    label=f"E{len(evidence) + 1}",
                    evidence_id=item.id,
                    evidence_type=item.evidence_type,
                    fact=item.observed_fact,
                    excerpt=item.excerpt,
                    source_url=item.source_url,
                    retrieved_at=item.retrieved_at,
                    basis=item.basis,
                    origin=item.origin,
                    stale=item.retrieved_at is not None and item.retrieved_at.date() < today - STALE_AFTER,
                )
            )
        view, hypotheses = brief_view(
            brief.content, brief.edited_content, {str(e.evidence_id): e.label for e in evidence}
        )
        return ProposalInputs(
            company={
                "name": snapshot.name if snapshot else None,
                "domain": snapshot.canonical_domain if snapshot else None,
            },
            company_domain=snapshot.canonical_domain if snapshot else None,
            brief=view,
            hypotheses=hypotheses,
            evidence=evidence,
            requirements=list(deal.confirmed_requirements),
            offerings=[
                OfferingTerms(
                    name=o.name,
                    description=o.description,
                    solution_category=o.solution_category,
                    price_amount=o.price_amount,
                    price_unit=o.price_unit,
                    currency=o.currency,
                    price_approved=o.price_approved,
                )
                for o in self._offerings()
            ],
        )

    def _fail(self, proposal: SalesProposal, message: str) -> None:
        proposal.status = ProposalStatus.FAILED.value
        proposal.message = message
        proposal.version += 1
        proposal.updated_at = utcnow()
        self.db.flush()
