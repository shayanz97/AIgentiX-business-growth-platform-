"use client";

import Link from "next/link";

import { IntentBadge, PriorityBadge, ProvisionalBadge, ReviewBadge } from "@/components/leads/lead-badges";
import { Card } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { formatCoverage, formatScoreRange } from "@/lib/leads";
import { useApi } from "@/lib/use-api";

/** Research summary of the company behind a deal. The score ranks leads; it is not a purchase probability. */
export function LeadSummaryCard({ companyId }: { companyId: string }) {
  const lead = useApi(() => api.GET("/api/v1/leads/{company_id}", { params: { path: { company_id: companyId } } }), [companyId]);
  const l = lead.data?.lead;
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium text-white">Lead research summary</h2>
        <Link href={`/leads/${companyId}`} className="text-sm text-accent hover:underline">
          Open lead
        </Link>
      </div>
      {lead.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {lead.error && !lead.data ? <p className="text-sm text-red-300">{lead.error}</p> : null}
      {lead.data && !l ? <p className="text-sm text-slate-400">This company has not been scored.</p> : null}
      {l ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold text-white">{formatScoreRange(l.score.score_low, l.score.score_high)}</span>
            <span className="text-xs text-slate-400">coverage {formatCoverage(l.score.coverage)}</span>
            <ProvisionalBadge provisional={l.score.provisional} />
            <PriorityBadge band={l.score.priority_band} />
            <IntentBadge status={l.score.intent_status} />
            <ReviewBadge status={l.review_status} />
          </div>
          <p className="text-xs text-slate-500">Prioritisation score, not a purchase probability. It ranks leads for review; it does not predict whether someone will buy.</p>
        </>
      ) : null}
    </Card>
  );
}
