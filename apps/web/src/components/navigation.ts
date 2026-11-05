export type NavItem = {
  label: string;
  href: string;
  /** Planned modules are shown so the product shape is visible, but are not navigable. */
  enabled: boolean;
  match: string;
};

export const NAV_ITEMS: NavItem[] = [
  { label: "Overview", href: "/dashboard", enabled: true, match: "/dashboard" },
  { label: "Lead Intelligence", href: "/projects", enabled: true, match: "/projects" },
  { label: "Sales", href: "#", enabled: false, match: "/sales" },
  { label: "Marketing", href: "#", enabled: false, match: "/marketing" },
  { label: "Analytics", href: "#", enabled: false, match: "/analytics" },
  { label: "Settings", href: "/settings", enabled: true, match: "/settings" },
];
