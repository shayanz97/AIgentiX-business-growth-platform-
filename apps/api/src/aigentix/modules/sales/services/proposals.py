"""Proposals: request an AI draft (worker workflow), list, read, human revisions, status, Markdown export.

Revisions are immutable: every human edit saves a new revision. Status changes are human actions only —
draft ↔ ready, ready → sent (the user confirms when they sent it outside AIgentiX; this records the
`proposal_sent` activity that unlocks the pipeline stage), sent → accepted | declined. AIgentiX sends nothing.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.core.db import utcnow
from aigentix.core.errors import InvalidInput, NotFound
from aigentix.modules.sales.agents.proposal_assistant import SECTION_KEYS
from aigentix.modules.sales.config import get_sales_settings
from aigentix.modules.sales.models import (
    ActivityType,
    BriefStatus,
    DealStatus,
    ProposalStatus,
    SalesActivity,
    SalesBrief,
    SalesOpportunity,
    SalesProposal,
    SalesProposalRevision,
)
from aigentix.modules.sales.services.briefs import effective_brief_status, run_ended_without_result, runs_by_id
from aigentix.modules.sales.services.common import audit, check_version, get_deal, touch
from aigentix.modules.sales.workflows.constants import PROPOSAL_WORKFLOW
from aigentix.platform.leads import get_lead_data_provider
from aigentix.platform.llm.safety import neutralise_markup
from aigentix.platform.organizations.service import TenantContext
from aigentix.platform.workflows import service as workflows
from aigentix.platform.workflows.models import WorkflowRun
from aigentix.platform.workflows.registry import default_registry

TRANSITIONS: dict[str, frozenset[str]] = {
    ProposalStatus.DRAFT.value: frozenset({ProposalStatus.READY.value}),
    ProposalStatus.READY.value: frozenset({ProposalStatus.DRAFT.value, ProposalStatus.SENT.value}),
    ProposalStatus.SENT.value: frozenset({ProposalStatus.ACCEPTED.value, ProposalStatus.DECLINED.value}),
}
_EDITABLE = (ProposalStatus.DRAFT.value, ProposalStatus.READY.value)
_CLOCK_SKEW = timedelta(minutes=5)


def effective_proposal_status(proposal: SalesProposal, run: WorkflowRun | None) -> tuple[str, str | None]:
    if proposal.status == ProposalStatus.GENERATING.value and run_ended_without_result(run):
        return ProposalStatus.FAILED.value, proposal.message or (run.error_message if run else None)
    return proposal.status, proposal.message


def _choose_brief(db: Session, tenant: TenantContext, deal_id: uuid.UUID, brief_id: uuid.UUID | None) -> SalesBrief:
    if brief_id is not None:
        brief = db.scalar(
            select(SalesBrief).where(SalesBrief.id == brief_id, SalesBrief.organization_id == tenant.organization_id)
        )
        if brief is None or brief.sales_opportunity_id != deal_id:
            raise NotFound("Sales brief not found")
        runs = runs_by_id(db, tenant, [brief.workflow_run_id])
        status, _ = effective_brief_status(brief, runs.get(brief.workflow_run_id) if brief.workflow_run_id else None)
        if status not in (BriefStatus.DRAFT.value, BriefStatus.APPROVED.value):
            raise InvalidInput(f"A {status} brief cannot be used for a proposal")
        return brief
    for status in (BriefStatus.APPROVED.value, BriefStatus.DRAFT.value):
        brief = db.scalar(
            select(SalesBrief)
            .where(
                SalesBrief.organization_id == tenant.organization_id,
                SalesBrief.sales_opportunity_id == deal_id,
                SalesBrief.status == status,
            )
            .order_by(SalesBrief.created_at.desc(), SalesBrief.id.desc())
            .limit(1)
        )
        if brief is not None:
            return brief
    raise InvalidInput("Generate a sales brief first: proposals are drafted from an approved or draft brief")


def request_proposal(
    db: Session, tenant: TenantContext, deal_id: uuid.UUID, *, brief_id: uuid.UUID | None, title: str | None
) -> SalesProposal:
    deal = get_deal(db, tenant, deal_id, for_update=True)
    if deal.status != DealStatus.OPEN.value:
        raise InvalidInput("The deal is closed; proposals can only be drafted for open deals")
    brief = _choose_brief(db, tenant, deal.id, brief_id)
    proposal = SalesProposal(
        organization_id=tenant.organization_id,
        sales_opportunity_id=deal.id,
        brief_id=brief.id,
        title=(title or f"Proposal: {deal.title}")[:200],
        status=ProposalStatus.GENERATING.value,
        current_revision=0,
        created_by_user_id=tenant.user.id,
    )
    db.add(proposal)
    db.flush()
    run = workflows.enqueue(
        db,
        tenant,
        workflow_type=PROPOSAL_WORKFLOW,
        registry=default_registry(),
        metadata={"proposal_id": str(proposal.id)},
        max_attempts=get_sales_settings().sales_max_attempts,
    )
    proposal.workflow_run_id = run.id
    audit(db, tenant, deal, "Proposal draft requested", proposal_id=str(proposal.id), brief_id=str(brief.id))
    db.flush()
    return proposal


def get_proposal(
    db: Session, tenant: TenantContext, proposal_id: uuid.UUID, *, for_update: bool = False
) -> SalesProposal:
    query = select(SalesProposal).where(
        SalesProposal.id == proposal_id, SalesProposal.organization_id == tenant.organization_id
    )
    proposal = db.scalar(query.with_for_update() if for_update else query)
    if proposal is None:
        raise NotFound("Proposal not found")
    return proposal


def list_proposals(db: Session, tenant: TenantContext, deal_id: uuid.UUID) -> list[SalesProposal]:
    get_deal(db, tenant, deal_id)
    return list(
        db.scalars(
            select(SalesProposal)
            .where(
                SalesProposal.organization_id == tenant.organization_id, SalesProposal.sales_opportunity_id == deal_id
            )
            .order_by(SalesProposal.created_at.desc(), SalesProposal.id.desc())
        )
    )


def current_revision(db: Session, proposal: SalesProposal) -> SalesProposalRevision | None:
    if proposal.current_revision < 1:
        return None
    return db.scalar(
        select(SalesProposalRevision).where(
            SalesProposalRevision.organization_id == proposal.organization_id,
            SalesProposalRevision.proposal_id == proposal.id,
            SalesProposalRevision.revision == proposal.current_revision,
        )
    )


def list_revisions(db: Session, tenant: TenantContext, proposal_id: uuid.UUID) -> list[SalesProposalRevision]:
    proposal = get_proposal(db, tenant, proposal_id)
    return list(
        db.scalars(
            select(SalesProposalRevision)
            .where(
                SalesProposalRevision.organization_id == tenant.organization_id,
                SalesProposalRevision.proposal_id == proposal.id,
            )
            .order_by(SalesProposalRevision.revision.desc())
        )
    )


def _section_status(body: str, requested: str | None) -> str:
    if requested is not None:
        return requested
    return "needs_input" if "[TO BE CONFIRMED" in body or "[PRICE TO BE CONFIRMED" in body or not body else "draft"


def update_proposal(
    db: Session,
    tenant: TenantContext,
    proposal_id: uuid.UUID,
    *,
    expected_version: int,
    title: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
    note: str | None = None,
    status: str | None = None,
    sent_at: datetime | None = None,
) -> SalesProposal:
    proposal = get_proposal(db, tenant, proposal_id, for_update=True)
    check_version(proposal.version, expected_version)
    deal = get_deal(db, tenant, proposal.sales_opportunity_id, for_update=True)
    edits_content = title is not None or sections is not None or assumptions is not None
    if proposal.status in (ProposalStatus.GENERATING.value, ProposalStatus.FAILED.value):
        raise InvalidInput(f"A {proposal.status} proposal cannot be changed")
    if edits_content and proposal.status not in _EDITABLE:
        raise InvalidInput("A sent proposal cannot be edited; draft a new proposal instead")
    if sent_at is not None and status != ProposalStatus.SENT.value:
        raise InvalidInput("sent_at is only recorded when marking the proposal as sent")
    if note is not None and sections is None and assumptions is None:
        raise InvalidInput("A note describes a revision; include the changed sections or assumptions")

    changed = False
    if title is not None and title != proposal.title:
        proposal.title = title
        changed = True
    if sections is not None or assumptions is not None:
        _new_revision(db, tenant, proposal, sections or [], assumptions, note)
        changed = True
    if status is not None and status != proposal.status:
        _transition(db, tenant, proposal, deal, status, sent_at)
        changed = True
    if changed:
        proposal.version += 1
        proposal.updated_at = utcnow()
    db.flush()
    return proposal


def _new_revision(
    db: Session,
    tenant: TenantContext,
    proposal: SalesProposal,
    edits: list[dict[str, Any]],
    assumptions: list[str] | None,
    note: str | None,
) -> None:
    previous = current_revision(db, proposal)
    if previous is None:
        raise InvalidInput("The proposal has no saved draft yet")
    by_key = {s["key"]: dict(s) for s in previous.sections}
    seen: set[str] = set()
    for edit in edits:
        key = edit["key"]
        if key not in SECTION_KEYS:
            raise InvalidInput("Unknown proposal section")
        if key in seen:
            raise InvalidInput("Each section can be edited once per change")
        seen.add(key)
        section = by_key[key]
        section["body"] = edit["body"]
        if edit.get("title"):
            section["title"] = edit["title"]
        section["status"] = _section_status(edit["body"], edit.get("status"))
    db.add(
        SalesProposalRevision(
            organization_id=proposal.organization_id,
            proposal_id=proposal.id,
            revision=proposal.current_revision + 1,
            origin="human",
            sections=[by_key[k] for k in SECTION_KEYS if k in by_key],
            assumptions=list(assumptions) if assumptions is not None else list(previous.assumptions),
            quality_flags=list(previous.quality_flags),
            source_evidence_ids=list(previous.source_evidence_ids),
            note=note,
            created_by_user_id=tenant.user.id,
        )
    )
    proposal.current_revision += 1


def _transition(
    db: Session,
    tenant: TenantContext,
    proposal: SalesProposal,
    deal: SalesOpportunity,
    status: str,
    sent_at: datetime | None,
) -> None:
    allowed = TRANSITIONS.get(proposal.status, frozenset())
    if status not in allowed:
        options = ", ".join(sorted(allowed)) or "none"
        raise InvalidInput(f"Cannot change a {proposal.status} proposal to {status}. Allowed: {options}.")
    if status == ProposalStatus.SENT.value:
        if deal.status != "open":
            raise InvalidInput("The deal is closed; reopen it before recording that a proposal was sent")
        if sent_at is None:
            raise InvalidInput("Confirm when you sent the proposal (sent_at); AIgentiX does not send it")
        if sent_at.tzinfo is None:
            raise InvalidInput("sent_at needs a time zone")
        if sent_at > utcnow() + _CLOCK_SKEW:
            raise InvalidInput("sent_at cannot be in the future")
        proposal.sent_at = sent_at
        db.add(
            SalesActivity(
                organization_id=proposal.organization_id,
                sales_opportunity_id=deal.id,
                activity_type=ActivityType.PROPOSAL_SENT.value,
                description=f"Proposal marked as sent: {proposal.title}",
                details={"proposal_id": str(proposal.id), "revision": proposal.current_revision},
                created_by_user_id=tenant.user.id,
                occurred_at=sent_at,
            )
        )
        touch(deal)
    else:
        audit(db, tenant, deal, f"Proposal marked as {status}", proposal_id=str(proposal.id))
    proposal.status = status


# --- export -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkdownExport:
    filename: str
    content: str


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*(?!https?://)[^)]*\)", re.I)
_BARE_SCHEME = re.compile(r"(?i)\b(?:javascript|data|vbscript|file):")


def _md(text: str) -> str:
    """Safe Markdown: no HTML (tags neutralised), no images (tracking pixels), no non-http(s) links."""
    text = neutralise_markup(text)
    text = _MD_IMAGE.sub(lambda m: m.group(1), text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    return _BARE_SCHEME.sub("", text)


def export_markdown(db: Session, tenant: TenantContext, proposal_id: uuid.UUID) -> MarkdownExport:
    proposal = get_proposal(db, tenant, proposal_id)
    revision = current_revision(db, proposal)
    if revision is None:
        raise InvalidInput("The proposal has no saved draft yet")
    deal = get_deal(db, tenant, proposal.sales_opportunity_id)
    company = get_lead_data_provider().company_names(db, tenant.organization_id, {deal.company_id}).get(deal.company_id)
    lines = [
        f"# {_md(proposal.title)}",
        "",
        "> Draft — verify before sending. Prepared with AI assistance and reviewed by people; check every statement,",
        "> price and date with the customer's situation. AIgentiX does not send proposals.",
        "",
        f"- Company: {_md(company.name) if company else 'unknown'}",
        f"- Status: {proposal.status} · revision {revision.revision} ({revision.origin})",
    ]
    if revision.model:
        lines.append(f"- Draft model: {_md(revision.model)} · prompt {_md(revision.generation_version or '')}")
    for section in revision.sections:
        lines += ["", f"## {_md(str(section.get('title', section['key'])))}"]
        if section.get("status") == "needs_input":
            lines.append("_Needs input before sending._")
        lines += ["", _md(str(section.get("body", "")))]
    if revision.assumptions:
        lines += ["", "## Assumptions to confirm", ""] + [f"- {_md(a)}" for a in revision.assumptions]
    if revision.quality_flags:
        lines += [
            "",
            "---",
            "",
            "Automatic checks removed or marked content in the AI draft: "
            + ", ".join(_md(f) for f in revision.quality_flags)
            + ".",
        ]
    slug = re.sub(r"[^a-z0-9]+", "-", proposal.title.lower()).strip("-")[:60] or "proposal"
    return MarkdownExport(filename=f"{slug}-r{revision.revision}.md", content="\n".join(lines) + "\n")
