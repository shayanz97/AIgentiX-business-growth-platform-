import { describe, expect, it } from "vitest";

import { safeNextPath } from "@/lib/redirect";

const ORIGIN = "http://localhost:3000";

describe("safeNextPath", () => {
  it.each([
    ["/projects", "/projects"],
    ["/projects/abc?tab=1#x", "/projects/abc?tab=1#x"],
  ])("keeps same-origin path %s", (input, expected) => {
    expect(safeNextPath(input, ORIGIN)).toBe(expected);
  });

  it.each([
    null,
    "",
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
  ])("rejects off-origin target %j", (input) => {
    expect(safeNextPath(input, ORIGIN)).toBe("/dashboard");
  });
});
