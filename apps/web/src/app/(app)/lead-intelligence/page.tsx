"use client";

import Link from "next/link";

import { ProvisionalBadge } from "@/components/leads/lead-badges";
import { StatusBadge } from "@/components/research/badges";
import { RunProgress } from "@/components/research/run-detail-view";
import { RequireOrganization } from "@/components/require-organization";
import { ButtonLink } from "@/components/ui/button";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { formatCoverage, formatScoreRange, humanize } from "@/lib/leads";
import { useApi } from "@/lib/use-api";

export default function LeadIntelligencePage() {
  return (
    <>
      <PageHeader
        title="Lead Intelligence"
        description="Research companies from their public websites and review AI-suggested opportunities."
        actions={<ButtonLink href="/companies/new">Add companies</ButtonLink>}
      />
      <RequireOrganization>
        <Overview />
      </RequireOrganization>
    </>
  );
}

function Overview() {
  const summary = useApi(() => api.GET("/api/v1/lead-intelligence/summary"), []);
  const top = useApi(() => api.GET("/api/v1/leads/ranked", { params: { query: { limit: 5, sort: "score" } } }), []);
  const runs = useApi(() => api.GET("/api/v1/research-runs", { params: { query: { limit: 10 } } }), []);

  const s = summary.data;
  const stats: [string, number | undefined][] = [
    ["Total companies", s?.total_companies],
    ["Research runs", s?.research_runs],
    ["Companies researched", s?.companies_researched],
    ["Opportunities found", s?.opportunities_found],
    ["Failed research", s?.failed_runs],
  ];

  return (
    <div className="space-y-8">
      {summary.error && !s ? <Alert>{summary.error}</Alert> : null}
      <section aria-label="Summary">
        <dl className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {stats.map(([label, value]) => (
            <Card key={label} className="p-4">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
              <dd className="mt-2 text-2xl font-semibold text-white">{value === undefined ? "…" : value}</dd>
            </Card>
          ))}
        </dl>
      </section>

      <section aria-labelledby="top-leads">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="top-leads" className="text-lg font-medium text-white">
            Top leads
          </h2>
          <Link href="/leads" className="text-sm text-accent hover:underline">
            Ranked leads
          </Link>
        </div>
        {top.error && !top.data ? <Alert>{top.error}</Alert> : null}
        {top.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
        {top.data && top.data.items.length === 0 ? (
          <EmptyState title="No scored leads yet">Leads appear here after a company has been enriched.</EmptyState>
        ) : null}
        {top.data && top.data.items.length > 0 ? (
          <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Top leads">
            {top.data.items.map((lead) => (
              <li key={lead.company_id}>
                <Link href={`/leads/${lead.company_id}`} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 hover:bg-navy-800/60">
                  <span className="min-w-0 truncate font-medium text-slate-100">{lead.company_name}</span>
                  <span className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
                    {formatScoreRange(lead.score.score_low, lead.score.score_high)}
                    <span className="text-xs text-slate-400">coverage {formatCoverage(lead.score.coverage)}</span>
                    <ProvisionalBadge provisional={lead.score.provisional} />
                    <span className="text-xs text-slate-400">{humanize(lead.score.priority_band)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        ) : null}
        {top.data && top.data.total > 5 ? <p className="mt-2 text-xs text-slate-400">Showing the top 5 of {top.data.total} scored leads.</p> : null}
      </section>

      <section aria-labelledby="recent-runs">
        <h2 id="recent-runs" className="mb-3 text-lg font-medium text-white">
          Recent research runs
        </h2>
        {runs.error && !runs.data ? <Alert>{runs.error}</Alert> : null}
        {runs.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
        {runs.data && runs.data.items.length === 0 ? (
          <EmptyState title="No research runs yet" action={<ButtonLink href="/companies/new">Add a company</ButtonLink>}>
            Add a company website and start research. Runs and their progress will be listed here.
          </EmptyState>
        ) : null}
        {runs.data && runs.data.items.length > 0 ? (
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Recent research runs">
            {runs.data.items.map((run) => (
              <li key={run.id}>
                <Link href={`/research-runs/${run.id}`} className="grid gap-3 px-5 py-4 hover:bg-navy-800/60 sm:grid-cols-[1fr_12rem_auto] sm:items-center">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-100">{run.company_name}</p>
                    <p className="text-xs text-slate-400">{formatDate(run.created_at)}</p>
                  </div>
                  <RunProgress run={run} />
                  <div className="sm:justify-self-end">
                    <StatusBadge status={run.status} />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
