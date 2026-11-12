import { describe, expect, it } from "vitest";

import type { Signal } from "@/lib/api";
import { buildLeadQuery, DEFAULT_FILTERS, formatCoverage, formatEventDate, formatScoreRange, groupSignals, provisionalExplanation, validateWeights, weightsSum } from "@/lib/leads";

const base: Signal = {
  company_id: "c1",
  confidence: "medium",
  date_candidates: [],
  date_conflict: false,
  date_precision: "day",
  deadline_on: null,
  details: {},
  evidence: [],
  first_seen_at: "2026-11-01T00:00:00Z",
  freshness: "recent",
  id: "s",
  last_seen_at: "2026-11-01T00:00:00Z",
  mention_count: 1,
  occurred_on: "2026-11-01",
  origin: "deterministic",
  relevance: "medium",
  signal_type: "hiring",
  source_urls: [],
  summary: "",
  title: "T",
};

describe("score helpers", () => {
  it("formats the conservative score with its upper bound", () => {
    expect(formatScoreRange(54.2, 78.6)).toBe("54 – 79");
    expect(formatScoreRange(40, 40)).toBe("40");
    expect(formatCoverage(0.625)).toBe("63%");
  });

  it("explains provisional scores and stays silent otherwise", () => {
    const text = provisionalExplanation({ provisional: true, coverage: 0.5, score_low: 30, score_high: 60 });
    expect(text).toContain("50%");
    expect(text).toContain("30 – 60");
    expect(provisionalExplanation({ provisional: false, coverage: 1, score_low: 30, score_high: 30 })).toBeNull();
  });

  it("builds the shared list/export query", () => {
    expect(buildLeadQuery({ ...DEFAULT_FILTERS, min_score: "40", provisional: "yes", hideExcluded: true, q: " acme " })).toMatchObject({
      min_score: 40,
      provisional: true,
      include_excluded: false,
      q: "acme",
      sort: "score",
    });
    expect(buildLeadQuery(DEFAULT_FILTERS)).toMatchObject({ include_excluded: true, provisional: undefined, min_score: undefined });
  });

  it("does not invent precision for partial dates", () => {
    expect(formatEventDate("2026-03-01", "month")).toBe("2026-03");
    expect(formatEventDate("2026-03-01", "year")).toBe("2026");
    expect(formatEventDate(null, "unknown")).toBe("Date unknown");
  });
});

describe("groupSignals", () => {
  it("sorts dated signals newest first and keeps undated and conflicting ones apart", () => {
    const signals: Signal[] = [
      { ...base, id: "old", occurred_on: "2026-01-05", title: "Old" },
      { ...base, id: "new", occurred_on: "2026-11-01", title: "New" },
      { ...base, id: "none", occurred_on: null, date_precision: "unknown", freshness: "unknown", title: "Undated" },
      { ...base, id: "conflict", occurred_on: "2026-10-01", date_conflict: true, title: "Conflict" },
    ];
    const { dated, undated } = groupSignals(signals);
    expect(dated.map((s) => s.id)).toEqual(["new", "old"]);
    expect(undated.map((s) => s.id).sort()).toEqual(["conflict", "none"]);
  });
});

describe("weights", () => {
  it("requires the weights to add up to 100", () => {
    expect(weightsSum({ opportunity: 35, fit: 25, triggers: 20, intent: 20 })).toBe(100);
    expect(validateWeights({ opportunity: 35, fit: 25, triggers: 20, intent: 20 })).toBeNull();
    expect(validateWeights({ opportunity: 25, fit: 25, triggers: 20, intent: 30 })).toBeNull();
    expect(validateWeights({ opportunity: 35, fit: 25, triggers: 20, intent: 30 })).toMatch(/110/);
    expect(validateWeights({ opportunity: NaN, fit: 25, triggers: 20, intent: 20 })).toMatch(/whole number/);
  });
});
