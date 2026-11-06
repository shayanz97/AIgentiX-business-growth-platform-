import Link from "next/link";

import { Alert } from "@/components/ui/surface";
import type { ResearchRunStartResult } from "@/lib/api";
import { SKIP_REASONS } from "@/lib/research";

/** Plain-English summary of POST /research-runs: what started and what was skipped, and why. */
export function StartFeedback({ result, names = {} }: { result: ResearchRunStartResult; names?: Record<string, string> }) {
  const { started, skipped } = result;
  return (
    <div role="status" className="space-y-3">
      {started.length > 0 ? (
        <Alert tone="info">
          Started research for {started.length} {started.length === 1 ? "company" : "companies"}.
          <ul className="mt-2 space-y-1">
            {started.map((run) => (
              <li key={run.id}>
                <Link href={`/research-runs/${run.id}`} className="text-accent hover:underline">
                  View research run for {run.company_name}
                </Link>
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}
      {skipped.length > 0 ? (
        <Alert tone="warning">
          Skipped {skipped.length} {skipped.length === 1 ? "company" : "companies"}:
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {skipped.map((s) => (
              <li key={`${s.company_id}-${s.reason}`}>
                {names[s.company_id] ?? "A company"} — {SKIP_REASONS[s.reason] ?? s.reason}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}
      {started.length === 0 && skipped.length === 0 ? <Alert tone="info">Nothing to research.</Alert> : null}
    </div>
  );
}
