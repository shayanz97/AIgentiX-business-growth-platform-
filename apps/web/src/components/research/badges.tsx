import { Badge } from "@/components/ui/surface";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STATUS_TONES: Record<string, "accent" | "warning" | "danger" | "neutral" | "muted"> = {
  completed: "accent",
  partial: "warning",
  failed: "danger",
  running: "neutral",
  pending: "neutral",
  cancelled: "muted",
};

/** Run / research status badge. Unknown or missing status means the company was never researched. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge tone="muted">Not researched</Badge>;
  const active = status === "pending" || status === "running";
  return (
    <Badge tone={STATUS_TONES[status] ?? "neutral"}>
      {active ? <span aria-hidden="true" className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-accent" /> : null}
      {STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function BasisBadge({ basis }: { basis: string | null | undefined }) {
  if (basis === "observed") return <Badge tone="accent">Observed</Badge>;
  if (basis === "inferred") return <Badge tone="warning">Inferred</Badge>;
  return null;
}

export function ConfidenceBadge({ confidence, label = "confidence" }: { confidence: string | null | undefined; label?: string }) {
  if (!confidence) return null;
  const tone = confidence === "high" ? "accent" : confidence === "medium" ? "neutral" : "muted";
  return (
    <Badge tone={tone}>
      {capitalize(confidence)} {label}
    </Badge>
  );
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
}
