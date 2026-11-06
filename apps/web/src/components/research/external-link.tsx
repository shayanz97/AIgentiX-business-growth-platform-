import type { ReactNode } from "react";

import { safeHref } from "@/lib/research";

/** External links never leak the opener/referrer; non-http(s) URLs are shown as plain text. */
export function ExternalLink({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  const safe = safeHref(href);
  if (!safe) return <span className={className}>{children}</span>;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer nofollow" className={className ?? "break-all text-accent hover:underline"}>
      {children}
    </a>
  );
}
