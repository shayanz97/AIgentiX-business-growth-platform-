"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type EnrichmentStartResult, type ScoreRunResult } from "@/lib/api";

const SKIP_TEXT: Record<string, string> = {
  not_found: "company was not found",
  no_website: "no website is saved for this company",
  already_running: "an enrichment is already running",
};

/** Enrich (re-crawl) and Re-score (stored data only) buttons with plain feedback about what happened. */
export function EnrichmentActions({
  companyId,
  hasWebsite,
  busy = false,
  onDone,
}: {
  companyId: string;
  hasWebsite: boolean;
  busy?: boolean;
  onDone: () => void;
}) {
  const [pending, setPending] = useState<"enrich" | "score" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enrich, setEnrich] = useState<EnrichmentStartResult | null>(null);
  const [score, setScore] = useState<ScoreRunResult | null>(null);

  async function run(kind: "enrich" | "score") {
    setPending(kind);
    setError(null);
    setEnrich(null);
    setScore(null);
    try {
      if (kind === "enrich") {
        const { data, error: e } = await api.POST("/api/v1/companies/{company_id}/enrich", {
          params: { path: { company_id: companyId } },
          body: { force: true },
        });
        if (!data) setError(errorMessage(e, "Could not start the enrichment."));
        else setEnrich(data);
      } else {
        const { data, error: e } = await api.POST("/api/v1/companies/{company_id}/score", { params: { path: { company_id: companyId } } });
        if (!data) setError(errorMessage(e, "Could not re-score this company."));
        else setScore(data);
      }
      onDone();
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Button onClick={() => void run("enrich")} disabled={pending !== null || busy || !hasWebsite}>
          {pending === "enrich" ? "Starting…" : "Enrich (re-crawl)"}
        </Button>
        <Button variant="secondary" onClick={() => void run("score")} disabled={pending !== null}>
          {pending === "score" ? "Scoring…" : "Re-score"}
        </Button>
      </div>
      <p className="text-xs text-slate-400">
        Enrich re-fetches the public website to find growth triggers and buying intent. Re-score only recalculates from stored data — no crawling.
      </p>
      {error ? <Alert>{error}</Alert> : null}
      {enrich ? (
        <div role="status" className="space-y-2">
          {enrich.started.map((r) => (
            <Alert key={r.id} tone="info">
              Enrichment started.{" "}
              <Link href={`/research-runs/${r.id}`} className="text-accent hover:underline">
                View enrichment run
              </Link>
            </Alert>
          ))}
          {enrich.rescored.length > 0 ? <Alert tone="info">Recently enriched, so only the score was recalculated.</Alert> : null}
          {enrich.skipped.map((s) => (
            <Alert key={`${s.company_id}-${s.reason}`} tone="warning">
              Skipped: {SKIP_TEXT[s.reason] ?? s.reason}.
            </Alert>
          ))}
        </div>
      ) : null}
      {score ? (
        <Alert tone="info">
          <span role="status">
            Re-scored {score.scored} {score.scored === 1 ? "company" : "companies"}; {score.new_snapshots} new score{" "}
            {score.new_snapshots === 1 ? "snapshot" : "snapshots"} saved{score.new_snapshots === 0 ? " (nothing changed)" : ""}.
          </span>
        </Alert>
      ) : null}
    </div>
  );
}
