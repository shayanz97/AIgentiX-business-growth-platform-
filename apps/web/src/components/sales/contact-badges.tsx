import { Badge } from "@/components/ui/surface";
import type { Contact } from "@/lib/api";
import { humanizeKey } from "@/lib/sales";

/** Per-channel permission as computed by the API (no permission unless an eligibility review allows it). */
export function PermissionBadges({ permissions }: { permissions: Contact["permissions"] }) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Channel permissions">
      {permissions.map((p) => (
        <li key={p.channel} title={p.reason}>
          <Badge tone={p.allowed ? "accent" : "muted"}>
            {humanizeKey(p.channel)}: {p.allowed ? "allowed" : "not allowed"}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

export function RestrictionBadge({ status }: { status: Contact["restriction_status"] }) {
  const tone = status === "suppressed" ? "danger" : status === "restricted" ? "warning" : "muted";
  return <Badge tone={tone}>{humanizeKey(status)}</Badge>;
}
