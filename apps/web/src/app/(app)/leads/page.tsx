"use client";

import Link from "next/link";
import { useState } from "react";

import { IntentBadge, PriorityBadge, ReviewBadge, ScoreSummary } from "@/components/leads/lead-badges";
import { ProjectSelect } from "@/components/research/project-select";
import { RequireOrganization } from "@/components/require-organization";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage } from "@/lib/api";
import {
  buildLeadQuery,
  DEFAULT_FILTERS,
  humanize,
  INTENT_STATUSES,
  leadHref,
  PRIORITY_BANDS,
  REVIEW_STATUSES,
  SIGNAL_TYPES,
  SORTS,
  type LeadFilters,
} from "@/lib/leads";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 20;
const control =
  "block w-full rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";

export default function LeadsPage() {
  return (
    <>
      <PageHeader
        title="Ranked leads"
        description="Companies ranked by an explainable score. Scores are provisional when important information is still missing."
      />
      <RequireOrganization>
        <RankedLeads />
      </RequireOrganization>
    </>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  all = "All",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly { value: string; label: string }[];
  all?: string | null;
}) {
  return (
    <label className="block text-sm font-medium text-slate-200">
      <span className="mb-1.5 block">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={control}>
        {all !== null ? <option value="">{all}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

const opts = (values: readonly string[]) => values.map((v) => ({ value: v, label: humanize(v) }));

function RankedLeads() {
  const [filters, setFilters] = useState<LeadFilters>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const query = buildLeadQuery(filters);
  const { data, error, loading } = useApi(
    () => api.GET("/api/v1/leads/ranked", { params: { query: { ...query, limit: PAGE_SIZE, offset } } }),
    [JSON.stringify(query), offset],
  );

  function set<K extends keyof LeadFilters>(key: K, value: LeadFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
    setOffset(0);
  }

  async function exportCsv() {
    setExporting(true);
    setExportError(null);
    try {
      const { data: csv, error: apiError } = await api.GET("/api/v1/leads/export", { params: { query }, parseAs: "text" });
      if (typeof csv !== "string") {
        setExportError(errorMessage(apiError, "Could not export the leads."));
        return;
      }
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "ranked-leads.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Cannot reach the server. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  const filtered = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  return (
    <div className="space-y-5">
      <section aria-label="Filters" className="rounded-lg border border-line bg-navy-900/70 p-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-sm font-medium text-slate-200">
            <span className="mb-1.5 block">Search company</span>
            <input type="search" value={filters.q} onChange={(e) => set("q", e.target.value)} className={control} placeholder="Name or domain" />
          </label>
          <Select label="Review status" value={filters.review_status} onChange={(v) => set("review_status", v)} options={opts(REVIEW_STATUSES)} />
          <Select label="Priority band" value={filters.priority_band} onChange={(v) => set("priority_band", v)} options={opts(PRIORITY_BANDS)} />
          <Select label="Intent status" value={filters.intent_status} onChange={(v) => set("intent_status", v)} options={opts(INTENT_STATUSES)} />
          <Select label="Signal type" value={filters.signal_type} onChange={(v) => set("signal_type", v)} options={opts(SIGNAL_TYPES)} />
          <label className="block text-sm font-medium text-slate-200">
            <span className="mb-1.5 block">Minimum score</span>
            <input
              type="number"
              min={0}
              max={100}
              value={filters.min_score}
              onChange={(e) => set("min_score", e.target.value)}
              className={control}
              placeholder="0 – 100"
            />
          </label>
          <Select
            label="Provisional"
            value={filters.provisional}
            onChange={(v) => set("provisional", v as LeadFilters["provisional"])}
            options={[
              { value: "yes", label: "Provisional only" },
              { value: "no", label: "Complete only" },
            ]}
          />
          <Select label="Sort by" value={filters.sort} onChange={(v) => set("sort", v)} options={SORTS} all={null} />
          <ProjectSelect value={filters.project_id} onChange={(v) => set("project_id", v)} />
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-200">
            <input type="checkbox" checked={filters.hideExcluded} onChange={(e) => set("hideExcluded", e.target.checked)} />
            Hide companies outside the ICP
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => void exportCsv()} disabled={exporting}>
            {exporting ? "Exporting…" : "Export CSV"}
          </Button>
          {filtered ? (
            <Button
              variant="ghost"
              onClick={() => {
                setFilters(DEFAULT_FILTERS);
                setOffset(0);
              }}
            >
              Reset filters
            </Button>
          ) : null}
        </div>
      </section>

      {exportError ? <Alert>{exportError}</Alert> : null}
      {error && !data ? <Alert>{error}</Alert> : null}
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {data && data.total === 0 ? (
        <EmptyState title={filtered ? "No leads match these filters" : "No scored leads yet"}>
          {filtered
            ? "Try removing a filter."
            : "Leads appear here after a company has been enriched: open a company and choose Enrich to collect growth triggers and buying intent, which are then scored."}
        </EmptyState>
      ) : null}
      {data && data.total > 0 ? (
        <>
          <ol aria-label="Ranked leads" className="space-y-3">
            {data.items.map((lead, i) => {
              const s = lead.score;
              return (
                <li key={lead.company_id} className="rounded-lg border border-line bg-navy-900/70 p-4" data-testid="lead-row">
                  <div className="grid gap-3 md:grid-cols-[3rem_1fr_auto] md:items-start">
                    <span className="text-sm font-semibold text-slate-400" aria-label={`Rank ${offset + i + 1}`}>
                      #{offset + i + 1}
                    </span>
                    <div className="min-w-0 space-y-2">
                      <Link href={leadHref(lead)} className="block truncate text-base font-medium text-accent hover:underline">
                        {lead.company_name}
                      </Link>
                      <p className="truncate text-xs text-slate-400">{lead.canonical_domain ?? "No website"}</p>
                      <div className="flex flex-wrap items-center gap-2">
                        <PriorityBadge band={s.priority_band} />
                        <IntentBadge status={s.intent_status} />
                        <ReviewBadge status={lead.review_status} />
                      </div>
                      <p className="text-xs text-slate-400">
                        Latest trigger: {s.latest_trigger_on ?? "none dated"} · Next step: {s.next_step_text}
                      </p>
                    </div>
                    <ScoreSummary low={s.score_low} high={s.score_high} coverage={s.coverage} provisional={s.provisional} />
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="flex items-center justify-between text-sm text-slate-400">
            <span>
              {offset + 1}–{offset + data.items.length} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Previous
              </Button>
              <Button variant="secondary" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                Next
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
