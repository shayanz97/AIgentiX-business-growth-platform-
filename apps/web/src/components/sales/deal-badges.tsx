import { Badge } from "@/components/ui/surface";
import type { DealStatus, Priority, Stage } from "@/lib/api";
import { STAGE_LABELS } from "@/lib/sales";

export function StageBadge({ stage }: { stage: Stage }) {
  const tone = stage === "won" ? "accent" : stage === "lost" ? "danger" : "neutral";
  return <Badge tone={tone}>{STAGE_LABELS[stage]}</Badge>;
}

export function DealStatusBadge({ status }: { status: DealStatus }) {
  const tone = status === "won" ? "accent" : status === "lost" ? "danger" : "muted";
  return <Badge tone={tone}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>;
}

export function DealPriorityBadge({ priority }: { priority: Priority }) {
  const tone = priority === "high" ? "warning" : priority === "medium" ? "neutral" : "muted";
  return <Badge tone={tone}>{priority.charAt(0).toUpperCase() + priority.slice(1)} priority</Badge>;
}
