"use client";

import { useState } from "react";

import { OpportunityCard } from "@/components/research/opportunity-card";
import { RequireOrganization } from "@/components/require-organization";
import { Button } from "@/components/ui/button";
import { cn } from "@/components/ui/cn";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, type OpportunityStatus } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 20;
const FILTERS: { label: string; value: OpportunityStatus | "" }[] = [
  { label: "All", value: "" },
  { label: "Proposed", value: "proposed" },
  { label: "Under review", value: "under_review" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
];

export default function OpportunitiesPage() {
  return (
    <>
      <PageHeader title="Opportunities" description="AI-suggested opportunities waiting for human review. They are hypotheses, not facts." />
      <RequireOrganization>
        <Queue />
      </RequireOrganization>
    </>
  );
}

function Queue() {
  const [status, setStatus] = useState<OpportunityStatus | "">("");
  const [offset, setOffset] = useState(0);
  const { data, error, loading } = useApi(
    () => api.GET("/api/v1/opportunities", { params: { query: { limit: PAGE_SIZE, offset, status: status || undefined } } }),
    [status, offset],
  );

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Filter by status" className="flex flex-wrap gap-1 border-b border-line">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            role="tab"
            aria-selected={status === f.value}
            onClick={() => {
              setStatus(f.value);
              setOffset(0);
            }}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              status === f.value ? "border-accent text-white" : "border-transparent text-slate-400 hover:text-slate-100",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && !data ? <Alert>{error}</Alert> : null}
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {data && data.total === 0 ? (
        <EmptyState title={status ? "No opportunities with this status" : "No opportunities yet"}>
          {status
            ? "Try another filter."
            : "Opportunities appear here after a company has been researched and the AI audit has produced evidence-backed suggestions."}
        </EmptyState>
      ) : null}
      {data && data.total > 0 ? (
        <>
          <div className="space-y-4">
            {data.items.map((op) => (
              <OpportunityCard key={op.id} opportunity={op} showCompany />
            ))}
          </div>
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
