import { ExternalLink } from "@/components/research/external-link";
import type { EvidenceLike } from "@/components/leads/score-breakdown";
import { Badge } from "@/components/ui/surface";
import type { Signal } from "@/lib/api";
import { formatEventDate, FRESHNESS_LABELS, groupSignals, humanize, PRECISION_LABELS } from "@/lib/leads";

function SignalItem({ signal: s }: { signal: Signal }) {
  const tone = s.freshness === "recent" ? "accent" : s.freshness === "unknown" ? "warning" : "muted";
  const candidates = s.date_candidates
    .map((c) => (typeof c.date === "string" ? c.date : typeof c.value === "string" ? c.value : null))
    .filter((x): x is string => !!x);
  return (
    <li className="rounded-md border border-line bg-navy-950/50 p-4 text-sm" data-testid="signal">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">{humanize(s.signal_type)}</Badge>
        <Badge tone={tone}>{FRESHNESS_LABELS[s.freshness] ?? s.freshness}</Badge>
        <span className="text-xs text-slate-400">
          {formatEventDate(s.occurred_on, s.date_precision)} ({PRECISION_LABELS[s.date_precision] ?? s.date_precision})
        </span>
        {s.mention_count > 1 ? <span className="text-xs text-slate-400">mentioned on {s.mention_count} pages</span> : null}
        {s.deadline_on ? <Badge tone="neutral">Deadline {s.deadline_on}</Badge> : null}
      </div>
      <p className="mt-2 font-medium text-slate-100">{s.title}</p>
      {s.summary ? <p className="mt-1 whitespace-pre-wrap text-slate-300">{s.summary}</p> : null}
      {s.date_conflict ? (
        <p className="mt-2 text-xs text-amber-300" role="note">
          Conflicting dates found on the website, so no date was chosen
          {candidates.length > 0 ? `: ${candidates.join(", ")}` : "."}
        </p>
      ) : null}
      {s.evidence.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {s.evidence.map((ev: EvidenceLike) => (
            <li key={ev.id} className="text-xs text-slate-400">
              <Badge tone="muted">{ev.label}</Badge>
              <blockquote className="mt-1 border-l-2 border-accent/40 pl-3">{ev.supporting_excerpt}</blockquote>
              {ev.source_url ? (
                <p className="mt-1">
                  Source: <ExternalLink href={ev.source_url}>{ev.source_url}</ExternalLink>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Dated triggers newest first; undated or contradictory ones sit in their own group and are never shown as current. */
export function TriggerTimeline({ signals }: { signals: Signal[] }) {
  const { dated, undated } = groupSignals(signals);
  if (signals.length === 0) return <p className="text-sm text-slate-400">No growth triggers were found in the checked sources.</p>;
  return (
    <div className="space-y-6">
      {dated.length > 0 ? (
        <ol aria-label="Dated triggers" className="space-y-3">
          {dated.map((s) => (
            <SignalItem key={s.id} signal={s} />
          ))}
        </ol>
      ) : null}
      {undated.length > 0 ? (
        <section aria-labelledby="undated-triggers">
          <h3 id="undated-triggers" className="mb-2 text-sm font-medium text-slate-200">
            Date unknown
          </h3>
          <p className="mb-3 text-xs text-slate-400">These triggers have no reliable date, so they are not treated as recent.</p>
          <ol aria-label="Triggers without a date" className="space-y-3">
            {undated.map((s) => (
              <SignalItem key={s.id} signal={s} />
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
