import { describe, expect, it } from "vitest";

import { isLeadIntelligencePath, isSalesPath, isSalesTabActive, isTabActive, SALES_TABS, LEAD_INTELLIGENCE_TABS, NAV_ITEMS } from "@/components/navigation";

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
    expect(disabled).toEqual(["Marketing", "Analytics"]);
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
      ["Ranked leads", "/leads"],
      ["Scoring", "/scoring"],
    ]);
  });

  it("recognises Lead Intelligence paths and the active tab", () => {
    expect(isLeadIntelligencePath("/companies/abc")).toBe(true);
    expect(isLeadIntelligencePath("/research-runs/abc")).toBe(true);
    expect(isLeadIntelligencePath("/leads/abc")).toBe(true);
    expect(isLeadIntelligencePath("/scoring")).toBe(true);
    expect(isTabActive("/leads/abc", "/leads")).toBe(true);
    expect(isLeadIntelligencePath("/settings")).toBe(false);
    expect(isTabActive("/companies/abc", "/companies")).toBe(true);
    expect(isTabActive("/companies", "/lead-intelligence")).toBe(false);
    expect(isTabActive("/lead-intelligence", "/lead-intelligence")).toBe(true);
  });

  it("enables Sales with its own tabs", () => {
    const sales = NAV_ITEMS.find((i) => i.label === "Sales");
    expect(sales?.enabled).toBe(true);
    expect(sales?.href).toBe("/sales");
    expect(SALES_TABS.map((t) => [t.label, t.href])).toEqual([
      ["Overview", "/sales"],
      ["Pipeline", "/sales/pipeline"],
      ["Follow-ups", "/sales/tasks"],
      ["Contacts", "/sales/contacts"],
      ["Services", "/sales/services"],
    ]);
  });

  it("recognises Sales paths and keeps opportunity pages under Pipeline", () => {
    expect(isSalesPath("/sales")).toBe(true);
    expect(isSalesPath("/sales/opportunities/abc")).toBe(true);
    expect(isSalesPath("/salesforce")).toBe(false);
    expect(isSalesTabActive("/sales", "/sales")).toBe(true);
    expect(isSalesTabActive("/sales/pipeline", "/sales")).toBe(false);
    expect(isSalesTabActive("/sales/opportunities/abc", "/sales/pipeline")).toBe(true);
    expect(isSalesTabActive("/sales/tasks", "/sales/tasks")).toBe(true);
  });
});
