import { describe, expect, it } from "vitest";

import { isLeadIntelligencePath, isTabActive, LEAD_INTELLIGENCE_TABS, NAV_ITEMS } from "@/components/navigation";

describe("navigation", () => {
  it("lists all product areas in order", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual([
      "Overview",
      "Lead Intelligence",
      "Sales",
      "Marketing",
      "Analytics",
      "Settings",
    ]);
  });

  it("does not present unimplemented modules as functional", () => {
    const disabled = NAV_ITEMS.filter((i) => !i.enabled).map((i) => i.label);
    expect(disabled).toEqual(["Sales", "Marketing", "Analytics"]);
  });

  it("sends Lead Intelligence to its overview page", () => {
    expect(NAV_ITEMS.find((i) => i.label === "Lead Intelligence")?.href).toBe("/lead-intelligence");
  });

  it("offers the Lead Intelligence secondary tabs", () => {
    expect(LEAD_INTELLIGENCE_TABS.map((t) => [t.label, t.href])).toEqual([
      ["Overview", "/lead-intelligence"],
      ["Companies", "/companies"],
      ["Projects", "/projects"],
      ["Opportunities", "/opportunities"],
    ]);
  });

  it("recognises Lead Intelligence paths and the active tab", () => {
    expect(isLeadIntelligencePath("/companies/abc")).toBe(true);
    expect(isLeadIntelligencePath("/research-runs/abc")).toBe(true);
    expect(isLeadIntelligencePath("/settings")).toBe(false);
    expect(isTabActive("/companies/abc", "/companies")).toBe(true);
    expect(isTabActive("/companies", "/lead-intelligence")).toBe(false);
    expect(isTabActive("/lead-intelligence", "/lead-intelligence")).toBe(true);
  });
});
