import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScoreBreakdown } from "@/components/leads/score-breakdown";
import { TriggerTimeline } from "@/components/leads/trigger-timeline";
import type { ScoreComponent, Signal } from "@/lib/api";

const components: ScoreComponent[] = [
  {
    key: "opportunity",
    label: "Opportunity",
    weight: 35,
    state: "unknown",
    summary: "No completed AI audit.",
    score_low: 0,
    score_high: 100,
    contribution_low: 0,
    contribution_high: 35,
    coverage: 0,
    criteria: [
      { key: "best", label: "Strongest opportunity", state: "unknown", points: null, max_points: 70, explanation: "Audit not run.", evidence_ids: [], references: [] },
    ],
  },
  {
    key: "intent",
    label: "Intent",
    weight: 20,
    state: "assessed",
    summary: "Explicit request.",
    score_low: 80,
    score_high: 80,
    contribution_low: 16,
    contribution_high: 16,
    coverage: 1,
    criteria: [
      { key: "strongest", label: "Strongest intent", state: "assessed", points: 80, max_points: 100, explanation: "Explicit request found.", evidence_ids: ["e1"], references: [] },
      { key: "x", label: "Other", state: "insufficient_evidence", points: 0, max_points: 10, explanation: "Nothing found.", evidence_ids: [], references: [] },
      { key: "y", label: "Not relevant", state: "not_applicable", points: 0, max_points: 0, explanation: "n/a", evidence_ids: [], references: [] },
    ],
  },
];

describe("ScoreBreakdown", () => {
  it("renders every component with its criteria states and evidence counts", () => {
    render(<ScoreBreakdown components={components} evidence={{ e1: { id: "e1", label: "E1", supporting_excerpt: "<b>x</b>", source_url: null } }} />);
    const opp = screen.getByTestId("component-opportunity");
    expect(within(opp).getByText("weight 35")).toBeInTheDocument();
    expect(within(opp).getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(within(opp).getByText("0 evidence items")).toBeInTheDocument();
    const intent = screen.getByTestId("component-intent");
    expect(within(intent).getAllByText("Assessed")).toHaveLength(2);
    expect(within(intent).getByText("Insufficient evidence")).toBeInTheDocument();
    expect(within(intent).getByText("Not applicable")).toBeInTheDocument();
    expect(within(intent).getByText("1 evidence item")).toBeInTheDocument();
    expect(within(intent).getByText("E1")).toBeInTheDocument();
    expect(within(intent).getByText(/16 of 20 points/)).toBeInTheDocument();
  });
});

const sig = (over: Partial<Signal>): Signal => ({
  company_id: "c",
  confidence: "high",
  date_candidates: [],
  date_conflict: false,
  date_precision: "day",
  deadline_on: null,
  details: {},
  evidence: [{ id: "e", basis: "observed", confidence: "high", evidence_type: "business_signal", label: "E1", observed_fact: "f", source_url: "javascript:alert(1)", supporting_excerpt: "<img src=x onerror=alert(1)>" }],
  first_seen_at: "2026-11-01T00:00:00Z",
  freshness: "recent",
  id: "s1",
  last_seen_at: "2026-11-01T00:00:00Z",
  mention_count: 3,
  occurred_on: "2026-11-01",
  origin: "deterministic",
  relevance: "high",
  signal_type: "hiring",
  source_urls: [],
  summary: "",
  title: "We are hiring",
  ...over,
});

describe("TriggerTimeline", () => {
  it("keeps undated triggers in their own group and renders website text as plain text", () => {
    const { container } = render(
      <TriggerTimeline
        signals={[
          sig({}),
          sig({ id: "s2", title: "Mystery announcement", occurred_on: null, date_precision: "unknown", freshness: "unknown" }),
          sig({ id: "s3", title: "Conflicting", occurred_on: null, date_conflict: true, date_candidates: [{ date: "2026-01-01" }, { date: "2026-05-05" }] }),
        ]}
      />,
    );
    const dated = screen.getByRole("list", { name: "Dated triggers" });
    expect(within(dated).getByText("We are hiring")).toBeInTheDocument();
    expect(within(dated).getByText("mentioned on 3 pages")).toBeInTheDocument();
    const undated = screen.getByRole("list", { name: "Triggers without a date" });
    expect(within(undated).getByText("Mystery announcement")).toBeInTheDocument();
    expect(within(undated).getByText(/2026-01-01, 2026-05-05/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Date unknown" })).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a[href^='javascript']")).toBeNull();
  });
});
