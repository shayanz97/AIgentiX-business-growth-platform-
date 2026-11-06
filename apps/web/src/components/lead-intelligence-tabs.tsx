"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/components/ui/cn";
import { isLeadIntelligencePath, isTabActive, LEAD_INTELLIGENCE_TABS } from "@/components/navigation";

/** Secondary navigation shown on every Lead Intelligence page. */
export function LeadIntelligenceTabs() {
  const pathname = usePathname();
  if (!isLeadIntelligencePath(pathname)) return null;
  return (
    <nav aria-label="Lead Intelligence sections" className="-mx-1 mb-8 flex gap-1 overflow-x-auto border-b border-line px-1">
      {LEAD_INTELLIGENCE_TABS.map((tab) => {
        const active = isTabActive(pathname, tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              active ? "border-accent text-white" : "border-transparent text-slate-400 hover:text-slate-100",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
