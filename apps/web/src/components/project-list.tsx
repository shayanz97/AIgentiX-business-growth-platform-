import Link from "next/link";

import { Badge } from "@/components/ui/surface";
import type { Project } from "@/lib/api";
import { formatDate } from "@/lib/format";

export function ProjectList({ projects }: { projects: Project[] }) {
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Research projects">
      {projects.map((p) => (
        <li key={p.id}>
          <Link href={`/projects/${p.id}`} className="flex flex-col gap-1 px-5 py-4 hover:bg-navy-800/60 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="truncate font-medium text-slate-100">{p.name}</p>
              <p className="truncate text-sm text-slate-400">{p.target_url ?? "No target URL"}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
              <Badge>{p.status}</Badge>
              <time dateTime={p.created_at}>{formatDate(p.created_at)}</time>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
