import { StateBadge } from "@/components/leads/lead-badges";
import { Badge } from "@/components/ui/surface";
import type { ScoreComponent } from "@/lib/api";
import { formatCoverage, formatScoreRange } from "@/lib/leads";

export type EvidenceLike = { id: string; label: string; supporting_excerpt: string; source_url: string | null };

const COMPONENT_NAMES: Record<string, string> = { opportunity: "Opportunity", fit: "Fit", triggers: "Triggers", intent: "Intent" };

function Range({ low, high, label }: { low: number; high: number; label: string }) {
  const l = Math.max(0, Math.min(100, low));
  const h = Math.max(l, Math.min(100, high));
  return (
    <div role="img" aria-label={label} className="relative h-2 overflow-hidden rounded-full bg-navy-800">
      <div className="absolute inset-y-0 rounded-full bg-accent/30" style={{ left: `${l}%`, width: `${h - l}%` }} />
      <div className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${l}%` }} />
    </div>
  );
}

/** Component-by-component explanation of a lead score; every criterion keeps its own state. */
export function ScoreBreakdown({ components, evidence = {} }: { components: ScoreComponent[]; evidence?: Record<string, EvidenceLike> }) {
  return (
    <ul aria-label="Score breakdown" className="space-y-5">
      {components.map((c) => {
        const name = COMPONENT_NAMES[c.key] ?? c.label;
        return (
          <li key={c.key} className="rounded-lg border border-line bg-navy-900/70 p-5" data-testid={`component-${c.key}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-medium text-white">
                {name} <span className="text-sm font-normal text-slate-400">weight {c.weight}</span>
              </h3>
              <StateBadge state={c.state} />
            </div>
            <p className="mt-1 text-sm text-slate-400">{c.summary}</p>
            <div className="mt-3 space-y-1">
              <Range low={c.score_low} high={c.score_high} label={`${name} score range ${formatScoreRange(c.score_low, c.score_high)} out of 100`} />
              <p className="text-xs text-slate-400">
                Component score {formatScoreRange(c.score_low, c.score_high)} / 100 · contributes{" "}
                {formatScoreRange(c.contribution_low, c.contribution_high)} of {c.weight} points · coverage {formatCoverage(c.coverage)}
              </p>
            </div>
            <ul className="mt-4 divide-y divide-line" aria-label={`${name} criteria`}>
              {c.criteria.map((cr) => (
                <li key={cr.key} className="py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-100">{cr.label}</span>
                    <StateBadge state={cr.state} />
                    <span className="text-xs text-slate-400">
                      {cr.points === null ? "–" : Math.round(cr.points * 10) / 10} / {cr.max_points} points
                    </span>
                    <span className="text-xs text-slate-500">
                      {cr.evidence_ids.length} evidence {cr.evidence_ids.length === 1 ? "item" : "items"}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-slate-300">{cr.explanation}</p>
                  {cr.evidence_ids.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {cr.evidence_ids.map((id) => (
                        <Badge key={id} tone="muted">
                          {evidence[id]?.label ?? "Evidence"}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
