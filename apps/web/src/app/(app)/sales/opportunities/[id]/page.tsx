"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ActivityPanel } from "@/components/sales/activity-panel";
import { BriefPanel } from "@/components/sales/brief-panel";
import { PermissionBadges, RestrictionBadge } from "@/components/sales/contact-badges";
import { DealEditForm } from "@/components/sales/deal-edit-form";
import { DealPriorityBadge, DealStatusBadge, StageBadge } from "@/components/sales/deal-badges";
import { DealTasksPanel } from "@/components/sales/deal-tasks-panel";
import { LeadSummaryCard } from "@/components/sales/lead-summary-card";
import { ProposalPanel } from "@/components/sales/proposal-panel";
import { StageControls } from "@/components/sales/stage-controls";
import { RequireOrganization } from "@/components/require-organization";
import { ButtonLink } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { formatMoney, humanizeKey, STAGE_LABELS } from "@/lib/sales";
import { useMembers } from "@/lib/use-members";
import { useApi } from "@/lib/use-api";

export default function OpportunityPage() {
  return (
    <RequireOrganization>
      <Opportunity />
    </RequireOrganization>
  );
}

function Opportunity() {
  const { id } = useParams<{ id: string }>();
  const { members, nameOf } = useMembers();
  const deal = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}", { params: { path: { deal_id: id } } }), [id]);
  const history = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}/history", { params: { path: { deal_id: id } } }), [id]);
  const briefs = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}/briefs", { params: { path: { deal_id: id } } }), [id]);
  const companyId = deal.data?.company.id;
  const contacts = useApi(
    () =>
      companyId
        ? api.GET("/api/v1/sales/contacts", { params: { query: { company_id: companyId } } })
        : Promise.resolve({ data: undefined as undefined, error: undefined }),
    [companyId],
  );

  function dealChanged() {
    deal.reload();
    history.reload();
    briefs.reload();
  }

  if (deal.loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!deal.data)
    return (
      <EmptyState title="Opportunity not found" action={<ButtonLink href="/sales/pipeline">Back to the pipeline</ButtonLink>}>
        It may have been removed, or it belongs to a different organization.
      </EmptyState>
    );
  const d = deal.data;
  const closed = d.status !== "open";

  return (
    <>
      <PageHeader
        title={d.title}
        description="Opportunity detail: stage, activities, brief, proposal and follow-ups."
        actions={
          <ButtonLink href="/sales/pipeline" variant="secondary">
            Pipeline
          </ButtonLink>
        }
      />
      <div className="space-y-8">
        {deal.error ? <Alert>{deal.error}</Alert> : null}
        <Card className="space-y-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3" data-testid="deal-header">
            <Fact label="Company">
              <Link href={`/leads/${d.company.id}`} className="text-accent hover:underline">
                {d.company.name}
              </Link>
            </Fact>
            <Fact label="Stage">
              <StageBadge stage={d.stage} />
            </Fact>
            <Fact label="Status">
              <DealStatusBadge status={d.status} />
            </Fact>
            <Fact label="Priority">
              <DealPriorityBadge priority={d.priority} />
            </Fact>
            <Fact label="Estimated value">{formatMoney(d.estimated_value, d.currency)}</Fact>
            <Fact label="Currency">{d.currency}</Fact>
            <Fact label="Expected close">{d.expected_close_date ?? "Not set"}</Fact>
            <Fact label="Owner">{nameOf(d.owner_user_id)}</Fact>
            <Fact label="Version">{d.version}</Fact>
            {d.status === "won" ? <Fact label="Won value">{formatMoney(d.won_value, d.currency)}</Fact> : null}
            {d.status === "lost" && d.lost_reason ? <Fact label="Lost reason">{d.lost_reason}</Fact> : null}
            {d.closed_at ? <Fact label="Closed">{formatDate(d.closed_at)}</Fact> : null}
          </dl>
          <StageControls deal={d} onChanged={dealChanged} />
        </Card>

        <LeadSummaryCard companyId={d.company.id} />

        <section aria-labelledby="edit" className="space-y-3">
          <h2 id="edit" className="text-lg font-medium text-white">
            Details
          </h2>
          <DealEditForm key={d.version} deal={d} members={members} onSaved={dealChanged} />
        </section>

        <ActivityPanel key={`act-${d.version}`} dealId={d.id} contacts={contacts.data ?? []} onChanged={dealChanged} />

        <section aria-labelledby="stage-history" className="space-y-3">
          <h2 id="stage-history" className="text-lg font-medium text-white">
            Stage history
          </h2>
          {history.data && history.data.length === 0 ? <p className="text-sm text-slate-400">No stage changes yet.</p> : null}
          {history.data && history.data.length > 0 ? (
            <ol aria-label="Stage history" className="divide-y divide-line rounded-lg border border-line bg-navy-900/70">
              {history.data.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-slate-300">
                  <span>
                    {h.previous_stage ? STAGE_LABELS[h.previous_stage] : "Created"} → <span className="font-medium text-white">{STAGE_LABELS[h.new_stage]}</span>
                  </span>
                  <span className="text-xs text-slate-400">{formatDate(h.changed_at)}</span>
                  {h.reason ? <span className="text-xs text-slate-400">Reason: {h.reason}</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </section>

        <section aria-labelledby="company-contacts" className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 id="company-contacts" className="text-lg font-medium text-white">
              Contacts
            </h2>
            <Link href="/sales/contacts" className="text-sm text-accent hover:underline">
              Manage contacts
            </Link>
          </div>
          <p className="text-xs text-slate-400">AIgentiX never sends messages. A channel is shown as allowed only after a person recorded an eligibility review.</p>
          {contacts.data && contacts.data.length === 0 ? <p className="text-sm text-slate-400">No contacts recorded for this company.</p> : null}
          {contacts.data && contacts.data.length > 0 ? (
            <ul className="divide-y divide-line rounded-lg border border-line bg-navy-900/70" aria-label="Company contacts">
              {contacts.data.map((c) => (
                <li key={c.id} className="space-y-1.5 px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-slate-100">
                      {c.name}
                      {c.role ? <span className="font-normal text-slate-400"> · {c.role}</span> : null}
                    </span>
                    <RestrictionBadge status={c.restriction_status} />
                  </div>
                  <p className="text-xs text-slate-400">Source: {humanizeKey(c.source)}</p>
                  <PermissionBadges permissions={c.permissions} />
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <BriefPanel dealId={d.id} closed={closed} />
        <ProposalPanel dealId={d.id} closed={closed} briefs={briefs.data ?? []} onDealChanged={dealChanged} />
        <DealTasksPanel dealId={d.id} members={members} nameOf={nameOf} closed={closed} onChanged={deal.reload} />
      </div>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-slate-100">{children}</dd>
    </div>
  );
}
