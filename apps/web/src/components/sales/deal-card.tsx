import Link from "next/link";

import { DealPriorityBadge } from "@/components/sales/deal-badges";
import { StageControls } from "@/components/sales/stage-controls";
import { Badge } from "@/components/ui/surface";
import type { Deal } from "@/lib/api";
import { formatMoney } from "@/lib/sales";

export function DealCard({ deal, ownerName, onChanged }: { deal: Deal; ownerName: string; onChanged: () => void }) {
  return (
    <li className="space-y-2 rounded-md border border-line bg-navy-950/60 p-3 text-sm" data-testid="deal-card">
      <Link href={`/sales/opportunities/${deal.id}`} className="block font-medium text-slate-100 hover:text-accent hover:underline">
        {deal.title}
      </Link>
      <p className="text-xs text-slate-400">{deal.company.name}</p>
      <p className="text-slate-200">{formatMoney(deal.estimated_value, deal.currency)}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <DealPriorityBadge priority={deal.priority} />
        {deal.overdue_tasks > 0 ? <Badge tone="danger">{deal.overdue_tasks} overdue</Badge> : null}
      </div>
      <p className="text-xs text-slate-400">
        Owner: {ownerName}
        {deal.expected_close_date ? ` · Close ${deal.expected_close_date}` : ""}
      </p>
      <StageControls deal={deal} onChanged={onChanged} />
    </li>
  );
}
