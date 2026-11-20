"use client";

import { useState } from "react";

import { ProposalEditor } from "@/components/sales/proposal-editor";
import { Button } from "@/components/ui/button";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, type Brief } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { isGenerating, PROPOSAL_STATUS_LABELS } from "@/lib/sales";
import { useApi, usePolling } from "@/lib/use-api";

export function ProposalStatusBadge({ status }: { status: string }) {
  const tone = status === "accepted" ? "accent" : status === "failed" || status === "declined" ? "danger" : status === "generating" ? "warning" : "neutral";
  return <Badge tone={tone}>{PROPOSAL_STATUS_LABELS[status] ?? status}</Badge>;
}

/** Proposal workspace: generate from the latest brief, edit as immutable revisions, move through statuses by hand. */
export function ProposalPanel({ dealId, closed, briefs, onDealChanged }: { dealId: string; closed: boolean; briefs: Brief[]; onDealChanged: () => void }) {
  const proposals = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}/proposals", { params: { path: { deal_id: dealId } } }), [dealId]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const list = proposals.data ?? [];
  const generating = list.some((p) => isGenerating(p.status));
  usePolling(proposals.reload, generating, 2000);
  const usableBrief = briefs.find((b) => b.status === "draft" || b.status === "approved") ?? null;

  async function generate() {
    setError(null);
    setStarting(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/proposals", {
        params: { path: { deal_id: dealId } },
        body: { brief_id: usableBrief?.id ?? null },
      });
      if (!data) setError(errorMessage(apiError, "Could not start the proposal."));
      else {
        setOpenId(data.id);
        proposals.reload();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section aria-labelledby="proposals" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="proposals" className="text-lg font-medium text-white">
          Proposals
        </h2>
        <Button variant="secondary" onClick={() => void generate()} disabled={starting || generating || closed}>
          {generating ? "Generating…" : "Generate proposal"}
        </Button>
      </div>
      <p className="text-sm text-slate-400">
        {usableBrief ? "Drafted from the latest sales brief." : "No usable brief yet: generate a brief first for a better draft."} Drafts are never sent by AIgentiX; you send
        proposals yourself and record it here.
      </p>
      {error ? <Alert>{error}</Alert> : null}
      {proposals.error && !proposals.data ? <Alert>{proposals.error}</Alert> : null}
      {proposals.data && list.length === 0 ? <p className="text-sm text-slate-400">No proposals yet.</p> : null}
      {list.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Proposals">
          {list.map((p) => (
            <li key={p.id} className="space-y-2 px-4 py-3 text-sm" data-testid="proposal-row">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-slate-100">{p.title}</p>
                  <p className="text-xs text-slate-400">
                    Revision {p.current_revision} · created {formatDate(p.created_at)}
                    {p.sent_at ? ` · sent ${formatDate(p.sent_at)}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <ProposalStatusBadge status={p.status} />
                  {p.status !== "generating" && p.status !== "failed" ? (
                    <Button variant="secondary" aria-expanded={openId === p.id} aria-label={`Open proposal ${p.title}`} onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                      {openId === p.id ? "Close" : "Open"}
                    </Button>
                  ) : null}
                </div>
              </div>
              {isGenerating(p.status) ? (
                <p role="status" className="text-slate-300">
                  Generating the proposal… {p.workflow ? `${p.workflow.progress}%` : ""}
                </p>
              ) : null}
              {p.status === "failed" ? <Alert>{p.message ?? p.workflow?.error_message ?? "Proposal generation failed."}</Alert> : null}
              {openId === p.id && p.status !== "generating" && p.status !== "failed" ? (
                <ProposalEditor
                  key={`${p.id}-${p.version}`}
                  proposalId={p.id}
                  onChanged={() => {
                    proposals.reload();
                    onDealChanged();
                  }}
                />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
