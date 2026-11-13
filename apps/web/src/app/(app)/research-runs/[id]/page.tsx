"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { RunDetailView } from "@/components/research/run-detail-view";
import { StatusBadge } from "@/components/research/badges";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage } from "@/lib/api";
import { isActiveStatus } from "@/lib/research";
import { useApi, usePolling } from "@/lib/use-api";

export default function ResearchRunPage() {
  return (
    <RequireOrganization>
      <RunPage />
    </RequireOrganization>
  );
}

const POLL_MS = 2000;

function RunPage() {
  const { id } = useParams<{ id: string }>();
  const { data: run, error, loading, reload } = useApi(
    () => api.GET("/api/v1/research-runs/{run_id}", { params: { path: { run_id: id } } }),
    [id],
  );
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const current = run;
  const active = isActiveStatus(current?.status);
  usePolling(reload, active, POLL_MS);

  if (loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!current)
    return (
      <EmptyState title="Research run not found" action={<ButtonLink href="/companies">Back to companies</ButtonLink>}>
        {error ?? "It may have been removed, or it belongs to a different organization."}
      </EmptyState>
    );

  async function cancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/research-runs/{run_id}/cancel", { params: { path: { run_id: id } } });
      if (!data) setCancelError(errorMessage(apiError, "Could not cancel the research run."));
      else reload();
    } catch {
      setCancelError("Cannot reach the server. Please try again.");
    } finally {
      setCancelling(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`${current.kind === "enrichment" ? "Enrichment" : "Research"}: ${current.company_name}`}
        description={
          current.kind === "enrichment"
            ? "Growth triggers, buying intent and lead score"
            : "Website research and AI opportunity audit"
        }
        actions={
          <>
            {active ? (
              <Button variant="secondary" onClick={() => void cancel()} disabled={cancelling || current.cancel_requested}>
                Cancel research
              </Button>
            ) : null}
            {current.kind === "enrichment" ? (
              <ButtonLink href={`/leads/${current.company_id}`} variant="secondary">
                View lead
              </ButtonLink>
            ) : null}
            <ButtonLink href={`/companies/${current.company_id}`}>View company results</ButtonLink>
          </>
        }
      />
      <div className="space-y-6">
        <p className="text-sm text-slate-400">
          Company:{" "}
          <Link href={`/companies/${current.company_id}`} className="text-accent hover:underline">
            {current.company_name}
          </Link>
        </p>
        <div aria-live="polite" className="sr-only" data-testid="run-status-live">
          Research status: {current.status}. Progress {current.progress}%.
        </div>
        {cancelError ? <Alert>{cancelError}</Alert> : null}
        {error ? <Alert tone="warning">Could not refresh the latest status: {error}</Alert> : null}
        <div className="flex items-center gap-2 text-sm text-slate-400">
          Status: <StatusBadge status={current.status} />
        </div>
        <RunDetailView run={current} />
      </div>
    </>
  );
}
