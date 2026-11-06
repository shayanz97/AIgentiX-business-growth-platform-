"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { LeadIntelligenceTabs } from "@/components/lead-intelligence-tabs";
import { NAV_ITEMS } from "@/components/navigation";
import { Badge } from "@/components/ui/surface";
import { cn } from "@/components/ui/cn";
import { useSession } from "@/lib/session";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { me, membership, selectOrganization, signOut } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {NAV_ITEMS.map((item) => {
        const active = item.match.some((m) => pathname.startsWith(m));
        if (!item.enabled) {
          return (
            <span
              key={item.label}
              aria-disabled="true"
              className="flex cursor-not-allowed items-center justify-between rounded-md px-3 py-2 text-sm text-slate-500"
            >
              {item.label}
              <Badge tone="muted">Soon</Badge>
            </span>
          );
        }
        return (
          <Link
            key={item.label}
            href={item.href}
            aria-current={active ? "page" : undefined}
            onClick={() => setMenuOpen(false)}
            className={cn(
              "rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active ? "bg-navy-800 text-white shadow-[inset_2px_0_0_var(--color-accent)]" : "text-slate-300 hover:bg-navy-800/60 hover:text-white",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[16rem_1fr]">
      <aside
        className={cn(
          "border-line bg-navy-950 px-4 py-6 lg:sticky lg:top-0 lg:block lg:h-screen lg:border-r",
          menuOpen ? "block border-b" : "hidden",
        )}
      >
        <Link href="/dashboard" className="mb-8 hidden items-center gap-2 px-3 lg:flex">
          <Logo />
        </Link>
        {nav}
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-line bg-navy-950/80 px-4 py-3 backdrop-blur sm:px-8">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded-md p-2 text-slate-300 hover:bg-navy-800 lg:hidden"
              aria-label="Toggle navigation"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span aria-hidden="true">☰</span>
            </button>
            <span className="lg:hidden">
              <Logo />
            </span>
            {me.memberships.length > 0 ? (
              <label className="flex items-center gap-2 text-sm text-slate-400">
                <span className="hidden sm:inline">Organization</span>
                <select
                  aria-label="Active organization"
                  value={membership?.organization.id ?? ""}
                  onChange={(e) => selectOrganization(e.target.value)}
                  className="rounded-md border border-line bg-navy-900 px-2 py-1.5 text-sm text-slate-100 focus:border-accent focus:outline-none"
                >
                  {me.memberships.map((m) => (
                    <option key={m.organization.id} value={m.organization.id}>
                      {m.organization.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-400 md:inline" data-testid="current-user">
              {me.user.email}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="whitespace-nowrap rounded-md border border-line px-3 py-1.5 text-sm text-slate-200 hover:bg-navy-800"
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-8">
          <LeadIntelligenceTabs />
          {children}
        </main>
      </div>
    </div>
  );
}

export function Logo() {
  return (
    <span className="flex items-center gap-2 text-base font-semibold tracking-tight text-white">
      <span aria-hidden="true" className="grid size-7 place-items-center rounded-md bg-accent/15 text-accent ring-1 ring-accent/40">
        ◆
      </span>
      AIgentiX
    </span>
  );
}
