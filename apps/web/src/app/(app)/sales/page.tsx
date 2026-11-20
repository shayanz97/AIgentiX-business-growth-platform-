"use client";

import Link from "next/link";

import { DealPriorityBadge, StageBadge } from "@/components/sales/deal-badges";
import { RequireOrganization } from "@/components/require-organization";
import { ButtonLink } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, type SalesMetrics } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { browserTimeZone, formatMoney, formatPerCurrency, formatRate, pipelineNote, STAGES, STAGE_LABELS } from "@/lib/sales";
import { useApi } from "@/lib/use-api";

export default function SalesOverviewPage() {
  return (
    <>
      <PageHeader
        title="Sales"
        description="Opportunities, follow-ups and proposals. AIgentiX prepares and tracks; people contact prospects."
        actions={<ButtonLink href="/sales/pipeline">Open pipeline</ButtonLink>}
      />
      <RequireOrganization>
        <Overview />
      </RequireOrganization>
    </>
  );
}

function Stat({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string | null }) {
  return (
    <Card className="p-4">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-2 text-2xl font-semibold text-white">{children}</dd>
      {hint ? <p className="mt-1 text-xs text-slate-400">{hint}</p> : null}
    </Card>
  );
}

function ValueLines({ values }: { values: Record<string, string> }) {
  const lines = formatPerCurrency(values);
  if (lines.length === 0) return <>—</>;
  return (
    <>
      {lines.map((l) => (
        <span key={l} className="block text-xl">
          {l}
        </span>
      ))}
    </>
  );
}

function Overview() {
  const tz = browserTimeZone();
  const metrics = useApi(() => api.GET("/api/v1/sales/metrics"), []);
  const tasks = useApi(() => api.GET("/api/v1/sales/tasks/summary", { params: { query: { tz } } }), [tz]);
  const recent = useApi(() => api.GET("/api/v1/sales/opportunities", { params: { query: { sort: "updated", limit: 5 } } }), []);
  const crm = useApi(() => api.GET("/api/v1/sales/crm/providers"), []);
  const m = metrics.data;

  return (
    <div className="space-y-8">
      {metrics.error && !m ? <Alert>{metrics.error}</Alert> : null}
      {metrics.loading ? <p className="text-sm text-slate-400">Loading metrics…</p> : null}
      {m ? <MetricsGrid m={m} /> : null}

      <section aria-labelledby="followups" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="followups" className="text-lg font-medium text-white">
            Follow-ups
          </h2>
          <Link href="/sales/tasks" className="text-sm text-accent hover:underline">
            All follow-ups
          </Link>
        </div>
        {tasks.error && !tasks.data ? <Alert>{tasks.error}</Alert> : null}
        {tasks.data ? (
          <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Overdue">{tasks.data.overdue}</Stat>
            <Stat label="Due today">{tasks.data.today}</Stat>
            <Stat label="Upcoming">{tasks.data.upcoming}</Stat>
            <Stat label="Assigned to me">{tasks.data.mine_open}</Stat>
          </dl>
        ) : null}
      </section>

      <section aria-labelledby="recent" className="space-y-3">
        <h2 id="recent" className="text-lg font-medium text-white">
          Recently updated opportunities
        </h2>
        {recent.error && !recent.data ? <Alert>{recent.error}</Alert> : null}
        {recent.data && recent.data.items.length === 0 ? (
          <EmptyState title="No opportunities yet" action={<ButtonLink href="/leads">Go to ranked leads</ButtonLink>}>
            Convert a reviewed lead into a sales opportunity to start tracking it here.
          </EmptyState>
        ) : null}
        {recent.data && recent.data.items.length > 0 ? (
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Recently updated opportunities">
            {recent.data.items.map((d) => (
              <li key={d.id}>
                <Link href={`/sales/opportunities/${d.id}`} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 hover:bg-navy-800/60">
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-100">{d.title}</span>
                    <span className="text-xs text-slate-400">
                      {d.company.name} · updated {formatDate(d.updated_at)}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
                    {formatMoney(d.estimated_value, d.currency)}
                    <DealPriorityBadge priority={d.priority} />
                    <StageBadge stage={d.stage} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="crm" className="space-y-3">
        <h2 id="crm" className="text-lg font-medium text-white">
          CRM
        </h2>
        {crm.error && !crm.data ? <Alert>{crm.error}</Alert> : null}
        {crm.data && crm.data.providers.length === 0 ? <p className="text-sm text-slate-300">No external CRM connected.</p> : null}
        {crm.data && crm.data.providers.length > 0 ? (
          <ul className="space-y-2" aria-label="CRM providers">
            {crm.data.providers.map((p) => (
              <li key={p.name} className="rounded-md border border-line bg-navy-900/70 px-4 py-3 text-sm text-slate-200">
                <span className="font-medium">{p.name}</span> · {p.status}
                {p.test_double ? " · test double" : ""}
                <p className="text-xs text-slate-400">{p.detail}</p>
              </li>
            ))}
          </ul>
        ) : null}
        {crm.data?.note ? <p className="text-xs text-slate-500">{crm.data.note}</p> : null}
      </section>
    </div>
  );
}

function MetricsGrid({ m }: { m: SalesMetrics }) {
  const note = pipelineNote(m);
  const wonNote = m.won_without_value > 0 ? `${m.won_without_value} won without value not included` : null;
  return (
    <section aria-labelledby="metrics" className="space-y-4">
      <h2 id="metrics" className="text-lg font-medium text-white">
        Pipeline metrics
      </h2>
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Open opportunities">{m.open_opportunities}</Stat>
        <Stat label="Pipeline value" hint={note}>
          <ValueLines values={m.pipeline_value} />
        </Stat>
        <Stat label="Won">{m.won_count}</Stat>
        <Stat label="Lost">{m.lost_count}</Stat>
        <Stat label="Won value" hint={wonNote}>
          <ValueLines values={m.won_value} />
        </Stat>
        <Stat label="Lead to opportunity">{formatRate(m.lead_to_opportunity_rate)}</Stat>
        <Stat label="Win rate">{formatRate(m.win_rate)}</Stat>
        <Stat label="Proposals drafted / sent">
          {m.proposals_drafted} / {m.proposals_sent}
        </Stat>
      </dl>

      <div>
        <h3 className="mb-2 text-sm font-medium text-slate-200">Opportunities by stage</h3>
        <ul className="flex flex-wrap gap-2" aria-label="Opportunities by stage">
          {STAGES.map((s) => (
            <li key={s} className="rounded-md border border-line bg-navy-900/70 px-3 py-1.5 text-sm text-slate-200">
              {STAGE_LABELS[s]}: <span className="font-semibold text-white">{m.opportunities_by_stage[s] ?? 0}</span>
            </li>
          ))}
        </ul>
      </div>

      <details className="rounded-md border border-line p-3 text-sm">
        <summary className="cursor-pointer text-slate-300">How these numbers are defined</summary>
        <dl className="mt-2 space-y-2 text-slate-400">
          {Object.entries(m.definitions).map(([k, v]) => (
            <div key={k}>
              <dt className="font-medium text-slate-300">{k.replace(/_/g, " ")}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-slate-500">Rates show “—” when there is no denominator. Values are never summed across currencies or estimated.</p>
      </details>
    </section>
  );
}
