import { StatusBadge } from "@/components/research/badges";
import { Alert, Badge, Card } from "@/components/ui/surface";
import type { ResearchRun } from "@/lib/api";
import { formatDate, formatDuration, formatUsd } from "@/lib/format";
import { isActiveStatus, STEP_LABELS } from "@/lib/research";

const STEP_ICONS: Record<string, { icon: string; label: string; className: string }> = {
  done: { icon: "✓", label: "Done", className: "text-accent" },
  current: { icon: "●", label: "In progress", className: "animate-pulse text-accent" },
  pending: { icon: "○", label: "Waiting", className: "text-slate-500" },
  skipped: { icon: "–", label: "Skipped", className: "text-slate-500" },
};

const AI_STATUS_TEXT: Record<string, string> = {
  pending: "Pending",
  completed: "Completed",
  unavailable: "Unavailable — no AI provider configured",
  failed: "Failed",
  skipped: "Skipped",
};

export function RunProgress({ run }: { run: ResearchRun }) {
  const value = Math.max(0, Math.min(100, run.progress));
  return (
    <div>
      <div className="mb-1.5 flex justify-between text-xs text-slate-400">
        <span>Progress</span>
        <span>{value}%</span>
      </div>
      <div
        role="progressbar"
        aria-label="Research progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        className="h-2 overflow-hidden rounded-full bg-navy-800"
      >
        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export function RunSteps({ run }: { run: ResearchRun }) {
  return (
    <ol aria-label="Research steps" className="divide-y divide-line rounded-md border border-line">
      {run.steps.map((step) => {
        const meta = STEP_ICONS[step.state] ?? { icon: "○", label: step.state, className: "text-slate-500" };
        return (
          <li key={step.name} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm" data-state={step.state}>
            <span className="flex items-center gap-3">
              <span aria-hidden="true" className={`w-4 text-center ${meta.className}`}>
                {meta.icon}
              </span>
              <span className={step.state === "pending" ? "text-slate-400" : "text-slate-100"}>{STEP_LABELS[step.name] ?? step.name}</span>
              <span className="sr-only">{meta.label}</span>
            </span>
            <span className="text-xs text-slate-500">{formatDuration(step.duration_ms)}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Everything about one research run that does not need to fetch or mutate anything. */
export function RunDetailView({ run }: { run: ResearchRun }) {
  const noTokens = run.input_tokens === 0 && run.output_tokens === 0;
  const retrying = run.status === "pending" && !!run.error_message;
  return (
    <div className="space-y-6">
      <Card className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={run.status} />
          <span className="text-sm text-slate-400">
            Attempt {run.attempts} of {run.max_attempts}
          </span>
          {run.cancel_requested && isActiveStatus(run.status) ? <Badge tone="warning">Cancellation requested</Badge> : null}
        </div>
        <RunProgress run={run} />
        <RunSteps run={run} />
        {retrying && run.next_attempt_at ? (
          <p className="text-sm text-slate-300">Next retry at {formatDate(run.next_attempt_at)}.</p>
        ) : null}
        {run.error_message && (run.status === "failed" || retrying) ? (
          <Alert tone="warning">
            <strong className="font-medium">{run.status === "failed" ? "Research failed" : "Last attempt failed, retrying"}</strong>
            {run.error_type ? <span> ({run.error_type})</span> : null}: {run.error_message}
          </Alert>
        ) : null}
      </Card>

      <Card>
        <h2 className="font-medium text-slate-100">AI analysis</h2>
        <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
          <Row label="AI status">{AI_STATUS_TEXT[run.ai_status] ?? run.ai_status}</Row>
          <Row label="Pages fetched">{String(run.pages_fetched)}</Row>
          <Row label="Tokens in / out">{noTokens ? "Not available" : `${run.input_tokens} / ${run.output_tokens}`}</Row>
          <Row label="Estimated cost">{noTokens && run.estimated_cost_usd === 0 ? "Not available" : formatUsd(run.estimated_cost_usd)}</Row>
          <Row label="Models used">{run.models_used.length > 0 ? run.models_used.join(", ") : "None"}</Row>
          <Row label="Prompt versions">
            {Object.keys(run.prompt_versions).length > 0
              ? Object.entries(run.prompt_versions)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(", ")
              : "None"}
          </Row>
          <Row label="Started">{run.started_at ? formatDate(run.started_at) : "Not started"}</Row>
          <Row label="Finished">{run.completed_at ? formatDate(run.completed_at) : "—"}</Row>
        </dl>
        {run.audit_summary ? (
          <div className="mt-4">
            <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Audit summary</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-200">{run.audit_summary}</p>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function Row({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 break-words text-slate-200">{children}</dd>
    </div>
  );
}
