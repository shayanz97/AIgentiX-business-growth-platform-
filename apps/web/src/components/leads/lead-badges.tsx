import { Badge } from "@/components/ui/surface";
import { formatCoverage, formatScoreRange, humanize, INTENT_LABELS, STATE_LABELS } from "@/lib/leads";

export function ProvisionalBadge({ provisional }: { provisional: boolean }) {
  return provisional ? <Badge tone="warning">Provisional</Badge> : null;
}

export function PriorityBadge({ band }: { band: string }) {
  const tone = band === "high" ? "accent" : band === "medium" ? "neutral" : band === "excluded" ? "danger" : "muted";
  return <Badge tone={tone}>{humanize(band)} priority</Badge>;
}

export function IntentBadge({ status }: { status: string }) {
  const tone = status === "explicit" || status === "strong" ? "accent" : status === "indirect" ? "neutral" : "muted";
  return <Badge tone={tone}>Intent: {INTENT_LABELS[status] ?? humanize(status)}</Badge>;
}

export function ReviewBadge({ status }: { status: string }) {
  const tone = status === "qualified_for_review" ? "accent" : status === "rejected" ? "danger" : status === "new" ? "muted" : "neutral";
  return <Badge tone={tone}>{humanize(status)}</Badge>;
}

export function StateBadge({ state }: { state: string }) {
  const tone = state === "assessed" ? "accent" : state === "insufficient_evidence" ? "warning" : "muted";
  return <Badge tone={tone}>{STATE_LABELS[state] ?? humanize(state)}</Badge>;
}

/** Score range plus coverage and the provisional label: a score is never shown without them. */
export function ScoreSummary({ low, high, coverage, provisional }: { low: number; high: number; coverage: number; provisional: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-lg font-semibold text-white" aria-label={`Score range ${formatScoreRange(low, high)} out of 100`}>
        {formatScoreRange(low, high)}
      </span>
      <span className="text-xs text-slate-400">coverage {formatCoverage(coverage)}</span>
      <ProvisionalBadge provisional={provisional} />
    </div>
  );
}
