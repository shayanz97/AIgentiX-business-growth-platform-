"use client";

import { useState } from "react";

import { DealCard } from "@/components/sales/deal-card";
import { ExportCsvButton } from "@/components/sales/export-button";
import { NewDealForm } from "@/components/sales/new-deal-form";
import { control } from "@/components/sales/styles";
import { RequireOrganization } from "@/components/require-organization";
import { Button } from "@/components/ui/button";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, type DealStatus, type Priority, type Stage } from "@/lib/api";
import { OPEN_STAGES, PRIORITIES, STAGE_LABELS, STAGES } from "@/lib/sales";
import { useSession } from "@/lib/session";
import { useMembers } from "@/lib/use-members";
import { useApi } from "@/lib/use-api";

export default function PipelinePage() {
  const [showNew, setShowNew] = useState(false);
  return (
    <>
      <PageHeader
        title="Pipeline"
        description="Move opportunities through the stages as real-world events happen. Nothing here sends messages."
        actions={
          <>
            <Button variant="secondary" onClick={() => setShowNew((v) => !v)} aria-expanded={showNew}>
              New opportunity
            </Button>
            <ExportCsvButton entity="opportunities" filename="sales-opportunities.csv" />
          </>
        }
      />
      <RequireOrganization>
        {showNew ? (
          <div className="mb-6">
            <NewDealForm />
          </div>
        ) : null}
        <Board />
      </RequireOrganization>
    </>
  );
}

type StatusFilter = DealStatus | "all";

function Board() {
  const { me } = useSession();
  const { nameOf } = useMembers();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [mine, setMine] = useState(false);
  const [priority, setPriority] = useState<Priority | "">("");
  const [status, setStatus] = useState<StatusFilter>("open");

  const deals = useApi(
    () =>
      api.GET("/api/v1/sales/opportunities", {
        params: {
          query: {
            limit: 100,
            sort: "updated",
            q: query || undefined,
            owner_user_id: mine ? me.user.id : undefined,
            priority: priority || undefined,
            status: status === "all" ? undefined : status,
          },
        },
      }),
    [query, mine, priority, status, me.user.id],
  );

  const columns: Stage[] = status === "open" ? OPEN_STAGES : status === "all" ? STAGES : [status];
  const items = deals.data?.items ?? [];

  return (
    <div className="space-y-4">
      <form
        role="search"
        aria-label="Filter opportunities"
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_10rem_10rem_auto_auto]"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(q.trim());
        }}
      >
        <label className="block">
          <span className="sr-only">Search opportunities</span>
          <input className={control} placeholder="Search title or company" value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="block">
          <span className="sr-only">Priority</span>
          <select className={control} value={priority} onChange={(e) => setPriority(e.target.value as Priority | "")}>
            <option value="">Any priority</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="sr-only">Status</span>
          <select className={control} value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="open">Open</option>
            <option value="won">Won</option>
            <option value="lost">Lost</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
          Mine
        </label>
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>

      {deals.error && !deals.data ? <Alert>{deals.error}</Alert> : null}
      {deals.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {deals.data && deals.data.total === 0 ? (
        <EmptyState title="No opportunities">Convert a qualified lead from its lead page, or create one manually, to start the pipeline.</EmptyState>
      ) : null}
      {deals.data && deals.data.total > items.length ? (
        <Alert tone="warning">
          Showing {items.length} of {deals.data.total} opportunities. Narrow the filters to see the rest.
        </Alert>
      ) : null}

      {deals.data && deals.data.total > 0 ? (
        <div className="-mx-4 overflow-x-auto px-4 pb-4 sm:-mx-8 sm:px-8">
          <div className="flex gap-4">
            {columns.map((stage) => {
              const inStage = items.filter((d) => d.stage === stage);
              return (
                <section key={stage} aria-label={`${STAGE_LABELS[stage]} column`} className="w-72 shrink-0 rounded-lg border border-line bg-navy-900/70 p-3">
                  <h2 className="mb-3 flex items-center justify-between text-sm font-medium text-white">
                    {STAGE_LABELS[stage]}
                    <span className="text-xs text-slate-400" aria-label={`${inStage.length} opportunities`}>
                      {inStage.length}
                    </span>
                  </h2>
                  {inStage.length === 0 ? (
                    <p className="text-xs text-slate-500">No opportunities</p>
                  ) : (
                    <ul className="space-y-3">
                      {inStage.map((d) => (
                        <DealCard key={d.id} deal={d} ownerName={nameOf(d.owner_user_id)} onChanged={deals.reload} />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
