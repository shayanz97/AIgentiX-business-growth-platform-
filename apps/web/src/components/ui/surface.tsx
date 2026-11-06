import type { ReactNode } from "react";

import { cn } from "./cn";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cn("rounded-lg border border-line bg-navy-900/70 p-6", className)}>{children}</section>;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "muted" | "warning" | "danger";
}) {
  const tones = {
    neutral: "border-line bg-navy-800 text-slate-300",
    accent: "border-accent/40 bg-accent/10 text-accent",
    muted: "border-line bg-transparent text-slate-500",
    warning: "border-amber-400/40 bg-amber-400/10 text-amber-300",
    danger: "border-red-400/40 bg-red-500/10 text-red-300",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", tones[tone])}>
      {children}
    </span>
  );
}

export function Alert({ children, tone = "danger" }: { children: ReactNode; tone?: "danger" | "warning" | "info" }) {
  const tones = {
    danger: "border-red-400/40 bg-red-500/10 text-red-200",
    warning: "border-amber-400/40 bg-amber-400/10 text-amber-200",
    info: "border-accent/40 bg-accent/10 text-slate-200",
  };
  return (
    <div role={tone === "danger" ? "alert" : "note"} className={cn("rounded-md border px-4 py-3 text-sm", tones[tone])}>
      {children}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-6 py-12 text-center">
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      <div className="mx-auto mt-2 max-w-md text-sm text-slate-400">{children}</div>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
        {description ? <p className="mt-1 text-sm text-slate-400">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-3">{actions}</div> : null}
    </div>
  );
}
