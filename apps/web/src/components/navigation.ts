export type NavItem = {
  label: string;
  href: string;
  /** Planned modules are shown so the product shape is visible, but are not navigable. */
  enabled: boolean;
  /** Path prefixes that mark this item as active. */
  match: string[];
};

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", href: "/dashboard", enabled: true, match: ["/dashboard"] },
  {
    label: "Lead Intelligence",
    href: "/lead-intelligence",
    enabled: true,
    match: ["/lead-intelligence", "/companies", "/projects", "/opportunities", "/research-runs", "/leads", "/scoring"],
  },
  { label: "Sales", href: "/sales", enabled: true, match: ["/sales"] },
  { label: "Marketing", href: "#", enabled: false, match: ["/marketing"] },
  { label: "Analytics", href: "#", enabled: false, match: ["/analytics"] },
  { label: "Settings", href: "/settings", enabled: true, match: ["/settings"] },
];

export const LEAD_INTELLIGENCE_TABS: { label: string; href: string }[] = [
  { label: "Overview", href: "/lead-intelligence" },
  { label: "Companies", href: "/companies" },
  { label: "Projects", href: "/projects" },
  { label: "Opportunities", href: "/opportunities" },
  { label: "Ranked leads", href: "/leads" },
  { label: "Scoring", href: "/scoring" },
];

export function isLeadIntelligencePath(pathname: string): boolean {
  const item = NAV_ITEMS.find((i) => i.label === "Lead Intelligence");
  return !!item && item.match.some((m) => pathname === m || pathname.startsWith(`${m}/`));
}

export function isTabActive(pathname: string, href: string): boolean {
  return pathname === href || (href !== "/lead-intelligence" && pathname.startsWith(`${href}/`));
}

export const SALES_TABS: { label: string; href: string }[] = [
  { label: "Overview", href: "/sales" },
  { label: "Pipeline", href: "/sales/pipeline" },
  { label: "Follow-ups", href: "/sales/tasks" },
  { label: "Contacts", href: "/sales/contacts" },
  { label: "Services", href: "/sales/services" },
];

export function isSalesPath(pathname: string): boolean {
  return pathname === "/sales" || pathname.startsWith("/sales/");
}

/** Opportunity detail pages belong to the Pipeline tab. */
export function isSalesTabActive(pathname: string, href: string): boolean {
  if (href === "/sales") return pathname === "/sales";
  if (href === "/sales/pipeline") return pathname === href || pathname.startsWith("/sales/opportunities");
  return pathname === href || pathname.startsWith(`${href}/`);
}
