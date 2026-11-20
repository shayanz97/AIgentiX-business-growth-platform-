"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isSalesPath, isSalesTabActive, SALES_TABS } from "@/components/navigation";
import { cn } from "@/components/ui/cn";

/** Secondary navigation shown on every Sales page. */
export function SalesTabs() {
  const pathname = usePathname();
  if (!isSalesPath(pathname)) return null;
  return (
    <nav aria-label="Sales sections" className="-mx-1 mb-8 flex gap-1 overflow-x-auto border-b border-line px-1">
      {SALES_TABS.map((tab) => {
        const active = isSalesTabActive(pathname, tab.href);
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
