import { describe, expect, it } from "vitest";

import { NAV_ITEMS } from "@/components/navigation";

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
});
